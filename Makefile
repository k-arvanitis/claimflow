.PHONY: install dev test lint api ui eval docker-up docker-down seed generate clean \
	download-real-public eval-health-public eval-property-public eval-loan-public eval-real-public \
	db-migrate db-init db-revision

install:
	uv sync

dev:
	uv sync --extra dev

db-migrate:
	uv run alembic upgrade head

db-init: db-migrate
	@echo "Database initialized at $$(uv run python -c 'from claimflow.config import settings; print(settings.db_path)')"

db-revision:
	uv run alembic revision --autogenerate -m "$(MSG)"

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

api:
	uv run uvicorn api.main:app --reload --port 8010

ui:
	uv run streamlit run streamlit_app.py --server.port 8011

eval:
	uv run python scripts/run_eval.py

docker-up:
	docker compose up -d

docker-down:
	docker compose down

seed:
	uv run python scripts/seed_qdrant.py

generate:
	uv run python scripts/generate_cms1500.py
	uv run python scripts/generate_xactimate.py
	uv run python scripts/generate_loan.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -name "*.pyc" -delete 2>/dev/null; true

# Real/public eval layer (eval/real_public/) — domain-specific validation and
# extraction against real public data, additional to (not a replacement for)
# the synthetic eval above. Horizontal OCR/classification benchmarks (FUNSD,
# RVL-CDIP) live in doc-intel's own eval instead — see its TODO.md.
download-real-public:
	uv run python eval/real_public/scripts/download_real_public.py --dataset all

eval-health-public:
	uv run python eval/real_public/scripts/prepare_health_public.py

eval-property-public:
	uv run python eval/real_public/scripts/prepare_property_public.py

eval-loan-public:
	uv run python eval/real_public/scripts/prepare_loan_public.py

eval-real-public: eval-health-public eval-property-public eval-loan-public
	uv run python eval/real_public/scripts/run_real_public_eval.py
	uv run python eval/real_public/scripts/aggregate_results.py
