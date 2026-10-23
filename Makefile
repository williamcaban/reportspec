# Development tasks. Everything installs under this directory: .venv (packages) and .uv (Python and uv cache).
# `make clean` removes both. Needs only uv (https://docs.astral.sh/uv/).
export UV_PYTHON_INSTALL_DIR := $(CURDIR)/.uv/python

.PHONY: setup test lint conformance serve clean

setup:            ## create .venv with the locked dependencies, including the optional render service
	uv sync --frozen --extra service

test: setup       ## unit tests
	uv run --frozen pytest -ra

lint: setup       ## ruff
	uv run --frozen ruff check src tests

conformance: setup
	uv run --frozen reportspec conformance conformance

serve: setup      ## run the render service on 127.0.0.1:8000 with the playground
	uv run --frozen reportspec serve --playground

clean:
	rm -rf .venv .uv .pytest_cache .ruff_cache dist
