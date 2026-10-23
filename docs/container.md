# Running in a container

The `Containerfile` builds a Fedora Python image that runs offline, non-root and read-only.

```bash
podman build -t reportspec .                          # quay.io/fedora/python-314 (Fedora 43); --build-arg PY=313 for Fedora 42
mkdir -p out
podman run --rm --network none --read-only --tmpfs /tmp -v "$PWD/out:/out:Z" reportspec \
  render examples/model-release.report.md --input examples/inputs/model-release.jsonl --format pdf -o /out/model-release.pdf
podman run --rm --network none reportspec conformance conformance
```

The image carries pango, pandoc, the fallback fonts (Liberation, DejaVu) and a virtualenv built from `uv.lock` with hash checking, so after the build it needs no network, and it runs under OpenShift's arbitrary-uid rule (group 0 owns the files). Red Hat Text and Mono are not installed from RPMs on purpose; the vendored files are the only source (see [fonts/README.md](../src/reportspec/fonts/README.md)). Regenerate the lock with `uv lock` after changing the dependencies in `pyproject.toml`. On macOS, a Podman machine may not be able to mount a directory under `/tmp`; use one under your home.
