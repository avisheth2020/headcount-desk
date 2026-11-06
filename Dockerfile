# Small image for Cloud Run. Built by `gcloud run deploy --source .` (no local Docker needed).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
RUN pip install --no-cache-dir uv

# Dependencies first, so this layer is cached when only code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app app
COPY db db
COPY scripts scripts
ENV PATH="/app/.venv/bin:$PATH"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
