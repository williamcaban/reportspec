"""ReportSpec render service (proof of concept): a stateless HTTP API over the same renderer the command line uses.

Nothing is stored. Each request carries the template and the results and gets the document back. The service
knows nothing about EvalHub, ASAGO or any other host; a host sends a ReportSpec template and its native results
(or a ResultsBundle) and receives a rendered report.

Renders run in a subprocess of the command line (`python -m reportspec render`), not in the server process:
a render can be killed on timeout, a crash or runaway template cannot take the server down, the subprocess
sees only a small allowlist of environment variables (never the API token), and the macOS Pango workaround
in the CLI applies unchanged.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import shutil
import signal
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from .. import __version__
from ..core import ADAPTERS, SpecError, build_bundle, host_namespaces, validate_text
from .settings import Settings

FORMATS = ("markdown", "json", "html", "pdf", "docx")
MEDIA_TYPES = {
    "markdown": "text/markdown; charset=utf-8",
    "json": "application/json",
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
EXTENSIONS = {"markdown": "md", "json": "json", "html": "html", "pdf": "pdf", "docx": "docx"}
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
CHILD_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "FONTCONFIG_PATH", "FONTCONFIG_FILE", "XDG_CACHE_HOME",
             "XDG_DATA_DIRS", "DYLD_FALLBACK_LIBRARY_PATH", "LD_LIBRARY_PATH", "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED")
PLAYGROUND_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
                  "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
# Reports are built from untrusted data. They are served as downloads and, when previewed, in a sandboxed frame.
DOCUMENT_HEADERS = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
                    "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; sandbox"}


class Input(BaseModel):
    """One results input. `content` is a JSON document (an object, adapter auto-detected unless `adapter` is
    given) or a string holding the text of a file (JSONL unless `adapter` names another adapter)."""
    model_config = ConfigDict(extra="forbid")
    content: str | dict[str, Any]
    adapter: str | None = Field(default=None, description=f"one of: {', '.join(ADAPTERS)}")
    name: str | None = Field(default=None, description="file name recorded in the evidence manifest, e.g. results.jsonl")


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: str = Field(description="the .report.md source")


class BundleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: list[Input] = Field(min_length=1)


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: str = Field(description="the .report.md source")
    inputs: list[Input] = Field(min_length=1)
    params: dict[str, str | int | float | bool] = Field(default_factory=dict, description="overrides for params declared in the template")
    format: Literal["markdown", "json", "html", "pdf", "docx"] = "html"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict[str, str] | None = None):
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


class BodyLimit:
    """ASGI middleware: refuse request bodies over the limit, including chunked ones that send no Content-Length."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        too_large = _error(413, "body_too_large", f"request body is over {self.max_bytes // 1024 // 1024 or 1} MB")
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            return await too_large(scope, receive, send)
        seen = 0
        rejected = False

        async def limited():
            nonlocal seen, rejected
            if rejected:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > self.max_bytes:
                    rejected = True
                    await too_large(scope, receive, send)  # answer now; the app then sees a disconnect and its own reply is dropped
                    return {"type": "http.disconnect"}
            return msg

        async def guarded_send(message):
            if not rejected:
                await send(message)

        await self.app(scope, limited, guarded_send)


def _write_inputs(tmp: Path, inputs: list[Input]) -> list[str]:
    """Write each input to a file named by us and return the `--input` arguments. User-supplied names are only
    ever file names (validated), never paths."""
    args = []
    for n, item in enumerate(inputs, 1):
        adapter = item.adapter
        if adapter is not None and adapter not in ADAPTERS:
            raise ApiError(422, "unknown_adapter", f"unknown adapter {adapter!r}; adapters: {', '.join(ADAPTERS)}")
        if item.name is not None and not SAFE_NAME.fullmatch(item.name):
            raise ApiError(422, "invalid_name", "input name must be a plain file name (letters, digits, . _ -), up to 64 characters")
        if isinstance(item.content, str):
            adapter = adapter or "jsonl"
            text = item.content
        else:
            text = json.dumps(item.content)
        suffix = ".jsonl" if adapter == "jsonl" else ".json"
        name = item.name or f"input-{n}{suffix}"
        if (tmp / name).exists():
            raise ApiError(422, "duplicate_name", f"two inputs are named {name!r}")
        (tmp / name).write_text(text, encoding="utf-8")
        args.append(f"{adapter}:{tmp / name}" if adapter else str(tmp / name))
    return args


def _child_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in CHILD_ENV if k in os.environ}
    brew = Path("/opt/homebrew/lib")
    if sys.platform == "darwin" and brew.is_dir():
        env["DYLD_FALLBACK_LIBRARY_PATH"] = f"{brew}:{env.get('DYLD_FALLBACK_LIBRARY_PATH', '')}".rstrip(":")
    return env


@lru_cache(maxsize=1)
def _capabilities() -> dict[str, Any]:
    """Which output formats this server can produce. PDF needs Pango, DOCX needs pandoc."""
    import subprocess
    try:
        pdf = subprocess.run([sys.executable, "-c", "import weasyprint"], env=_child_env(), capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        pdf = False
    formats = ["markdown", "json", "html"] + (["pdf"] if pdf else []) + (["docx"] if shutil.which("pandoc") else [])
    return {"formats": formats, "adapters": list(ADAPTERS)}


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    app = FastAPI(
        title="ReportSpec render service (proof of concept)",
        version=__version__,
        summary="Stateless HTTP API: template and results in, report out.",
        description=("Renders ReportSpec v1alpha1 templates. A proof of concept: not final, not adopted by any project, "
                     "and not a stable interface. Nothing is stored. See https://github.com/williamcaban/reportspec"),
        docs_url="/docs" if cfg.docs else None, redoc_url=None, openapi_url="/openapi.json" if cfg.docs else None,
    )
    app.add_middleware(BodyLimit, max_bytes=cfg.max_body_bytes)
    if cfg.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_methods=["GET", "POST"],
                           allow_headers=["Authorization", "Content-Type"], expose_headers=["X-ReportSpec-Spec-Digest", "X-ReportSpec-Warnings"])
    gate = asyncio.Semaphore(cfg.max_concurrency)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError):
        return _error(e.status, e.code, e.message, e.headers)

    @app.exception_handler(RequestValidationError)
    async def bad_request(_: Request, e: RequestValidationError):
        # Report where and why, never the offending value: it can be a large document.
        detail = "; ".join(f"{'.'.join(str(p) for p in err['loc'] if p != 'body')}: {err['msg']}" for err in e.errors()[:5])
        return _error(422, "invalid_request", detail or "invalid request")

    def authorize(request: Request) -> None:
        if cfg.api_token is None:
            return
        given = request.headers.get("authorization", "")
        if not (given.startswith("Bearer ") and hmac.compare_digest(given[7:], cfg.api_token)):
            raise ApiError(401, "unauthorized", "a valid bearer token is required", {"WWW-Authenticate": "Bearer"})

    auth = [Depends(authorize)]

    @app.get("/healthz", tags=["service"], summary="Liveness")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/capabilities", tags=["service"], dependencies=auth, summary="Version, formats this server can produce, limits")
    def capabilities() -> dict[str, Any]:
        return {"version": __version__, "spec": "v1alpha1", **_capabilities(),
                "limits": {"max_body_bytes": cfg.max_body_bytes, "max_inputs": cfg.max_inputs, "render_timeout_seconds": cfg.render_timeout,
                           "max_concurrency": cfg.max_concurrency}}

    @app.post("/v1/validate", tags=["render"], dependencies=auth, summary="Check a template without rendering")
    def validate(req: ValidateRequest) -> dict[str, Any]:
        rep, fm, *_ = validate_text(req.spec)
        return {"valid": not rep.errors, "errors": list(rep.errors), "warnings": list(rep.warnings),
                "host_namespaces": host_namespaces(fm) if fm else []}

    @app.post("/v1/bundle", tags=["render"], dependencies=auth, summary="Normalize results into a ResultsBundle")
    def bundle(req: BundleRequest) -> dict[str, Any]:
        if len(req.inputs) > cfg.max_inputs:
            raise ApiError(422, "too_many_inputs", f"at most {cfg.max_inputs} inputs per request")
        with tempfile.TemporaryDirectory(prefix="reportspec-") as d:
            args = _write_inputs(Path(d), req.inputs)
            try:
                return build_bundle(args)
            except SpecError as e:
                raise ApiError(422, "invalid_input", str(e).replace(d + "/", "")) from e

    @app.post("/v1/render", tags=["render"], dependencies=auth, summary="Render a report",
              response_class=Response, responses={200: {"description": "The rendered document", "content": {m: {} for m in MEDIA_TYPES.values()}}})
    async def render(req: RenderRequest) -> Response:
        if len(req.inputs) > cfg.max_inputs:
            raise ApiError(422, "too_many_inputs", f"at most {cfg.max_inputs} inputs per request")
        if req.format not in (await asyncio.to_thread(_capabilities))["formats"]:
            raise ApiError(501, "format_unavailable", f"this server cannot produce {req.format}: " +
                           ("Pango is not installed" if req.format == "pdf" else "pandoc is not installed"))
        try:
            await asyncio.wait_for(gate.acquire(), cfg.queue_timeout)
        except TimeoutError:
            raise ApiError(503, "busy", "the server is rendering other requests; retry shortly", {"Retry-After": "5"}) from None
        try:
            return await _render(req, cfg)
        finally:
            gate.release()

    if cfg.playground:
        page = (Path(__file__).parent / "playground.html").read_text(encoding="utf-8")
        example_spec = (Path(__file__).parent / "examples" / "quickstart.report.md").read_text(encoding="utf-8")
        example_data = (Path(__file__).parent / "examples" / "quickstart.jsonl").read_text(encoding="utf-8")
        page = page.replace("__SPEC__", json.dumps(example_spec).replace("<", "\\u003c")).replace("__DATA__", json.dumps(example_data).replace("<", "\\u003c"))

        @app.get("/", include_in_schema=False)
        def playground() -> HTMLResponse:
            return HTMLResponse(page, headers={"Content-Security-Policy": PLAYGROUND_CSP, "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    return app


async def _render(req: RenderRequest, cfg: Settings) -> Response:
    with tempfile.TemporaryDirectory(prefix="reportspec-") as d:
        tmp = Path(d)
        inputs = _write_inputs(tmp, req.inputs)
        spec = tmp / "spec.report.md"
        spec.write_text(req.spec, encoding="utf-8")
        out = tmp / f"out.{EXTENSIONS[req.format]}"
        cmd = [sys.executable, "-m", "reportspec", "render", str(spec), "--format", req.format, "-o", str(out)]
        for i in inputs:
            cmd += ["--input", i]
        for k, v in req.params.items():
            cmd += ["--param", f"{k}={str(v).lower() if isinstance(v, bool) else v}"]
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=d, env=_child_env(), start_new_session=True,
                                                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), cfg.render_timeout)
        except TimeoutError:
            os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            raise ApiError(504, "render_timeout", f"rendering took longer than {cfg.render_timeout:g} seconds") from None
        text = stderr.decode("utf-8", "replace").replace(d + "/", "")
        warnings = [ln[len("warning: "):] for ln in text.splitlines() if ln.startswith("warning: ")]
        if proc.returncode != 0:
            failed = [ln[len("failed: "):] for ln in text.splitlines() if ln.startswith("failed: ")]
            if failed and "pandoc not found" in failed[0]:
                raise ApiError(501, "format_unavailable", failed[0])
            if failed:
                raise ApiError(422, "render_failed", "\n".join(failed))
            print(f"render subprocess exited {proc.returncode}:\n{text}", file=sys.stderr)  # server log only; may be long
            raise ApiError(500, "render_error", "the renderer failed unexpectedly; see the server log")
        body = out.read_bytes()
        headers = {**DOCUMENT_HEADERS, "Content-Disposition": f'attachment; filename="report.{EXTENSIONS[req.format]}"',
                   "X-ReportSpec-Warnings": str(len(warnings)),
                   "X-ReportSpec-Spec-Digest": "sha256:" + hashlib.sha256(req.spec.encode()).hexdigest()}
        return Response(body, media_type=MEDIA_TYPES[req.format], headers=headers)
