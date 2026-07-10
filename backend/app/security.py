import re
from dataclasses import dataclass


INJECTION_PATTERNS = [
    r"忽略(之前|以上|所有).{0,20}(指令|规则|要求)",
    r"ignore (previous|all|above).{0,20}(instruction|rule|system)",
    r"system prompt",
    r"developer message",
    r"越权|绕过权限|导出全部|输出全部文档",
    r"泄露|密钥|密码|token|api[_ -]?key",
]

SENSITIVE_PATTERNS = [
    r"AKIA[0-9A-Z]{16}",
    r"sk-[A-Za-z0-9]{20,}",
    r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+",
    r"(?i)(mysql|postgres|postgresql|mongodb|redis)://[^\s)\"']+",
    r"(?i)jdbc:[^\s)\"']+",
    r"(?i)(access_key|secret_key|client_secret)\s*[:=]\s*\S+",
    r"(?<!\d)1[3-9]\d{9}(?!\d)",
    r"\b\d{17}[\dXx]\b",
    r"\b(?:\d[ -]*?){13,19}\b",
    r"(合同总价|合同金额|报价|首付款|尾款|付款比例)(为|是|：|:)?\s*\d+(?:\.\d+)?\s*(元|万元|人民币|%)",
]


@dataclass
class SecurityResult:
    allowed: bool
    reason: str | None = None


def inspect_question(question: str) -> SecurityResult:
    lowered = question.strip().lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            return SecurityResult(False, "检测到疑似 Prompt 注入或越权查询")
    return SecurityResult(True)


def mask_sensitive(text: str) -> str:
    masked = text
    for pattern in SENSITIVE_PATTERNS:
        masked = re.sub(pattern, "[已脱敏]", masked)
    return masked
