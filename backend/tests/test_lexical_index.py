import json

from app import search
from app.db import get_conn, utc_now
from app.lexical_index import LexicalSearchResult, search_lexical_candidates
from app.text_processing import token_counts


def insert_document_with_chunks(
    title: str,
    contents: list[str],
    *,
    access_level: str = "internal",
) -> tuple[int, list[int]]:
    with get_conn() as conn:
        document_id = conn.execute(
            """
            INSERT INTO documents(
                title, filename, file_type, storage_path, access_level,
                status, chunk_count, version, created_at
            )
            VALUES (?, ?, 'md', 'test', ?, 'ready', ?, 1, ?)
            """,
            (title, f"{title}.md", access_level, len(contents), utc_now()),
        ).lastrowid
        chunk_ids = []
        for index, content in enumerate(contents):
            chunk_ids.append(
                conn.execute(
                    """
                    INSERT INTO chunks(
                        document_id, chunk_index, content, token_json,
                        embedding_json, embedding_model, content_hash, created_at
                    )
                    VALUES (?, ?, ?, ?, '[]', NULL, ?, ?)
                    """,
                    (
                        document_id,
                        index,
                        content,
                        json.dumps(token_counts(content)),
                        f"hash-{index}",
                        utc_now(),
                    ),
                ).lastrowid
            )
    return int(document_id), [int(chunk_id) for chunk_id in chunk_ids]


def lexical_ids(question: str, levels: list[str] | None = None) -> list[int]:
    with get_conn() as conn:
        result = search_lexical_candidates(conn, question, levels or ["internal"], 100)
    assert result.status == "ready", result.error
    return result.chunk_ids


def test_fts_index_tracks_direct_chunk_inserts_updates_and_deletes():
    document_id, chunk_ids = insert_document_with_chunks("Leave handbook", ["Submit leave one day early"])

    assert lexical_ids("leave") == chunk_ids

    with get_conn() as conn:
        conn.execute("UPDATE documents SET title = 'Absence handbook' WHERE id = ?", (document_id,))
    assert lexical_ids("absence") == chunk_ids

    with get_conn() as conn:
        conn.execute("UPDATE chunks SET content = 'Manager approval is required' WHERE id = ?", (chunk_ids[0],))
    assert lexical_ids("approval") == chunk_ids
    assert lexical_ids("leave") == []

    with get_conn() as conn:
        conn.execute("DELETE FROM chunks WHERE id = ?", (chunk_ids[0],))
    assert lexical_ids("approval") == []


def test_fts_query_is_safe_for_operator_and_punctuation_input():
    _, chunk_ids = insert_document_with_chunks("Policy", ["alpha beta policy"])

    assert lexical_ids('alpha OR "unterminated -beta') == chunk_ids
    assert lexical_ids('" OR * NEAR(') == []


def test_fts_uses_application_tokenization_for_chinese_queries():
    title = "\u8bf7\u5047\u5236\u5ea6"
    content = "\u5458\u5de5\u4e8b\u5047\u9700\u63d0\u524d\u4e00\u5929\u7533\u8bf7"
    _, chunk_ids = insert_document_with_chunks(title, [content])

    assert lexical_ids("\u4e8b\u5047\u7533\u8bf7") == chunk_ids


def test_fts_candidates_enforce_live_document_access_levels():
    _, public_ids = insert_document_with_chunks("Public policy", ["travel allowance"], access_level="public")
    _, restricted_ids = insert_document_with_chunks(
        "Restricted policy",
        ["travel allowance secret"],
        access_level="sensitive",
    )

    assert lexical_ids("travel", ["public", "internal"]) == public_ids
    manager_ids = lexical_ids("travel", ["public", "internal", "sensitive"])
    assert set(manager_ids) == set(public_ids + restricted_ids)


def test_search_loads_a_bounded_lexical_candidate_set(monkeypatch):
    contents = [f"policy handbook section {index}" for index in range(80)]
    insert_document_with_chunks("Policy handbook", contents)
    monkeypatch.setenv("RAG_LEXICAL_CANDIDATE_LIMIT", "25")

    hits = search.search_chunks("policy", 5, ["internal"])

    assert hits
    assert hits[0].lexical_backend == "sqlite_fts5"
    assert hits[0].lexical_degraded is False
    assert hits[0].candidate_count == 25
    assert hits[0].corpus_count == 80


def test_fts_failure_falls_back_to_full_scan_and_reports_degradation(monkeypatch):
    insert_document_with_chunks("Policy", ["policy alpha", "policy beta"])
    monkeypatch.setattr(
        search,
        "search_lexical_candidates",
        lambda *_args, **_kwargs: LexicalSearchResult(
            backend="full_scan",
            status="degraded",
            error="fts5_unavailable",
        ),
    )

    hits = search.search_chunks("policy", 5, ["internal"])

    assert hits
    assert hits[0].lexical_backend == "full_scan"
    assert hits[0].lexical_degraded is True
    assert hits[0].lexical_error == "fts5_unavailable"
    assert hits[0].candidate_count == hits[0].corpus_count == 2


def test_missing_sync_trigger_disables_fts_candidates():
    insert_document_with_chunks("Policy", ["policy alpha"])
    with get_conn() as conn:
        conn.execute("DROP TRIGGER chunks_fts_after_insert")
        result = search_lexical_candidates(conn, "policy", ["internal"], 10)

    assert result.backend == "full_scan"
    assert result.status == "degraded"
    assert result.error == "lexical_sync_triggers_missing"
