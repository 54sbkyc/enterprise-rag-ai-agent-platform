import json
import math
from collections import Counter
from dataclasses import dataclass, field

from .config import positive_int_env
from .db import get_conn
from .embeddings import embed_query
from .lexical_index import lexical_candidate_limit, search_lexical_candidates
from .text_processing import token_counts, tokenize
from .vector_store import (
    VectorStoreConfigurationError,
    query_chunk_vectors,
    vector_store_backend,
    vector_store_fallback_enabled,
)


BM25_K1 = 1.5
BM25_B = 0.75
BM25_CONTENT_WEIGHT = 0.70
BM25_TITLE_WEIGHT = 0.30
RESTRICTED_TITLE_COVERAGE = 0.35
RESTRICTED_QUERY_COVERAGE = 0.40
MAX_VECTOR_CANDIDATE_LIMIT = 1000
SQLITE_CANDIDATE_BATCH_SIZE = 500
RESTRICTED_TOPIC_ALIASES = {
    "合同审批与风险控制指南": (("合同", "审批"),),
    "信息安全事件应急预案": (("信息安全", "事件"), ("安全事件",)),
    "数据分级与保密管理制度": (("敏感资料",), ("敏感数据",), ("数据分级",)),
    "销售报价与客户分级策略": (("销售", "折扣"), ("销售", "报价")),
}


@dataclass
class SearchHit:
    chunk_id: int
    document_id: int
    document_title: str
    document_filename: str
    document_access_level: str
    chunk_index: int
    content: str
    score: float
    matched_terms: list[str]
    query_terms: list[str]
    bm25_score: float = 0.0
    vector_score: float = 0.0
    rerank_score: float = 0.0
    retrieval_mode: str = "bm25"
    vector_backend: str = "none"
    vector_degraded: bool = False
    vector_error: str | None = None
    lexical_backend: str = "sqlite_fts5"
    lexical_degraded: bool = False
    lexical_error: str | None = None
    candidate_count: int = 0
    corpus_count: int = 0


@dataclass(frozen=True)
class _VectorCandidates:
    backend: str
    scores: dict[int, float] = field(default_factory=dict)
    degraded: bool = False
    error: str | None = None
    requires_local_scan: bool = False


def search_chunks(question: str, top_k: int, access_levels: list[str] | None = None) -> list[SearchHit]:
    access_levels = access_levels or ["public", "internal"]
    placeholders = ",".join("?" for _ in access_levels)
    with get_conn() as conn:
        document_rows = conn.execute(
            f"""
            SELECT id
            FROM documents
            WHERE access_level IN ({placeholders}) AND status = 'ready'
            """,
            access_levels,
        ).fetchall()
        allowed_document_ids = [int(row["id"]) for row in document_rows]
        if not allowed_document_ids:
            return []
        corpus_count = int(
            conn.execute(
                f"""
                SELECT COUNT(*) AS count
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.access_level IN ({placeholders}) AND d.status = 'ready'
                """,
                access_levels,
            ).fetchone()["count"]
        )
        model_row = conn.execute(
            f"""
            SELECT c.embedding_model, COUNT(*) AS count
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.access_level IN ({placeholders})
              AND d.status = 'ready'
              AND c.embedding_model IS NOT NULL
              AND c.embedding_model != ''
            GROUP BY c.embedding_model
            ORDER BY count DESC, c.embedding_model
            LIMIT 1
            """,
            access_levels,
        ).fetchone()
        lexical_result = search_lexical_candidates(
            conn,
            question,
            access_levels,
            lexical_candidate_limit(top_k),
        )

    if not corpus_count:
        return []

    embedding_model = model_row["embedding_model"] if model_row else None
    query_embedding = embed_query(question, embedding_model) if embedding_model else None
    vector_result = _vector_candidates(
        query_embedding,
        embedding_model,
        allowed_document_ids,
        top_k,
    )
    candidate_ids = set(lexical_result.chunk_ids) | set(vector_result.scores)
    use_full_scan = lexical_result.status != "ready" or vector_result.requires_local_scan
    if not candidate_ids and not use_full_scan:
        return []

    with get_conn() as conn:
        rows = _load_candidate_rows(
            conn,
            access_levels,
            None if use_full_scan else sorted(candidate_ids),
        )
    if not rows:
        return []

    chunk_counts = [_json_dict(row["token_json"]) for row in rows]
    query_counts = token_counts(question)
    query_terms = sorted(query_counts)
    content_bm25 = _normalize_positive(_bm25_scores(query_counts, chunk_counts))
    title_counts = [token_counts(row["title"]) for row in rows]
    title_bm25 = _normalize_positive(_bm25_scores(query_counts, title_counts))
    bm25_normalized = [
        BM25_CONTENT_WEIGHT * content_score + BM25_TITLE_WEIGHT * title_score
        for content_score, title_score in zip(content_bm25, title_bm25)
    ]

    if vector_result.requires_local_scan:
        vector_raw = _local_vector_scores(rows, query_embedding)
    else:
        vector_raw = [vector_result.scores.get(int(row["id"]), 0.0) for row in rows]
    vector_normalized = _normalize_positive(vector_raw)
    hybrid_active = bool(query_embedding and any(vector_normalized))

    ranked: list[SearchHit] = []
    for index, (row, counts) in enumerate(zip(rows, chunk_counts)):
        matched_terms = sorted(
            set(query_counts) & set(counts),
            key=lambda token: query_counts.get(token, 0),
            reverse=True,
        )
        rerank_score = _local_rerank(question, query_counts, row["title"], row["content"], counts)
        if hybrid_active:
            final_score = 0.48 * bm25_normalized[index] + 0.42 * vector_normalized[index] + 0.10 * rerank_score
            retrieval_mode = "hybrid"
        else:
            final_score = 0.86 * bm25_normalized[index] + 0.14 * rerank_score
            retrieval_mode = "bm25"
        if final_score <= 0:
            continue
        ranked.append(
            SearchHit(
                chunk_id=row["id"],
                document_id=row["document_id"],
                document_title=row["title"],
                document_filename=row["filename"],
                document_access_level=row["access_level"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                score=round(final_score, 6),
                matched_terms=matched_terms[:10],
                query_terms=query_terms[:20],
                bm25_score=round(bm25_normalized[index], 6),
                vector_score=round(vector_raw[index], 6),
                rerank_score=round(rerank_score, 6),
                retrieval_mode=retrieval_mode,
                vector_backend=vector_result.backend,
                vector_degraded=vector_result.degraded,
                vector_error=vector_result.error,
                lexical_backend=lexical_result.backend,
                lexical_degraded=lexical_result.status != "ready",
                lexical_error=lexical_result.error,
                candidate_count=len(rows),
                corpus_count=corpus_count,
            )
        )

    return sorted(ranked, key=lambda item: (item.score, item.bm25_score, item.vector_score), reverse=True)[:top_k]


def _vector_candidates(
    query_embedding: list[float] | None,
    embedding_model: str | None,
    allowed_document_ids: list[int],
    top_k: int,
) -> _VectorCandidates:
    if not query_embedding or not embedding_model:
        return _VectorCandidates(backend="none")

    try:
        backend = vector_store_backend()
    except VectorStoreConfigurationError as exc:
        backend = "invalid"
        configuration_error = str(exc)
    else:
        configuration_error = None

    if backend == "pgvector":
        result = query_chunk_vectors(
            query_embedding,
            embedding_model,
            allowed_document_ids,
            _vector_candidate_limit(top_k),
        )
        if result.status == "ready":
            return _VectorCandidates(backend="pgvector", scores=result.scores)
        if not vector_store_fallback_enabled():
            return _VectorCandidates(backend="pgvector", degraded=True, error=result.error)
        return _VectorCandidates(
            backend="sqlite_fallback",
            degraded=True,
            error=result.error,
            requires_local_scan=True,
        )
    elif backend == "invalid" and not vector_store_fallback_enabled():
        return _VectorCandidates(backend="invalid", degraded=True, error=configuration_error)

    degraded = backend in {"invalid", "sqlite_fallback"}
    public_backend = "sqlite_json" if backend == "sqlite" else backend
    return _VectorCandidates(
        backend=public_backend,
        degraded=degraded,
        error=configuration_error,
        requires_local_scan=True,
    )


def _vector_candidate_limit(top_k: int) -> int:
    configured = positive_int_env("RAG_VECTOR_CANDIDATE_LIMIT", 100)
    return max(top_k, min(configured, MAX_VECTOR_CANDIDATE_LIMIT))


def _local_vector_scores(rows, query_embedding: list[float] | None) -> list[float]:
    if not query_embedding:
        return [0.0 for _ in rows]
    embeddings = [_json_vector(row["embedding_json"]) for row in rows]
    return [
        max(0.0, _dense_cosine(query_embedding, vector)) if vector else 0.0
        for vector in embeddings
    ]


def _load_candidate_rows(conn, access_levels: list[str], chunk_ids: list[int] | None):
    access_placeholders = ",".join("?" for _ in access_levels)
    base_query = f"""
        SELECT c.id, c.document_id, c.chunk_index, c.content, c.token_json,
               c.embedding_json, c.embedding_model, d.title, d.filename, d.access_level
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.access_level IN ({access_placeholders}) AND d.status = 'ready'
    """
    if chunk_ids is None:
        return conn.execute(f"{base_query} ORDER BY c.id DESC", access_levels).fetchall()

    rows = []
    for start in range(0, len(chunk_ids), SQLITE_CANDIDATE_BATCH_SIZE):
        batch = chunk_ids[start : start + SQLITE_CANDIDATE_BATCH_SIZE]
        id_placeholders = ",".join("?" for _ in batch)
        rows.extend(
            conn.execute(
                f"{base_query} AND c.id IN ({id_placeholders}) ORDER BY c.id DESC",
                (*access_levels, *batch),
            ).fetchall()
        )
    return rows


def has_restricted_topic_match(question: str, access_levels: list[str]) -> bool:
    """Detect a strong inaccessible-title match without reading restricted content."""
    placeholders = ",".join("?" for _ in access_levels)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT title
            FROM documents
            WHERE access_level NOT IN ({placeholders}) AND status = 'ready'
            """,
            access_levels,
        ).fetchall()
    query_terms = _semantic_terms(question)
    if not query_terms:
        return False
    compact_question = "".join(question.lower().split())
    for row in rows:
        aliases = RESTRICTED_TOPIC_ALIASES.get(row["title"], ())
        if any(all(term in compact_question for term in group) for group in aliases):
            return True
        title_terms = _semantic_terms(row["title"])
        if not title_terms:
            continue
        overlap = query_terms & title_terms
        if (
            len(overlap) >= 2
            and len(overlap) / len(title_terms) >= RESTRICTED_TITLE_COVERAGE
            and len(overlap) / len(query_terms) >= RESTRICTED_QUERY_COVERAGE
        ):
            return True
    return False


def _semantic_terms(text: str) -> set[str]:
    ignored = {"需要", "哪些", "什么", "如何", "怎么", "怎样", "请问", "是否"}
    return {term for term in tokenize(text) if len(term) >= 2 and term not in ignored}


def _bm25_scores(query_counts: dict[str, int], documents: list[dict[str, int]]) -> list[float]:
    if not query_counts or not documents:
        return [0.0 for _ in documents]
    document_count = len(documents)
    lengths = [sum(counts.values()) for counts in documents]
    average_length = sum(lengths) / document_count or 1.0
    document_frequency: Counter[str] = Counter()
    for counts in documents:
        document_frequency.update(counts.keys())

    scores = []
    for counts, length in zip(documents, lengths):
        score = 0.0
        for term, query_frequency in query_counts.items():
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            df = document_frequency.get(term, 0)
            inverse_frequency = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
            denominator = frequency + BM25_K1 * (1 - BM25_B + BM25_B * length / average_length)
            score += inverse_frequency * (frequency * (BM25_K1 + 1) / denominator) * min(query_frequency, 2)
        scores.append(score)
    return scores


def _local_rerank(
    question: str,
    query_counts: dict[str, int],
    title: str,
    content: str,
    content_counts: dict[str, int],
) -> float:
    query_terms = set(query_counts)
    if not query_terms:
        return 0.0
    coverage = len(query_terms & set(content_counts)) / len(query_terms)
    title_terms = set(token_counts(title))
    title_coverage = len(query_terms & title_terms) / len(query_terms)
    compact_question = "".join(question.lower().split())
    compact_content = "".join(content.lower().split())
    phrase_bonus = 1.0 if compact_question and compact_question in compact_content else 0.0
    return min(1.0, coverage * 0.65 + title_coverage * 0.25 + phrase_bonus * 0.10)


def _normalize_positive(values: list[float]) -> list[float]:
    maximum = max(values, default=0.0)
    if maximum <= 0:
        return [0.0 for _ in values]
    return [max(0.0, value) / maximum for value in values]


def _dense_cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    numerator = sum(left * right for left, right in zip(a, b))
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if not norm_a or not norm_b:
        return 0.0
    return numerator / (norm_a * norm_b)


def _json_dict(raw: str) -> dict[str, int]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _json_vector(raw: str | None) -> list[float]:
    try:
        value = json.loads(raw or "[]")
        return [float(item) for item in value] if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
