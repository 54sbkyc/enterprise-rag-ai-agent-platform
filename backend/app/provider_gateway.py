import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit


RETRYABLE_HTTP_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class ProviderPolicy:
    timeout_seconds: float
    max_attempts: int
    retry_base_seconds: float
    retry_max_seconds: float


@dataclass(frozen=True)
class ProviderResponse:
    payload: dict | None
    error: str | None
    attempts: int
    latency_ms: int
    status_code: int | None = None

    @property
    def ready(self) -> bool:
        return self.payload is not None and self.error is None


@dataclass
class _Circuit:
    consecutive_failures: int = 0
    open_until: float = 0.0
    probe_in_flight: bool = False
    last_error: str | None = None


@dataclass
class _GatewayMetrics:
    requests: int = 0
    attempts: int = 0
    retries: int = 0
    successes: int = 0
    failures: int = 0
    circuit_rejections: int = 0


_lock = threading.Lock()
_circuits: dict[str, _Circuit] = {}
_metrics = _GatewayMetrics()


def policy_from_env(
    prefix: str,
    *,
    default_timeout_seconds: float,
    default_max_attempts: int,
) -> ProviderPolicy:
    return ProviderPolicy(
        timeout_seconds=_bounded_float(f"{prefix}_TIMEOUT_SECONDS", default_timeout_seconds, 0.1, 300.0),
        max_attempts=_bounded_int(f"{prefix}_MAX_ATTEMPTS", default_max_attempts, 1, 10),
        retry_base_seconds=_bounded_float(f"{prefix}_RETRY_BASE_SECONDS", 0.25, 0.01, 10.0),
        retry_max_seconds=_bounded_float(f"{prefix}_RETRY_MAX_SECONDS", 2.0, 0.01, 60.0),
    )


def post_json(
    url: str,
    *,
    payload: dict,
    headers: dict[str, str],
    policy: ProviderPolicy,
) -> ProviderResponse:
    started = time.monotonic()
    circuit_key = _circuit_key(url)
    failure_threshold = _bounded_int("MODEL_GATEWAY_CIRCUIT_FAILURE_THRESHOLD", 5, 1, 100)
    cooldown_seconds = _bounded_float("MODEL_GATEWAY_CIRCUIT_COOLDOWN_SECONDS", 30.0, 0.1, 3600.0)
    max_response_bytes = _bounded_int(
        "MODEL_GATEWAY_MAX_RESPONSE_BYTES",
        5 * 1024 * 1024,
        1024,
        20 * 1024 * 1024,
    )

    if not _acquire_circuit(circuit_key):
        latency_ms = _elapsed_ms(started)
        _record_metrics(attempts=0, success=False, circuit_rejected=True)
        return ProviderResponse(
            payload=None,
            error="provider_circuit_open",
            attempts=0,
            latency_ms=latency_ms,
        )

    attempts = 0
    last_error = "provider_unavailable"
    last_status_code: int | None = None
    retryable_failure = True
    while attempts < policy.max_attempts:
        attempts += 1
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        retry_after: float | None = None
        try:
            with urllib.request.urlopen(request, timeout=policy.timeout_seconds) as response:
                raw_body = response.read(max_response_bytes + 1)
                if len(raw_body) > max_response_bytes:
                    raise ValueError("provider response is too large")
                raw_payload = json.loads(raw_body.decode("utf-8"))
                if not isinstance(raw_payload, dict):
                    raise ValueError("provider response must be a JSON object")
                status_code = int(getattr(response, "status", 200))
            latency_ms = _elapsed_ms(started)
            _record_success(circuit_key)
            _record_metrics(attempts=attempts, success=True)
            return ProviderResponse(
                payload=raw_payload,
                error=None,
                attempts=attempts,
                latency_ms=latency_ms,
                status_code=status_code,
            )
        except urllib.error.HTTPError as exc:
            last_status_code = int(exc.code)
            last_error = _http_error_name(last_status_code)
            retryable_failure = last_status_code in RETRYABLE_HTTP_STATUS_CODES
            retry_after = _retry_after_seconds(exc.headers)
            exc.close()
        except (TimeoutError, socket.timeout):
            last_error = "provider_timeout"
            retryable_failure = True
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                last_error = "provider_timeout"
            else:
                last_error = "provider_unavailable"
            retryable_failure = True
        except (OSError, ConnectionError):
            last_error = "provider_unavailable"
            retryable_failure = True
        except (TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            last_error = "invalid_provider_response"
            retryable_failure = False

        if retryable_failure and attempts < policy.max_attempts:
            delay = _retry_delay(attempts, retry_after, policy)
            if delay > 0:
                time.sleep(delay)
            continue
        break

    latency_ms = _elapsed_ms(started)
    _record_failure(
        circuit_key,
        error=last_error,
        retryable=retryable_failure,
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
    )
    _record_metrics(attempts=attempts, success=False)
    return ProviderResponse(
        payload=None,
        error=last_error,
        attempts=attempts,
        latency_ms=latency_ms,
        status_code=last_status_code,
    )


def provider_gateway_health() -> dict:
    configured = _provider_is_configured()
    now = time.monotonic()
    with _lock:
        open_circuits = sum(1 for item in _circuits.values() if item.open_until > now)
        half_open_circuits = sum(
            1
            for item in _circuits.values()
            if item.open_until and item.open_until <= now
        )
        state = "open" if open_circuits else "half_open" if half_open_circuits else "closed"
        status = "not_configured" if not configured else "degraded" if state != "closed" else "ready"
        return {
            "status": status,
            "circuit_state": state,
            "tracked_providers": len(_circuits),
            "open_circuits": open_circuits,
            "requests": _metrics.requests,
            "attempts": _metrics.attempts,
            "retries": _metrics.retries,
            "successes": _metrics.successes,
            "failures": _metrics.failures,
            "circuit_rejections": _metrics.circuit_rejections,
        }


def reset_provider_gateway_state() -> None:
    with _lock:
        _circuits.clear()
        _metrics.requests = 0
        _metrics.attempts = 0
        _metrics.retries = 0
        _metrics.successes = 0
        _metrics.failures = 0
        _metrics.circuit_rejections = 0


def _acquire_circuit(key: str) -> bool:
    now = time.monotonic()
    with _lock:
        circuit = _circuits.setdefault(key, _Circuit())
        if not circuit.open_until:
            return True
        if circuit.open_until > now:
            return False
        if circuit.probe_in_flight:
            return False
        circuit.probe_in_flight = True
        return True


def _record_success(key: str) -> None:
    with _lock:
        circuit = _circuits.setdefault(key, _Circuit())
        circuit.consecutive_failures = 0
        circuit.open_until = 0.0
        circuit.probe_in_flight = False
        circuit.last_error = None


def _record_failure(
    key: str,
    *,
    error: str,
    retryable: bool,
    failure_threshold: int,
    cooldown_seconds: float,
) -> None:
    with _lock:
        circuit = _circuits.setdefault(key, _Circuit())
        circuit.probe_in_flight = False
        circuit.last_error = error
        if not retryable:
            circuit.consecutive_failures = 0
            circuit.open_until = 0.0
            return
        circuit.consecutive_failures += 1
        if circuit.consecutive_failures >= failure_threshold:
            circuit.open_until = time.monotonic() + cooldown_seconds


def _record_metrics(*, attempts: int, success: bool, circuit_rejected: bool = False) -> None:
    with _lock:
        _metrics.requests += 1
        _metrics.attempts += attempts
        _metrics.retries += max(0, attempts - 1)
        if success:
            _metrics.successes += 1
        else:
            _metrics.failures += 1
        if circuit_rejected:
            _metrics.circuit_rejections += 1


def _retry_delay(attempt: int, retry_after: float | None, policy: ProviderPolicy) -> float:
    exponential = policy.retry_base_seconds * (2 ** max(0, attempt - 1))
    requested = retry_after if retry_after is not None else exponential
    return min(policy.retry_max_seconds, max(0.0, requested))


def _retry_after_seconds(headers) -> float | None:
    if not headers:
        return None
    raw_value = headers.get("Retry-After")
    if not raw_value:
        return None
    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        pass
    try:
        retry_at = parsedate_to_datetime(str(raw_value))
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _http_error_name(status_code: int) -> str:
    if status_code in {401, 403}:
        return "provider_auth_error"
    if status_code == 429:
        return "provider_rate_limited"
    if status_code == 408:
        return "provider_timeout"
    if status_code >= 500:
        return "provider_unavailable"
    return "provider_request_rejected"


def _circuit_key(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _provider_is_configured() -> bool:
    llm_ready = bool(os.getenv("LLM_API_KEY", "").strip() and os.getenv("LLM_MODEL", "").strip())
    embedding_key = (os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
    embedding_ready = bool(embedding_key and os.getenv("EMBEDDING_MODEL", "").strip())
    return llm_ready or embedding_ready


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = _positive_int(name, default)
    return min(maximum, max(minimum, value))


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    value = _positive_float(name, default)
    return min(maximum, max(minimum, value))
