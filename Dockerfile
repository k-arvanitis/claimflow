FROM python:3.13-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libreoffice \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

RUN useradd -m -u 1001 appuser

WORKDIR /app

# doc-intel is a sibling, editable-install dependency (pyproject.toml's
# [tool.uv.sources] points at ../doc-intel, i.e. /doc-intel from here) — not
# inside this build context by default. Build with:
#   docker build --build-context doc-intel=../doc-intel -t claimflow .
# Only pyproject.toml/README/src are needed to build its wheel — `COPY --from
# ... .` (the whole tree) would drag in doc-intel's own multi-GB .venv too.
COPY --chown=appuser:appuser --from=doc-intel pyproject.toml README.md /doc-intel/
COPY --chown=appuser:appuser --from=doc-intel src/ /doc-intel/src/

COPY --chown=appuser:appuser pyproject.toml uv.lock* ./
RUN chown appuser:appuser /app && chown appuser:appuser /doc-intel
USER appuser
RUN uv sync --no-dev --no-editable

COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser api/ ./api/
COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser alembic/ ./alembic/
# Code-set lookups (icd10/cpt validators) and the policy PDFs the Policies
# page serves/reindexes — both read from disk at runtime, not bundled into
# the wheel. data/synthetic and data/real_public (eval fixtures, not needed
# to run the app) are deliberately not copied.
COPY --chown=appuser:appuser data/lookups/ ./data/lookups/
COPY --chown=appuser:appuser data/policies/ ./data/policies/

ENV PYTHONUNBUFFERED=1

EXPOSE 8010

CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8010"]
