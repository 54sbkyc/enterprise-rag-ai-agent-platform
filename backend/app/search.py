import json
import math
from collections import Counter
from dataclasses import dataclass

from .db import get_conn
from .embeddings import embed_query
from .text_processing import token_counts, tokenize


BM25_K1 = 1.5
BM25_B = 0.75
BM25_CONTENT_WEIGHT = 0.70
BM25_TITLE_WEIGHT = 0.30
RESTRICTED_TITLE_COVERAGE = 0.25


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


def search_chunks(question: str, top_k: int, access_levels: list[str] | None = None) -> list[SearchHit]:
    access_levels = access_levels or ["public", "internal"]
    placeholders = ",".join("?" for _ in access_levels)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.id, c.document_id, c.chunk_index, c.content, c.token_json,
                   c.embedding_json, c.embedding_model, d.title, d.filename, d.access_level
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.access_level IN ({placeholders}) AND d.status = 'ready'
            ORDER BY c.id DESC
            """,
            access_levels,
        ).fetchall()

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

    embeddings = [_json_vector(row["embedding_json"]) for row in rows]
    embedding_models = Counter(
        row["embedding_model"] for row, vector in zip(rows, embeddings) if row["embedding_model"] and vector
    )
    embedding_model = embedding_models.most_common(1)[0][0] if embedding_models else None
    query_embedding = embed_query(question, embedding_model) if embedding_model else None
    vector_raw = [
        max(0.0, _dense_cosine(query_embedding, vector)) if query_embedding and vector else 0.0
        for vector in embeddings
    ]
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
            )
        )

    return sorted(ranked, key=lambda item: (item.score, item.bm25_score, item.vector_score), reverse=True)[:top_k]


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
    query_terms = set(tokenize(question))
    if not query_terms:
        return False
    for row in rows:
        title_terms = set(tokenize(row["title"]))
        if not title_terms:
            continue
        overlap = query_terms & title_terms
        semantic_overlap = any(len(term) >= 2 for term in overlap)
        if semantic_overlap and len(overlap) / len(title_terms) >= RESTRICTED_TITLE_COVERAGE:
            return True
    return False


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
