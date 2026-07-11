FROM python:3.13-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libreoffice \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-editable

COPY src/ ./src/
COPY api/ ./api/

RUN useradd -m -u 1001 appuser && chown -R appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1

EXPOSE 8010

CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8010"]
