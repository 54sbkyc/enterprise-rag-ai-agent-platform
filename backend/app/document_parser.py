from pathlib import Path

from .text_processing import normalize_text


SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf", ".docx"}


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return normalize_text(path.read_text(encoding="utf-8", errors="ignore"))
    if suffix == ".pdf":
        return normalize_text(_extract_pdf(path))
    if suffix == ".docx":
        return normalize_text(_extract_docx(path))
    raise ValueError(f"Unsupported document type: {suffix}")


def _extract_pdf(path: Path) -> str:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PDF parsing requires PyMuPDF. Run: pip install -r requirements.txt") from exc

    parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    return "\n".join(parts)


def _extract_docx(path: Path) -> str:
    try:
        import docx
    except ImportError as exc:
        raise RuntimeError("DOCX parsing requires python-docx. Run: pip install -r requirements.txt") from exc

    document = docx.Document(str(path))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)
