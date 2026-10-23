"""CLI behavior that the spec-level conformance cases do not cover: exit codes and error messages."""

import json
import shutil
from pathlib import Path

import pytest

from reportspec import __version__
from reportspec.cli import main

ROOT = Path(__file__).parent.parent
SPEC = ROOT / "examples" / "model-release.report.md"
JSONL = ROOT / "examples" / "inputs" / "model-release.jsonl"


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_conformance_suite_passes():
    assert main(["conformance", str(ROOT / "conformance")]) == 0


def test_conformance_missing_dir_fails(capsys, tmp_path):
    assert main(["conformance", str(tmp_path / "nope")]) == 2
    assert "no conformance cases" in capsys.readouterr().err


def test_validate_example():
    assert main(["validate", str(SPEC)]) == 0


@pytest.mark.parametrize("fmt", ["markdown", "json"])
def test_render_text_formats(fmt, capsys):
    assert main(["render", str(SPEC), "--input", str(JSONL), "--format", fmt]) == 0
    out = capsys.readouterr().out
    assert "Model Release Readiness" in out
    if fmt == "json":
        json.loads(out)


def test_render_html_is_self_contained(tmp_path):
    out = tmp_path / "r.html"
    assert main(["render", str(SPEC), "--input", str(JSONL), "--format", "html", "-o", str(out)]) == 0
    html = out.read_text()
    assert "<svg" in html and "@font-face" in html
    assert 'src="http' not in html and 'href="http' not in html.replace("fontawesome.com", "")
    assert (tmp_path / "r.manifest.json").exists()


def test_pdf_needs_output(capsys):
    assert main(["render", str(SPEC), "--input", str(JSONL), "--format", "pdf"]) == 2
    assert "needs -o" in capsys.readouterr().err


@pytest.mark.parametrize("args, message", [
    (["render", "/nonexistent.md", "--input", str(JSONL)], "No such file"),
    (["render", str(SPEC), "--input", "/nonexistent.jsonl"], "cannot read input"),
    (["render", str(SPEC), "--input", f"nope:{JSONL}"], "unknown adapter 'nope'"),
])
def test_user_errors_are_clean(args, message, capsys):
    assert main(args) == 2
    assert message in capsys.readouterr().err


def test_malformed_json_input(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert main(["render", str(SPEC), "--input", str(bad)]) == 2
    assert "bad.json is not valid JSON" in capsys.readouterr().err


def test_bad_param_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as e:
        main(["render", str(SPEC), "--input", str(JSONL), "--param", "nonsense"])
    assert e.value.code == 2
    assert "NAME=VALUE" in capsys.readouterr().err


def test_render_pdf():
    try:
        from weasyprint import HTML  # noqa: F401  (needs Pango; on macOS the CLI sets the library path itself)
    except OSError:
        pytest.skip("Pango not loadable in this process")
    from reportspec.core import render_text
    out, _ = render_text(SPEC.read_text(encoding="utf-8"), SPEC.name, [str(JSONL)], "pdf", {})
    assert out.startswith(b"%PDF") and len(out) > 20_000


@pytest.mark.skipif(not shutil.which("pandoc"), reason="needs pandoc")
def test_docx_without_pandoc_is_a_clean_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert main(["render", str(SPEC), "--input", str(JSONL), "--format", "docx", "-o", str(tmp_path / "x.docx")]) == 2
    assert "pandoc not found" in capsys.readouterr().err
