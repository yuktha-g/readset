UV ?= uv

.PHONY: setup test lint fmt types check demo demo-svg bench build clean

setup:
	$(UV) sync --group dev

test:
	$(UV) run pytest --cov=readset --cov-report=term-missing

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

types:
	$(UV) run mypy

check: lint types test

demo:
	$(UV) run readset demo

demo-svg:
	$(UV) run python scripts/demo_cast.py > docs/assets/demo.cast
	uvx --python 3.12 termtosvg render docs/assets/demo.cast docs/assets/demo.svg -t window_frame_powershell -M 1500

bench:
	$(UV) run python scripts/bench.py

build:
	$(UV) build

clean:
	rm -rf dist .pytest_cache .mypy_cache .ruff_cache .coverage
