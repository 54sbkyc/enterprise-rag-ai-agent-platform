import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Header, HTTPException

from .config import (
    BOOTSTRAP_ADMIN_PASSWORD,
    BOOTSTRAP_ADMIN_USERNAME,
    RUNTIME_ENV,
    SESSION_TTL_HOURS,
)
from .db import get_conn, utc_now


LEGACY_PASSWORD_SALT = "enterprise-rag-demo"
PASSWORD_ITERATIONS = 210_000
ADMIN_ROLE = "admin"
TECH_ROLE = "tech"
EMPLOYEE_ROLE = "employee"
MANAGER_ROLES = {ADMIN_ROLE, TECH_ROLE}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PASSWORD_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest}"


def verify_password(stored_hash: str, password: str) -> bool:
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt, expected = stored_hash.split("$", 3)
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt),
                int(iterations),
            ).hex()
            return hmac.compare_digest(actual, expected)
        except (TypeError, ValueError):
            return False

    legacy_payload = f"{LEGACY_PASSWORD_SALT}:{password}".encode("utf-8")
    legacy_hash = hashlib.sha256(legacy_payload).hexdigest()
    return hmac.compare_digest(legacy_hash, stored_hash)


def seed_default_users() -> None:
    if RUNTIME_ENV == "production":
        seed_production_admin()
        return

    defaults = [
        ("admin", "admin123", ADMIN_ROLE, "系统管理员"),
        ("employee", "user123", EMPLOYEE_ROLE, "普通员工"),
    ]
    with get_conn() as conn:
        for username, password, role, display_name in defaults:
            exists = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if exists:
                continue
            conn.execute(
                """
                INSERT INTO users(username, password_hash, role, display_name, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (username, hash_password(password), role, display_name, utc_now()),
            )


def seed_production_admin() -> None:
    with get_conn() as conn:
        existing_admin = conn.execute(
            "SELECT id FROM users WHERE role = ? LIMIT 1",
            (ADMIN_ROLE,),
        ).fetchone()
        if existing_admin:
            return

        username = BOOTSTRAP_ADMIN_USERNAME.strip()
        password = BOOTSTRAP_ADMIN_PASSWORD
        if not 2 <= len(username) <= 32 or any(character.isspace() for character in username):
            raise RuntimeError(
                "RAG_BOOTSTRAP_ADMIN_USERNAME must contain 2-32 characters without whitespace"
            )
        if len(password) < 12:
            raise RuntimeError(
                "RAG_BOOTSTRAP_ADMIN_PASSWORD is required in production and must be at least 12 characters"
            )
        collision = conn.execute(
            "SELECT id FROM users WHERE username = ? LIMIT 1",
            (username,),
        ).fetchone()
        if collision:
            raise RuntimeError("RAG_BOOTSTRAP_ADMIN_USERNAME is already used by a non-admin account")
        conn.execute(
            """
            INSERT INTO users(username, password_hash, role, display_name, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (username, hash_password(password), ADMIN_ROLE, "平台管理员", utc_now()),
        )


def create_session(username: str, password: str) -> dict[str, Any]:
    with get_conn() as conn:
        user = conn.execute(
            """
            SELECT id, username, password_hash, role, display_name, is_active
            FROM users WHERE username = ?
            """,
            (username,),
        ).fetchone()
        if not user or not verify_password(user["password_hash"], password):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="账号已被禁用")
        if not user["password_hash"].startswith("pbkdf2_sha256$"):
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password), user["id"]),
            )

        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO sessions(token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user["id"], utc_now()),
        )

    from .permissions import permissions_for_role

    return {
        "token": token,
        "user": public_user(dict(user)),
        "permissions": sorted(permissions_for_role(user["role"])),
    }


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "display_name": user["display_name"],
        "is_active": bool(user.get("is_active", 1)),
    }


def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization.split(" ", 1)[1].strip()
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.role, u.display_name, u.is_active,
                   s.created_at AS session_created_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="登录已失效")
        if session_expired(row["session_created_at"]):
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
        user = dict(row)
    user.pop("session_created_at", None)
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user


def session_expired(created_at: str) -> bool:
    try:
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - created >= timedelta(hours=SESSION_TTL_HOURS)


def require_admin(user: dict[str, Any]) -> None:
    if user["role"] != ADMIN_ROLE:
        raise HTTPException(status_code=403, detail="仅管理员可执行该操作")


def require_manager(user: dict[str, Any]) -> None:
    if user["role"] not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="仅管理角色可执行该操作")


def allowed_access_levels(user: dict[str, Any]) -> list[str]:
    if user["role"] in MANAGER_ROLES:
        return ["public", "internal", "sensitive"]
    return ["public", "internal"]


def logout(token: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
