import json
import os
import time
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import (
    AgentTaskConflictError,
    AgentTaskLimitError,
    create_agent_run,
    create_or_get_agent_task,
    execute_agent_task,
    finish_agent_run,
    recover_interrupted_agent_runs,
    request_agent_run_cancel,
    run_agent,
    runtime_error_result,
)
from .auth import (
    MANAGER_ROLES,
    allowed_access_levels,
    create_session,
    current_user,
    logout,
    public_user,
    require_admin,
    require_manager,
)
from .config import (
    AGENT_TASK_WORKERS,
    APP_NAME,
    APP_VERSION,
    CORS_ORIGINS,
    DEFAULT_TOP_K,
    MAX_UPLOAD_BYTES,
    UPLOAD_DIR,
)
from .db import get_conn, init_db, utc_now
from .document_parser import SUPPORTED_EXTENSIONS, extract_text
from .embeddings import build_chunk_index
from .evaluation_dataset import cases_fingerprint, load_evaluation_baseline, load_evaluation_dataset
from .evaluation_gate import (
    DEFAULT_MINIMUM_CASES,
    DEFAULT_THRESHOLDS,
    QualityGatePolicy,
    evaluate_quality_gate,
    rounded_summary,
    summarize_evaluation_breakdowns,
    summarize_evaluation_results,
)
from .evaluation_metrics import evaluate_case_signals
from .lexical_index import lexical_index_health
from .migrations import migration_status
from .observability import build_agent_trace, build_usage_summary
from .pagination import normalize_pagination, paginated
from .permissions import (
    DEFAULT_ROLE_PERMISSIONS,
    has_permission,
    permission_catalog,
    permissions_for_role,
    permissions_for_user,
    require_permission,
    update_role_permissions,
)
from .provider_gateway import provider_gateway_health
from .quality import calculate_quality
from .qa import build_grounded_answer, build_restricted_access_refusal
from .search import has_restricted_topic_match, search_chunks
from .security import inspect_question
from .text_processing import chunk_text, token_counts
from .vector_store import (
    ChunkVector,
    VectorStoreConfigurationError,
    close_vector_store_pool,
    delete_document_vectors,
    sync_chunk_vectors,
    vector_store_fallback_enabled,
    vector_store_backend,
    vector_store_health,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    recover_interrupted_agent_runs()
    executor = ThreadPoolExecutor(max_workers=AGENT_TASK_WORKERS, thread_name_prefix="agent-task")
    _app.state.agent_executor = executor
    try:
        yield
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        close_vector_store_pool()


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(CORS_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def disable_frontend_cache(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1200)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=10)


class AgentRunRequest(BaseModel):
    goal: str = Field(..., min_length=1, max_length=1200)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=10)


class AgentTaskRequest(AgentRunRequest):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class AgentRetryRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)


class EvaluateRequest(BaseModel):
    question: str = Field(..., min_length=1)
    expected_keywords: list[str] = Field(default_factory=list)
    expected_documents: list[str] = Field(default_factory=list)


class EvaluationThresholds(BaseModel):
    recall_at_k: float = Field(default=DEFAULT_THRESHOLDS["recall_at_k"], ge=0, le=1)
    mrr: float = Field(default=DEFAULT_THRESHOLDS["mrr"], ge=0, le=1)
    answer_accuracy: float = Field(default=DEFAULT_THRESHOLDS["answer_accuracy"], ge=0, le=1)
    abstention_accuracy: float = Field(default=DEFAULT_THRESHOLDS["abstention_accuracy"], ge=0, le=1)
    access_control_accuracy: float = Field(default=DEFAULT_THRESHOLDS["access_control_accuracy"], ge=0, le=1)
    citation_faithfulness: float = Field(default=DEFAULT_THRESHOLDS["citation_faithfulness"], ge=0, le=1)
    safety_assertion_accuracy: float = Field(
        default=DEFAULT_THRESHOLDS["safety_assertion_accuracy"], ge=0, le=1
    )


class BatchEvaluateRequest(BaseModel):
    case_ids: list[int] | None = None
    include_custom: bool = False
    use_baseline: bool = True
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=10)
    baseline_run_id: int | None = Field(default=None, ge=1)
    thresholds: EvaluationThresholds = Field(default_factory=EvaluationThresholds)
    minimum_cases: int = Field(default=DEFAULT_MINIMUM_CASES, ge=1, le=1000)
    max_regression: float = Field(default=0.05, ge=0, le=1)


class EvaluationCaseRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1200)
    expected_keywords: list[str] = Field(default_factory=list)
    expected_documents: list[str] = Field(default_factory=list)
    should_answer: bool = True
    category: str = Field(default="custom", min_length=1, max_length=40)
    actor_role: Literal["admin", "tech", "employee"] = "employee"


class DocumentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    access_level: str | None = None


class EmbeddingRebuildRequest(BaseModel):
    document_ids: list[int] | None = None
    force: bool = False


class VectorStoreSyncRequest(BaseModel):
    document_ids: list[int] | None = None


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=4, max_length=64)
    role: str = Field(default="employee")
    display_name: str | None = Field(default=None, min_length=1, max_length=40)


class UserUpdateRequest(BaseModel):
    password: str | None = Field(default=None, min_length=4, max_length=64)
    role: str | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=40)
    is_active: bool | None = None


class RolePermissionsUpdateRequest(BaseModel):
    permissions: list[str] = Field(default_factory=list)


class KnowledgeGapCreateRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1200)
    source_log_id: int | None = None
    note: str | None = Field(default=None, max_length=500)


class KnowledgeGapUpdateRequest(BaseModel):
    status: str | None = None
    note: str | None = Field(default=None, max_length=500)
    assigned_to: int | None = None
    resolution_action: str | None = Field(default=None, max_length=500)


class QaFeedbackRequest(BaseModel):
    log_id: int
    rating: str = Field(..., min_length=1, max_length=20)
    note: str | None = Field(default=None, max_length=500)


STRUCTURE_CHECKS = [
    ("制度范围", ("范围", "适用", "对象", "原则")),
    ("流程步骤", ("流程", "步骤", "申请", "审批", "提交")),
    ("风险处理", ("风险", "异常", "违规", "处理", "应急")),
]

SENSITIVE_KEYWORDS = ("合同", "报价", "薪酬", "数据", "保密", "客户", "安全事件", "供应商")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/api/health")
def health() -> dict:
    return {"name": APP_NAME, "version": APP_VERSION, "status": "ok"}


@app.get("/api/health/live")
def liveness() -> dict:
    return {"name": APP_NAME, "version": APP_VERSION, "status": "alive"}


@app.get("/api/health/ready")
def readiness() -> dict:
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
            schema_health = migration_status(conn)
            if not schema_health.ready:
                raise RuntimeError("database schema is not ready")
            lexical_health = lexical_index_health(conn)
    except Exception:
        raise HTTPException(status_code=503, detail="service is not ready") from None
    vector_health = vector_store_health()
    if vector_health.status == "degraded" and not vector_store_fallback_enabled():
        raise HTTPException(status_code=503, detail="service is not ready")
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "status": "ready",
        "database": "ok",
        "schema_migrations": schema_health.public_dict(),
        "lexical_index": lexical_health.public_dict(),
        "vector_store": vector_health.public_dict(),
        "model_gateway": provider_gateway_health(),
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> dict:
    return create_session(payload.username.strip(), payload.password)


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)) -> dict:
    return {"user": public_user(user), "permissions": sorted(permissions_for_user(user))}


@app.get("/api/permissions/catalog")
def get_permission_catalog(user: dict = Depends(current_user)) -> dict:
    require_permission(user, "roles.manage")
    return {"items": permission_catalog()}


@app.get("/api/role-permissions")
def get_role_permissions(user: dict = Depends(current_user)) -> dict:
    require_permission(user, "roles.manage")
    return {
        "roles": {
            role: sorted(permissions_for_role(role))
            for role in DEFAULT_ROLE_PERMISSIONS
        }
    }


@app.put("/api/role-permissions/{role}")
def put_role_permissions(
    role: str,
    payload: RolePermissionsUpdateRequest,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "roles.manage")
    permissions = update_role_permissions(role, set(payload.permissions), user)
    write_audit(user, "update_role_permissions", "role", None, {"role": role, "permissions": permissions})
    return {"role": role, "permissions": permissions}


@app.post("/api/auth/logout")
def logout_route(authorization: str | None = Header(default=None)) -> dict:
    if authorization and authorization.lower().startswith("bearer "):
        logout(authorization.split(" ", 1)[1].strip())
    return {"ok": True}


def require_admin_area(user: dict) -> None:
    require_manager(user)


@app.get("/api/users")
def list_users(
    page: int = 1,
    page_size: int = 5,
    q: str | None = None,
    role: str | None = None,
    status: str | None = None,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "users.manage")
    page, page_size, offset = normalize_pagination(page, page_size)
    where = []
    values: list[object] = []
    if q:
        where.append("(username LIKE ? OR display_name LIKE ?)")
        values.extend([f"%{q.strip()}%", f"%{q.strip()}%"])
    if role:
        if role not in {*MANAGER_ROLES, "employee"}:
            raise HTTPException(status_code=400, detail="用户角色不合法")
        where.append("role = ?")
        values.append(role)
    if status:
        if status not in {"active", "disabled"}:
            raise HTTPException(status_code=400, detail="用户状态不合法")
        where.append("is_active = ?")
        values.append(1 if status == "active" else 0)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS count FROM users {clause}", values).fetchone()["count"]
        rows = conn.execute(
            f"""
            SELECT id, username, role, display_name, is_active, created_at
            FROM users {clause}
            ORDER BY id
            LIMIT ? OFFSET ?
            """,
            [*values, page_size, offset],
        ).fetchall()
    return paginated([serialize_user(row) for row in rows], total, page, page_size)


@app.post("/api/users")
def create_user(payload: UserCreateRequest, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "users.manage")
    if payload.role not in {*MANAGER_ROLES, "employee"}:
        raise HTTPException(status_code=400, detail="用户角色不合法")
    from .auth import hash_password

    username = payload.username.strip()
    display_name = payload.display_name.strip() if payload.display_name else username
    with get_conn() as conn:
        exists = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="用户名已存在")
        cursor = conn.execute(
            """
            INSERT INTO users(username, password_hash, role, display_name, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                username,
                hash_password(payload.password),
                payload.role,
                display_name,
                utc_now(),
            ),
        )
        row = conn.execute(
            "SELECT id, username, role, display_name, is_active, created_at FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    write_audit(user, "create_user", "user", row["id"], {"username": username, "role": payload.role})
    return serialize_user(row)


def ensure_active_admin_remains(
    user_id: int,
    next_role: str | None = None,
    next_is_active: bool | None = None,
    deleting: bool = False,
) -> None:
    with get_conn() as conn:
        target = conn.execute(
            "SELECT role, is_active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not target or target["role"] != "admin" or not target["is_active"]:
            return
        removes_admin = deleting or next_role not in {None, "admin"} or next_is_active is False
        if not removes_admin:
            return
        active_admins = conn.execute(
            "SELECT COUNT(*) AS count FROM users WHERE role = 'admin' AND is_active = 1"
        ).fetchone()["count"]
        if active_admins <= 1:
            raise HTTPException(status_code=400, detail="系统必须保留至少一个启用状态的管理员")


@app.patch("/api/users/{user_id}")
def update_user(user_id: int, payload: UserUpdateRequest, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "users.manage")
    ensure_active_admin_remains(user_id, payload.role, payload.is_active)
    updates = []
    values = []
    if payload.password:
        from .auth import hash_password

        updates.append("password_hash = ?")
        values.append(hash_password(payload.password))
    if payload.role is not None:
        if payload.role not in {*MANAGER_ROLES, "employee"}:
            raise HTTPException(status_code=400, detail="用户角色不合法")
        updates.append("role = ?")
        values.append(payload.role)
    if payload.display_name is not None:
        updates.append("display_name = ?")
        values.append(payload.display_name.strip())
    if payload.is_active is not None:
        updates.append("is_active = ?")
        values.append(1 if payload.is_active else 0)
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    with get_conn() as conn:
        exists = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", [*values, user_id])
        if payload.is_active is False:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        row = conn.execute(
            "SELECT id, username, role, display_name, is_active, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    write_audit(user, "update_user", "user", user_id, payload.model_dump(exclude_none=True))
    return serialize_user(row)


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "users.manage")
    ensure_active_admin_remains(user_id, deleting=True)
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, role, display_name FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    write_audit(user, "delete_user", "user", user_id, {"username": row["username"], "role": row["role"]})
    return {"deleted": True}


@app.post("/api/documents/upload")
def upload_document(
    file: UploadFile = File(...),
    access_level: str = Form(default="internal"),
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "documents.manage")
    if access_level not in {"public", "internal", "sensitive"}:
        raise HTTPException(status_code=400, detail="文档密级不合法")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"仅支持: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

    created = utc_now()
    safe_name = Path(file.filename or f"document{suffix}").name
    storage_name = f"{created.replace(':', '-').replace('+', 'Z')}_{safe_name}"
    storage_path = UPLOAD_DIR / storage_name

    save_upload_with_limit(file, storage_path)

    try:
        text = extract_text(storage_path)
        chunks = chunk_text(text)
    except Exception as exc:
        storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not chunks:
        storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="文档没有解析出有效文本")

    chunk_index = build_chunk_index(chunks)

    vector_items: list[ChunkVector] = []
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO documents(
                title, filename, file_type, storage_path, access_level,
                status, chunk_count, embedding_status, embedding_model, created_at
            )
            VALUES (?, ?, ?, 'pending', ?, 'indexing', 0, ?, ?, ?)
            """,
            (
                Path(safe_name).stem,
                safe_name,
                suffix.lstrip("."),
                access_level,
                chunk_index.status,
                chunk_index.model,
                created,
            ),
        )
        doc_id = cursor.lastrowid
        for index, item in enumerate(chunk_index.items):
            cursor = conn.execute(
                """
                INSERT INTO chunks(
                    document_id, chunk_index, content, token_json,
                    embedding_json, embedding_model, content_hash, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    index,
                    item.content,
                    item.token_json,
                    json.dumps(item.embedding),
                    chunk_index.model if item.embedding else None,
                    item.content_hash,
                    created,
                ),
            )
            if item.embedding and chunk_index.model:
                vector_items.append(
                    ChunkVector(
                        chunk_id=cursor.lastrowid,
                        document_id=doc_id,
                        embedding_model=chunk_index.model,
                        content_hash=item.content_hash,
                        embedding=item.embedding,
                    )
                )
        conn.execute(
            "UPDATE documents SET storage_path = ?, status = 'ready', chunk_count = ? WHERE id = ?",
            (str(storage_path), len(chunks), doc_id),
        )
        conn.execute(
            """
            INSERT INTO document_versions(document_id, version, action, title, access_level, chunk_count, created_by, created_at)
            VALUES (?, 1, 'upload', ?, ?, ?, ?, ?)
            """,
            (doc_id, Path(safe_name).stem, access_level, len(chunks), user["id"], created),
        )

    vector_result = sync_chunk_vectors(vector_items)

    write_audit(
        user,
        "upload_document",
        "document",
        doc_id,
        {
            "filename": safe_name,
            "access_level": access_level,
            "chunk_count": len(chunks),
            "embedding_gateway": chunk_index.provider_diagnostics(),
            "vector_store": vector_result.public_dict(),
        },
    )
    return {
        "id": doc_id,
        "filename": safe_name,
        "access_level": access_level,
        "chunk_count": len(chunks),
        "status": "ready",
        "embedding_status": chunk_index.status,
        "embedding_model": chunk_index.model,
        "embedding_gateway": chunk_index.provider_diagnostics(),
        "vector_store": vector_result.public_dict(),
    }


def save_upload_with_limit(file: UploadFile, storage_path: Path) -> None:
    written = 0
    try:
        with storage_path.open("wb") as buffer:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件大小不能超过 {format_byte_limit(MAX_UPLOAD_BYTES)}",
                    )
                buffer.write(chunk)
    except Exception:
        storage_path.unlink(missing_ok=True)
        raise


def format_byte_limit(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):g} MB"
    if size >= 1024:
        return f"{size / 1024:g} KB"
    return f"{size} B"


@app.post("/api/documents/embeddings/rebuild")
def rebuild_document_embeddings(
    payload: EmbeddingRebuildRequest,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "documents.manage")
    model = os.getenv("EMBEDDING_MODEL", "").strip()
    api_key = (os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()
    if not model or not api_key:
        raise HTTPException(status_code=400, detail="请先配置 EMBEDDING_MODEL 和 EMBEDDING_API_KEY")

    where = ["status = 'ready'"]
    values: list[object] = []
    if payload.document_ids:
        placeholders = ",".join("?" for _ in payload.document_ids)
        where.append(f"id IN ({placeholders})")
        values.extend(payload.document_ids)
    with get_conn() as conn:
        documents = conn.execute(
            f"""
            SELECT id, embedding_status, embedding_model
            FROM documents WHERE {' AND '.join(where)} ORDER BY id
            """,
            values,
        ).fetchall()

    details = []
    indexed = failed = skipped = 0
    for document in documents:
        if (
            not payload.force
            and document["embedding_status"] == "ready"
            and document["embedding_model"] == model
        ):
            skipped += 1
            details.append({"document_id": document["id"], "status": "skipped"})
            continue
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, content FROM chunks WHERE document_id = ? ORDER BY chunk_index, id",
                (document["id"],),
            ).fetchall()
        chunk_index = build_chunk_index([row["content"] for row in rows], model=model)
        if chunk_index.status != "ready" or len(chunk_index.items) != len(rows):
            failed += 1
            with get_conn() as conn:
                conn.execute(
                    "UPDATE documents SET embedding_status = ?, embedding_model = ? WHERE id = ?",
                    (chunk_index.status, chunk_index.model, document["id"]),
                )
            details.append(
                {
                    "document_id": document["id"],
                    "status": chunk_index.status,
                    "error": chunk_index.error,
                    "embedding_gateway": chunk_index.provider_diagnostics(),
                }
            )
            continue
        with get_conn() as conn:
            for row, item in zip(rows, chunk_index.items):
                conn.execute(
                    """
                    UPDATE chunks
                    SET token_json = ?, embedding_json = ?, embedding_model = ?, content_hash = ?
                    WHERE id = ?
                    """,
                    (
                        item.token_json,
                        json.dumps(item.embedding),
                        chunk_index.model,
                        item.content_hash,
                        row["id"],
                    ),
                )
            conn.execute(
                "UPDATE documents SET embedding_status = 'ready', embedding_model = ? WHERE id = ?",
                (chunk_index.model, document["id"]),
            )
        vector_result = sync_chunk_vectors(
            [
                ChunkVector(
                    chunk_id=row["id"],
                    document_id=document["id"],
                    embedding_model=chunk_index.model,
                    content_hash=item.content_hash,
                    embedding=item.embedding,
                )
                for row, item in zip(rows, chunk_index.items)
                if item.embedding and chunk_index.model
            ]
        )
        indexed += 1
        details.append(
            {
                "document_id": document["id"],
                "status": "ready",
                "chunks": len(rows),
                "embedding_gateway": chunk_index.provider_diagnostics(),
                "vector_store": vector_result.public_dict(),
            }
        )

    summary = {
        "model": model,
        "total": len(documents),
        "indexed": indexed,
        "failed": failed,
        "skipped": skipped,
        "details": details,
    }
    write_audit(user, "rebuild_embeddings", "document_index", None, summary)
    return summary


@app.post("/api/documents/vector-store/sync")
def sync_document_vector_store(
    payload: VectorStoreSyncRequest,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "documents.manage")
    try:
        if vector_store_backend() != "pgvector":
            raise HTTPException(status_code=400, detail="RAG_VECTOR_STORE must be pgvector")
    except VectorStoreConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    where = ["d.status = 'ready'"]
    values: list[object] = []
    if payload.document_ids:
        placeholders = ",".join("?" for _ in payload.document_ids)
        where.append(f"d.id IN ({placeholders})")
        values.extend(payload.document_ids)
    with get_conn() as conn:
        documents = conn.execute(
            f"SELECT d.id FROM documents d WHERE {' AND '.join(where)} ORDER BY d.id",
            values,
        ).fetchall()

    indexed_documents = failed_documents = indexed_chunks = skipped_chunks = 0
    details = []
    for document in documents:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT id, embedding_json, embedding_model, content_hash
                FROM chunks
                WHERE document_id = ?
                ORDER BY id
                """,
                (document["id"],),
            ).fetchall()
        items = []
        for row in rows:
            embedding = _decode_embedding(row["embedding_json"])
            if not embedding or not row["embedding_model"]:
                skipped_chunks += 1
                continue
            items.append(
                ChunkVector(
                    chunk_id=row["id"],
                    document_id=document["id"],
                    embedding_model=row["embedding_model"],
                    content_hash=row["content_hash"],
                    embedding=embedding,
                )
            )
        cleanup_result = delete_document_vectors(document["id"])
        sync_result = sync_chunk_vectors(items)
        if cleanup_result.status == "ready" and sync_result.status == "ready":
            indexed_documents += 1
            indexed_chunks += sync_result.count
            status = "ready"
        else:
            failed_documents += 1
            status = "degraded"
        details.append(
            {
                "document_id": document["id"],
                "status": status,
                "chunks": len(items),
                "cleanup": cleanup_result.public_dict(),
                "sync": sync_result.public_dict(),
            }
        )

    summary = {
        "backend": "pgvector",
        "documents": len(documents),
        "indexed_documents": indexed_documents,
        "failed_documents": failed_documents,
        "indexed_chunks": indexed_chunks,
        "skipped_chunks": skipped_chunks,
        "details": details,
    }
    write_audit(user, "sync_vector_store", "document_index", None, summary)
    return summary


def _decode_embedding(raw: str | None) -> list[float]:
    try:
        value = json.loads(raw or "[]")
        return [float(item) for item in value] if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


@app.get("/api/documents")
def list_documents(
    q: str | None = None,
    access_level: str | None = None,
    file_type: str | None = None,
    sort: str = "newest",
    page: int = 1,
    page_size: int = 5,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "documents.view")
    page, page_size, offset = normalize_pagination(page, page_size)
    levels = allowed_access_levels(user)
    if access_level:
        if access_level not in levels:
            return []
        levels = [access_level]
    placeholders = ",".join("?" for _ in levels)
    where = [f"access_level IN ({placeholders})"]
    values = list(levels)
    if q:
        where.append("(title LIKE ? OR filename LIKE ?)")
        values.extend([f"%{q.strip()}%", f"%{q.strip()}%"])
    if file_type:
        where.append("file_type = ?")
        values.append(file_type.strip().lower())
    order_by = "created_at ASC" if sort == "oldest" else "created_at DESC"
    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS count FROM documents WHERE {' AND '.join(where)}",
            values,
        ).fetchone()["count"]
        rows = conn.execute(
            f"""
            SELECT id, title, filename, file_type, access_level, status, chunk_count, version,
                   embedding_status, embedding_model, created_at
            FROM documents
            WHERE {' AND '.join(where)}
            ORDER BY {order_by}, id DESC
            LIMIT ? OFFSET ?
            """,
            [*values, page_size, offset],
        ).fetchall()
    return paginated([dict(row) for row in rows], total, page, page_size)


@app.get("/api/documents/{document_id}/chunks")
def list_document_chunks(
    document_id: int,
    page: int = 1,
    page_size: int = 5,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "documents.view")
    page, page_size, offset = normalize_pagination(page, page_size)
    levels = allowed_access_levels(user)
    placeholders = ",".join("?" for _ in levels)
    with get_conn() as conn:
        document = conn.execute(
            f"""
            SELECT id, title, filename, file_type, access_level, status, chunk_count, version,
                   embedding_status, embedding_model, created_at
            FROM documents
            WHERE id = ? AND access_level IN ({placeholders})
            """,
            [document_id, *levels],
        ).fetchone()
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在或无权访问")
        total = conn.execute(
            "SELECT COUNT(*) AS count FROM chunks WHERE document_id = ?",
            (document_id,),
        ).fetchone()["count"]
        chunks = conn.execute(
            """
            SELECT id, chunk_index, content, created_at
            FROM chunks WHERE document_id = ?
            ORDER BY chunk_index
            LIMIT ? OFFSET ?
            """,
            (document_id, page_size, offset),
        ).fetchall()

    result = paginated([dict(row) for row in chunks], total, page, page_size)
    result["document"] = dict(document)
    return result


@app.patch("/api/documents/{document_id}")
def update_document(document_id: int, payload: DocumentUpdateRequest, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "documents.manage")
    updates = []
    values = []
    if payload.title is not None:
        updates.append("title = ?")
        values.append(payload.title.strip())
    if payload.access_level is not None:
        if payload.access_level not in {"public", "internal", "sensitive"}:
            raise HTTPException(status_code=400, detail="文档密级不合法")
        updates.append("access_level = ?")
        values.append(payload.access_level)
    if not updates:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    created = utc_now()
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT id, title, access_level, chunk_count, version FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="文档不存在")
        conn.execute(f"UPDATE documents SET {', '.join(updates)}, version = version + 1 WHERE id = ?", [*values, document_id])
        row = conn.execute(
            """
            SELECT id, title, filename, file_type, access_level, status, chunk_count, version,
                   embedding_status, embedding_model, created_at
            FROM documents WHERE id = ?
            """,
            (document_id,),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO document_versions(document_id, version, action, title, access_level, chunk_count, created_by, created_at)
            VALUES (?, ?, 'metadata_update', ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                row["version"],
                row["title"],
                row["access_level"],
                row["chunk_count"],
                user["id"],
                created,
            ),
        )
    write_audit(user, "update_document", "document", document_id, payload.model_dump(exclude_none=True))
    return dict(row)


@app.get("/api/documents/{document_id}/versions")
def list_document_versions(
    document_id: int,
    page: int = 1,
    page_size: int = 5,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "documents.view")
    page, page_size, offset = normalize_pagination(page, page_size)
    levels = allowed_access_levels(user)
    placeholders = ",".join("?" for _ in levels)
    with get_conn() as conn:
        document = conn.execute(
            f"SELECT id FROM documents WHERE id = ? AND access_level IN ({placeholders})",
            [document_id, *levels],
        ).fetchone()
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在或无权访问")
        total = conn.execute(
            "SELECT COUNT(*) AS count FROM document_versions WHERE document_id = ?",
            (document_id,),
        ).fetchone()["count"]
        rows = conn.execute(
            """
            SELECT v.id, v.document_id, v.version, v.action, v.title, v.access_level, v.chunk_count, v.created_at,
                   u.username, u.display_name
            FROM document_versions v
            LEFT JOIN users u ON u.id = v.created_by
            WHERE v.document_id = ?
            ORDER BY v.version DESC, v.id DESC
            LIMIT ? OFFSET ?
            """,
            (document_id, page_size, offset),
        ).fetchall()
    return paginated([dict(row) for row in rows], total, page, page_size)


@app.post("/api/documents/{document_id}/reindex")
def reindex_document(document_id: int, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "documents.manage")
    with get_conn() as conn:
        document = conn.execute(
            "SELECT id, title, access_level, storage_path, version FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if not document:
            raise HTTPException(status_code=404, detail="文档不存在")

    path = Path(document["storage_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="原始文件不存在，无法重新索引")

    text = extract_text(path)
    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="文档没有解析出有效文本")

    chunk_index = build_chunk_index(chunks)

    created = utc_now()
    vector_items: list[ChunkVector] = []
    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        for index, item in enumerate(chunk_index.items):
            cursor = conn.execute(
                """
                INSERT INTO chunks(
                    document_id, chunk_index, content, token_json,
                    embedding_json, embedding_model, content_hash, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    index,
                    item.content,
                    item.token_json,
                    json.dumps(item.embedding),
                    chunk_index.model if item.embedding else None,
                    item.content_hash,
                    created,
                ),
            )
            if item.embedding and chunk_index.model:
                vector_items.append(
                    ChunkVector(
                        chunk_id=cursor.lastrowid,
                        document_id=document_id,
                        embedding_model=chunk_index.model,
                        content_hash=item.content_hash,
                        embedding=item.embedding,
                    )
                )
        conn.execute(
            """
            UPDATE documents
            SET chunk_count = ?, status = 'ready', version = version + 1,
                embedding_status = ?, embedding_model = ?
            WHERE id = ?
            """,
            (len(chunks), chunk_index.status, chunk_index.model, document_id),
        )
        new_version = int(document["version"] or 1) + 1
        conn.execute(
            """
            INSERT INTO document_versions(document_id, version, action, title, access_level, chunk_count, created_by, created_at)
            VALUES (?, ?, 'reindex', ?, ?, ?, ?, ?)
            """,
            (document_id, new_version, document["title"], document["access_level"], len(chunks), user["id"], created),
        )

    cleanup_result = delete_document_vectors(document_id)
    vector_result = sync_chunk_vectors(vector_items)

    write_audit(
        user,
        "reindex_document",
        "document",
        document_id,
        {
            "chunk_count": len(chunks),
            "embedding_gateway": chunk_index.provider_diagnostics(),
            "vector_cleanup": cleanup_result.public_dict(),
            "vector_store": vector_result.public_dict(),
        },
    )
    return {
        "id": document_id,
        "chunk_count": len(chunks),
        "status": "ready",
        "version": new_version,
        "embedding_status": chunk_index.status,
        "embedding_model": chunk_index.model,
        "embedding_gateway": chunk_index.provider_diagnostics(),
        "vector_cleanup": cleanup_result.public_dict(),
        "vector_store": vector_result.public_dict(),
    }


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: int, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "documents.manage")
    with get_conn() as conn:
        row = conn.execute("SELECT storage_path FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="文档不存在")
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    vector_result = delete_document_vectors(document_id)
    path = Path(row["storage_path"])
    path.unlink(missing_ok=True)
    write_audit(
        user,
        "delete_document",
        "document",
        document_id,
        {"storage_path": row["storage_path"], "vector_store": vector_result.public_dict()},
    )
    return {"deleted": True, "vector_store": vector_result.public_dict()}


@app.get("/api/search")
def search_preview(q: str, top_k: int = DEFAULT_TOP_K, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "retrieval.debug")
    if not q.strip():
        raise HTTPException(status_code=400, detail="检索问题不能为空")
    top_k = max(1, min(top_k, 10))
    levels = allowed_access_levels(user)
    hits = search_chunks(q.strip(), top_k, levels)
    retrieval_mode = hits[0].retrieval_mode if hits else "bm25"
    return {
        "query": q.strip(),
        "explanation": {
            "algorithm": "字段加权 BM25 + 向量召回 + 本地重排" if retrieval_mode == "hybrid" else "字段加权 BM25 + 本地重排",
            "retrieval_mode": retrieval_mode,
            "vector_backend": hits[0].vector_backend if hits else "none",
            "vector_degraded": hits[0].vector_degraded if hits else False,
            "vector_error": hits[0].vector_error if hits else None,
            "lexical_backend": hits[0].lexical_backend if hits else "sqlite_fts5",
            "lexical_degraded": hits[0].lexical_degraded if hits else False,
            "lexical_error": hits[0].lexical_error if hits else None,
            "candidate_count": hits[0].candidate_count if hits else 0,
            "corpus_count": hits[0].corpus_count if hits else 0,
            "permission_scope": levels,
            "query_terms": hits[0].query_terms if hits else sorted(token_counts(q.strip()).keys())[:20],
            "ranking_rule": "先按权限过滤，以正文 70%、标题 30% 计算字段加权 BM25，再融合可用的向量相似度和本地重排分数。",
        },
        "hits": [
            {
                "chunk_id": hit.chunk_id,
                "document_id": hit.document_id,
                "document_title": hit.document_title,
                "document_filename": hit.document_filename,
                "document_access_level": hit.document_access_level,
                "chunk_index": hit.chunk_index,
                "score": round(hit.score, 4),
                "retrieval_mode": hit.retrieval_mode,
                "vector_backend": hit.vector_backend,
                "vector_degraded": hit.vector_degraded,
                "lexical_backend": hit.lexical_backend,
                "lexical_degraded": hit.lexical_degraded,
                "score_breakdown": {
                    "bm25": round(hit.bm25_score, 4),
                    "vector": round(hit.vector_score, 4),
                    "rerank": round(hit.rerank_score, 4),
                    "final": round(hit.score, 4),
                },
                "matched_terms": hit.matched_terms,
                "why": (
                    f"使用 {hit.retrieval_mode} 召回并重排；命中 {len(hit.matched_terms)} 个问题词项，"
                    f"当前角色可访问 {hit.document_access_level} 密级。"
                ),
                "content": hit.content,
            }
            for hit in hits
        ],
    }


@app.post("/api/ask")
def ask(
    payload: AskRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "qa.use")
    result = run_ask(payload, user)
    background_tasks.add_task(run_quality_assessment, result["log_id"])
    return result


@app.post("/api/agent/run")
def agent_run(payload: AgentRunRequest, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "qa.use")
    run_id = create_agent_run(payload.goal, user, top_k=payload.top_k)
    try:
        result = run_agent(payload.goal, payload.top_k, user)
    except Exception as exc:
        result = runtime_error_result(exc)
        finish_agent_run(run_id, result)
        raise HTTPException(status_code=500, detail="Agent 运行失败，请查看运行记录") from exc
    finish_agent_run(run_id, result)
    return {"run_id": run_id, **result}


@app.post("/api/agent/tasks", status_code=202)
def create_agent_task(
    payload: AgentTaskRequest,
    request: Request,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "qa.use")
    try:
        run_id, reused = create_or_get_agent_task(
            payload.goal,
            payload.top_k,
            user,
            idempotency_key=payload.idempotency_key,
        )
    except AgentTaskConflictError as exc:
        raise HTTPException(status_code=409, detail="幂等键已用于其他任务参数") from exc
    except AgentTaskLimitError as exc:
        raise HTTPException(status_code=429, detail="当前运行中的 Agent 任务过多，请稍后再试") from exc
    if not reused:
        try:
            request.app.state.agent_executor.submit(
                execute_agent_task,
                run_id,
                payload.goal,
                payload.top_k,
                dict(user),
            )
        except RuntimeError as exc:
            finish_agent_run(run_id, runtime_error_result(exc))
            raise HTTPException(status_code=503, detail="Agent 任务执行器暂不可用") from exc
        write_audit(
            user,
            "agent_task_queued",
            "agent_run",
            run_id,
            {"top_k": payload.top_k, "idempotent": bool(payload.idempotency_key)},
        )
    result = get_agent_run_for_user(run_id, user)
    result["run_id"] = run_id
    result["reused"] = reused
    return result


@app.get("/api/agent/runs")
def list_agent_runs(
    page: int = 1,
    page_size: int = 5,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "qa.use")
    page, page_size, offset = normalize_pagination(page, page_size)
    where = []
    values: list[object] = []
    if user["role"] not in MANAGER_ROLES:
        where.append("a.user_id = ?")
        values.append(user["id"])
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with get_conn() as conn:
        total = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM agent_runs a
            {clause}
            """,
            values,
        ).fetchone()["count"]
        rows = conn.execute(
            f"""
            SELECT a.id, a.goal, a.status, a.final_answer, a.tool_calls_json,
                   a.plan_json, a.planner_mode, a.error_message, a.started_at, a.completed_at, a.created_at,
                   a.execution_mode, a.top_k, a.idempotency_key, a.parent_run_id,
                   a.cancel_requested_at, a.updated_at,
                   u.username, u.display_name
            FROM agent_runs a
            LEFT JOIN users u ON u.id = a.user_id
            {clause}
            ORDER BY a.id DESC
            LIMIT ? OFFSET ?
            """,
            [*values, page_size, offset],
        ).fetchall()
    items = []
    for row in rows:
        items.append(serialize_agent_run(row))
    return paginated(items, total, page, page_size)


@app.get("/api/agent/runs/{run_id}")
def get_agent_run(run_id: int, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "qa.use")
    return get_agent_run_for_user(run_id, user)


@app.post("/api/agent/runs/{run_id}/cancel")
def cancel_agent_run(run_id: int, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "qa.use")
    current = get_agent_run_for_user(run_id, user)
    if current["execution_mode"] != "async":
        raise HTTPException(status_code=409, detail="同步 Agent 运行不支持取消")
    status = request_agent_run_cancel(run_id)
    if status == "cancel_requested" and current["status"] != "cancel_requested":
        write_audit(user, "agent_task_cancel_requested", "agent_run", run_id, {"previous_status": current["status"]})
    return get_agent_run_for_user(run_id, user)


@app.post("/api/agent/runs/{run_id}/retry", status_code=202)
def retry_agent_run(
    run_id: int,
    payload: AgentRetryRequest,
    request: Request,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "qa.use")
    current = get_agent_run_for_user(run_id, user)
    if current["status"] not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="仅失败或已取消的任务可以重试")
    try:
        retry_run_id, reused = create_or_get_agent_task(
            current["goal"],
            current["top_k"],
            user,
            idempotency_key=payload.idempotency_key,
            parent_run_id=run_id,
        )
    except AgentTaskConflictError as exc:
        raise HTTPException(status_code=409, detail="幂等键已用于其他任务参数") from exc
    except AgentTaskLimitError as exc:
        raise HTTPException(status_code=429, detail="当前运行中的 Agent 任务过多，请稍后再试") from exc
    if not reused:
        try:
            request.app.state.agent_executor.submit(
                execute_agent_task,
                retry_run_id,
                current["goal"],
                current["top_k"],
                dict(user),
            )
        except RuntimeError as exc:
            finish_agent_run(retry_run_id, runtime_error_result(exc))
            raise HTTPException(status_code=503, detail="Agent 任务执行器暂不可用") from exc
        write_audit(user, "agent_task_retried", "agent_run", retry_run_id, {"parent_run_id": run_id})
    result = get_agent_run_for_user(retry_run_id, user)
    result["run_id"] = retry_run_id
    result["reused"] = reused
    return result


def compute_answer(payload: AskRequest, user: dict) -> dict:
    question = payload.question.strip()
    security_result = inspect_question(question)
    if not security_result.allowed:
        return {
            "answer": "该问题触发安全策略，系统已拒绝执行。",
            "confidence": 0.0,
            "blocked": True,
            "block_reason": security_result.reason,
            "citations": [],
        }

    access_levels = allowed_access_levels(user)
    if has_restricted_topic_match(question, access_levels):
        answer, confidence, citations, generation = build_restricted_access_refusal()
    else:
        hits = search_chunks(question, payload.top_k, access_levels)
        answer, confidence, citations, generation = build_grounded_answer(question, hits)
    return {
        "answer": answer,
        "confidence": round(confidence, 4),
        "blocked": False,
        "block_reason": None,
        "citations": citations,
        "generation": generation,
    }


def run_quality_assessment(log_id: int) -> None:
    try:
        with get_conn() as conn:
            row = conn.execute(
                """
                SELECT id, question, answer, confidence, blocked, citations_json
                FROM qa_logs WHERE id = ?
                """,
                (log_id,),
            ).fetchone()
            if not row:
                return
            feedback = conn.execute(
                """
                SELECT rating FROM qa_feedback
                WHERE log_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (log_id,),
            ).fetchone()
            citations = json.loads(row["citations_json"] or "[]")
            assessment = calculate_quality(
                confidence=row["confidence"],
                citation_scores=[float(item.get("score", 0)) for item in citations],
                feedback_rating=feedback["rating"] if feedback else None,
                blocked=bool(row["blocked"]),
            )
            conn.execute(
                """
                INSERT INTO qa_quality_assessments(
                    log_id, confidence_score, top_similarity_score, citation_score,
                    feedback_score, quality_score, quality_level, risk_reasons,
                    status, error_message, assessed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', NULL, ?)
                ON CONFLICT(log_id) DO UPDATE SET
                    confidence_score = excluded.confidence_score,
                    top_similarity_score = excluded.top_similarity_score,
                    citation_score = excluded.citation_score,
                    feedback_score = excluded.feedback_score,
                    quality_score = excluded.quality_score,
                    quality_level = excluded.quality_level,
                    risk_reasons = excluded.risk_reasons,
                    status = 'completed',
                    error_message = NULL,
                    assessed_at = excluded.assessed_at
                """,
                (
                    log_id,
                    assessment.confidence_score,
                    assessment.top_similarity_score,
                    assessment.citation_score,
                    assessment.feedback_score,
                    assessment.quality_score,
                    assessment.quality_level,
                    json.dumps(assessment.risk_reasons, ensure_ascii=False),
                    utc_now(),
                ),
            )
            if assessment.quality_level == "review" and not row["blocked"]:
                existing = conn.execute(
                    """
                    SELECT id FROM knowledge_gaps
                    WHERE source_log_id = ? AND status IN ('open', 'processing')
                    LIMIT 1
                    """,
                    (log_id,),
                ).fetchone()
                if not existing:
                    conn.execute(
                        """
                        INSERT INTO knowledge_gaps(
                            question, source_log_id, status, note, created_at
                        )
                        VALUES (?, ?, 'open', ?, ?)
                        """,
                        (
                            row["question"],
                            log_id,
                            "系统自动质量筛查发现回答需要人工复核",
                            utc_now(),
                        ),
                    )
    except Exception as exc:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO qa_quality_assessments(
                    log_id, confidence_score, top_similarity_score, citation_score,
                    feedback_score, quality_score, quality_level, risk_reasons,
                    status, error_message, assessed_at
                )
                VALUES (?, 0, 0, 0, 0, 0, 'failed', '[]', 'failed', ?, ?)
                ON CONFLICT(log_id) DO UPDATE SET
                    status = 'failed',
                    quality_level = 'failed',
                    error_message = excluded.error_message,
                    assessed_at = excluded.assessed_at
                """,
                (log_id, str(exc), utc_now()),
            )


def run_ask(payload: AskRequest, user: dict) -> dict:
    question = payload.question.strip()
    security_result = inspect_question(question)
    if not security_result.allowed:
        answer = "该问题触发安全策略，系统已拒绝执行。"
        usage = build_usage_summary(
            question,
            [],
            answer,
            {
                "mode": "blocked",
                "model": "none",
                "requested_model": None,
                "provider_usage": {},
                "fallback_reason": "security_policy",
            },
        )
        agent_trace = build_agent_trace(
            security_allowed=False,
            block_reason=security_result.reason,
            access_levels=[],
            hit_count=0,
            top_score=0,
            confidence=0,
            answer=answer,
            usage=usage,
        )
        with get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO qa_logs(
                    question, answer, confidence, blocked, block_reason, user_id,
                    citations_json, agent_trace_json, usage_json, created_at
                )
                VALUES (?, ?, 0, 1, ?, ?, '[]', ?, ?, ?)
                """,
                (
                    question,
                    answer,
                    security_result.reason,
                    user["id"],
                    json.dumps(agent_trace, ensure_ascii=False),
                    json.dumps(usage, ensure_ascii=False),
                    utc_now(),
                ),
            )
            log_id = cursor.lastrowid
        return {
            "log_id": log_id,
            "answer": answer,
            "confidence": 0,
            "blocked": True,
            "block_reason": security_result.reason,
            "citations": [],
            "agent_trace": agent_trace,
            "usage": usage,
        }

    access_levels = allowed_access_levels(user)
    if has_restricted_topic_match(question, access_levels):
        hits = []
        answer, confidence, citations, generation = build_restricted_access_refusal()
    else:
        hits = search_chunks(question, payload.top_k, access_levels)
        answer, confidence, citations, generation = build_grounded_answer(question, hits)
    usage = build_usage_summary(question, citations, answer, generation)
    agent_trace = build_agent_trace(
        security_allowed=True,
        block_reason=None,
        access_levels=access_levels,
        hit_count=len(hits),
        top_score=hits[0].score if hits else 0,
        confidence=confidence,
        answer=answer,
        usage=usage,
    )

    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO qa_logs(
                question, answer, confidence, blocked, block_reason, user_id,
                citations_json, agent_trace_json, usage_json, created_at
            )
            VALUES (?, ?, ?, 0, NULL, ?, ?, ?, ?, ?)
            """,
            (
                question,
                answer,
                confidence,
                user["id"],
                json.dumps(citations, ensure_ascii=False),
                json.dumps(agent_trace, ensure_ascii=False),
                json.dumps(usage, ensure_ascii=False),
                utc_now(),
            ),
        )
        log_id = cursor.lastrowid

    return {
        "log_id": log_id,
        "answer": answer,
        "confidence": round(confidence, 4),
        "blocked": False,
        "block_reason": None,
        "citations": citations if user["role"] in MANAGER_ROLES else [],
        "agent_trace": agent_trace,
        "usage": usage,
    }


@app.get("/api/logs")
def list_logs(
    page: int = 1,
    page_size: int = 5,
    q: str | None = None,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "audit.view")
    page, page_size, offset = normalize_pagination(page, page_size)
    where = []
    values: list[object] = []
    if q:
        keyword = f"%{q.strip()}%"
        where.append("(q.question LIKE ? OR q.answer LIKE ? OR u.username LIKE ? OR u.display_name LIKE ?)")
        values.extend([keyword, keyword, keyword, keyword])
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with get_conn() as conn:
        total = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM qa_logs q LEFT JOIN users u ON u.id = q.user_id
            {clause}
            """,
            values,
        ).fetchone()["count"]
        rows = conn.execute(
            f"""
            SELECT q.id, q.question, q.answer, q.confidence, q.blocked, q.block_reason,
                   q.citations_json, q.agent_trace_json, q.usage_json, q.created_at,
                   u.username, u.display_name
            FROM qa_logs q
            LEFT JOIN users u ON u.id = q.user_id
            {clause}
            ORDER BY q.id DESC
            LIMIT ? OFFSET ?
            """,
            [*values, page_size, offset],
        ).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        item["blocked"] = bool(item["blocked"])
        item["citations"] = json.loads(item.pop("citations_json"))
        item["agent_trace"] = json.loads(item.pop("agent_trace_json") or "[]")
        item["usage"] = json.loads(item.pop("usage_json") or "{}")
        result.append(item)
    return paginated(result, total, page, page_size)


@app.delete("/api/logs")
def clear_logs(user: dict = Depends(current_user)) -> dict:
    require_admin(user)
    with get_conn() as conn:
        log_count = conn.execute("SELECT COUNT(*) AS count FROM qa_logs").fetchone()["count"]
        feedback_count = conn.execute("SELECT COUNT(*) AS count FROM qa_feedback").fetchone()["count"]
        detached_gap_count = conn.execute(
            "SELECT COUNT(*) AS count FROM knowledge_gaps WHERE source_log_id IS NOT NULL"
        ).fetchone()["count"]
        conn.execute("DELETE FROM qa_feedback")
        conn.execute("UPDATE knowledge_gaps SET source_log_id = NULL WHERE source_log_id IS NOT NULL")
        conn.execute("DELETE FROM qa_logs")
    write_audit(
        user,
        "clear_qa_logs",
        "qa_log",
        None,
        {"deleted_logs": log_count, "deleted_feedback": feedback_count, "detached_gaps": detached_gap_count},
    )
    return {"deleted_logs": log_count, "deleted_feedback": feedback_count, "detached_gaps": detached_gap_count}


@app.post("/api/qa-feedback")
def submit_qa_feedback(payload: QaFeedbackRequest, user: dict = Depends(current_user)) -> dict:
    rating = payload.rating.strip()
    if rating not in {"helpful", "unhelpful", "needs_info"}:
        raise HTTPException(status_code=400, detail="反馈类型不合法")
    note = (payload.note or "").strip()
    created = utc_now()
    with get_conn() as conn:
        log = conn.execute(
            "SELECT id, question, user_id, blocked FROM qa_logs WHERE id = ?",
            (payload.log_id,),
        ).fetchone()
        if not log:
            raise HTTPException(status_code=404, detail="问答记录不存在")
        if user["role"] not in MANAGER_ROLES and log["user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="无权反馈该问答记录")
        cursor = conn.execute(
            """
            INSERT INTO qa_feedback(log_id, rating, note, created_by, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(log_id, created_by) DO UPDATE SET
              rating = excluded.rating,
              note = excluded.note,
              created_at = excluded.created_at
            """,
            (payload.log_id, rating, note, user["id"], created),
        )
        feedback_id = cursor.lastrowid or conn.execute(
            "SELECT id FROM qa_feedback WHERE log_id = ? AND created_by = ?",
            (payload.log_id, user["id"]),
        ).fetchone()["id"]
        gap_id = None
        if rating == "helpful":
            conn.execute(
                """
                DELETE FROM knowledge_gaps
                WHERE source_log_id = ? AND created_by = ? AND status = 'open'
                """,
                (payload.log_id, user["id"]),
            )
        elif not log["blocked"]:
            existing_gap = conn.execute(
                """
                SELECT id FROM knowledge_gaps
                WHERE status != 'resolved' AND (source_log_id = ? OR question = ?)
                LIMIT 1
                """,
                (payload.log_id, log["question"]),
            ).fetchone()
            if existing_gap:
                gap_id = existing_gap["id"]
            else:
                gap_note = note or ("员工反馈回答无用" if rating == "unhelpful" else "员工反馈需要补充资料")
                gap_cursor = conn.execute(
                    """
                    INSERT INTO knowledge_gaps(question, source_log_id, status, note, created_by, created_at)
                    VALUES (?, ?, 'open', ?, ?, ?)
                    """,
                    (log["question"], payload.log_id, gap_note, user["id"], created),
                )
                gap_id = gap_cursor.lastrowid
    run_quality_assessment(payload.log_id)
    return {"id": feedback_id, "rating": rating, "gap_id": gap_id}


@app.get("/api/qa-feedback")
def list_qa_feedback(
    page: int = 1,
    page_size: int = 5,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "feedback.manage")
    page, page_size, offset = normalize_pagination(page, page_size)
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS count FROM qa_feedback").fetchone()["count"]
        rows = conn.execute(
            """
            SELECT f.id, f.log_id, f.rating, f.note, f.created_at,
                   q.question, q.answer, q.confidence, q.blocked,
                   u.username, u.display_name,
                   g.id AS gap_id, g.status AS gap_status
            FROM qa_feedback f
            JOIN qa_logs q ON q.id = f.log_id
            LEFT JOIN users u ON u.id = f.created_by
            LEFT JOIN knowledge_gaps g ON g.source_log_id = f.log_id AND g.status != 'resolved'
            ORDER BY f.id DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()
    return paginated([serialize_feedback(row) for row in rows], total, page, page_size)


@app.post("/api/evaluate")
def evaluate(payload: EvaluateRequest, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "evaluation.manage")
    ask_result = compute_answer(AskRequest(question=payload.question, top_k=DEFAULT_TOP_K), user)
    answer = ask_result["answer"]
    keywords = normalize_list(payload.expected_keywords)
    expected_documents = normalize_list(payload.expected_documents)
    score = keyword_score(answer, keywords, ask_result["confidence"])
    citation_hit = citation_hit_score(ask_result["citations"], expected_documents)

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO evaluations(question, expected_keywords, expected_documents, answer, score, citation_hit, user_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.question,
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(expected_documents, ensure_ascii=False),
                answer,
                score,
                citation_hit,
                user["id"],
                utc_now(),
            ),
        )

    return {
        "score": round(score, 4),
        "citation_hit": round(citation_hit, 4),
        "answer": answer,
        "ask_result": ask_result,
    }


@app.get("/api/evaluations")
def list_evaluations(
    page: int = 1,
    page_size: int = 5,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "evaluation.manage")
    page, page_size, offset = normalize_pagination(page, page_size)
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS count FROM evaluations").fetchone()["count"]
        rows = conn.execute(
            """
            SELECT e.id, e.question, e.expected_keywords, e.expected_documents, e.answer, e.score,
                   e.citation_hit, e.created_at,
                   u.username, u.display_name
            FROM evaluations e
            LEFT JOIN users u ON u.id = e.user_id
            ORDER BY e.id DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        item["expected_keywords"] = json.loads(item["expected_keywords"])
        item["expected_documents"] = json.loads(item["expected_documents"])
        result.append(item)
    return paginated(result, total, page, page_size)


@app.get("/api/evaluation/cases")
def list_evaluation_cases(
    page: int = 1,
    page_size: int = 5,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "evaluation.manage")
    page, page_size, offset = normalize_pagination(page, page_size)
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS count FROM evaluation_cases").fetchone()["count"]
        rows = conn.execute(
            """
            SELECT id, case_key, dataset_version, category, difficulty, capabilities_json,
                   actor_role, question, expected_keywords, required_keyword_groups_json,
                   forbidden_keywords_json, expected_documents, expected_document_groups_json,
                   forbidden_documents_json, min_citations, should_answer, created_at, updated_at
            FROM evaluation_cases ORDER BY id
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()
    result = [serialize_evaluation_case(row) for row in rows]
    return paginated(result, total, page, page_size)


@app.get("/api/evaluation/dataset")
def get_evaluation_dataset(user: dict = Depends(current_user)) -> dict:
    require_permission(user, "evaluation.manage")
    dataset = load_evaluation_dataset()
    baseline = load_evaluation_baseline()
    return {
        "version": dataset["version"],
        "description": dataset["description"],
        "case_count": len(dataset["cases"]),
        "roles": sorted({case["actor_role"] for case in dataset["cases"]}),
        "fingerprint": dataset["fingerprint"],
        "default_thresholds": DEFAULT_THRESHOLDS,
        "approved_baseline": {
            "version": baseline["version"],
            "dataset_fingerprint": baseline["dataset_fingerprint"],
            "top_k": baseline["top_k"],
            "metrics": baseline["metrics"],
        },
    }


@app.post("/api/evaluation/cases")
def create_evaluation_case(payload: EvaluationCaseRequest, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "evaluation.manage")
    keywords = normalize_list(payload.expected_keywords)
    documents = normalize_list(payload.expected_documents)
    created = utc_now()
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO evaluation_cases(
                case_key, dataset_version, category, actor_role, question,
                expected_keywords, expected_documents, should_answer, created_at, updated_at
            )
            VALUES (NULL, 'custom', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.category.strip().lower(),
                payload.actor_role,
                payload.question.strip(),
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(documents, ensure_ascii=False),
                1 if payload.should_answer else 0,
                created,
                created,
            ),
        )
        row = conn.execute(
            """
            SELECT id, case_key, dataset_version, category, difficulty, capabilities_json,
                   actor_role, question, expected_keywords, required_keyword_groups_json,
                   forbidden_keywords_json, expected_documents, expected_document_groups_json,
                   forbidden_documents_json, min_citations, should_answer, created_at, updated_at
            FROM evaluation_cases WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    write_audit(user, "create_evaluation_case", "evaluation_case", row["id"], {"question": payload.question})
    return serialize_evaluation_case(row)


@app.patch("/api/evaluation/cases/{case_id}")
def update_evaluation_case(case_id: int, payload: EvaluationCaseRequest, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "evaluation.manage")
    keywords = normalize_list(payload.expected_keywords)
    documents = normalize_list(payload.expected_documents)
    with get_conn() as conn:
        exists = conn.execute(
            "SELECT id, case_key, actor_role FROM evaluation_cases WHERE id = ?",
            (case_id,),
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="评测用例不存在")
        if exists["case_key"]:
            raise HTTPException(status_code=409, detail="版本化黄金用例只读，请在数据集文件中修改并升级版本")
        conn.execute(
            """
            UPDATE evaluation_cases
            SET category = ?, actor_role = ?, question = ?, expected_keywords = ?, expected_documents = ?,
                should_answer = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                payload.category.strip().lower(),
                payload.actor_role if "actor_role" in payload.model_fields_set else exists["actor_role"],
                payload.question.strip(),
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(documents, ensure_ascii=False),
                1 if payload.should_answer else 0,
                utc_now(),
                case_id,
            ),
        )
        row = conn.execute(
            """
            SELECT id, case_key, dataset_version, category, difficulty, capabilities_json,
                   actor_role, question, expected_keywords, required_keyword_groups_json,
                   forbidden_keywords_json, expected_documents, expected_document_groups_json,
                   forbidden_documents_json, min_citations, should_answer, created_at, updated_at
            FROM evaluation_cases WHERE id = ?
            """,
            (case_id,),
        ).fetchone()
    write_audit(user, "update_evaluation_case", "evaluation_case", case_id, {"question": payload.question})
    return serialize_evaluation_case(row)


@app.delete("/api/evaluation/cases/{case_id}")
def delete_evaluation_case(case_id: int, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "evaluation.manage")
    with get_conn() as conn:
        row = conn.execute("SELECT question, case_key FROM evaluation_cases WHERE id = ?", (case_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="评测用例不存在")
        if row["case_key"]:
            raise HTTPException(status_code=409, detail="版本化黄金用例不能删除")
        conn.execute("DELETE FROM evaluation_cases WHERE id = ?", (case_id,))
    write_audit(user, "delete_evaluation_case", "evaluation_case", case_id, {"question": row["question"]})
    return {"deleted": True}


@app.post("/api/evaluation/batch/run")
def run_batch_evaluation(payload: BatchEvaluateRequest, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "evaluation.manage")
    if payload.baseline_run_id and not payload.use_baseline:
        raise HTTPException(status_code=400, detail="禁用基线时不能指定 baseline_run_id")
    with get_conn() as conn:
        if payload.case_ids:
            placeholders = ",".join("?" for _ in payload.case_ids)
            rows = conn.execute(
                f"""
                SELECT id, case_key, dataset_version, category, difficulty, capabilities_json,
                       actor_role, question, expected_keywords, required_keyword_groups_json,
                       forbidden_keywords_json, expected_documents, expected_document_groups_json,
                       forbidden_documents_json, min_citations, should_answer
                FROM evaluation_cases WHERE id IN ({placeholders}) ORDER BY id
                """,
                payload.case_ids,
            ).fetchall()
        else:
            scope_clause = "" if payload.include_custom else "WHERE case_key IS NOT NULL"
            rows = conn.execute(
                f"""
                SELECT id, case_key, dataset_version, category, difficulty, capabilities_json,
                       actor_role, question, expected_keywords, required_keyword_groups_json,
                       forbidden_keywords_json, expected_documents, expected_document_groups_json,
                       forbidden_documents_json, min_citations, should_answer
                FROM evaluation_cases {scope_clause} ORDER BY id
                """
            ).fetchall()

    if not rows:
        raise HTTPException(status_code=400, detail="没有可运行的评测用例")

    cases = []
    for raw_row in rows:
        row = dict(raw_row)
        row["expected_keywords"] = json.loads(row["expected_keywords"])
        row["expected_documents"] = json.loads(row["expected_documents"])
        row["capabilities"] = json.loads(row.pop("capabilities_json", "[]") or "[]")
        row["required_keyword_groups"] = json.loads(
            row.pop("required_keyword_groups_json", "[]") or "[]"
        )
        row["forbidden_keywords"] = json.loads(
            row.pop("forbidden_keywords_json", "[]") or "[]"
        )
        row["expected_document_groups"] = json.loads(
            row.pop("expected_document_groups_json", "[]") or "[]"
        )
        row["forbidden_documents"] = json.loads(
            row.pop("forbidden_documents_json", "[]") or "[]"
        )
        row["should_answer"] = bool(row["should_answer"])
        cases.append(row)

    results = []
    for row in cases:
        keywords = row["expected_keywords"]
        expected_documents = row["expected_documents"]
        case_user = {**user, "role": row["actor_role"]}
        case_access_levels = allowed_access_levels(case_user)
        started = time.perf_counter()
        ask_result = compute_answer(AskRequest(question=row["question"], top_k=payload.top_k), case_user)
        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        generation = ask_result.get("generation") or {
            "mode": "blocked",
            "model": "none",
            "prompt_version": "grounded-answer-v1",
            "fallback_reason": "security_policy",
        }
        usage = build_usage_summary(
            row["question"], ask_result["citations"], ask_result["answer"], generation
        )
        score = keyword_score(ask_result["answer"], keywords, ask_result["confidence"])
        citation_hit = citation_hit_score(ask_result["citations"], expected_documents)
        should_answer = row["should_answer"]
        signals = evaluate_case_signals(
            answer=ask_result["answer"],
            confidence=ask_result["confidence"],
            citations=ask_result["citations"],
            expected_keywords=keywords,
            expected_documents=expected_documents,
            should_answer=should_answer,
            allowed_access_levels=case_access_levels,
            required_keyword_groups=row["required_keyword_groups"],
            forbidden_keywords=row["forbidden_keywords"],
            expected_document_groups=row["expected_document_groups"],
            forbidden_documents=row["forbidden_documents"],
            min_citations=row["min_citations"],
        )
        results.append(
            {
                "case_id": row["id"],
                "case_key": row["case_key"],
                "category": row["category"],
                "difficulty": row["difficulty"],
                "capabilities": row["capabilities"],
                "actor_role": row["actor_role"],
                "question": row["question"],
                "expected_keywords": keywords,
                "required_keyword_groups": row["required_keyword_groups"],
                "forbidden_keywords": row["forbidden_keywords"],
                "expected_documents": expected_documents,
                "expected_document_groups": row["expected_document_groups"],
                "forbidden_documents": row["forbidden_documents"],
                "min_citations": row["min_citations"],
                "answer": ask_result["answer"],
                "score": score,
                "confidence": ask_result["confidence"],
                "citation_hit": citation_hit,
                "citations": ask_result["citations"],
                "should_answer": should_answer,
                "retrieval_recall": signals.retrieval_recall,
                "reciprocal_rank": signals.reciprocal_rank,
                "answer_completeness": signals.answer_completeness,
                "citation_faithfulness": signals.citation_faithfulness,
                "answer_correct": signals.answer_correct,
                "abstention_correct": signals.abstention_correct,
                "access_control_correct": signals.access_control_correct,
                "forbidden_keyword_correct": signals.forbidden_keyword_correct,
                "forbidden_document_correct": signals.forbidden_document_correct,
                "citation_count_correct": signals.citation_count_correct,
                "safety_assertion_correct": signals.safety_assertion_correct,
                "generation_mode": usage["generation_mode"],
                "model": usage["model"],
                "prompt_version": usage["prompt_version"],
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "total_tokens": usage["total_tokens"],
                "estimated_cost_usd": usage["estimated_cost_usd"],
                "latency_ms": latency_ms,
            }
        )

    summary = summarize_evaluation_results(results)
    breakdowns = summarize_evaluation_breakdowns(results)
    benchmark = {
        "generation_modes": sorted({item["generation_mode"] for item in results}),
        "models": sorted({item["model"] for item in results}),
        "prompt_versions": sorted({item["prompt_version"] for item in results}),
        "total_prompt_tokens": sum(item["prompt_tokens"] for item in results),
        "total_completion_tokens": sum(item["completion_tokens"] for item in results),
        "total_tokens": sum(item["total_tokens"] for item in results),
        "estimated_cost_usd": round(sum(item["estimated_cost_usd"] for item in results), 6),
        "avg_latency_ms": round(sum(item["latency_ms"] for item in results) / len(results), 2),
    }
    versions = sorted({row["dataset_version"] for row in cases})
    dataset_version = versions[0] if len(versions) == 1 else "mixed"
    dataset_hash = cases_fingerprint(cases)
    baseline = (
        find_evaluation_baseline(payload.baseline_run_id, dataset_hash, payload.top_k)
        if payload.use_baseline
        else None
    )
    policy = QualityGatePolicy(
        thresholds=payload.thresholds.model_dump(),
        minimum_cases=payload.minimum_cases,
        max_regression=payload.max_regression,
    )
    gate = evaluate_quality_gate(summary, policy, baseline)
    created = utc_now()

    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO batch_eval_runs(
                user_id, dataset_version, dataset_hash, top_k,
                total, avg_score, avg_confidence, citation_hit_rate,
                recall_at_k, mrr, answer_accuracy, abstention_accuracy, access_control_accuracy,
                gate_status, thresholds_json, minimum_cases, max_regression,
                failed_metrics_json, metric_deltas_json, baseline_run_id, baseline_reference, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                dataset_version,
                dataset_hash,
                payload.top_k,
                summary["total"],
                summary["avg_score"],
                summary["avg_confidence"],
                summary["citation_hit_rate"],
                summary["recall_at_k"],
                summary["mrr"],
                summary["answer_accuracy"],
                summary["abstention_accuracy"],
                summary["access_control_accuracy"],
                gate["status"],
                json.dumps(gate["thresholds"], ensure_ascii=False),
                gate["minimum_cases"],
                gate["max_regression"],
                json.dumps(gate["failed_metrics"], ensure_ascii=False),
                json.dumps(gate["metric_deltas"], ensure_ascii=False),
                gate["baseline_run_id"],
                str(gate["baseline_reference"]) if gate["baseline_reference"] is not None else None,
                created,
            ),
        )
        run_id = cursor.lastrowid
        conn.execute(
            """
            UPDATE batch_eval_runs
            SET citation_faithfulness = ?, safety_assertion_accuracy = ?,
                generation_modes_json = ?, models_json = ?, prompt_versions_json = ?,
                total_prompt_tokens = ?, total_completion_tokens = ?, total_tokens = ?,
                estimated_cost_usd = ?, avg_latency_ms = ?, breakdown_json = ?
            WHERE id = ?
            """,
            (
                summary["citation_faithfulness"],
                summary["safety_assertion_accuracy"],
                json.dumps(benchmark["generation_modes"], ensure_ascii=False),
                json.dumps(benchmark["models"], ensure_ascii=False),
                json.dumps(benchmark["prompt_versions"], ensure_ascii=False),
                benchmark["total_prompt_tokens"],
                benchmark["total_completion_tokens"],
                benchmark["total_tokens"],
                benchmark["estimated_cost_usd"],
                benchmark["avg_latency_ms"],
                json.dumps(breakdowns, ensure_ascii=False),
                run_id,
            ),
        )
        for item in results:
            result_cursor = conn.execute(
                """
                INSERT INTO batch_eval_results(
                    run_id, case_id, actor_role, question, expected_keywords, expected_documents,
                    answer, score, confidence, citation_hit, citations_json,
                    should_answer, retrieval_recall, reciprocal_rank,
                    answer_correct, abstention_correct, access_control_correct, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    item["case_id"],
                    item["actor_role"],
                    item["question"],
                    json.dumps(item["expected_keywords"], ensure_ascii=False),
                    json.dumps(item["expected_documents"], ensure_ascii=False),
                    item["answer"],
                    item["score"],
                    item["confidence"],
                    item["citation_hit"],
                    json.dumps(item["citations"], ensure_ascii=False),
                    1 if item["should_answer"] else 0,
                    item["retrieval_recall"],
                    item["reciprocal_rank"],
                    item["answer_correct"],
                    item["abstention_correct"],
                    item["access_control_correct"],
                    created,
                ),
            )
            conn.execute(
                """
                UPDATE batch_eval_results
                SET difficulty = ?, capabilities_json = ?,
                    required_keyword_groups_json = ?, forbidden_keywords_json = ?,
                    expected_document_groups_json = ?, forbidden_documents_json = ?,
                    min_citations = ?, answer_completeness = ?, citation_faithfulness = ?,
                    forbidden_keyword_correct = ?, forbidden_document_correct = ?,
                    citation_count_correct = ?, safety_assertion_correct = ?,
                    generation_mode = ?, model = ?, prompt_version = ?,
                    prompt_tokens = ?, completion_tokens = ?, total_tokens = ?,
                    estimated_cost_usd = ?, latency_ms = ?
                WHERE id = ?
                """,
                (
                    item["difficulty"],
                    json.dumps(item["capabilities"], ensure_ascii=False),
                    json.dumps(item["required_keyword_groups"], ensure_ascii=False),
                    json.dumps(item["forbidden_keywords"], ensure_ascii=False),
                    json.dumps(item["expected_document_groups"], ensure_ascii=False),
                    json.dumps(item["forbidden_documents"], ensure_ascii=False),
                    item["min_citations"],
                    item["answer_completeness"],
                    item["citation_faithfulness"],
                    item["forbidden_keyword_correct"],
                    item["forbidden_document_correct"],
                    item["citation_count_correct"],
                    item["safety_assertion_correct"],
                    item["generation_mode"],
                    item["model"],
                    item["prompt_version"],
                    item["prompt_tokens"],
                    item["completion_tokens"],
                    item["total_tokens"],
                    item["estimated_cost_usd"],
                    item["latency_ms"],
                    result_cursor.lastrowid,
                ),
            )

    write_audit(
        user,
        "run_evaluation_gate",
        "batch_eval_run",
        run_id,
        {
            "dataset_version": dataset_version,
            "dataset_hash": dataset_hash,
            "gate_status": gate["status"],
            "failed_metrics": gate["failed_metrics"],
        },
    )
    return {
        "run_id": run_id,
        "dataset": {
            "version": dataset_version,
            "fingerprint": dataset_hash,
            "top_k": payload.top_k,
        },
        "summary": rounded_summary(summary),
        "breakdowns": breakdowns,
        "benchmark": benchmark,
        "gate": gate,
        "results": [
            {
                **item,
                "score": round(item["score"], 4),
                "confidence": round(item["confidence"], 4),
                "citation_hit": round(item["citation_hit"], 4),
                "retrieval_recall": (
                    round(item["retrieval_recall"], 4) if item["retrieval_recall"] is not None else None
                ),
                "reciprocal_rank": (
                    round(item["reciprocal_rank"], 4) if item["reciprocal_rank"] is not None else None
                ),
            }
            for item in results
        ],
    }


@app.get("/api/evaluation/batch/runs")
def list_batch_runs(
    page: int = 1,
    page_size: int = 5,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "evaluation.manage")
    page, page_size, offset = normalize_pagination(page, page_size)
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS count FROM batch_eval_runs").fetchone()["count"]
        rows = conn.execute(
            """
            SELECT r.id, r.dataset_version, r.dataset_hash, r.top_k,
                   r.total, r.avg_score, r.avg_confidence, r.citation_hit_rate,
                   r.recall_at_k, r.mrr, r.answer_accuracy, r.abstention_accuracy, r.access_control_accuracy,
                   r.citation_faithfulness, r.safety_assertion_accuracy,
                   r.generation_modes_json, r.models_json, r.prompt_versions_json,
                   r.total_prompt_tokens, r.total_completion_tokens, r.total_tokens,
                   r.estimated_cost_usd, r.avg_latency_ms, r.breakdown_json,
                   r.gate_status, r.thresholds_json, r.minimum_cases, r.max_regression,
                   r.failed_metrics_json, r.metric_deltas_json, r.baseline_run_id, r.baseline_reference, r.created_at,
                   u.display_name
            FROM batch_eval_runs r
            LEFT JOIN users u ON u.id = r.user_id
            ORDER BY r.id DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()
    return paginated([serialize_batch_run(row) for row in rows], total, page, page_size)


@app.get("/api/evaluation/batch/runs/{run_id}/export")
def export_batch_run(run_id: int, format: str = "md", user: dict = Depends(current_user)) -> PlainTextResponse:
    require_permission(user, "evaluation.manage")
    with get_conn() as conn:
        if user["role"] in MANAGER_ROLES:
            run = conn.execute(
                """
                SELECT r.id, r.dataset_version, r.dataset_hash, r.top_k,
                       r.total, r.avg_score, r.avg_confidence, r.citation_hit_rate,
                       r.recall_at_k, r.mrr, r.answer_accuracy, r.abstention_accuracy, r.access_control_accuracy,
                       r.citation_faithfulness, r.safety_assertion_accuracy,
                       r.generation_modes_json, r.models_json, r.prompt_versions_json,
                       r.total_prompt_tokens, r.total_completion_tokens, r.total_tokens,
                       r.estimated_cost_usd, r.avg_latency_ms, r.breakdown_json,
                       r.gate_status, r.thresholds_json, r.minimum_cases, r.max_regression,
                       r.failed_metrics_json, r.metric_deltas_json, r.baseline_run_id, r.baseline_reference, r.created_at,
                       u.display_name
                FROM batch_eval_runs r
                LEFT JOIN users u ON u.id = r.user_id
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
        else:
            run = conn.execute(
                """
                SELECT r.id, r.dataset_version, r.dataset_hash, r.top_k,
                       r.total, r.avg_score, r.avg_confidence, r.citation_hit_rate,
                       r.recall_at_k, r.mrr, r.answer_accuracy, r.abstention_accuracy, r.access_control_accuracy,
                       r.citation_faithfulness, r.safety_assertion_accuracy,
                       r.generation_modes_json, r.models_json, r.prompt_versions_json,
                       r.total_prompt_tokens, r.total_completion_tokens, r.total_tokens,
                       r.estimated_cost_usd, r.avg_latency_ms, r.breakdown_json,
                       r.gate_status, r.thresholds_json, r.minimum_cases, r.max_regression,
                       r.failed_metrics_json, r.metric_deltas_json, r.baseline_run_id, r.baseline_reference, r.created_at,
                       u.display_name
                FROM batch_eval_runs r
                LEFT JOIN users u ON u.id = r.user_id
                WHERE r.id = ? AND r.user_id = ?
                """,
                (run_id, user["id"]),
            ).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail="批量评测记录不存在")
        rows = conn.execute(
            """
            SELECT actor_role, question, expected_keywords, expected_documents, answer, score,
                   confidence, citation_hit, citations_json, should_answer,
                   retrieval_recall, reciprocal_rank, answer_correct, abstention_correct,
                   access_control_correct, difficulty, capabilities_json,
                   answer_completeness, citation_faithfulness,
                   forbidden_keyword_correct, forbidden_document_correct,
                   citation_count_correct, safety_assertion_correct,
                   generation_mode, model, prompt_version,
                   prompt_tokens, completion_tokens, total_tokens,
                   estimated_cost_usd, latency_ms
            FROM batch_eval_results
            WHERE run_id = ?
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()

    run_dict = serialize_batch_run(run)
    results = [dict(row) for row in rows]
    if format.lower() == "csv":
        content = render_batch_csv(run_dict, results)
        media_type = "text/csv; charset=utf-8"
        filename = f"batch_eval_run_{run_id}.csv"
    else:
        content = render_batch_markdown(run_dict, results)
        media_type = "text/markdown; charset=utf-8"
        filename = f"batch_eval_run_{run_id}.md"
    return PlainTextResponse(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/stats")
def stats(user: dict = Depends(current_user)) -> dict:
    if not (has_permission(user, "evaluation.manage") or has_permission(user, "health.view")):
        raise HTTPException(status_code=403, detail="当前角色没有查看统计数据的权限")
    levels = allowed_access_levels(user)
    placeholders = ",".join("?" for _ in levels)
    with get_conn() as conn:
        document_count = conn.execute(
            f"SELECT COUNT(*) AS count FROM documents WHERE access_level IN ({placeholders})",
            levels,
        ).fetchone()["count"]
        chunk_count = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE d.access_level IN ({placeholders})
            """,
            levels,
        ).fetchone()["count"]

        if user["role"] in MANAGER_ROLES:
            qa_count = conn.execute("SELECT COUNT(*) AS count FROM qa_logs").fetchone()["count"]
            blocked_count = conn.execute("SELECT COUNT(*) AS count FROM qa_logs WHERE blocked = 1").fetchone()["count"]
            avg_confidence = conn.execute(
                "SELECT AVG(confidence) AS value FROM qa_logs WHERE blocked = 0 AND confidence > 0"
            ).fetchone()["value"]
            evaluation_count = conn.execute("SELECT COUNT(*) AS count FROM evaluations").fetchone()["count"]
            avg_evaluation_score = conn.execute("SELECT AVG(score) AS value FROM evaluations").fetchone()["value"]
            usage_rows = conn.execute("SELECT usage_json FROM qa_logs").fetchall()
        else:
            qa_count = conn.execute("SELECT COUNT(*) AS count FROM qa_logs WHERE user_id = ?", (user["id"],)).fetchone()[
                "count"
            ]
            blocked_count = conn.execute(
                "SELECT COUNT(*) AS count FROM qa_logs WHERE blocked = 1 AND user_id = ?", (user["id"],)
            ).fetchone()["count"]
            avg_confidence = conn.execute(
                """
                SELECT AVG(confidence) AS value
                FROM qa_logs WHERE blocked = 0 AND confidence > 0 AND user_id = ?
                """,
                (user["id"],),
            ).fetchone()["value"]
            evaluation_count = conn.execute(
                "SELECT COUNT(*) AS count FROM evaluations WHERE user_id = ?", (user["id"],)
            ).fetchone()["count"]
            avg_evaluation_score = conn.execute(
                "SELECT AVG(score) AS value FROM evaluations WHERE user_id = ?", (user["id"],)
            ).fetchone()["value"]
            usage_rows = conn.execute("SELECT usage_json FROM qa_logs WHERE user_id = ?", (user["id"],)).fetchall()

        ai_usage = summarize_ai_usage([row["usage_json"] for row in usage_rows])

    return {
        "document_count": document_count,
        "chunk_count": chunk_count,
        "qa_count": qa_count,
        "blocked_count": blocked_count,
        "avg_confidence": round(avg_confidence or 0, 4),
        "evaluation_count": evaluation_count,
        "avg_evaluation_score": round(avg_evaluation_score or 0, 4),
        "llm_enabled": bool(os.getenv("LLM_API_KEY", "").strip()),
        "ai_usage": ai_usage,
    }


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(current_user)) -> dict:
    require_permission(user, "health.view")
    base_stats = stats(user)
    base_analytics = analytics(user)
    recent_logs = list_logs(page=1, page_size=6, user=user)["items"] if has_permission(user, "audit.view") else []
    recent_runs = list_batch_runs(page=1, page_size=3, user=user)["items"] if has_permission(user, "evaluation.manage") else []
    levels = allowed_access_levels(user)
    placeholders = ",".join("?" for _ in levels)
    today = utc_now()[:10]
    with get_conn() as conn:
        if user["role"] in MANAGER_ROLES:
            user_count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
            active_user_count = conn.execute("SELECT COUNT(*) AS count FROM users WHERE is_active = 1").fetchone()[
                "count"
            ]
            today_qa_count = conn.execute(
                "SELECT COUNT(*) AS count FROM qa_logs WHERE substr(created_at, 1, 10) = ?",
                (today,),
            ).fetchone()["count"]
            low_confidence_rows = conn.execute(
                """
                SELECT id, question, confidence, created_at
                FROM qa_logs
                WHERE blocked = 0 AND confidence < 0.18
                ORDER BY id DESC LIMIT 5
                """
            ).fetchall()
            low_confidence_count = conn.execute(
                "SELECT COUNT(*) AS count FROM qa_logs WHERE blocked = 0 AND confidence < 0.18"
            ).fetchone()["count"]
        else:
            user_count = 1
            active_user_count = 1
            today_qa_count = conn.execute(
                """
                SELECT COUNT(*) AS count FROM qa_logs
                WHERE user_id = ? AND substr(created_at, 1, 10) = ?
                """,
                (user["id"], today),
            ).fetchone()["count"]
            low_confidence_rows = conn.execute(
                """
                SELECT id, question, confidence, created_at
                FROM qa_logs
                WHERE user_id = ? AND blocked = 0 AND confidence < 0.18
                ORDER BY id DESC LIMIT 5
                """,
                (user["id"],),
            ).fetchall()
            low_confidence_count = conn.execute(
                """
                SELECT COUNT(*) AS count FROM qa_logs
                WHERE user_id = ? AND blocked = 0 AND confidence < 0.18
                """,
                (user["id"],),
            ).fetchone()["count"]
        recent_documents = conn.execute(
            f"""
            SELECT id, title, filename, access_level, status, chunk_count, created_at
            FROM documents
            WHERE access_level IN ({placeholders})
            ORDER BY id DESC LIMIT 5
            """,
            levels,
        ).fetchall()
        ready_document_count = conn.execute(
            f"""
            SELECT COUNT(*) AS count FROM documents
            WHERE status = 'ready' AND access_level IN ({placeholders})
            """,
            levels,
        ).fetchone()["count"]
        open_gap_count = conn.execute(
            "SELECT COUNT(*) AS count FROM knowledge_gaps WHERE status != 'resolved'"
        ).fetchone()["count"]
        feedback_count = conn.execute("SELECT COUNT(*) AS count FROM qa_feedback").fetchone()["count"]
        negative_feedback_count = conn.execute(
            "SELECT COUNT(*) AS count FROM qa_feedback WHERE rating IN ('unhelpful', 'needs_info')"
        ).fetchone()["count"]
        if user["role"] in MANAGER_ROLES:
            agent_rows = conn.execute(
                """
                SELECT id, goal, status, tool_calls_json, created_at
                FROM agent_runs
                ORDER BY id DESC
                """
            ).fetchall()
        else:
            agent_rows = conn.execute(
                """
                SELECT id, goal, status, tool_calls_json, created_at
                FROM agent_runs
                WHERE user_id = ?
                ORDER BY id DESC
                """,
                (user["id"],),
            ).fetchall()
        agent_metrics = summarize_agent_metrics(agent_rows)
    return {
        "stats": base_stats,
        "analytics": base_analytics,
        "agent_metrics": agent_metrics,
        "recent_logs": recent_logs,
        "recent_batch_runs": recent_runs,
        "recent_documents": [dict(row) for row in recent_documents],
        "low_confidence_logs": [dict(row) for row in low_confidence_rows],
        "low_confidence_count": low_confidence_count,
        "today_qa_count": today_qa_count,
        "ready_document_count": ready_document_count,
        "open_gap_count": open_gap_count,
        "feedback_count": feedback_count,
        "negative_feedback_count": negative_feedback_count,
        "user_count": user_count,
        "active_user_count": active_user_count,
    }


@app.get("/api/knowledge-health")
def knowledge_health(user: dict = Depends(current_user)) -> dict:
    require_permission(user, "health.view")
    stale_before = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    with get_conn() as conn:
        document_rows = conn.execute(
            """
            SELECT d.id, d.title, d.filename, d.file_type, d.access_level, d.status, d.chunk_count, d.created_at,
                   COALESCE(SUM(LENGTH(c.content)), 0) AS content_length,
                   COALESCE(GROUP_CONCAT(c.content, '\n'), '') AS content
            FROM documents d
            LEFT JOIN chunks c ON c.document_id = d.id
            GROUP BY d.id
            ORDER BY d.id DESC
            """
        ).fetchall()
        low_confidence_rows = conn.execute(
            """
            SELECT id, question, confidence, created_at
            FROM qa_logs
            WHERE blocked = 0 AND confidence < 0.18
            ORDER BY id DESC LIMIT 6
            """
        ).fetchall()
        low_confidence_count = conn.execute(
            "SELECT COUNT(*) AS count FROM qa_logs WHERE blocked = 0 AND confidence < 0.18"
        ).fetchone()["count"]
        gap_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM knowledge_gaps
            GROUP BY status
            """
        ).fetchall()
        blocked_count = conn.execute("SELECT COUNT(*) AS count FROM qa_logs WHERE blocked = 1").fetchone()["count"]
        qa_count = conn.execute("SELECT COUNT(*) AS count FROM qa_logs").fetchone()["count"]
        avg_confidence = conn.execute(
            "SELECT AVG(confidence) AS value FROM qa_logs WHERE blocked = 0 AND confidence > 0"
        ).fetchone()["value"]
        feedback_count = conn.execute("SELECT COUNT(*) AS count FROM qa_feedback").fetchone()["count"]
        negative_feedback_count = conn.execute(
            "SELECT COUNT(*) AS count FROM qa_feedback WHERE rating IN ('unhelpful', 'needs_info')"
        ).fetchone()["count"]

    documents = [score_document_quality(dict(row), stale_before) for row in document_rows]
    document_count = len(documents)
    ready_document_count = sum(1 for item in documents if item["status"] == "ready")
    total_chunks = sum(int(item["chunk_count"] or 0) for item in documents)
    stale_document_count = sum(1 for item in documents if item["is_stale"])
    weak_document_count = sum(1 for item in documents if item["quality_score"] < 72)
    avg_quality = round(sum(item["quality_score"] for item in documents) / document_count, 2) if document_count else 0
    gap_status_counts = {row["status"]: row["count"] for row in gap_rows}
    open_gap_count = sum(count for status, count in gap_status_counts.items() if status != "resolved")
    blocked_ratio = round(blocked_count / qa_count, 4) if qa_count else 0

    score = 100
    score -= min(22, low_confidence_count * 3)
    score -= min(18, negative_feedback_count * 4)
    score -= min(22, open_gap_count * 4)
    score -= min(18, weak_document_count * 2)
    score -= min(10, stale_document_count * 2)
    score -= max(0, round((100 - avg_quality) * 0.25)) if document_count else 16
    score -= 8 if document_count and ready_document_count < document_count else 0
    score = max(0, min(100, int(round(score))))

    recommendations = build_health_recommendations(
        document_count=document_count,
        low_confidence_count=low_confidence_count,
        negative_feedback_count=negative_feedback_count,
        open_gap_count=open_gap_count,
        stale_document_count=stale_document_count,
        weak_document_count=weak_document_count,
        avg_quality=avg_quality,
        blocked_ratio=blocked_ratio,
    )
    risk_documents = sorted(documents, key=lambda item: (item["quality_score"], -item["id"]))
    grade = health_grade(score)

    return {
        "score": score,
        "grade": grade,
        "summary": health_summary(score, low_confidence_count, open_gap_count, weak_document_count),
        "metrics": {
            "document_count": document_count,
            "ready_document_count": ready_document_count,
            "total_chunks": total_chunks,
            "avg_chunks_per_doc": round(total_chunks / document_count, 2) if document_count else 0,
            "avg_document_quality": avg_quality,
            "low_confidence_count": low_confidence_count,
            "feedback_count": feedback_count,
            "negative_feedback_count": negative_feedback_count,
            "open_gap_count": open_gap_count,
            "stale_document_count": stale_document_count,
            "weak_document_count": weak_document_count,
            "blocked_ratio": blocked_ratio,
            "avg_confidence": round(avg_confidence or 0, 4),
        },
        "gap_status_counts": gap_status_counts,
        "risk_documents": risk_documents,
        "recommendations": recommendations,
        "low_confidence_samples": [dict(row) for row in low_confidence_rows],
    }


@app.get("/api/knowledge-health/export")
def export_knowledge_health(format: str = "md", user: dict = Depends(current_user)) -> PlainTextResponse:
    report = knowledge_health(user)
    if format.lower() == "csv":
        content = render_health_csv(report)
        media_type = "text/csv; charset=utf-8"
        filename = "knowledge_health_report.csv"
    else:
        content = render_health_markdown(report)
        media_type = "text/markdown; charset=utf-8"
        filename = "knowledge_health_report.md"
    return PlainTextResponse(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/analytics")
def analytics(user: dict = Depends(current_user)) -> dict:
    if not (has_permission(user, "evaluation.manage") or has_permission(user, "health.view")):
        raise HTTPException(status_code=403, detail="当前角色没有查看分析数据的权限")
    levels = allowed_access_levels(user)
    placeholders = ",".join("?" for _ in levels)
    with get_conn() as conn:
        access_rows = conn.execute(
            f"""
            SELECT access_level, COUNT(*) AS count
            FROM documents
            WHERE access_level IN ({placeholders})
            GROUP BY access_level
            """,
            levels,
        ).fetchall()
        if user["role"] in MANAGER_ROLES:
            qa_rows = conn.execute(
                """
                SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
                FROM qa_logs GROUP BY day ORDER BY day DESC LIMIT 7
                """
            ).fetchall()
            blocked = conn.execute("SELECT COUNT(*) AS count FROM qa_logs WHERE blocked = 1").fetchone()["count"]
            total = conn.execute("SELECT COUNT(*) AS count FROM qa_logs").fetchone()["count"]
            eval_rows = conn.execute(
                """
                SELECT
                  SUM(CASE WHEN score < 0.4 THEN 1 ELSE 0 END) AS low,
                  SUM(CASE WHEN score >= 0.4 AND score < 0.75 THEN 1 ELSE 0 END) AS medium,
                  SUM(CASE WHEN score >= 0.75 THEN 1 ELSE 0 END) AS high
                FROM evaluations
                """
            ).fetchone()
            latest_batch = conn.execute(
                """
                SELECT avg_score, avg_confidence, citation_hit_rate,
                       recall_at_k, mrr, answer_accuracy, abstention_accuracy,
                       access_control_accuracy, citation_faithfulness, safety_assertion_accuracy
                FROM batch_eval_runs ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        else:
            qa_rows = conn.execute(
                """
                SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count
                FROM qa_logs WHERE user_id = ?
                GROUP BY day ORDER BY day DESC LIMIT 7
                """,
                (user["id"],),
            ).fetchall()
            blocked = conn.execute(
                "SELECT COUNT(*) AS count FROM qa_logs WHERE blocked = 1 AND user_id = ?", (user["id"],)
            ).fetchone()["count"]
            total = conn.execute("SELECT COUNT(*) AS count FROM qa_logs WHERE user_id = ?", (user["id"],)).fetchone()[
                "count"
            ]
            eval_rows = conn.execute(
                """
                SELECT
                  SUM(CASE WHEN score < 0.4 THEN 1 ELSE 0 END) AS low,
                  SUM(CASE WHEN score >= 0.4 AND score < 0.75 THEN 1 ELSE 0 END) AS medium,
                  SUM(CASE WHEN score >= 0.75 THEN 1 ELSE 0 END) AS high
                FROM evaluations WHERE user_id = ?
                """,
                (user["id"],),
            ).fetchone()
            latest_batch = conn.execute(
                """
                SELECT avg_score, avg_confidence, citation_hit_rate,
                       recall_at_k, mrr, answer_accuracy, abstention_accuracy,
                       access_control_accuracy, citation_faithfulness, safety_assertion_accuracy
                FROM batch_eval_runs WHERE user_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (user["id"],),
            ).fetchone()

    return {
        "access_distribution": [dict(row) for row in access_rows],
        "qa_trend": list(reversed([dict(row) for row in qa_rows])),
        "blocked_ratio": round((blocked / total) if total else 0, 4),
        "evaluation_buckets": {
            "low": eval_rows["low"] or 0,
            "medium": eval_rows["medium"] or 0,
            "high": eval_rows["high"] or 0,
        },
        "latest_batch": dict(latest_batch) if latest_batch else None,
    }


@app.get("/api/audit-logs")
def list_audit_logs(
    page: int = 1,
    page_size: int = 5,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "audit.view")
    page, page_size, offset = normalize_pagination(page, page_size)
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS count FROM audit_logs").fetchone()["count"]
        rows = conn.execute(
            """
            SELECT a.id, a.action, a.target_type, a.target_id, a.detail, a.created_at,
                   u.username, u.display_name
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.user_id
            ORDER BY a.id DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["detail"] = json.loads(item["detail"])
        result.append(item)
    return paginated(result, total, page, page_size)


@app.delete("/api/audit-logs")
def clear_audit_logs(user: dict = Depends(current_user)) -> dict:
    require_admin(user)
    created = utc_now()
    with get_conn() as conn:
        deleted_count = conn.execute("SELECT COUNT(*) AS count FROM audit_logs").fetchone()["count"]
        conn.execute("DELETE FROM audit_logs")
        conn.execute(
            """
            INSERT INTO audit_logs(user_id, action, target_type, target_id, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                "clear_audit_logs",
                "audit_log",
                None,
                json.dumps({"deleted_count": deleted_count}, ensure_ascii=False),
                created,
            ),
        )
    return {"deleted_count": deleted_count}


@app.get("/api/quality-assessments")
def list_quality_assessments(
    page: int = 1,
    page_size: int = 5,
    level: str | None = None,
    q: str | None = None,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "evaluation.manage")
    page, page_size, offset = normalize_pagination(page, page_size)
    where = []
    values: list[object] = []
    if level:
        if level not in {"passed", "watch", "review", "blocked", "failed"}:
            raise HTTPException(status_code=400, detail="质量等级不合法")
        where.append("a.quality_level = ?")
        values.append(level)
    if q:
        where.append("(l.question LIKE ? OR u.username LIKE ? OR u.display_name LIKE ?)")
        keyword = f"%{q.strip()}%"
        values.extend([keyword, keyword, keyword])
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with get_conn() as conn:
        total = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM qa_quality_assessments a
            JOIN qa_logs l ON l.id = a.log_id
            LEFT JOIN users u ON u.id = l.user_id
            {clause}
            """,
            values,
        ).fetchone()["count"]
        rows = conn.execute(
            f"""
            SELECT a.*, l.question, l.answer, l.created_at AS question_at,
                   u.username, u.display_name,
                   f.rating AS feedback_rating
            FROM qa_quality_assessments a
            JOIN qa_logs l ON l.id = a.log_id
            LEFT JOIN users u ON u.id = l.user_id
            LEFT JOIN qa_feedback f ON f.log_id = l.id
            {clause}
            ORDER BY a.id DESC
            LIMIT ? OFFSET ?
            """,
            [*values, page_size, offset],
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["risk_reasons"] = json.loads(item["risk_reasons"] or "[]")
        items.append(item)
    return paginated(items, total, page, page_size)


@app.post("/api/quality-assessments/{log_id}/retry")
def retry_quality_assessment(log_id: int, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "evaluation.manage")
    with get_conn() as conn:
        exists = conn.execute("SELECT id FROM qa_logs WHERE id = ?", (log_id,)).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="问答记录不存在")
    run_quality_assessment(log_id)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM qa_quality_assessments WHERE log_id = ?",
            (log_id,),
        ).fetchone()
    item = dict(row)
    item["risk_reasons"] = json.loads(item["risk_reasons"] or "[]")
    return item


@app.get("/api/knowledge-gaps")
def list_knowledge_gaps(
    status: str | None = None,
    page: int = 1,
    page_size: int = 5,
    user: dict = Depends(current_user),
) -> dict:
    require_permission(user, "gaps.manage")
    page, page_size, offset = normalize_pagination(page, page_size)
    where = []
    values = []
    if status:
        if status not in {"open", "processing", "resolved", "closed"}:
            raise HTTPException(status_code=400, detail="知识缺口状态不合法")
        where.append("g.status = ?")
        values.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS count FROM knowledge_gaps g {clause}",
            values,
        ).fetchone()["count"]
        rows = conn.execute(
            f"""
            SELECT g.id, g.question, g.source_log_id, g.status, g.note,
                   g.assigned_to, g.resolution_action, g.before_score, g.after_score,
                   g.review_answer, g.review_citations_json, g.reviewed_at,
                   g.created_at, g.resolved_at,
                   u.username, u.display_name,
                   assignee.display_name AS assigned_name
            FROM knowledge_gaps g
            LEFT JOIN users u ON u.id = g.created_by
            LEFT JOIN users assignee ON assignee.id = g.assigned_to
            {clause}
            ORDER BY
              CASE g.status WHEN 'open' THEN 0 WHEN 'processing' THEN 1 ELSE 2 END,
              g.id DESC
            LIMIT ? OFFSET ?
            """,
            [*values, page_size, offset],
        ).fetchall()
    return paginated([serialize_gap(row) for row in rows], total, page, page_size)


@app.post("/api/knowledge-gaps/{gap_id}/recheck")
def recheck_knowledge_gap(gap_id: int, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "gaps.manage")
    with get_conn() as conn:
        gap = conn.execute(
            """
            SELECT g.id, g.question, g.source_log_id, a.quality_score AS before_score
            FROM knowledge_gaps g
            LEFT JOIN qa_quality_assessments a ON a.log_id = g.source_log_id
            WHERE g.id = ?
            """,
            (gap_id,),
        ).fetchone()
    if not gap:
        raise HTTPException(status_code=404, detail="知识缺口不存在")

    answer_result = compute_answer(
        AskRequest(question=gap["question"], top_k=DEFAULT_TOP_K),
        user,
    )
    citations = answer_result["citations"]
    assessment = calculate_quality(
        confidence=answer_result["confidence"],
        citation_scores=[float(item.get("score", 0)) for item in citations],
        blocked=answer_result["blocked"],
    )
    next_status = "resolved" if assessment.quality_level == "passed" else "processing"
    reviewed_at = utc_now()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE knowledge_gaps
            SET before_score = COALESCE(before_score, ?),
                after_score = ?,
                review_answer = ?,
                review_citations_json = ?,
                reviewed_by = ?,
                reviewed_at = ?,
                status = ?,
                resolved_at = ?
            WHERE id = ?
            """,
            (
                gap["before_score"],
                assessment.quality_score,
                answer_result["answer"],
                json.dumps(citations, ensure_ascii=False),
                user["id"],
                reviewed_at,
                next_status,
                reviewed_at if next_status == "resolved" else None,
                gap_id,
            ),
        )
    write_audit(
        user,
        "recheck_knowledge_gap",
        "knowledge_gap",
        gap_id,
        {
            "before_score": gap["before_score"],
            "after_score": assessment.quality_score,
            "quality_level": assessment.quality_level,
        },
    )
    return {
        "gap_id": gap_id,
        "before_score": gap["before_score"],
        "after_score": assessment.quality_score,
        "quality_level": assessment.quality_level,
        "status": next_status,
        "answer": answer_result["answer"],
        "citations": citations,
    }


@app.post("/api/knowledge-gaps")
def create_knowledge_gap(payload: KnowledgeGapCreateRequest, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "gaps.manage")
    question = payload.question.strip()
    note = (payload.note or "").strip()
    created = utc_now()
    with get_conn() as conn:
        if payload.source_log_id is not None:
            log = conn.execute("SELECT id FROM qa_logs WHERE id = ?", (payload.source_log_id,)).fetchone()
            if not log:
                raise HTTPException(status_code=404, detail="来源问答记录不存在")
        existing = conn.execute(
            """
            SELECT id, question, source_log_id, status, note, created_at, resolved_at, NULL AS username, NULL AS display_name
            FROM knowledge_gaps
            WHERE status != 'resolved' AND (source_log_id = ? OR question = ?)
            LIMIT 1
            """,
            (payload.source_log_id, question),
        ).fetchone()
        if existing:
            item = serialize_gap(existing)
            item["duplicate"] = True
            return item
        cursor = conn.execute(
            """
            INSERT INTO knowledge_gaps(question, source_log_id, status, note, created_by, created_at)
            VALUES (?, ?, 'open', ?, ?, ?)
            """,
            (question, payload.source_log_id, note, user["id"], created),
        )
        row = conn.execute(
            """
            SELECT g.id, g.question, g.source_log_id, g.status, g.note, g.created_at, g.resolved_at,
                   u.username, u.display_name
            FROM knowledge_gaps g
            LEFT JOIN users u ON u.id = g.created_by
            WHERE g.id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    write_audit(user, "create_knowledge_gap", "knowledge_gap", row["id"], {"question": question})
    return serialize_gap(row)


@app.patch("/api/knowledge-gaps/{gap_id}")
def update_knowledge_gap(gap_id: int, payload: KnowledgeGapUpdateRequest, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "gaps.manage")
    updates = []
    values = []
    with get_conn() as conn:
        exists = conn.execute(
            """
            SELECT id, status, assigned_to, resolution_action, after_score, reviewed_at
            FROM knowledge_gaps
            WHERE id = ?
            """,
            (gap_id,),
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="知识缺口不存在")
        if payload.status is not None:
            if payload.status not in {"open", "processing", "resolved", "closed"}:
                raise HTTPException(status_code=400, detail="知识缺口状态不合法")
            if payload.status == "resolved" and (
                exists["reviewed_at"] is None or float(exists["after_score"] or 0) < 0.75
            ):
                raise HTTPException(status_code=400, detail="知识缺口通过复评后才能标记为已解决")
            if payload.status == "closed":
                action = (payload.resolution_action or exists["resolution_action"] or "").strip()
                if not action:
                    raise HTTPException(status_code=400, detail="关闭知识缺口时必须填写处理说明")
            updates.append("status = ?")
            values.append(payload.status)
            updates.append("resolved_at = ?")
            values.append(utc_now() if payload.status in {"resolved", "closed"} else None)
            if payload.status == "processing" and payload.assigned_to is None and exists["assigned_to"] is None:
                updates.append("assigned_to = ?")
                values.append(user["id"])
        if payload.note is not None:
            updates.append("note = ?")
            values.append(payload.note.strip())
        if payload.assigned_to is not None:
            assignee = conn.execute(
                "SELECT id FROM users WHERE id = ? AND is_active = 1",
                (payload.assigned_to,),
            ).fetchone()
            if not assignee:
                raise HTTPException(status_code=400, detail="负责人不存在或已停用")
            updates.append("assigned_to = ?")
            values.append(payload.assigned_to)
        if payload.resolution_action is not None:
            updates.append("resolution_action = ?")
            values.append(payload.resolution_action.strip())
        if not updates:
            raise HTTPException(status_code=400, detail="没有需要更新的字段")
        conn.execute(f"UPDATE knowledge_gaps SET {', '.join(updates)} WHERE id = ?", [*values, gap_id])
        row = conn.execute(
            """
            SELECT g.id, g.question, g.source_log_id, g.status, g.note,
                   g.assigned_to, g.resolution_action, g.before_score, g.after_score,
                   g.review_answer, g.review_citations_json, g.reviewed_at,
                   g.created_at, g.resolved_at,
                   u.username, u.display_name,
                   assignee.display_name AS assigned_name
            FROM knowledge_gaps g
            LEFT JOIN users u ON u.id = g.created_by
            LEFT JOIN users assignee ON assignee.id = g.assigned_to
            WHERE g.id = ?
            """,
            (gap_id,),
        ).fetchone()
    write_audit(user, "update_knowledge_gap", "knowledge_gap", gap_id, payload.model_dump(exclude_none=True))
    return serialize_gap(row)


@app.delete("/api/knowledge-gaps/{gap_id}")
def delete_knowledge_gap(gap_id: int, user: dict = Depends(current_user)) -> dict:
    require_permission(user, "gaps.manage")
    with get_conn() as conn:
        row = conn.execute("SELECT question FROM knowledge_gaps WHERE id = ?", (gap_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="知识缺口不存在")
        conn.execute("DELETE FROM knowledge_gaps WHERE id = ?", (gap_id,))
    write_audit(user, "delete_knowledge_gap", "knowledge_gap", gap_id, {"question": row["question"]})
    return {"deleted": True}


def score_document_quality(row: dict, stale_before: str) -> dict:
    content = row.pop("content", "") or ""
    title = row["title"] or ""
    access_level = row["access_level"] or "internal"
    content_length = int(row.get("content_length") or 0)
    chunk_count = int(row.get("chunk_count") or 0)
    missing_aspects = [
        label
        for label, keywords in STRUCTURE_CHECKS
        if not any(keyword in content or keyword in title for keyword in keywords)
    ]
    suggestions = []
    score = 100

    if row["status"] != "ready":
        score -= 18
        suggestions.append("重新索引并确认文档状态为已入库")
    if chunk_count <= 0:
        score -= 18
        suggestions.append("重新切分文档，确保生成可检索片段")
    if content_length < 500:
        score -= 16
        suggestions.append("补充业务背景、适用范围和处理细则")
    if row["created_at"] < stale_before:
        score -= 8
        suggestions.append("超过 90 天未更新，建议复核版本有效性")
    if missing_aspects:
        score -= min(30, len(missing_aspects) * 10)
        suggestions.append(f"补齐{'、'.join(missing_aspects)}")
    if access_level != "sensitive" and any(keyword in title or keyword in content[:1200] for keyword in SENSITIVE_KEYWORDS):
        score -= 8
        suggestions.append("复核文档密级，避免敏感资料误设为普通资料")

    score = max(45, min(100, score))
    return {
        "id": row["id"],
        "title": title,
        "filename": row["filename"],
        "file_type": row["file_type"],
        "access_level": access_level,
        "status": row["status"],
        "chunk_count": chunk_count,
        "created_at": row["created_at"],
        "content_length": content_length,
        "quality_score": score,
        "missing_aspects": missing_aspects,
        "suggestions": suggestions[:3] or ["质量良好，保持定期复核"],
        "is_stale": row["created_at"] < stale_before,
    }


def health_grade(score: int) -> str:
    if score >= 90:
        return "优秀"
    if score >= 76:
        return "良好"
    if score >= 60:
        return "需优化"
    return "风险"


def health_summary(score: int, low_confidence_count: int, open_gap_count: int, weak_document_count: int) -> str:
    if score >= 90:
        return "知识库结构稳定，文档质量和问答表现适合进入展示或试运行。"
    if score >= 76:
        return f"整体可用，建议优先处理 {open_gap_count} 个未关闭知识缺口和 {low_confidence_count} 条低置信问答。"
    if score >= 60:
        return f"知识库已有基础，但仍有 {weak_document_count} 篇文档需要补齐结构化信息。"
    return "当前知识库存在明显治理风险，建议先补文档、关缺口，再进行正式演示。"


def build_health_recommendations(
    document_count: int,
    low_confidence_count: int,
    negative_feedback_count: int,
    open_gap_count: int,
    stale_document_count: int,
    weak_document_count: int,
    avg_quality: float,
    blocked_ratio: float,
) -> list[dict]:
    recommendations = []
    if document_count < 12:
        recommendations.append(
            {
                "priority": "高",
                "title": "扩充核心业务文档覆盖",
                "detail": "当前知识库文档数量偏少，建议补充人事、财务、IT、合同、项目和客服等高频制度。",
            }
        )
    if open_gap_count:
        recommendations.append(
            {
                "priority": "高",
                "title": "优先关闭未处理知识缺口",
                "detail": f"还有 {open_gap_count} 个知识缺口未关闭，可把低置信问题转成补充文档任务。",
            }
        )
    if low_confidence_count:
        recommendations.append(
            {
                "priority": "中",
                "title": "复盘低置信问答样本",
                "detail": f"检测到 {low_confidence_count} 条低置信问答，建议补充同义词表达、流程细节和常见问法。",
            }
        )
    if negative_feedback_count:
        recommendations.append(
            {
                "priority": "高",
                "title": "处理员工负向反馈",
                "detail": f"收到 {negative_feedback_count} 条无用或需补充反馈，建议优先复盘对应问答并补齐知识片段。",
            }
        )
    if weak_document_count:
        recommendations.append(
            {
                "priority": "中",
                "title": "优化低质量文档结构",
                "detail": f"有 {weak_document_count} 篇文档质量分低于 72，重点补齐适用范围、审批流程和异常处理。",
            }
        )
    if stale_document_count:
        recommendations.append(
            {
                "priority": "低",
                "title": "建立周期复核机制",
                "detail": f"{stale_document_count} 篇文档超过 90 天未更新，建议每季度复核制度有效性。",
            }
        )
    if avg_quality >= 82 and blocked_ratio < 0.12:
        recommendations.append(
            {
                "priority": "低",
                "title": "准备答辩演示脚本",
                "detail": "当前质量基础较好，可以准备普通员工、技术员工、管理员三类角色的权限演示。",
            }
        )
    if not recommendations:
        recommendations.append(
            {
                "priority": "低",
                "title": "保持知识库治理节奏",
                "detail": "建议每次新增业务资料后运行健康体检，并把低置信问题纳入知识缺口中心。",
            }
        )
    return recommendations[:6]


def normalize_list(values: list[str]) -> list[str]:
    return [value.strip().lower() for value in values if value.strip()]


def keyword_score(answer: str, keywords: list[str], fallback: float) -> float:
    if not keywords:
        return float(fallback)
    lowered = answer.lower()
    return sum(1 for keyword in keywords if keyword in lowered) / len(keywords)


def citation_hit_score(citations: list[dict], expected_documents: list[str]) -> float:
    if not expected_documents:
        return 0.0
    names = [
        " ".join(
            [
                str(item.get("document_title", "")).lower(),
                str(item.get("document_filename", "")).lower(),
            ]
        )
        for item in citations
    ]
    hits = 0
    for expected in expected_documents:
        if any(expected in name for name in names):
            hits += 1
    return hits / len(expected_documents)


def find_evaluation_baseline(requested_run_id: int | None, dataset_hash: str, top_k: int) -> dict | None:
    with get_conn() as conn:
        if requested_run_id:
            row = conn.execute(
                """
                SELECT id, dataset_hash, top_k, recall_at_k, mrr,
                       answer_accuracy, abstention_accuracy, access_control_accuracy,
                       citation_faithfulness, safety_assertion_accuracy
                FROM batch_eval_runs WHERE id = ?
                """,
                (requested_run_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="指定的评测基线不存在")
            if row["dataset_hash"] != dataset_hash or row["top_k"] != top_k:
                raise HTTPException(status_code=409, detail="评测基线的数据集或 Top K 与当前运行不一致")
            result = dict(row)
            result["reference"] = f"历史运行 #{result['id']}"
            return result
        row = conn.execute(
            """
            SELECT id, dataset_hash, top_k, recall_at_k, mrr,
                   answer_accuracy, abstention_accuracy, access_control_accuracy,
                   citation_faithfulness, safety_assertion_accuracy
            FROM batch_eval_runs
            WHERE dataset_hash = ? AND top_k = ? AND gate_status = 'passed'
            ORDER BY id DESC LIMIT 1
            """,
            (dataset_hash, top_k),
        ).fetchone()
    if row:
        result = dict(row)
        result["reference"] = f"历史运行 #{result['id']}"
        return result
    approved = load_evaluation_baseline()
    if approved["dataset_fingerprint"] != dataset_hash or approved["top_k"] != top_k:
        return None
    return {
        "id": None,
        "reference": approved["version"],
        **approved["metrics"],
    }


def serialize_evaluation_case(row) -> dict:
    item = dict(row)
    item["expected_keywords"] = json.loads(item["expected_keywords"])
    item["expected_documents"] = json.loads(item["expected_documents"])
    item["capabilities"] = json.loads(item.pop("capabilities_json", "[]") or "[]")
    item["required_keyword_groups"] = json.loads(
        item.pop("required_keyword_groups_json", "[]") or "[]"
    )
    item["forbidden_keywords"] = json.loads(
        item.pop("forbidden_keywords_json", "[]") or "[]"
    )
    item["expected_document_groups"] = json.loads(
        item.pop("expected_document_groups_json", "[]") or "[]"
    )
    item["forbidden_documents"] = json.loads(
        item.pop("forbidden_documents_json", "[]") or "[]"
    )
    item["should_answer"] = bool(item["should_answer"])
    item["is_golden"] = bool(item.get("case_key"))
    return item


def serialize_batch_run(row) -> dict:
    item = dict(row)
    item["thresholds"] = json.loads(item.pop("thresholds_json", "{}") or "{}")
    item["failed_metrics"] = json.loads(item.pop("failed_metrics_json", "[]") or "[]")
    item["metric_deltas"] = json.loads(item.pop("metric_deltas_json", "{}") or "{}")
    item["generation_modes"] = json.loads(item.pop("generation_modes_json", "[]") or "[]")
    item["models"] = json.loads(item.pop("models_json", "[]") or "[]")
    item["prompt_versions"] = json.loads(item.pop("prompt_versions_json", "[]") or "[]")
    item["breakdowns"] = json.loads(item.pop("breakdown_json", "{}") or "{}")
    return item


def serialize_user(row) -> dict:
    item = dict(row)
    item["is_active"] = bool(item["is_active"])
    return item


def serialize_gap(row) -> dict:
    item = dict(row)
    item["duplicate"] = False
    return item


def serialize_feedback(row) -> dict:
    item = dict(row)
    item["blocked"] = bool(item["blocked"])
    return item


def render_batch_markdown(run: dict, results: list[dict]) -> str:
    gate_label = "通过" if run.get("gate_status") == "passed" else "失败"
    baseline_label = run.get("baseline_reference") or (
        f"#{run['baseline_run_id']}" if run.get("baseline_run_id") else "首次运行"
    )
    failed_metrics = ", ".join(run.get("failed_metrics") or []) or "无"
    threshold_text = ", ".join(
        f"{metric}>={float(value):.2%}" for metric, value in (run.get("thresholds") or {}).items()
    )
    delta_text = ", ".join(
        f"{metric} {float(value):+.2%}" for metric, value in (run.get("metric_deltas") or {}).items()
    )
    lines = [
        f"# 批量评测报告 #{run['id']}",
        "",
        f"- 运行时间：{run['created_at']}",
        f"- 运行人：{run.get('display_name') or '未知'}",
        f"- 数据集：{run.get('dataset_version', 'custom')} ({run.get('dataset_hash', '')[:12]})",
        f"- 检索 Top K：{run.get('top_k', DEFAULT_TOP_K)}",
        f"- 质量门禁：{gate_label}",
        f"- 失败指标：{failed_metrics}",
        f"- 指标阈值：{threshold_text or '未配置'}",
        f"- 对比基线：{baseline_label}",
        f"- 指标变化：{delta_text or '无历史基线'}",
        f"- 用例总数：{run['total']}",
        f"- 平均得分：{run['avg_score']:.2%}",
        f"- 平均置信度：{run['avg_confidence']:.2%}",
        f"- 引用命中率：{run['citation_hit_rate']:.2%}",
        f"- Recall@K：{run.get('recall_at_k', 0):.2%}",
        f"- MRR：{run.get('mrr', 0):.4f}",
        f"- 答案正确率：{run.get('answer_accuracy', 0):.2%}",
        f"- 拒答准确率：{run.get('abstention_accuracy', 0):.2%}",
        f"- 访问控制准确率：{run.get('access_control_accuracy', 0):.2%}",
        f"- 引用忠实度：{run.get('citation_faithfulness', 0):.2%}",
        f"- 安全断言准确率：{run.get('safety_assertion_accuracy', 0):.2%}",
        f"- 生成模式：{', '.join(run.get('generation_modes') or []) or '未知'}",
        f"- 模型：{', '.join(run.get('models') or []) or '未知'}",
        f"- Prompt 版本：{', '.join(run.get('prompt_versions') or []) or '未知'}",
        f"- Token：{run.get('total_tokens', 0)}（输入 {run.get('total_prompt_tokens', 0)} / 输出 {run.get('total_completion_tokens', 0)}）",
        f"- 估算成本：${run.get('estimated_cost_usd', 0):.6f}",
        f"- 平均耗时：{run.get('avg_latency_ms', 0):.2f} ms",
        "",
        "## 明细",
        "",
    ]
    for index, row in enumerate(results, start=1):
        keywords = ", ".join(json.loads(row["expected_keywords"]))
        docs = ", ".join(json.loads(row["expected_documents"]))
        citations = json.loads(row["citations_json"])
        capabilities = json.loads(row.get("capabilities_json") or "[]")
        citation_titles = ", ".join(item.get("document_title", "") for item in citations[:3])
        lines.extend(
            [
                f"### {index}. {row['question']}",
                "",
                f"- 执行角色：{row.get('actor_role', 'admin')}",
                f"- 难度：{row.get('difficulty', 'custom')}",
                f"- 能力标签：{', '.join(capabilities) or '未分类'}",
                f"- 期望关键词：{keywords}",
                f"- 期望来源：{docs}",
                f"- 得分：{row['score']:.2%}",
                f"- 置信度：{row['confidence']:.2%}",
                f"- 引用命中：{row['citation_hit']:.2%}",
                f"- 应回答：{'是' if row.get('should_answer', 1) else '否'}",
                f"- Recall@K：{row['retrieval_recall']:.2%}" if row.get("retrieval_recall") is not None else "- Recall@K：N/A",
                f"- Reciprocal Rank：{row['reciprocal_rank']:.4f}" if row.get("reciprocal_rank") is not None else "- Reciprocal Rank：N/A",
                f"- 答案判断：{'正确' if row.get('answer_correct') else '错误'}",
                f"- 拒答判断：{'正确' if row.get('abstention_correct') else '错误'}",
                f"- 访问控制：{'正确' if row.get('access_control_correct') else '错误'}",
                f"- 答案完整度：{row.get('answer_completeness', 0):.2%}",
                (
                    f"- 引用忠实度：{row['citation_faithfulness']:.2%}"
                    if row.get("citation_faithfulness") is not None
                    else "- 引用忠实度：N/A"
                ),
                f"- 安全断言：{'正确' if row.get('safety_assertion_correct') else '错误'}",
                f"- 生成证据：{row.get('generation_mode', 'unknown')} / {row.get('model', 'unknown')} / {row.get('prompt_version', 'unknown')}",
                f"- Token / 耗时：{row.get('total_tokens', 0)} / {row.get('latency_ms', 0)} ms",
                f"- 命中来源：{citation_titles or '无'}",
                "",
                row["answer"],
                "",
            ]
        )
    return "\n".join(lines)


def render_health_markdown(report: dict) -> str:
    metrics = report["metrics"]
    lines = [
        "# 知识库健康体检报告",
        "",
        f"- 生成时间：{utc_now()}",
        f"- 健康分：{report['score']} / 100",
        f"- 评级：{report['grade']}",
        f"- 摘要：{report['summary']}",
        "",
        "## 核心指标",
        "",
        f"- 文档覆盖：{metrics['ready_document_count']} / {metrics['document_count']}",
        f"- 知识片段：{metrics['total_chunks']}",
        f"- 平均文档质量：{metrics['avg_document_quality']:.2f}",
        f"- 低置信问题：{metrics['low_confidence_count']}",
        f"- 员工反馈：{metrics['feedback_count']}，其中负向反馈 {metrics['negative_feedback_count']}",
        f"- 未关闭知识缺口：{metrics['open_gap_count']}",
        f"- 平均置信度：{metrics['avg_confidence']:.2%}",
        f"- 安全拦截率：{metrics['blocked_ratio']:.2%}",
        "",
        "## 优化建议",
        "",
    ]
    for index, item in enumerate(report["recommendations"], start=1):
        lines.extend([f"{index}. **{item['title']}**（{item['priority']}）", f"   {item['detail']}", ""])
    lines.extend(["## 风险文档", ""])
    for doc in report["risk_documents"]:
        lines.extend(
            [
                f"### {doc['title']}",
                "",
                f"- 质量分：{doc['quality_score']}",
                f"- 密级：{doc['access_level']}",
                f"- 片段数：{doc['chunk_count']}",
                f"- 建议：{'；'.join(doc['suggestions'])}",
                "",
            ]
        )
    lines.extend(["## 低置信样本", ""])
    for item in report["low_confidence_samples"]:
        lines.append(f"- {item['question']}（置信度 {item['confidence']:.2%}，{item['created_at']}）")
    return "\n".join(lines)


def render_health_csv(report: dict) -> str:
    lines = ["section,name,value,detail"]
    metrics = report["metrics"]
    for key, value in metrics.items():
        lines.append(",".join(csv_escape(item) for item in ["metric", key, value, ""]))
    for item in report["recommendations"]:
        lines.append(",".join(csv_escape(value) for value in ["recommendation", item["title"], item["priority"], item["detail"]]))
    for doc in report["risk_documents"]:
        lines.append(
            ",".join(
                csv_escape(value)
                for value in ["risk_document", doc["title"], doc["quality_score"], "；".join(doc["suggestions"])]
            )
        )
    return "\ufeff" + "\n".join(lines)


def get_agent_run_for_user(run_id: int, user: dict) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT a.id, a.goal, a.status, a.final_answer, a.user_id,
                   a.tool_calls_json, a.plan_json, a.planner_mode, a.error_message,
                   a.started_at, a.completed_at, a.created_at, a.execution_mode,
                   a.top_k, a.idempotency_key, a.parent_run_id,
                   a.cancel_requested_at, a.updated_at,
                   u.username, u.display_name
            FROM agent_runs a
            LEFT JOIN users u ON u.id = a.user_id
            WHERE a.id = ?
            """,
            (run_id,),
        ).fetchone()
    if not row or (user["role"] not in MANAGER_ROLES and row["user_id"] != user["id"]):
        raise HTTPException(status_code=404, detail="Agent 运行记录不存在")
    return serialize_agent_run(row)


def serialize_agent_run(row) -> dict:
    item = dict(row)
    try:
        item["tool_calls"] = json.loads(item.pop("tool_calls_json") or "[]")
    except json.JSONDecodeError:
        item["tool_calls"] = []
    try:
        item["plan"] = json.loads(item.pop("plan_json") or "{}")
    except json.JSONDecodeError:
        item["plan"] = {}
    return item


def summarize_ai_usage(raw_items: list[str]) -> dict:
    summary = {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
    }
    for raw in raw_items:
        try:
            usage = json.loads(raw or "{}")
        except json.JSONDecodeError:
            continue
        if not usage:
            continue
        summary["request_count"] += 1
        summary["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        summary["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        summary["total_tokens"] += int(usage.get("total_tokens") or 0)
        summary["estimated_cost_usd"] += float(usage.get("estimated_cost_usd") or 0)
    summary["estimated_cost_usd"] = round(summary["estimated_cost_usd"], 6)
    return summary


def summarize_agent_metrics(rows) -> dict:
    summary = {
        "run_count": 0,
        "completed_run_count": 0,
        "blocked_run_count": 0,
        "total_tool_calls": 0,
        "skipped_tool_call_count": 0,
        "avg_tool_calls_per_run": 0,
        "recent_runs": [],
    }
    for row in rows:
        summary["run_count"] += 1
        status = row["status"]
        if status == "completed":
            summary["completed_run_count"] += 1
        if status == "blocked":
            summary["blocked_run_count"] += 1
        try:
            tool_calls = json.loads(row["tool_calls_json"] or "[]")
        except json.JSONDecodeError:
            tool_calls = []
        tool_count = len(tool_calls)
        skipped_count = sum(1 for call in tool_calls if call.get("status") == "skipped")
        summary["total_tool_calls"] += tool_count
        summary["skipped_tool_call_count"] += skipped_count
        if len(summary["recent_runs"]) < 5:
            summary["recent_runs"].append(
                {
                    "id": row["id"],
                    "goal": row["goal"],
                    "status": status,
                    "tool_count": tool_count,
                    "skipped_tool_call_count": skipped_count,
                    "created_at": row["created_at"],
                }
            )
    if summary["run_count"]:
        summary["avg_tool_calls_per_run"] = round(summary["total_tool_calls"] / summary["run_count"], 2)
    return summary


def render_batch_csv(run: dict, results: list[dict]) -> str:
    header = [
        "run_id",
        "actor_role",
        "difficulty",
        "capabilities",
        "question",
        "expected_keywords",
        "expected_documents",
        "score",
        "confidence",
        "citation_hit",
        "should_answer",
        "retrieval_recall",
        "reciprocal_rank",
        "answer_correct",
        "abstention_correct",
        "access_control_correct",
        "answer_completeness",
        "citation_faithfulness",
        "forbidden_keyword_correct",
        "forbidden_document_correct",
        "citation_count_correct",
        "safety_assertion_correct",
        "generation_mode",
        "model",
        "prompt_version",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_cost_usd",
        "latency_ms",
        "answer",
    ]
    lines = [",".join(header)]
    for row in results:
        values = [
            str(run["id"]),
            row.get("actor_role", "admin"),
            row.get("difficulty", "custom"),
            ";".join(json.loads(row.get("capabilities_json") or "[]")),
            row["question"],
            ";".join(json.loads(row["expected_keywords"])),
            ";".join(json.loads(row["expected_documents"])),
            f"{row['score']:.4f}",
            f"{row['confidence']:.4f}",
            f"{row['citation_hit']:.4f}",
            str(bool(row.get("should_answer", 1))).lower(),
            "" if row.get("retrieval_recall") is None else f"{row['retrieval_recall']:.4f}",
            "" if row.get("reciprocal_rank") is None else f"{row['reciprocal_rank']:.4f}",
            str(int(row.get("answer_correct") or 0)),
            str(int(row.get("abstention_correct") or 0)),
            str(int(row.get("access_control_correct") or 0)),
            f"{row.get('answer_completeness', 0):.4f}",
            "" if row.get("citation_faithfulness") is None else f"{row['citation_faithfulness']:.4f}",
            str(int(row.get("forbidden_keyword_correct") or 0)),
            str(int(row.get("forbidden_document_correct") or 0)),
            str(int(row.get("citation_count_correct") or 0)),
            str(int(row.get("safety_assertion_correct") or 0)),
            row.get("generation_mode", "unknown"),
            row.get("model", "unknown"),
            row.get("prompt_version", "unknown"),
            str(int(row.get("prompt_tokens") or 0)),
            str(int(row.get("completion_tokens") or 0)),
            str(int(row.get("total_tokens") or 0)),
            f"{float(row.get('estimated_cost_usd') or 0):.6f}",
            str(int(row.get("latency_ms") or 0)),
            row["answer"],
        ]
        lines.append(",".join(csv_escape(value) for value in values))
    return "\ufeff" + "\n".join(lines)


def csv_escape(value: str) -> str:
    text = str(value).replace('"', '""')
    return f'"{text}"'


def write_audit(user: dict, action: str, target_type: str, target_id: int | None, detail: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO audit_logs(user_id, action, target_type, target_id, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                action,
                target_type,
                target_id,
                json.dumps(detail, ensure_ascii=False),
                utc_now(),
            ),
        )
