import pytest
from fastapi import HTTPException

from app.db import get_conn, utc_now
from app.pagination import normalize_pagination, paginated


def test_normalize_page_defaults():
    assert normalize_pagination(None, None) == (1, 5, 0)


def test_page_size_is_capped():
    assert normalize_pagination(2, 1000) == (2, 100, 100)


def test_page_below_one_is_rejected():
    with pytest.raises(HTTPException):
        normalize_pagination(0, 10)


def test_paginated_calculates_total_pages():
    result = paginated([{"id": 11}], total=21, page=2, page_size=10)

    assert result == {
        "items": [{"id": 11}],
        "page": 2,
        "page_size": 10,
        "total": 21,
        "total_pages": 3,
    }


def test_users_endpoint_returns_bounded_page(client, admin_headers):
    for index in range(12):
        response = client.post(
            "/api/users",
            headers=admin_headers,
            json={
                "username": f"page_user_{index}",
                "password": "pass1234",
                "role": "employee",
            },
        )
        assert response.status_code == 200

    response = client.get("/api/users?page=2&page_size=5", headers=admin_headers)

    assert response.status_code == 200
    result = response.json()
    assert result["page"] == 2
    assert result["page_size"] == 5
    assert result["total"] == 15
    assert len(result["items"]) == 5


def test_document_chunks_and_versions_are_paginated(client, admin_headers):
    from app.db import get_conn, utc_now

    with get_conn() as conn:
        document_id = conn.execute(
            """
            INSERT INTO documents(
                title, filename, file_type, storage_path, access_level,
                status, chunk_count, version, created_at
            )
            VALUES ('分页文档', 'paging.md', 'md', 'test', 'internal', 'ready', 3, 3, ?)
            """,
            (utc_now(),),
        ).lastrowid
        for index in range(3):
            conn.execute(
                """
                INSERT INTO chunks(document_id, chunk_index, content, token_json, created_at)
                VALUES (?, ?, ?, '{}', ?)
                """,
                (document_id, index, f"片段 {index}", utc_now()),
            )
            conn.execute(
                """
                INSERT INTO document_versions(
                    document_id, version, action, title, access_level,
                    chunk_count, created_at
                )
                VALUES (?, ?, 'upload', '分页文档', 'internal', 3, ?)
                """,
                (document_id, index + 1, utc_now()),
            )

    chunks = client.get(
        f"/api/documents/{document_id}/chunks?page=2&page_size=2",
        headers=admin_headers,
    )
    versions = client.get(
        f"/api/documents/{document_id}/versions?page=2&page_size=2",
        headers=admin_headers,
    )

    assert chunks.status_code == 200
    assert chunks.json()["total"] == 3
    assert len(chunks.json()["items"]) == 1
    assert chunks.json()["document"]["id"] == document_id
    assert versions.status_code == 200
    assert versions.json()["total"] == 3
    assert len(versions.json()["items"]) == 1


@pytest.mark.parametrize(
    ("path", "header_fixture"),
    [
        ("/api/logs?page=1&page_size=5", "admin"),
        ("/api/evaluations?page=1&page_size=5", "tech"),
        ("/api/evaluation/cases?page=1&page_size=5", "tech"),
        ("/api/evaluation/batch/runs?page=1&page_size=5", "tech"),
        ("/api/qa-feedback?page=1&page_size=5", "tech"),
        ("/api/audit-logs?page=1&page_size=5", "admin"),
        ("/api/knowledge-gaps?page=1&page_size=5", "tech"),
    ],
)
def test_growing_list_endpoints_use_pagination(
    request,
    client,
    path,
    header_fixture,
):
    headers = request.getfixturevalue(f"{header_fixture}_headers")

    response = client.get(path, headers=headers)

    assert response.status_code == 200
    result = response.json()
    assert set(("items", "page", "page_size", "total", "total_pages")) <= set(result)
    assert result["page_size"] == 5


def test_knowledge_health_does_not_truncate_risk_documents(client, admin_headers):
    with get_conn() as conn:
        for index in range(7):
            conn.execute(
                """
                INSERT INTO documents(
                    title, filename, file_type, storage_path, access_level,
                    status, chunk_count, version, created_at
                )
                VALUES (?, ?, 'md', 'test', 'public', 'ready', 1, 1, ?)
                """,
                (f"风险文档 {index}", f"risk-{index}.md", utc_now()),
            )

    response = client.get("/api/knowledge-health", headers=admin_headers)

    assert response.status_code == 200
    risk_documents = response.json()["risk_documents"]
    assert len(risk_documents) == 7
