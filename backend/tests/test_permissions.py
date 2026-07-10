from app.permissions import (
    ADMIN_ROLE,
    EMPLOYEE_ROLE,
    TECH_ROLE,
    permissions_for_role,
)


def test_default_permission_matrix_is_seeded():
    assert {"users.manage", "roles.manage", "documents.manage"} <= permissions_for_role(ADMIN_ROLE)
    assert "documents.manage" in permissions_for_role(TECH_ROLE)
    assert permissions_for_role(EMPLOYEE_ROLE) == {"qa.use"}


def test_admin_protected_permissions_cannot_be_disabled(client, admin_headers):
    response = client.put(
        "/api/role-permissions/admin",
        headers=admin_headers,
        json={"permissions": ["qa.use"]},
    )

    assert response.status_code == 200
    permissions = set(response.json()["permissions"])
    assert {"users.manage", "roles.manage", "audit.view"} <= permissions


def test_technical_permissions_can_be_configured(client, admin_headers, tech_headers):
    response = client.put(
        "/api/role-permissions/tech",
        headers=admin_headers,
        json={"permissions": ["qa.use", "evaluation.manage"]},
    )
    assert response.status_code == 200

    me = client.get("/api/auth/me", headers=tech_headers)

    assert me.status_code == 200
    assert set(me.json()["permissions"]) == {"qa.use", "evaluation.manage"}


def test_question_workspace_is_locked_for_technical_role(client, admin_headers):
    response = client.put(
        "/api/role-permissions/tech",
        headers=admin_headers,
        json={"permissions": ["evaluation.manage"]},
    )

    assert response.status_code == 200
    assert "qa.use" in response.json()["permissions"]


def test_employee_cannot_manage_documents(client, employee_headers):
    response = client.get("/api/documents", headers=employee_headers)

    assert response.status_code == 403


def test_last_active_admin_cannot_be_disabled(client, admin_headers):
    me = client.get("/api/auth/me", headers=admin_headers).json()["user"]

    response = client.patch(
        f"/api/users/{me['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )

    assert response.status_code == 400


def test_last_active_admin_cannot_be_demoted(client, admin_headers):
    me = client.get("/api/auth/me", headers=admin_headers).json()["user"]

    response = client.patch(
        f"/api/users/{me['id']}",
        headers=admin_headers,
        json={"role": "employee"},
    )

    assert response.status_code == 400
