# Development

Everything a developer needs is inside the repository. Nothing depends on the parent directory, a system Python, or a user-level uv cache. The only prerequisite is [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/williamcaban/reportspec && cd reportspec
make setup        # creates .venv with the locked dependencies, including the optional service
make test         # pytest
make lint         # ruff
make conformance  # the 46 conformance cases
make serve        # the render service on 127.0.0.1:8000 with the playground
make clean        # removes .venv and .uv
```

## What lives where

| Path | Contents | In git? |
|---|---|---|
| `pyproject.toml`, `uv.lock` | Dependencies, locked and hash-checked | yes |
| `.python-version` | The Python for development (3.13) | yes |
| `uv.toml` | Project-local uv settings: only uv-managed Pythons, and a package cache inside the repository | yes |
| `.venv/` | The virtual environment | no |
| `.uv/python/`, `.uv/cache/` | The Python interpreter and the package cache, so `.venv` does not point outside the repository | no |

`pyproject.toml` declares this directory as its own uv workspace root, so uv never looks at a parent directory's `pyproject.toml`, and ruff's rules are pinned there too.

The Python install location cannot be set in a uv config file, only by the environment variable `UV_PYTHON_INSTALL_DIR`. The Makefile sets it to `.uv/python`. If you run `uv` directly and want the same isolation, export it first:

```bash
export UV_PYTHON_INSTALL_DIR="$PWD/.uv/python"
uv sync --extra service
```

Without it everything still works; the interpreter is then taken from uv's default location in your home directory.

## Python versions

The code runs on Python 3.13 and 3.14. CI tests both. To try another version locally: `UV_PYTHON=3.14 uv sync --extra service`.

## Optional extras

| Extra | Adds | Command |
|---|---|---|
| `service` | FastAPI and uvicorn for [the render service](service.md) | `uv sync --extra service` |

The tests for an optional part skip themselves when its dependencies are missing, so `uv sync` without extras followed by `uv run pytest` still passes.

## macOS notes

- **PDF needs Pango.** `brew install pango`. The command line finds Homebrew's copy by itself.
- **iCloud.** If the repository is in a folder that iCloud Drive syncs (Documents, Desktop), the sync can flag files in `.venv` as hidden, and Python then ignores them: `ModuleNotFoundError: No module named 'reportspec'`. Clone the repository outside those folders, or name the environment directory `.venv.nosync` with `.venv` as a symlink to it.

## Continuous integration

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on every pull request: `uv lock --check`, ruff, pytest, the conformance suite, a wheel installed in a clean environment (with and without the service extra), a PDF font audit, and container builds for Python 3.13 and 3.14 that run conformance and the service under the same restrictions as OpenShift.
