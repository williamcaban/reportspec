"""The optional HTTP render service. Skipped when the `service` extra is not installed."""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx2")

from fastapi.testclient import TestClient  # noqa: E402

from reportspec.cli import main  # noqa: E402
from reportspec.service.app import _capabilities, _child_env, create_app  # noqa: E402
from reportspec.service.settings import Settings  # noqa: E402

ROOT = Path(__file__).parent.parent
SPEC = (ROOT / "examples" / "quickstart.report.md").read_text(encoding="utf-8")
JSONL = (ROOT / "examples" / "inputs" / "quickstart.jsonl").read_text(encoding="utf-8")


def settings(**kw) -> Settings:
    base = {"playground": False, "docs": True, "api_token": None, "cors_origins": []}
    return Settings(**{**base, **kw})


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(settings()))


def body(**kw):
    return {"spec": SPEC, "inputs": [{"content": JSONL, "adapter": "jsonl"}], "format": "markdown", **kw}


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_capabilities(client):
    c = client.get("/v1/capabilities").json()
    assert {"markdown", "json", "html"} <= set(c["formats"])
    assert "jsonl" in c["adapters"] and c["spec"] == "v1alpha1"
    assert c["limits"]["max_body_bytes"] > 0


def test_validate_ok_and_invalid(client):
    assert client.post("/v1/validate", json={"spec": SPEC}).json()["valid"] is True
    bad = client.post("/v1/validate", json={"spec": "no front matter"})
    assert bad.status_code == 200 and bad.json()["valid"] is False and bad.json()["errors"]


def test_bundle_from_jsonl(client):
    r = client.post("/v1/bundle", json={"inputs": [{"content": JSONL, "adapter": "jsonl"}]})
    assert r.status_code == 200
    b = r.json()
    assert [e["id"] for e in b["evaluations"]] == ["capability", "safety"]
    assert b["evaluations"][0]["metrics"]["ifeval"]["value"] is None


def test_bundle_from_json_document_autodetects(client):
    doc = {"suite_name": "weather", "run_id": "r1", "utility": {"a,b": True}, "security": {"a,b": False}, "security_reason": {}}
    r = client.post("/v1/bundle", json={"inputs": [{"content": doc}]})
    assert r.status_code == 200 and r.json()["evaluations"][0]["id"] == "midojo.weather"


def test_render_markdown_and_digest_header(client):
    r = client.post("/v1/render", json=body())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "above the 10% ceiling" in r.text and "data unavailable" in r.text
    assert r.headers["x-reportspec-spec-digest"] == "sha256:" + hashlib.sha256(SPEC.encode()).hexdigest()
    assert r.headers["x-reportspec-warnings"] == "0"


def test_render_html_is_a_locked_down_download(client):
    r = client.post("/v1/render", json=body(format="html"))
    assert r.status_code == 200 and "<svg" in r.text
    assert r.headers["content-disposition"].startswith("attachment")
    assert "default-src 'none'" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"


def test_render_json_is_the_manifest(client):
    m = client.post("/v1/render", json=body(format="json")).json()
    assert m["report"]["spec_name"] == "spec" and m["sources"][0]["adapter"] == "jsonl"


def test_param_override(client):
    r = client.post("/v1/render", json=body(params={"team": "API team", "min_accuracy": 0.5}))
    assert "API team" in r.text and "Threshold: 50.0%" in r.text


@pytest.mark.parametrize("params,message", [
    ({"asr_ceiling": 0.5}, "not overridable"),
    ({"nope": 1}, "not declared"),
    ({"min_accuracy": "abc"}, "is not a number"),
])
def test_bad_params_are_422(client, params, message):
    r = client.post("/v1/render", json=body(params=params))
    assert r.status_code == 422 and r.json()["error"]["code"] == "render_failed" and message in r.json()["error"]["message"]


def test_bad_input_is_422_without_server_paths(client):
    r = client.post("/v1/render", json=body(inputs=[{"content": "not json", "adapter": "jsonl"}]))
    assert r.status_code == 422
    msg = r.json()["error"]["message"]
    assert "invalid JSON" in msg and "/" not in msg


def test_invalid_template_is_422(client):
    r = client.post("/v1/render", json=body(spec="no front matter"))
    assert r.status_code == 422 and "invalid" in r.json()["error"]["message"]


@pytest.mark.parametrize("name", ["../../etc/passwd", "a/b.jsonl", ".hidden", "x" * 80])
def test_input_names_must_be_plain_file_names(client, name):
    r = client.post("/v1/render", json=body(inputs=[{"content": JSONL, "adapter": "jsonl", "name": name}]))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_name"


def test_unknown_adapter_duplicate_name_and_unknown_field(client):
    r = client.post("/v1/bundle", json={"inputs": [{"content": "{}", "adapter": "nope"}]})
    assert r.json()["error"]["code"] == "unknown_adapter"
    two = [{"content": JSONL, "adapter": "jsonl", "name": "r.jsonl"}] * 2
    assert client.post("/v1/bundle", json={"inputs": two}).json()["error"]["code"] == "duplicate_name"
    r = client.post("/v1/render", json={**body(), "bogus": 1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request" and "bogus" in r.json()["error"]["message"]
    assert client.post("/v1/render", json={"spec": SPEC, "inputs": []}).status_code == 422


def test_invalid_request_error_does_not_echo_the_payload(client):
    secret = "S3CRET-" * 50
    r = client.post("/v1/render", json={"spec": SPEC, "inputs": [{"content": JSONL}], "format": secret})
    assert r.status_code == 422 and "S3CRET" not in r.text


def test_too_many_inputs():
    c = TestClient(create_app(settings(max_inputs=1)))
    r = c.post("/v1/bundle", json={"inputs": [{"content": JSONL, "adapter": "jsonl", "name": f"{i}.jsonl"} for i in range(2)]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "too_many_inputs"


def test_body_limit():
    c = TestClient(create_app(settings(max_body_bytes=2000)))
    r = c.post("/v1/validate", json={"spec": "x" * 5000})
    assert r.status_code == 413 and r.json()["error"]["code"] == "body_too_large"


def test_body_limit_applies_to_chunked_bodies_without_content_length():
    c = TestClient(create_app(settings(max_body_bytes=2000)))

    def chunks():
        for _ in range(10):
            yield b'{"spec": "' + b"x" * 400 if _ == 0 else b"x" * 400

    r = c.post("/v1/validate", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "body_too_large"


def test_render_timeout_kills_the_render():
    c = TestClient(create_app(settings(render_timeout=0.05)))
    r = c.post("/v1/render", json=body())
    assert r.status_code == 504 and r.json()["error"]["code"] == "render_timeout"


def test_bearer_token():
    c = TestClient(create_app(settings(api_token="s3cret")))
    assert c.get("/healthz").status_code == 200
    r = c.post("/v1/validate", json={"spec": SPEC})
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert c.post("/v1/validate", json={"spec": SPEC}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.post("/v1/validate", json={"spec": SPEC}, headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_renderer_does_not_see_the_token_or_other_secrets(monkeypatch):
    monkeypatch.setenv("REPORTSPEC_API_TOKEN", "s3cret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    env = _child_env()
    assert "REPORTSPEC_API_TOKEN" not in env and "AWS_SECRET_ACCESS_KEY" not in env and "PATH" in env


def test_playground_is_off_by_default_and_locked_down_when_on():
    assert TestClient(create_app(settings())).get("/").status_code == 404
    r = TestClient(create_app(settings(playground=True))).get("/")
    assert r.status_code == 200 and "Quickstart Report" in r.text and "ReportSpec Playground" in r.text
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp


def test_docs_can_be_disabled():
    assert TestClient(create_app(settings(docs=False))).get("/openapi.json").status_code == 404


def test_bundled_example_matches_the_repository_example():
    pkg = ROOT / "src" / "reportspec" / "service" / "examples"
    assert (pkg / "quickstart.report.md").read_text() == SPEC and (pkg / "quickstart.jsonl").read_text() == JSONL


@pytest.mark.skipif(not shutil.which("pdffonts"), reason="needs poppler-utils")
def test_pdf_has_only_red_hat_fonts(client, tmp_path):
    if "pdf" not in _capabilities()["formats"]:
        pytest.skip("Pango not available")
    r = client.post("/v1/render", json=body(format="pdf"))
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(r.content)
    rows = subprocess.run(["pdffonts", str(pdf)], capture_output=True, text=True, check=True).stdout.splitlines()[2:]
    assert rows and all("Red-Hat-" in row for row in rows if row.strip())


@pytest.mark.skipif(not shutil.which("pandoc"), reason="needs pandoc")
def test_docx(client):
    r = client.post("/v1/render", json=body(format="docx"))
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_serve_without_the_extra_is_a_clean_error(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    assert main(["serve"]) == 2
    assert 'pip install "reportspec[service]"' in capsys.readouterr().err
