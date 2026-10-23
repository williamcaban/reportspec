# Running in a container

The container is the second way to run ReportSpec, next to the [command line](cli.md). It is the same program with everything it needs installed: Pango for PDF, pandoc for DOCX, fallback fonts, and Python dependencies locked by `uv.lock` and hash-checked. You need only Podman or Docker. After the build it needs no network, so it suits CI jobs and locked-down hosts.

There is no published image yet. Build it once from a clone.

## Build

```bash
git clone https://github.com/williamcaban/reportspec && cd reportspec
podman build -t reportspec .
```

| Build argument | Result |
|---|---|
| (none) | `quay.io/fedora/python-314`: Fedora 43, Python 3.14 |
| `--build-arg PY=313` | `quay.io/fedora/python-313`: Fedora 42, Python 3.13 |

```bash
podman build --build-arg PY=313 -t reportspec:py313 .
```

Docker takes the same arguments but needs the file name: `docker build -f Containerfile -t reportspec .`. The build downloads packages, so it needs network access. The image is about 1.5 GB because of pandoc and poppler.

Check it:

```bash
podman run --rm reportspec --version
podman run --rm reportspec conformance conformance      # 34/34 cases
```

## Run the examples

The repository, including `examples/`, is inside the image, so the example paths work as they are:

```bash
podman run --rm reportspec validate examples/safety-compliance.report.md
podman run --rm reportspec render examples/quickstart.report.md --input examples/inputs/quickstart.jsonl --format markdown
```

The image's entry point is the `reportspec` command, so everything after the image name is a [CLI command](cli.md).

## Run the render service

The image includes the optional [render service](service.md). Start it, listening on all interfaces inside the container, and publish the port:

```bash
podman run --rm -p 8000:8000 --read-only --tmpfs /tmp reportspec serve --host 0.0.0.0 --playground
```

Then open `http://127.0.0.1:8000/` for the playground, or call the API (`/docs` lists it). The service renders PDF and DOCX inside the container, so the client needs nothing installed. Set `-e REPORTSPEC_API_TOKEN=...` to require a bearer token, and see [Render service](service.md) for the other settings. It prints a warning if it listens on a non-local address without a token; put it behind a gateway with TLS before exposing it beyond your machine.

## Run it on your own files

Mount a folder into the container and write the output into it. PDF, HTML and DOCX need `-o`:

```bash
mkdir -p work && cp my.report.md results.jsonl work/
podman run --rm --network none --read-only --tmpfs /tmp -v "$PWD/work:/work:Z" reportspec \
  render /work/my.report.md --input /work/results.jsonl --format pdf -o /work/report.pdf
```

The flags, one by one:

| Flag | Why |
|---|---|
| `--network none` | Rendering never needs the network. This proves it |
| `--read-only --tmpfs /tmp` | The root filesystem is not written. Python needs a temporary directory, and Docker (unlike Podman) does not add one, so pass `--tmpfs /tmp` |
| `-v "$PWD/work:/work:Z"` | Your files. `:Z` relabels the folder for SELinux (Fedora, RHEL); drop it elsewhere |

The report appears in `work/` next to a `report.manifest.json` evidence record.

**File ownership on Linux.** The container runs as user 1001. If the output files must belong to you, pass your uid with group 0, as OpenShift does: `--user "$(id -u):0"` with Docker, or `--userns=keep-id` with rootless Podman. The mounted folder must be writable by that user. On macOS and Windows, Podman and Docker Desktop handle ownership themselves.

**macOS.** The Podman machine may be unable to mount folders under `/tmp`; use a folder in your home directory.

## What is inside

| | |
|---|---|
| Base | Fedora Python image from `quay.io/fedora/`, referenced by tag (pinning by digest is on the [roadmap](roadmap.md)) |
| Packages | `pango`, `pandoc`, `poppler-utils` (`pdffonts` for the font audit), Liberation and DejaVu fonts as fallbacks |
| Python | A virtualenv at `/opt/app-root/venv`, built with `uv sync --frozen --extra service` from `uv.lock`, using the image's own Python. `uv` is used only while building |
| Fonts | Red Hat Text and Mono come from [`src/reportspec/fonts/`](../src/reportspec/fonts/README.md) and nowhere else. Fedora's RPMs for them are the same version but OTF, and having both would make the font name resolve to two different files |
| User | Non-root (1001, group 0), so it also runs under OpenShift's arbitrary-uid rule |
| Entry point | `reportspec` |

## Change the dependencies

Edit `dependencies` in `pyproject.toml`, run `uv lock`, commit `uv.lock`, and rebuild. The build fails if the lock and `pyproject.toml` disagree (`--frozen`).

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) builds both variants with Docker on every pull request and runs conformance and a PDF render offline, read-only and as an arbitrary uid, then audits the PDF's fonts.
