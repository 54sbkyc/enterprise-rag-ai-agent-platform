from dataclasses import asdict, dataclass

from fastapi import HTTPException

from .auth import ADMIN_ROLE, EMPLOYEE_ROLE, TECH_ROLE
from .db import get_conn, utc_now


@dataclass(frozen=True)
class PermissionDefinition:
    code: str
    name: str
    description: str


PERMISSION_CATALOG = (
    PermissionDefinition("qa.use", "使用问答工作台", "提交问题并查看个人问答结果"),
    PermissionDefinition("documents.view", "查看文档", "查看文档、片段和版本信息"),
    PermissionDefinition("documents.manage", "维护文档", "上传、修改、删除和重建索引"),
    PermissionDefinition("retrieval.debug", "检索调试", "查看 Top-K 命中和相似度"),
    PermissionDefinition("evaluation.manage", "质量评测", "查看质量筛查并维护标准评测"),
    PermissionDefinition("gaps.manage", "知识优化", "处理知识缺口并重新评测"),
    PermissionDefinition("health.view", "健康体检", "查看和导出知识库健康报告"),
    PermissionDefinition("feedback.manage", "反馈管理", "查看员工反馈并联动知识缺口"),
    PermissionDefinition("users.manage", "用户管理", "创建、修改、禁用和删除用户"),
    PermissionDefinition("roles.manage", "角色权限", "配置角色权限矩阵"),
    PermissionDefinition("audit.view", "操作审计", "查看问答和管理操作记录"),
)

ALL_PERMISSION_CODES = {item.code for item in PERMISSION_CATALOG}
PROTECTED_ADMIN_PERMISSIONS = {"qa.use", "users.manage", "roles.manage", "audit.view"}
FORBIDDEN_NON_ADMIN_PERMISSIONS = {"users.manage", "roles.manage"}
REQUIRED_ALL_ROLE_PERMISSIONS = {"qa.use"}

DEFAULT_ROLE_PERMISSIONS = {
    ADMIN_ROLE: set(ALL_PERMISSION_CODES),
    TECH_ROLE: {
        "qa.use",
        "documents.view",
        "documents.manage",
        "retrieval.debug",
        "evaluation.manage",
        "gaps.manage",
        "health.view",
        "feedback.manage",
    },
    EMPLOYEE_ROLE: {"qa.use"},
}


def seed_default_permissions(conn) -> None:
    for role, permissions in DEFAULT_ROLE_PERMISSIONS.items():
        for definition in PERMISSION_CATALOG:
            conn.execute(
                """
                INSERT INTO role_permissions(role, permission_code, is_allowed, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(role, permission_code) DO NOTHING
                """,
                (role, definition.code, 1 if definition.code in permissions else 0, utc_now()),
            )


def permission_catalog() -> list[dict]:
    return [asdict(item) for item in PERMISSION_CATALOG]


def permissions_for_role(role: str) -> set[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT permission_code
            FROM role_permissions
            WHERE role = ? AND is_allowed = 1
            """,
            (role,),
        ).fetchall()
    return {row["permission_code"] for row in rows}


def permissions_for_user(user: dict) -> set[str]:
    return permissions_for_role(user["role"])


def has_permission(user: dict, permission_code: str) -> bool:
    return permission_code in permissions_for_user(user)


def require_permission(user: dict, permission_code: str) -> None:
    if not has_permission(user, permission_code):
        raise HTTPException(status_code=403, detail="当前角色没有执行该操作的权限")


def update_role_permissions(role: str, requested: set[str], actor: dict) -> list[str]:
    if role not in DEFAULT_ROLE_PERMISSIONS:
        raise HTTPException(status_code=400, detail="用户角色不合法")
    unknown = requested - ALL_PERMISSION_CODES
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知权限：{', '.join(sorted(unknown))}")

    effective = set(requested)
    effective |= REQUIRED_ALL_ROLE_PERMISSIONS
    if role == ADMIN_ROLE:
        effective |= PROTECTED_ADMIN_PERMISSIONS
    else:
        effective -= FORBIDDEN_NON_ADMIN_PERMISSIONS

    with get_conn() as conn:
        for definition in PERMISSION_CATALOG:
            conn.execute(
                """
                INSERT INTO role_permissions(role, permission_code, is_allowed, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(role, permission_code) DO UPDATE SET
                    is_allowed = excluded.is_allowed,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    role,
                    definition.code,
                    1 if definition.code in effective else 0,
                    actor["id"],
                    utc_now(),
                ),
            )
    return sorted(effective)
