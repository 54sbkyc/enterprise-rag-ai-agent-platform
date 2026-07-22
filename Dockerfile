# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/backend \
    RAG_RUNTIME_ENV=production \
    RAG_DB_PATH=/app/data/rag_platform.db \
    RAG_UPLOAD_DIR=/app/data/uploads

RUN groupadd --gid "${APP_GID}" rag \
    && useradd --uid "${APP_UID}" --gid rag --create-home --shell /usr/sbin/nologin rag \
    && mkdir -p /app/backend /app/frontend /app/data/uploads \
    && chown -R rag:rag /app

WORKDIR /app

COPY backend/requirements-runtime.txt /tmp/requirements-runtime.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-runtime.txt

COPY --chown=rag:rag backend/app /app/backend/app
COPY --chown=rag:rag backend/evaluation /app/backend/evaluation
COPY --chown=rag:rag frontend /app/frontend

WORKDIR /app/backend
USER rag

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=3).read()"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
