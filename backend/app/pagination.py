import math

from fastapi import HTTPException


DEFAULT_PAGE_SIZE = 5
MAX_PAGE_SIZE = 100


def normalize_pagination(page: int | None, page_size: int | None) -> tuple[int, int, int]:
    normalized_page = 1 if page is None else page
    normalized_size = DEFAULT_PAGE_SIZE if page_size is None else min(page_size, MAX_PAGE_SIZE)
    if normalized_page < 1:
        raise HTTPException(status_code=400, detail="页码必须大于或等于 1")
    if normalized_size < 1:
        raise HTTPException(status_code=400, detail="每页数量必须大于或等于 1")
    return normalized_page, normalized_size, (normalized_page - 1) * normalized_size


def paginated(items: list[dict], total: int, page: int, page_size: int) -> dict:
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }
