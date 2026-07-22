import os
from pathlib import Path


def parse_cors_origins(raw: str) -> tuple[str, ...]:
    origins = tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    if "*" in origins:
        raise ValueError("RAG_CORS_ORIGINS does not allow wildcard origins")
    return origins


def positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = Path(os.environ.get("RAG_UPLOAD_DIR", DATA_DIR / "uploads"))
DB_PATH = Path(os.environ.get("RAG_DB_PATH", DATA_DIR / "rag_platform.db"))

APP_NAME = "企业知识库问答管理系统"
APP_VERSION = "1.2.0"

CHUNK_SIZE = 700
CHUNK_OVERLAP = 120
DEFAULT_TOP_K = 5
MIN_CONFIDENCE_FOR_ANSWER = 0.16
MAX_UPLOAD_BYTES = positive_int_env("RAG_MAX_UPLOAD_MB", 10) * 1024 * 1024
SESSION_TTL_HOURS = positive_int_env("RAG_SESSION_TTL_HOURS", 12)
CORS_ORIGINS = parse_cors_origins(os.environ.get("RAG_CORS_ORIGINS", ""))
AGENT_TASK_WORKERS = positive_int_env("AGENT_TASK_WORKERS", 2)
AGENT_TASK_MAX_ACTIVE_PER_USER = positive_int_env("AGENT_TASK_MAX_ACTIVE_PER_USER", 3)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
