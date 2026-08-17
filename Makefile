.DEFAULT_GOAL := help
.PHONY: help sync format format-check lint fix types test ci run dry-run clean

help:
	@echo "sync          install the locked environment"
	@echo "format        rewrite files with ruff"
	@echo "format-check  fail if files are not formatted"
	@echo "lint          ruff check"
	@echo "fix           ruff check --fix"
	@echo "types         mypy (strict)"
	@echo "test          pytest"
	@echo "ci            everything CI runs, in the same order"
	@echo "run           collect today's snapshot"
	@echo "dry-run       collect but write nothing"
	@echo "clean         remove caches and build artefacts"

sync:
	uv sync --frozen --all-groups

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

fix:
	uv run ruff check --fix .

types:
	uv run mypy

test:
	uv run pytest

ci: sync lint format-check types test

run:
	./run.sh

dry-run:
	./run.sh --dry-run

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
