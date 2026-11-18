.PHONY: install lint format type test all

install:
	uv sync

lint:
	uv run ruff check .

format:
	uv run ruff format .

type:
	uv run mypy legacy_migration_tool

test:
	uv run pytest

all: lint type test
