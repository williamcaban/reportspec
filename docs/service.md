# Render service (optional)

The render service is a small HTTP API over the same renderer the command line uses: send a template and results, get a report back. It is optional. The CLI and the Python package work without it, and nothing in them depends on it.

It is a standalone service. It knows nothing about EvalHub, ASAGO or any other product. Any client that can send a ReportSpec template and results can use it, now or later. Like the rest of ReportSpec it is a proof of concept: not a stable interface.

**Stateless.** Nothing is stored. Each request carries everything and gets the document back.

## Install and start

```bash
pip install "reportspec[service] @ git+https://github.com/williamcaban/reportspec"   # or: uv tool install "reportspec[service] @ git+https://github.com/williamcaban/reportspec"
reportspec serve --playground
```

From a clone: `make serve` (see [Development](development.md)). In a container, the image already includes the service ([Running in a container](container.md)):

```bash
podman run --rm -p 8000:8000 reportspec serve --host 0.0.0.0 --playground
```

Without the extra, `reportspec serve` stops with `the render service needs its optional dependencies: pip install "reportspec[service]"`.

It listens on `127.0.0.1:8000` by default. Interactive API documentation is at `/docs`, and the machine-readable description at `/openapi.json`.

## The playground

With `--playground` (or `REPORTSPEC_PLAYGROUND=1`), `http://127.0.0.1:8000/` serves a page where you paste a template and JSONL results and render them: a preview in the page, and downloads for PDF, DOCX, Markdown and the evidence manifest. It starts with the [quickstart](tutorial.md) example. It is off by default, and it makes no requests to anything but the service itself.

## Endpoints

| Method and path | Purpose |
|---|---|
| `GET /healthz` | Liveness. Always open, even when a token is required |
| `GET /v1/capabilities` | Version, the formats this server can produce (PDF needs Pango, DOCX needs pandoc), the adapters, and the limits |
| `POST /v1/validate` | Check a template without rendering |
| `POST /v1/bundle` | Normalize results into a [ResultsBundle](results-and-bindings.md) |
| `POST /v1/render` | Render a report |

All request bodies are JSON. Unknown fields are rejected.

### Inputs

A request's `inputs` list holds the results. Each input is an object:

| Field | Meaning |
|---|---|
| `content` | Required. Either a JSON **object** (a native document such as an EvalHub job or a MiDojo `results.json`; the adapter is detected) or a **string** (the text of a file; JSONL unless `adapter` says otherwise) |
| `adapter` | Optional: `jsonl`, `evalhub-job`, `midojo`, `asago-risk-extraction` or `bundle` |
| `name` | Optional file name recorded in the evidence manifest, such as `results.jsonl`. A plain name only: letters, digits, `.`, `_`, `-`, at most 64 characters |

Several inputs can be sent, as with repeated `--input` on the command line.

### Render

```json
{
  "spec": "<the .report.md text>",
  "inputs": [{ "content": "<JSONL text>", "adapter": "jsonl" }],
  "params": { "min_accuracy": 0.5, "team": "Red team" },
  "format": "pdf"
}
```

`format` is `markdown`, `json`, `html` (the default), `pdf` or `docx`. `params` overrides parameters declared in the template, with the same rules as `--param` ([Parameters](parameters.md)): undeclared, locked or wrongly typed values are rejected.

The response body is the document itself, with these headers:

| Header | Value |
|---|---|
| `Content-Type` | `text/markdown`, `application/json`, `text/html`, `application/pdf` or the DOCX type |
| `Content-Disposition` | `attachment; filename="report.<ext>"` |
| `X-ReportSpec-Spec-Digest` | `sha256:` of the template you sent |
| `X-ReportSpec-Warnings` | Number of render warnings. Run `/v1/validate` to read them |

`format: json` returns the evidence manifest: every resolved value, the source digests, the effective parameters and the warnings.

### Examples

With `curl` and `jq` (from a clone, for the example files):

```bash
jq -n --rawfile spec examples/quickstart.report.md --rawfile data examples/inputs/quickstart.jsonl \
  '{spec: $spec, inputs: [{content: $data, adapter: "jsonl"}], format: "pdf"}' |
  curl -s -X POST http://127.0.0.1:8000/v1/render -H 'Content-Type: application/json' --data @- -o report.pdf
```

Validate a template:

```bash
jq -n --rawfile spec examples/quickstart.report.md '{spec: $spec}' |
  curl -s -X POST http://127.0.0.1:8000/v1/validate -H 'Content-Type: application/json' --data @-
# {"valid":true,"errors":[],"warnings":[],"host_namespaces":[]}
```

From Python:

```python
import json, urllib.request

req = {"spec": open("examples/quickstart.report.md").read(),
       "inputs": [{"content": open("examples/inputs/quickstart.jsonl").read(), "adapter": "jsonl"}],
       "params": {"team": "API team"}, "format": "markdown"}
r = urllib.request.Request("http://127.0.0.1:8000/v1/render", json.dumps(req).encode(), {"Content-Type": "application/json"})
print(urllib.request.urlopen(r).read().decode())
```

## Errors

Every error is JSON, `{"error": {"code": "...", "message": "..."}}`. Messages never contain server paths, and a rejected request is never echoed back.

| Status | Code | Meaning |
|---|---|---|
| 401 | `unauthorized` | A bearer token is required and missing or wrong |
| 413 | `body_too_large` | Request over the size limit |
| 422 | `invalid_request` | The JSON does not match the request shape (field and reason are named) |
| 422 | `render_failed` | The template or results are invalid, or a parameter was rejected. The message is the same one-line text the CLI prints |
| 422 | `invalid_input`, `invalid_name`, `unknown_adapter`, `duplicate_name`, `too_many_inputs` | Problems with `inputs` |
| 501 | `format_unavailable` | This server cannot produce that format (no Pango or no pandoc). `/v1/capabilities` lists what it can |
| 503 | `busy` | All render slots are in use. Retry after the `Retry-After` seconds |
| 504 | `render_timeout` | The render ran too long and was killed |
| 500 | `render_error` | The renderer crashed. Details are in the server log only |

## Configuration

Environment variables (the defaults suit a local trial):

| Variable | Default | Meaning |
|---|---|---|
| `REPORTSPEC_API_TOKEN` | unset | If set, every `/v1/*` request needs `Authorization: Bearer <token>` |
| `REPORTSPEC_PLAYGROUND` | off | Serve the playground at `/` (same as `--playground`) |
| `REPORTSPEC_DOCS` | on | Serve `/docs` and `/openapi.json` (`--no-docs` turns them off) |
| `REPORTSPEC_MAX_BODY_MB` | 5 | Largest request body |
| `REPORTSPEC_MAX_INPUTS` | 16 | Most inputs per request |
| `REPORTSPEC_RENDER_TIMEOUT` | 60 | Seconds before a render is killed |
| `REPORTSPEC_MAX_CONCURRENCY` | 2 | Renders running at once |
| `REPORTSPEC_QUEUE_TIMEOUT` | 10 | Seconds a request waits for a slot before `503` |
| `REPORTSPEC_CORS_ORIGINS` | none | Comma-separated origins allowed to call the API from a browser |

Flags: `--host`, `--port`, `--playground`, `--no-docs`.

## How it renders, and what that means for security

Templates and results are untrusted input: they can contain hostile text, and a template is a small program. The service does these things about it:

- **A subprocess per render.** Each render runs as `python -m reportspec render` in a temporary directory, so a timeout can kill it, a crash cannot take the server down, and nothing from one request stays around for the next. The cost is about 1 to 2 seconds of start-up per render.
- **A small environment.** The subprocess gets only a short allowlist of variables (`PATH`, `HOME`, locale and library paths). It never sees `REPORTSPEC_API_TOKEN` or any other secret.
- **The same defences as the CLI.** The template sandbox, output escaping, no network and no local files in PDF output, and the missing-data rules all apply ([Concepts](concepts.md), [Output and conformance](output-and-conformance.md)).
- **Reports are served as downloads** with `nosniff`, `no-store` and a restrictive `Content-Security-Policy`, because a report is built from untrusted data. The playground shows the preview in a sandboxed frame with scripts disabled.
- **Limits** on body size (including streamed bodies without a `Content-Length`), input count, concurrency and time. Input names can only be plain file names.

**What it does not do.** There is no TLS, no user management, no rate limiting and no audit log. The optional bearer token is a single shared secret. Do not expose the service to untrusted networks directly: put it behind a gateway or reverse proxy that provides TLS and authentication. Binding to anything but localhost without a token prints a warning. It has not been load-tested.
