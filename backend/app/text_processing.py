import math
import re
from collections import Counter
from typing import Iterable

from .config import CHUNK_OVERLAP, CHUNK_SIZE


TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+")
SENTENCE_RE = re.compile(r"(?<=[。！？.!?])\s+|\n+")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text):
        lowered = raw.lower()
        if re.fullmatch(r"[\u4e00-\u9fff]+", lowered):
            tokens.extend(_tokenize_chinese(lowered))
        else:
            tokens.append(lowered)
    return tokens


def _tokenize_chinese(text: str) -> list[str]:
    terms: list[str] = []
    try:
        import jieba

        terms.extend(token for token in jieba.lcut(text) if token.strip())
    except ImportError:
        pass

    # Keep character-level tokens as a fallback so old indexes and short queries still match.
    terms.extend(list(text))
    return terms


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    clean = normalize_text(text)
    if not clean:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + size)
        slice_text = clean[start:end]
        last_break = max(slice_text.rfind("\n"), slice_text.rfind("。"), slice_text.rfind("."), slice_text.rfind("!"), slice_text.rfind("?"))
        if last_break > size * 0.55 and end < len(clean):
            end = start + last_break + 1
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(clean):
            break
        start = max(0, end - overlap)
    return chunks


def token_counts(text: str) -> dict[str, int]:
    return dict(Counter(tokenize(text)))


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    numerator = sum(a[token] * b[token] for token in common)
    norm_a = math.sqrt(sum(value * value for value in a.values()))
    norm_b = math.sqrt(sum(value * value for value in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return numerator / (norm_a * norm_b)


def build_idf(token_docs: Iterable[dict[str, int]]) -> dict[str, float]:
    docs = list(token_docs)
    total = len(docs)
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(doc.keys())
    return {token: math.log((1 + total) / (1 + count)) + 1 for token, count in df.items()}


def tfidf_vector(counts: dict[str, int], idf: dict[str, float]) -> dict[str, float]:
    total = sum(counts.values()) or 1
    return {token: (count / total) * idf.get(token, 1.0) for token, count in counts.items()}


def split_sentences(text: str) -> list[str]:
    return [item.strip() for item in SENTENCE_RE.split(text) if item.strip()]
