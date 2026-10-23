"""Command line for the ReportSpec reference implementation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import ADAPTERS, MissingValueError, SpecError, build_bundle, host_namespaces, render_text, run_conformance, validate_text
from .htmlout import ensure_native_libs

DESCRIPTION = """ReportSpec v1alpha1 (DRAFT): render a Markdown report template and JSON/JSONL results to Markdown, JSON, HTML, PDF or DOCX.

  reportspec validate examples/safety-compliance.report.md
  reportspec bundle --input examples/inputs/evalhub-job.json
  reportspec render examples/model-release.report.md --input examples/inputs/model-release.jsonl --format pdf -o model-release.pdf
  reportspec conformance conformance/
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reportspec", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"reportspec {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("spec", type=Path)
    bnd = sub.add_parser("bundle", help="print the ResultsBundle built from the inputs")
    r = sub.add_parser("render")
    r.add_argument("spec", type=Path)
    for p in (bnd, r):
        p.add_argument("--input", action="append", required=True, metavar="[ADAPTER:]PATH",
                       help=f"native results file; adapter auto-detected or one of {', '.join(ADAPTERS)}")
    r.add_argument("--format", choices=["markdown", "json", "html", "pdf", "docx"], default="markdown")
    r.add_argument("-o", "--output", type=Path, help="write the report here (required for pdf and docx); html, pdf and docx also write <name>.manifest.json next to it")
    r.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    c = sub.add_parser("conformance")
    c.add_argument("dir", type=Path)
    a = ap.parse_args(argv)
    bad = [p for p in getattr(a, "param", []) if "=" not in p]
    if bad:
        ap.error(f"--param expects NAME=VALUE, got {bad[0]!r}")

    if a.cmd == "conformance":
        return run_conformance(a.dir)
    if a.cmd == "render" and a.format in ("pdf", "docx") and not a.output:
        print(f"failed: --format {a.format} needs -o OUTPUT.{a.format}", file=sys.stderr)
        return 2
    if a.cmd == "render" and a.format == "pdf":
        ensure_native_libs()
    try:
        if a.cmd == "validate":
            rep, fm, *_ = validate_text(a.spec.read_text(encoding="utf-8"))
            for w in rep.warnings:
                print(f"warning: {w}")
            for e in rep.errors:
                print(f"error: {e}")
            hosts = host_namespaces(fm) if fm else []
            print(("valid" if not rep.errors else f"invalid ({len(rep.errors)} errors)")
                  + (f"; host namespaces not checked by core: {', '.join(hosts)}" if hosts else ""))
            return 1 if rep.errors else 0
        if a.cmd == "bundle":
            print(json.dumps(build_bundle(a.input), indent=2))
            return 0
        out, rep = render_text(a.spec.read_text(encoding="utf-8"), a.spec.name, a.input, a.format,
                               dict(p.split("=", 1) for p in a.param))
        for w in rep.warnings:
            print(f"warning: {w}", file=sys.stderr)
        if a.output:
            a.output.parent.mkdir(parents=True, exist_ok=True)
            a.output.write_bytes(out) if isinstance(out, bytes) else a.output.write_text(out, encoding="utf-8")
            note = f"wrote {a.output} ({a.output.stat().st_size:,} bytes)"
            if a.format in ("html", "pdf", "docx"):
                mpath = a.output.with_name(a.output.stem + ".manifest.json")
                mpath.write_text(json.dumps(rep.manifest, indent=2, default=str), encoding="utf-8")
                note += f"; evidence manifest {mpath}"
            print(note, file=sys.stderr)
        else:
            print(out)
    except OSError as e:
        print(f"failed: {e.strerror}: {e.filename}", file=sys.stderr)
        return 2
    except (SpecError, MissingValueError) as e:
        print(f"failed: {e}", file=sys.stderr)
        return 2
    return 0
