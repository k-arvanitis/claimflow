.PHONY: install dev test lint api ui

install:
	uv sync

dev:
	uv sync --extra dev

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check src tests

api:
	uv run uvicorn api.main:app --reload --port 8010

ui:
	uv run streamlit run streamlit_app.py --server.port 8011
