# /// script
# requires-python = ">=3.13"
# dependencies = ["pyyaml>=6", "jsonschema>=4.23", "jinja2>=3.1.4", "jsonpath-rfc9535>=0.1.5", "markdown-it-py>=3", "altair>=6", "vl-convert-python>=1.9", "weasyprint>=68"]  # docx output also needs the pandoc binary
# ///
"""Reference validator, bundler and renderer for ReportSpec v1alpha1 (DRAFT): Markdown, JSON, HTML and PDF.

Host-neutral: a spec binds to a ResultsBundle, and adapters turn each host's native
results (EvalHub job, MiDojo results.json, Policy Mapper risk-extraction.json) into one.
Not product code. It exists to prove the spec is implementable and to pin down semantics.

    uv run reportspec.py validate examples/safety-compliance.report.md
    uv run reportspec.py bundle --input examples/inputs/evalhub-job.json
    uv run reportspec.py render examples/agent-redteam.report.md \
        --input examples/inputs/asago-risk-extraction.json \
        --input examples/inputs/midojo-results.json --format markdown
    uv run reportspec.py render examples/model-release.report.md \
        --input examples/inputs/model-release.jsonl --format pdf -o model-release.pdf
    uv run reportspec.py conformance conformance/
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonpath_rfc9535 as jsonpath
import yaml
from jinja2 import StrictUndefined, nodes
from jinja2.sandbox import SandboxedEnvironment
from jsonschema import Draft202012Validator
from markdown_it import MarkdownIt

HERE = Path(__file__).parent
SPEC_SCHEMA = HERE / "schemas" / "reportspec-v1alpha1.schema.json"
BUNDLE_SCHEMA = HERE / "schemas" / "results-bundle-v1alpha1.schema.json"
VIZ_FENCE = "reportspec-viz"
VIZ_TOKEN = "@@REPORTSPEC_VIZ:{}@@"
VIZ_TOKEN_RE = re.compile(r"^@@REPORTSPEC_VIZ:([a-z][a-z0-9-]*)@@$", re.M)

CORE_NAMESPACES = {"params", "format", "reportspec"}
REPORT_KEYS = {"generated_at", "spec_name", "spec_version", "spec_digest", "title"}
SUBJECT_KEYS = {"kind", "name", "version", "uri"}
RUN_KEYS = {"id", "producer", "producer_version", "started_at", "completed_at", "context"}
EVALUATION_FIELDS = ["id", "label", "source", "metric", "score", "threshold", "pass"]
BUILTINS: dict[str, dict[str, Any]] = {
    "overall_score": {"type": "scalar", "kind": "builtin"},
    "overall_threshold": {"type": "scalar", "kind": "builtin"},
    "overall_pass": {"type": "scalar", "kind": "builtin", "display": "boolean"},
    "evaluations": {"type": "table", "kind": "records", "records": "@evaluations",
                    "fields": {f: f for f in EVALUATION_FIELDS}},
}
BUILTIN_OPTIONS = {"required", "display", "precision", "description", "direction", "unit"}
SOURCE_KEYS = ("metric", "items", "field", "records", "from")

FILTERS = {
    "round", "int", "float", "abs", "default", "upper", "lower", "title", "capitalize", "trim",
    "length", "join", "sort", "first", "last", "min", "max", "replace", "truncate",
    "percent", "number", "status", "code",
}
TESTS = {
    "available", "missing", "defined", "none", "number", "string", "true", "false",
    "eq", "ne", "lt", "le", "gt", "ge", "in", "even", "odd", "divisibleby",
}
FORBIDDEN_NODES = (
    nodes.Extends, nodes.Include, nodes.Import, nodes.FromImport, nodes.Macro, nodes.CallBlock,
    nodes.FilterBlock, nodes.With, nodes.Block, nodes.Call, nodes.AssignBlock,
    nodes.ScopedEvalContextModifier, nodes.EvalContextModifier,
)
VIZ_DATA_TYPES = {"radar": "series", "radial": "series", "bar": "series", "line": "series", "heatmap": "matrix", "table": "table", "boxplot": "table"}
CHART_TYPES = {"bar", "line", "heatmap", "radar", "radial", "boxplot"}  # drawn by reportspec_charts; table and summary_cards are text
RESOLVED_SCHEMA = HERE / "schemas" / "resolved-viz-v1alpha1.schema.json"
NA = "N/A"
MD_ESCAPE_RE = re.compile(r"([\\`*_\[\]<>|!#])")
BAD_METRIC_KEY_CHARS = re.compile(r"[^a-zA-Z0-9_\-.\s:/]+")  # eval-hub-sdk adapter/mlflow.py


class SpecError(Exception):
    pass


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)  # evidence manifest of the last render

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


# --- Front matter ----------------------------------------------------------------


class _Loader(yaml.SafeLoader):
    """SafeLoader with no timestamps (dates stay strings), no aliases, no duplicate keys."""

    yaml_implicit_resolvers = {
        k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
        for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    def compose_node(self, parent, index):  # type: ignore[override]
        if self.check_event(yaml.AliasEvent):
            raise SpecError(f"YAML aliases are not allowed (line {self.peek_event().start_mark.line + 1})")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):  # type: ignore[override]
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise SpecError(f"duplicate key {key!r} (line {key_node.start_mark.line + 1})")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_Loader)  # noqa: S506 - _Loader extends SafeLoader


def split_front_matter(text: str) -> tuple[dict[str, Any], str, int]:
    """Return (front matter, body, body line offset). Jekyll/Pandoc rules, YAML only."""
    if text.startswith("\ufeff"):
        raise SpecError("byte-order mark not allowed; file must start with '---'")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise SpecError("file must start with a '---' front matter delimiter on line 1")
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") in ("---", "..."):
            fm = load_yaml("".join(lines[1:i])) or {}
            if not isinstance(fm, dict):
                raise SpecError("front matter must be a YAML mapping")
            return fm, "".join(lines[i + 1 :]), i + 1
    raise SpecError("front matter is not closed with '---' or '...'")


def host_namespaces(fm: dict[str, Any]) -> list[str]:
    return [k for k, v in fm.items() if k not in CORE_NAMESPACES and isinstance(v, dict)]


def meta_of(fm: dict[str, Any]) -> dict[str, Any]:
    hosts = set(host_namespaces(fm))
    return {k: v for k, v in fm.items() if k not in CORE_NAMESPACES and k not in hosts}


# --- Viz extraction ------------------------------------------------------------


def extract_viz(body: str, offset: int, rep: Report) -> tuple[str, list[dict[str, Any]]]:
    """Replace each ```reportspec-viz fence with a placeholder line; return parsed blocks."""
    if "@@REPORTSPEC_VIZ:" in body:
        rep.err("template body contains the reserved placeholder text '@@REPORTSPEC_VIZ:'")
    lines = body.splitlines(keepends=True)
    blocks: list[dict[str, Any]] = []
    for tok in reversed(MarkdownIt("commonmark").parse(body)):
        if tok.type != "fence" or tok.map is None:
            continue
        info = tok.info.strip()
        if info != VIZ_FENCE:
            if info.endswith("-viz"):
                rep.warn(f"fence '{info}' at line {tok.map[0] + 1 + offset} is not a viz block; did you mean '{VIZ_FENCE}'?")
            continue
        start, end = tok.map
        where = f"viz block at line {start + 1 + offset}"
        if re.search(r"\{\{|\{%|\{#", tok.content):
            rep.err(f"{where}: template syntax is not allowed inside viz blocks; reference bindings by name")
            continue
        try:
            block = load_yaml(tok.content)
        except (yaml.YAMLError, SpecError) as e:
            rep.err(f"{where}: invalid YAML: {e}")
            continue
        if not isinstance(block, dict):
            rep.err(f"{where}: body must be a YAML mapping")
            continue
        block["_line"] = start + 1 + offset
        blocks.append(block)
        vid = block.get("id", f"invalid-{start}")
        indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
        lines[start:end] = [f"{indent}{VIZ_TOKEN.format(vid)}\n"]
    blocks.reverse()
    return "".join(lines), blocks


# --- Binding normalization -------------------------------------------------------


def has_glob(ref: str) -> bool:
    return "*" in ref


def normalize_bindings(declared: dict[str, Any], rep: Report) -> dict[str, dict[str, Any]]:
    """Expand short forms, infer types, merge built-in options. Returns name -> normalized binding."""
    out: dict[str, dict[str, Any]] = {k: dict(v) for k, v in BUILTINS.items()}
    for name, decl in declared.items():
        where = f"reportspec.bindings.{name}"
        if isinstance(decl, str):
            out[name] = {"type": "series" if has_glob(decl) else "scalar", "kind": "metric", "metric": decl}
            if name in BUILTINS:
                rep.err(f"{where}: '{name}' is a built-in; list it with options only")
            continue
        if isinstance(decl, list):
            items = [{"binding": x} if "/" not in x else {"metric": x} for x in decl]
            out[name] = {"type": "series", "kind": "items", "items": items}
            if name in BUILTINS:
                rep.err(f"{where}: '{name}' is a built-in; list it with options only")
            continue
        sources = [k for k in SOURCE_KEYS if k in decl]
        if "evaluation" in decl and "field" not in decl:
            rep.err(f"{where}: 'evaluation' needs 'field'")
            continue
        if "field" in decl and "evaluation" not in decl:
            rep.err(f"{where}: 'field' needs 'evaluation'")
            continue
        if name in BUILTINS:
            extra = set(decl) - BUILTIN_OPTIONS
            if sources or extra:
                rep.err(f"{where}: '{name}' is a built-in; only {sorted(BUILTIN_OPTIONS)} may be set")
            else:
                out[name] |= decl
            continue
        if len(sources) != 1:
            rep.err(f"{where}: needs exactly one of {list(SOURCE_KEYS)}" + (f", got {sources}" if sources else ""))
            continue
        src = sources[0]
        b = dict(decl)
        b["kind"] = src
        inferred: str | None = None
        match src:
            case "metric":
                inferred = "series" if has_glob(decl["metric"]) else "scalar"
            case "items":
                inferred = "series"
                for it in decl["items"]:
                    if "metric" in it and has_glob(it["metric"]):
                        rep.err(f"{where}: item {it['label']!r}: a wildcard reference is a series, not an item")
            case "field":
                inferred = "scalar"
            case "records":
                has_fields, has_row = "fields" in decl, "row" in decl
                if has_fields == has_row:
                    rep.err(f"{where}: records needs either 'fields' (table) or 'row' (matrix)")
                    continue
                if has_row and ("columns" in decl) == ("column" in decl or "value" in decl):
                    rep.err(f"{where}: matrix needs 'columns' (wide) or 'column' + 'value' (long)")
                    continue
                if has_row and "columns" not in decl and not ("column" in decl and "value" in decl):
                    rep.err(f"{where}: long-form matrix needs both 'column' and 'value'")
                    continue
                inferred = "table" if has_fields else "matrix"
            case "from":
                inferred = decl.get("type")
                if inferred not in ("scalar", "table"):
                    rep.err(f"{where}: 'from' needs type scalar or table")
                    continue
                if inferred == "table" and "fields" not in decl:
                    rep.err(f"{where}: table from 'from' needs 'fields'")
                    continue
        if "type" in decl and decl["type"] != inferred:
            rep.err(f"{where}: type {decl['type']!r} does not match its source ({src} gives {inferred})")
            continue
        if "default" in decl and inferred != "scalar":
            rep.err(f"{where}: 'default' is only allowed on scalars")
        b["type"] = inferred
        out[name] = b
    return out


def table_fields(b: dict[str, Any]) -> set[str]:
    return set(b.get("fields", {}))


# --- Static validation -------------------------------------------------------------


def param_value(p: Any) -> Any:
    return p["value"] if isinstance(p, dict) else p


def param_type(p: Any) -> str:
    if isinstance(p, dict) and "type" in p:
        return p["type"]
    v = param_value(p)
    return "boolean" if isinstance(v, bool) else "number" if isinstance(v, int | float) else "string"


def validate_text(text: str) -> tuple[Report, dict[str, Any], dict[str, Any], str, list[dict[str, Any]]]:
    rep = Report()
    try:
        fm, body, offset = split_front_matter(text)
    except (SpecError, yaml.YAMLError) as e:
        rep.err(f"front matter: {e}")
        return rep, {}, {}, "", []

    schema = json.loads(SPEC_SCHEMA.read_text())
    for e in sorted(Draft202012Validator(schema).iter_errors(fm), key=lambda e: list(e.path)):
        rep.err(f"front matter /{'/'.join(map(str, e.path))}: {e.message}")
    if rep.errors:
        return rep, fm, {}, body, []

    bindings = normalize_bindings(fm["reportspec"].get("bindings", {}), rep)
    params: dict[str, Any] = fm.get("params", {})

    for name, p in params.items():
        if isinstance(p, dict):
            if "type" in p and param_type({"value": p["value"]}) != p["type"]:
                rep.err(f"params.{name}: value {p['value']!r} does not match type {p['type']}")
            if "choices" in p and p["value"] not in p["choices"]:
                rep.err(f"params.{name}: value not in choices")

    def check_number_ref(ref: Any, where: str) -> None:
        if isinstance(ref, dict) and "param" in ref:
            if ref["param"] not in params:
                rep.err(f"{where}: unknown param {ref['param']!r}")
            elif param_type(params[ref["param"]]) != "number":
                rep.err(f"{where}: param {ref['param']!r} is not a number")
        elif isinstance(ref, dict) and "binding" in ref:
            if bindings.get(ref["binding"], {}).get("type") != "scalar":
                rep.err(f"{where}: {ref['binding']!r} is not a scalar binding")

    for name, b in bindings.items():
        if b["kind"] != "items":
            continue
        for item in b["items"]:
            ref = item.get("binding")
            if ref is None:
                continue
            label = item.get("label", ref)
            target = bindings.get(ref)
            if target is None or target["type"] != "scalar":
                rep.err(f"reportspec.bindings.{name}: item {label!r} references {ref!r}, which is not a scalar binding")
            elif b.get("direction") and target.get("direction") and target["direction"] != b["direction"]:
                rep.err(f"reportspec.bindings.{name}: item {label!r} is {target['direction']} but series is {b['direction']}")

    tmpl, blocks = extract_viz(body, offset, rep)
    viz_validator = Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/vizBlock"})
    seen_ids: set[str] = set()
    for blk in blocks:
        line = blk.pop("_line")
        where = f"viz '{blk.get('id', '?')}' (line {line})"
        errs = list(viz_validator.iter_errors(blk))
        for e in errs:
            rep.err(f"{where} /{'/'.join(map(str, e.path))}: {e.message}")
        if errs:
            continue
        if blk["id"] in seen_ids:
            rep.err(f"{where}: duplicate viz id")
        seen_ids.add(blk["id"])
        want = VIZ_DATA_TYPES.get(blk["type"])
        if want:
            b = bindings.get(blk["data"])
            if b is None:
                rep.err(f"{where}: unknown binding {blk['data']!r}")
                continue
            if b["type"] != want:
                rep.err(f"{where}: {blk['type']} needs a {want} binding; {blk['data']!r} is {b['type']}")
                continue
            if blk["type"] == "radar" and b["kind"] == "items" and not b.get("direction"):
                dirs = {bindings[i["binding"]].get("direction") for i in b["items"] if "binding" in i}
                if len(dirs - {None}) > 1:
                    rep.err(f"{where}: radar axes mix higher_is_better and lower_is_better")
            if blk["type"] == "boxplot":
                fields = table_fields(b)
                for key in ("x", "y"):
                    if blk[key] not in fields:
                        rep.err(f"{where}: {key} field {blk[key]!r} not in binding {blk['data']!r}")
            if blk["type"] == "table":
                fields = table_fields(b)
                for col in blk.get("columns", []):
                    if col["field"] not in fields:
                        rep.err(f"{where}: column field {col['field']!r} not in binding {blk['data']!r}")
                if "status_field" in blk and blk["status_field"] not in fields:
                    rep.err(f"{where}: status_field {blk['status_field']!r} not in binding fields")
                if "sort_by" in blk and blk["sort_by"]["field"] not in fields:
                    rep.err(f"{where}: sort_by field not in binding fields")
        if blk["type"] == "summary_cards":
            for card in blk["cards"]:
                if bindings.get(card["value"], {}).get("type") != "scalar":
                    rep.err(f"{where}: card {card['label']!r} value {card['value']!r} is not a scalar binding")
                if "threshold" in card:
                    check_number_ref(card["threshold"], f"{where} card {card['label']!r} threshold")
        for key in ("threshold", "midpoint"):
            if key in blk:
                check_number_ref(blk[key], f"{where} {key}")

    check_template(tmpl, offset, fm, bindings, rep)
    if fm["reportspec"].get("strict") and rep.warnings:
        rep.errors += [f"strict: {w}" for w in rep.warnings]
    return rep, fm, bindings, tmpl, blocks


def check_template(tmpl: str, offset: int, fm: dict[str, Any], bindings: dict[str, Any], rep: Report) -> None:
    env = make_env("data unavailable")
    try:
        ast = env.parse(tmpl)
    except Exception as e:  # jinja2.TemplateSyntaxError
        line = (getattr(e, "lineno", None) or 0) + offset
        rep.err(f"template syntax (line {line}): {e}")
        return

    params = fm.get("params", {})
    meta_keys = set(meta_of(fm))
    stored = {n.name for n in ast.find_all(nodes.Name) if n.ctx in ("store", "param")}
    allowed = set(bindings) | {"meta", "params", "report", "subject", "run", "loop"} | stored
    roots = {"meta": meta_keys, "params": set(params), "report": REPORT_KEYS, "subject": SUBJECT_KEYS, "run": RUN_KEYS}
    loop_fields: dict[str, set[str]] = {}

    for n in ast.find_all(nodes.For):
        if isinstance(n.iter, nodes.Name) and bindings.get(n.iter.name, {}).get("type") == "table" and isinstance(n.target, nodes.Name):
            loop_fields[n.target.name] = table_fields(bindings[n.iter.name])
        for td in n.find_all(nodes.TemplateData):
            for m in VIZ_TOKEN_RE.finditer(td.data):
                rep.err(f"viz '{m.group(1)}' is inside a {{% for %}} loop (line {n.lineno + offset}); not supported in v1alpha1")

    for n in ast.find_all(nodes.Node):
        where = f"template line {(getattr(n, 'lineno', None) or 0) + offset}"
        if isinstance(n, FORBIDDEN_NODES):
            rep.err(f"{where}: '{type(n).__name__}' is not allowed (no includes, macros, blocks, or function calls)")
        elif isinstance(n, nodes.Name) and n.ctx == "load" and n.name not in allowed:
            rep.err(f"{where}: unknown name {n.name!r}; templates may only use bindings, meta, params, report, subject, run")
        elif isinstance(n, nodes.Filter) and n.name not in FILTERS:
            rep.err(f"{where}: filter {n.name!r} is not allowed")
        elif isinstance(n, nodes.Test) and n.name not in TESTS:
            rep.err(f"{where}: test {n.name!r} is not allowed")
        elif isinstance(n, nodes.Getattr | nodes.Getitem):
            attr = n.attr if isinstance(n, nodes.Getattr) else getattr(n.arg, "value", None)
            if isinstance(attr, str) and attr.startswith("_"):
                rep.err(f"{where}: access to underscore attribute {attr!r} is not allowed")
            if isinstance(n.node, nodes.Name) and isinstance(attr, str):
                root = n.node.name
                known = roots.get(root) if root in roots else loop_fields.get(root)
                if known is not None and attr not in known:
                    rep.err(f"{where}: {root}.{attr} is not defined")

    # A missing value can be printed, never compared. Flag unguarded uses in conditions/loops.
    optional = {k for k, b in bindings.items() if not b.get("required") and "default" not in b}

    def guarded(expr: nodes.Node) -> set[str]:
        tests = [expr, *expr.find_all(nodes.Test)] if isinstance(expr, nodes.Test) else expr.find_all(nodes.Test)
        return {t.node.name for t in tests if t.name in ("available", "missing") and isinstance(t.node, nodes.Name)}

    def report_unguarded(expr: nodes.Node, lineno: int, what: str) -> None:
        names = {expr.name} if isinstance(expr, nodes.Name) else {x.name for x in expr.find_all(nodes.Name)}
        for name in sorted((names & optional) - guarded(expr)):
            rep.warn(f"template line {lineno + offset}: {what} uses optional binding {name!r} without an "
                     f"'is available' guard; the render fails if it is missing")

    for n in ast.find_all(nodes.If):
        report_unguarded(n.test, n.lineno, "{% if %}")
    for n in ast.find_all(nodes.For):
        if isinstance(n.iter, nodes.Name):
            report_unguarded(n.iter, n.lineno, "{% for %}")


# --- Adapters: native results -> ResultsBundle parts -------------------------------


def sanitize_metric_key(name: str) -> str:
    """Same mapping as eval-hub-sdk sanitize_metric_key_for_api (MLflow keys)."""
    return BAD_METRIC_KEY_CHARS.sub("_", name).strip().strip("_") or "metric"


def _metric(value: Any, mtype: str | None = None, direction: str | None = None, name: str | None = None) -> dict[str, Any]:
    if mtype is None:
        mtype = "boolean" if isinstance(value, bool) else "numeric" if isinstance(value, int | float) or value is None else "categorical"
    m: dict[str, Any] = {"value": value, "type": mtype}
    if direction:
        m["direction"] = direction
    if name is not None and sanitize_metric_key(name) != name:
        m["aliases"] = [sanitize_metric_key(name)]
    return m


def adapt_evalhub_job(doc: dict[str, Any]) -> dict[str, Any]:
    """EvalHub GET /api/v1/evaluations/jobs/{id} (api.EvaluationJobResource), bare or as {job: ...}.

    Direction is left unset: the job JSON doesn't carry polarity. The server-side adapter fills it
    from the provider config (primary_score.lower_is_better).
    """
    job = doc.get("job", doc)
    results = job.get("results") or {}
    evaluations = []
    for b in results.get("benchmarks") or []:
        types = {s["name"]: s.get("type") for s in b.get("metrics_schema") or []}
        artifacts = dict(b.get("artifacts") or {})
        attributes: dict[str, Any] = {}
        for key, short in (("evalhub.env_card", "env_card"), ("evalhub.eval_card", "eval_card")):
            if key in artifacts:
                attributes[short] = artifacts.pop(key)
        for key in ("oci_reference", "oci_digest"):
            if key in artifacts:
                attributes[key] = artifacts.pop(key)
        if artifacts:
            attributes["artifacts"] = artifacts
        for key in ("mlflow_run_id", "logs_path", "benchmark_index"):
            if b.get(key) is not None:
                attributes[key] = b[key]
        t = b.get("test") or {}
        ev: dict[str, Any] = {
            "id": b["id"], "label": b["id"], "source": b.get("provider_id"),
            "metrics": {k: _metric(v, types.get(k), name=k) for k, v in (b.get("metrics") or {}).items()},
            "attributes": attributes,
        }
        if t:
            ev["verdict"] = {"metric": t.get("primary_score_metric"), "score": t.get("primary_score"),
                             "threshold": t.get("threshold"), "pass": t.get("pass")}
        evaluations.append({k: v for k, v in ev.items() if v is not None})
    res = job.get("resource") or {}
    model = job.get("model") or {}
    part: dict[str, Any] = {
        "subject": {k: v for k, v in {"kind": "model", "name": model.get("name"), "uri": model.get("url")}.items() if v},
        "run": {"id": res.get("id"), "producer": {"name": "evalhub"}, "started_at": res.get("created_at"),
                "context": {k: v for k, v in {"collection_id": (job.get("collection") or {}).get("id"),
                                              "job_name": job.get("name"), "tenant": res.get("tenant")}.items() if v}},
        "evaluations": evaluations,
    }
    if results.get("test"):
        part["verdict"] = {k: results["test"].get(k) for k in ("score", "threshold", "pass")}
    return part


def adapt_midojo(doc: dict[str, Any]) -> dict[str, Any]:
    """MiDojo midojo-run results.json: {run_id, suite_name, utility, security, security_reason}."""
    rows = []
    for key, completed in doc["utility"].items():
        user_task, _, injection_task = key.partition(",")
        rows.append({"user_task": user_task, "injection_task": injection_task or None, "task_completed": completed,
                     "attack_succeeded": doc.get("security", {}).get(key),
                     "reason": doc.get("security_reason", {}).get(key)})
    attacked = [r for r in rows if r["injection_task"]]
    reached = [r for r in attacked if r["attack_succeeded"] is not None]
    asr = sum(r["attack_succeeded"] for r in reached) / len(reached) if reached else None
    utility = sum(r["task_completed"] for r in rows) / len(rows) if rows else None
    suite = doc["suite_name"]
    ev = {
        "id": f"midojo.{suite}", "label": f"MiDojo {suite}", "source": "midojo",
        "metrics": {
            "utility_rate": _metric(utility, direction="higher_is_better"),
            "attack_success_rate": _metric(asr, direction="lower_is_better"),
            "pairs": _metric(len(rows)),
            "pairs_attacked": _metric(len(attacked)),
            "pairs_not_reached": _metric(len(attacked) - len(reached)),
        },
        "verdict": {"metric": "attack_success_rate", "score": asr, "threshold": None, "pass": None},
        "records": {"pairs": rows},
    }
    return {"run": {"id": doc.get("run_id"), "producer": {"name": "midojo"}, "context": {"midojo_suite": suite}},
            "evaluations": [ev]}


def adapt_asago_risk_extraction(doc: dict[str, Any]) -> dict[str, Any]:
    """ASAGO Policy Mapper risk-extraction.json (version 0.3)."""
    risks = doc.get("risks") or []
    sources = doc.get("source_documents") or []
    first_doc = Path(str(sources[0])).name if sources else None
    ev_block = doc.get("eval") or {}
    policy = ev_block.get("policy") or (Path(first_doc).stem if first_doc else "policy")
    by_tax = Counter(r["taxonomy"] for r in risks)
    high = Counter(r["taxonomy"] for r in risks if r.get("grounding_confidence") == "high")
    actions = {m["action_id"] for r in risks for m in r.get("mitigations") or []}
    metrics = {
        "risks_extracted": _metric(len(risks)),
        "risks_high_confidence": _metric(sum(high.values())),
        "taxonomies": _metric(len(by_tax)),
        "mitigations_linked": _metric(len(actions)),
    }
    records: dict[str, list[dict[str, Any]]] = {
        "risks": [{"risk_id": r["risk_id"], "risk_name": r.get("risk_name", "").strip(), "taxonomy": r["taxonomy"],
                   "confidence": r.get("confidence"), "grounding": r.get("grounding_confidence"),
                   "section": (r.get("evidence") or [{}])[0].get("section"),
                   "page": (r.get("evidence") or [{}])[0].get("page"),
                   "mitigations": len(r.get("mitigations") or [])} for r in risks],
        "taxonomies": [{"taxonomy": t, "risks": n, "high_confidence": high.get(t, 0)} for t, n in by_tax.most_common()],
    }
    ev: dict[str, Any] = {"id": f"policy-mapper.{policy}", "label": f"Policy Mapper {policy}",
                          "source": "asago-policy-mapper", "metrics": metrics, "records": records,
                          "attributes": {"model": (doc.get("metadata") or {}).get("model"),
                                         "schema_version": doc.get("version")}}
    if ev_block:
        for k in ("precision", "recall", "f1"):
            metrics[k] = _metric(ev_block.get(k), direction="higher_is_better")
        metrics["risks_expected"] = _metric(ev_block.get("total_expected"))
        metrics["risks_matched"] = _metric(ev_block.get("matched"))
        ev["verdict"] = {"metric": "f1", "score": ev_block.get("f1"), "threshold": None, "pass": ev_block.get("pass")}
        records["taxonomy_scores"] = [{"taxonomy": t} | {k: v.get(k) for k in ("expected", "extracted", "matched", "precision", "recall", "f1")}
                                      for t, v in (ev_block.get("per_taxonomy") or {}).items()]
    return {"run": {"context": {k: v for k, v in {"policy": policy, "policy_document": first_doc}.items() if v}},
            "evaluations": [ev]}


def parse_jsonl(raw: bytes, path: Path) -> list[dict[str, Any]]:
    rows = []
    for n, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise SpecError(f"{path.name} line {n}: invalid JSON: {e.msg}") from e
        if not isinstance(row, dict):
            raise SpecError(f"{path.name} line {n}: expected a JSON object")
        rows.append(row | {"_line": n})
    return rows


def adapt_jsonl(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """One JSON object per line. The simplest way to hand results to a report:

      {"subject": {...}, "run": {...}, "verdict": {...}}                  optional header, any line without "evaluation"
      {"evaluation": "bbq", "metric": "acc", "value": 0.81}               a metric (optional: direction, unit, type)
      {"evaluation": "bbq", "set": "samples", "model": "A", "score": .7}  one row of a named record set
      {"evaluation": "bbq", "verdict": {"metric": "acc", "score": .81, "threshold": .75, "pass": true}}
      {"evaluation": "bbq", "label": "BBQ", "source": "lm-eval"}          optional on any line; the first one wins
    """
    part: dict[str, Any] = {"evaluations": []}
    evals: dict[str, dict[str, Any]] = {}
    for row in rows:
        n = row.pop("_line")
        if "evaluation" not in row:
            extra = set(row) - {"subject", "run", "verdict"}
            if extra:
                raise SpecError(f"line {n}: a line without 'evaluation' may only hold subject, run or verdict; found {sorted(extra)}")
            part |= row
            continue
        e = evals.get(row["evaluation"])
        if e is None:
            e = evals[row["evaluation"]] = {"id": str(row["evaluation"]), "metrics": {}}
            part["evaluations"].append(e)
        for k in ("label", "source"):
            if k in row:
                e.setdefault(k, row[k])
        if "metric" in row:
            if "value" not in row:
                raise SpecError(f"line {n}: metric {row['metric']!r} has no 'value'")
            m = _metric(row["value"], row.get("type"), row.get("direction"), name=str(row["metric"]))
            if "unit" in row:
                m["unit"] = row["unit"]
            e["metrics"][str(row["metric"])] = m
        elif "set" in row:
            e.setdefault("records", {}).setdefault(str(row["set"]), []).append(
                {k: v for k, v in row.items() if k not in ("evaluation", "set", "label", "source")})
        elif "verdict" in row:
            e["verdict"] = row["verdict"]
        elif not ({"label", "source"} & set(row)):
            raise SpecError(f"line {n}: needs one of metric, set, verdict, label or source besides 'evaluation'")
    return part


def adapt_bundle(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k in ("subject", "run", "verdict", "evaluations")}


ADAPTERS = {
    "evalhub-job": adapt_evalhub_job,
    "midojo": adapt_midojo,
    "asago-risk-extraction": adapt_asago_risk_extraction,
    "bundle": adapt_bundle,
    "jsonl": adapt_jsonl,
}


def detect_adapter(doc: Any) -> str:
    if isinstance(doc, dict):
        if "bundle_version" in doc:
            return "bundle"
        if "job" in doc or ("resource" in doc and "results" in doc):
            return "evalhub-job"
        if "suite_name" in doc and "utility" in doc:
            return "midojo"
        if "risks" in doc and "version" in doc:
            return "asago-risk-extraction"
    raise SpecError("cannot detect the input format; prefix the path with an adapter name: " + ", ".join(ADAPTERS))


def build_bundle(inputs: list[str]) -> dict[str, Any]:
    """Run each input through its adapter and merge into one ResultsBundle."""
    bundle: dict[str, Any] = {"bundle_version": "v1alpha1", "evaluations": [], "sources": [], "warnings": []}
    warn = bundle["warnings"].append
    for spec in inputs:
        name, sep, rest = spec.partition(":")
        adapter, path = (name, Path(rest)) if sep and name in ADAPTERS else (None, Path(spec))
        raw = path.read_bytes()
        if adapter == "jsonl" or (adapter is None and path.suffix.lower() in (".jsonl", ".ndjson")):
            adapter, doc = "jsonl", parse_jsonl(raw, path)
        else:
            doc = json.loads(raw)
            adapter = adapter or detect_adapter(doc)
        part = ADAPTERS[adapter](doc)
        ids = [e["id"] for e in part.get("evaluations", [])]
        for e in part.get("evaluations", []):
            if any(x["id"] == e["id"] for x in bundle["evaluations"]):
                raise SpecError(f"evaluation id {e['id']!r} from {path} is already in the bundle")
            bundle["evaluations"].append(e)
        for key in ("subject", "verdict"):
            if part.get(key):
                if key not in bundle:
                    bundle[key] = part[key]
                elif bundle[key] != part[key]:
                    warn(f"{key} from {path.name} ignored; the bundle already has one from an earlier input")
        run = part.get("run") or {}
        if run:
            merged = bundle.setdefault("run", {})
            # Run identity moves as a unit from the first source that has an id; never mix runs.
            if run.get("id") and "id" not in merged:
                merged.update({k: v for k, v in run.items() if k != "context" and v is not None})
            ctx = merged.setdefault("context", {})
            for ck, cv in (run.get("context") or {}).items():
                if ck in ctx and ctx[ck] != cv:
                    warn(f"run.context.{ck} from {path.name} ignored ({cv!r}); keeping {ctx[ck]!r}")
                ctx.setdefault(ck, cv)
        src = {"adapter": adapter, "uri": path.name, "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "evaluations": ids}
        if run.get("id"):
            src["run_id"] = run["id"]
        bundle["sources"].append(src)
    schema = json.loads(BUNDLE_SCHEMA.read_text())
    errs = [f"/{'/'.join(map(str, e.path))}: {e.message}" for e in Draft202012Validator(schema).iter_errors(bundle)]
    if errs:
        raise SpecError("adapter output is not a valid ResultsBundle:\n  " + "\n  ".join(errs[:10]))
    return bundle


# --- Rendering -------------------------------------------------------------------


class MissingValueError(Exception):
    pass


class SafeMarkdown(str):
    """Output produced by trusted filters; skips Markdown escaping."""


@dataclass(frozen=True)
class Missing:
    """Unresolved binding. Prints as the marker; any comparison, truth test, or iteration raises."""

    name: str
    marker: str

    def __str__(self) -> str:
        return f"*{self.marker}*"

    def _fail(self, *_: Any) -> Any:
        raise MissingValueError(f"{self.name!r} is missing; guard with '{self.name.split('.')[0]} is available'")

    __bool__ = __lt__ = __le__ = __gt__ = __ge__ = __iter__ = __len__ = __float__ = _fail
    __add__ = __sub__ = __mul__ = __truediv__ = __radd__ = __rsub__ = __rmul__ = __rtruediv__ = _fail


@dataclass(frozen=True)
class Value:
    """Resolved value carrying its display hint. Compares as the raw value, prints formatted."""

    raw: Any
    display: str | None = None
    precision: int | None = None

    def __str__(self) -> str:
        return fmt(self.raw, self.display, self.precision)

    def __bool__(self) -> bool:
        return bool(self.raw)

    def __float__(self) -> float:
        return float(self.raw)

    def __eq__(self, o: object) -> bool:
        return self.raw == unwrap(o)

    def __hash__(self) -> int:
        return hash(self.raw)

    def __lt__(self, o: Any) -> bool: return self.raw < unwrap(o)
    def __le__(self, o: Any) -> bool: return self.raw <= unwrap(o)
    def __gt__(self, o: Any) -> bool: return self.raw > unwrap(o)
    def __ge__(self, o: Any) -> bool: return self.raw >= unwrap(o)


class Fields(dict):
    """Template object (subject, run, run.context): unknown keys resolve to Missing, not an error."""

    def __init__(self, prefix: str, marker: str, items: dict[str, Any]):
        super().__init__(items)
        self.prefix, self.marker = prefix, marker

    def __missing__(self, key: str) -> Missing:
        return Missing(f"{self.prefix}.{key}", self.marker)


def unwrap(v: Any) -> Any:
    if isinstance(v, Missing):
        v._fail()
    return v.raw if isinstance(v, Value) else v


def fmt(v: Any, display: str | None, precision: int | None) -> str:
    if isinstance(v, bool) or display == "boolean":
        return "yes" if v else "no"
    if isinstance(v, int | float):
        if display == "percent":
            return f"{v * 100:.{1 if precision is None else precision}f}%"
        if display == "integer":
            return f"{int(round(v))}"
        if display == "number" or precision is not None:
            return f"{v:.{3 if precision is None else precision}f}"
    return str(v)


def make_env(marker: str) -> SandboxedEnvironment:
    def finalize(v: Any) -> Any:
        if isinstance(v, SafeMarkdown | Missing):
            return str(v)
        return MD_ESCAPE_RE.sub(r"\\\1", str(v))

    env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False, finalize=finalize,
                               trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)

    def status(v: Any) -> Any:
        return v if isinstance(v, Missing) else ("PASS" if unwrap(v) else "FAIL")

    def code(v: Any) -> Any:
        if isinstance(v, Missing):
            return v
        s = str(unwrap(v))
        ticks = "`" * (max((len(m) for m in re.findall(r"`+", s)), default=0) + 1)
        pad = " " if s.startswith("`") or s.endswith("`") else ""
        return SafeMarkdown(f"{ticks}{pad}{s}{pad}{ticks}")

    def default(v: Any, fallback: Any = "") -> Any:
        return fallback if isinstance(v, Missing) else v

    env.filters.update(
        percent=lambda v, p=1: v if isinstance(v, Missing) else fmt(float(unwrap(v)), "percent", p),
        number=lambda v, p=3: v if isinstance(v, Missing) else fmt(float(unwrap(v)), "number", p),
        status=status, code=code, default=default,
    )
    env.filters = {k: v for k, v in env.filters.items() if k in FILTERS}
    env.tests["available"] = lambda v: not isinstance(v, Missing)
    env.tests["missing"] = lambda v: isinstance(v, Missing)
    env.tests = {k: v for k, v in env.tests.items() if k in TESTS}
    env.globals.clear()
    return env


@dataclass
class Resolver:
    bundle: dict[str, Any]
    marker: str
    rep: Report

    def __post_init__(self) -> None:
        self.evals = {e["id"]: e for e in self.bundle["evaluations"]}

    def wrap(self, raw: Any, name: str, b: dict[str, Any]) -> Any:
        return Missing(name, self.marker) if raw is None else Value(raw, b.get("display"), b.get("precision"))

    def lookup_metric(self, ev: dict[str, Any], metric: str) -> dict[str, Any] | None:
        metrics = ev.get("metrics", {})
        if metric in metrics:
            return metrics[metric]
        for m in metrics.values():
            if metric in m.get("aliases", []):
                return m
        key = sanitize_metric_key(metric)
        return next((m for k, m in metrics.items() if sanitize_metric_key(k) == key), None)

    def metric_series(self, ref: str) -> list[tuple[str, dict[str, Any] | None]]:
        """Expand a wildcard reference to [(label, metric object)] in bundle order."""
        e_pat, _, m_pat = ref.partition("/")
        glob = lambda p: re.compile("^" + re.escape(p).replace(r"\*", "(.*)") + "$")  # noqa: E731
        out: list[tuple[str, dict[str, Any] | None]] = []
        if "*" in e_pat:
            rx = glob(e_pat)
            for ev in self.bundle["evaluations"]:
                if rx.match(ev["id"]) and (m := self.lookup_metric(ev, m_pat)) is not None:
                    out.append((ev.get("label") or ev["id"], m))
        else:
            ev = self.evals.get(e_pat)
            rx = glob(m_pat)
            for k, m in (ev or {}).get("metrics", {}).items():
                if hit := rx.match(k):
                    out.append((hit.group(1), m))
        return out

    def scalar_metric(self, ref: str) -> dict[str, Any] | None:
        e, _, m = ref.partition("/")
        ev = self.evals.get(e)
        return self.lookup_metric(ev, m) if ev else None

    def direction_check(self, name: str, b: dict[str, Any], metrics: list[dict[str, Any] | None]) -> str | None:
        found = {m["direction"] for m in metrics if m and m.get("direction")}
        if b.get("direction"):
            if found - {b["direction"]}:
                self.rep.warn(f"binding {name!r} declares {b['direction']} but the bundle says {sorted(found)}")
            return b["direction"]
        return found.pop() if len(found) == 1 else ("mixed" if found else None)

    def resolve(self, bindings: dict[str, dict[str, Any]], on_missing: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, str | None]]:
        ctx: dict[str, Any] = {}
        log: dict[str, Any] = {}
        directions: dict[str, str | None] = {}
        order = sorted(bindings.items(), key=lambda kv: kv[1]["kind"] == "items")  # items reference other bindings
        for name, b in order:
            value: Any
            ref: Any = b.get(b["kind"]) if b["kind"] != "field" else f"{b['evaluation']}:{b['field']}"
            match b["kind"]:
                case "builtin":
                    verdict = self.bundle.get("verdict") or {}
                    value = self.wrap(verdict.get(name.removeprefix("overall_")), name, b)
                    ref = f"verdict.{name.removeprefix('overall_')}"
                case "metric" if b["type"] == "scalar":
                    m = self.scalar_metric(b["metric"])
                    raw = m["value"] if m else None
                    if raw is None and "default" in b:
                        raw = b["default"]
                    value = self.wrap(raw, name, b)
                    directions[name] = self.direction_check(name, b, [m])
                case "metric":
                    pairs = self.metric_series(b["metric"])
                    value = [(lbl, self.wrap(m["value"] if m else None, f"{name}[{lbl}]", b)) for lbl, m in pairs] or Missing(name, self.marker)
                    directions[name] = self.direction_check(name, b, [m for _, m in pairs])
                case "items":
                    items, metrics = [], []
                    for it in b["items"]:
                        if "binding" in it:
                            label = it.get("label", it["binding"])
                            v = ctx[it["binding"]]
                            if isinstance(v, Value) and (b.get("display") or b.get("precision") is not None):
                                v = Value(v.raw, b.get("display") or v.display, b.get("precision", v.precision))
                            items.append((label, v))
                            metrics.append({"direction": directions.get(it["binding"]) or bindings[it["binding"]].get("direction")})
                        else:
                            m = self.scalar_metric(it["metric"])
                            label = it.get("label", it["metric"])
                            items.append((label, self.wrap(m["value"] if m else None, f"{name}[{label}]", b)))
                            metrics.append(m)
                    value = Missing(name, self.marker) if all(isinstance(v, Missing) for _, v in items) else items
                    directions[name] = self.direction_check(name, b, [m for m in metrics if m and m.get("direction")])
                case "field":
                    node: Any = self.evals.get(b["evaluation"])
                    for seg in b["field"].split("."):
                        node = node.get(seg) if isinstance(node, dict) else None
                    if isinstance(node, dict | list):
                        raise SpecError(f"binding {name!r}: {ref} is an object or list, not a scalar")
                    if node is None and "default" in b:
                        node = b["default"]
                    value = self.wrap(node, name, b)
                case "records":
                    rows = self.records(b["records"])
                    value = self.shape(name, b, rows) if rows else Missing(name, self.marker)
                case "from":
                    hits = list(jsonpath.find(b["from"], self.bundle).values())
                    if b["type"] == "scalar":
                        if len(hits) > 1:
                            raise SpecError(f"binding {name!r}: {b['from']} selected {len(hits)} nodes; a scalar must select one")
                        raw = hits[0] if hits else b.get("default")
                        value = self.wrap(raw, name, b)
                    else:
                        rows = [h for h in hits if isinstance(h, dict)]
                        value = self.shape(name, b, rows) if rows else Missing(name, self.marker)
                case _:
                    raise SpecError(f"binding {name!r}: unsupported source {b['kind']!r}")
            if isinstance(value, Missing) and (b.get("required") or on_missing == "fail"):
                raise MissingValueError(f"binding {name!r} did not resolve ({ref})")
            ctx[name] = value
            log[name] = {"type": b["type"], "ref": ref, "status": "missing" if isinstance(value, Missing) else "resolved",
                         "value": _plain(value)}
            if directions.get(name):
                log[name]["direction"] = directions[name]
        return ctx, log, directions

    def records(self, ref: str) -> list[dict[str, Any]]:
        if ref == "@evaluations":
            out = []
            for ev in self.bundle["evaluations"]:
                v = ev.get("verdict") or {}
                out.append({"id": ev["id"], "label": ev.get("label") or ev["id"], "source": ev.get("source"),
                            "metric": v.get("metric"), "score": v.get("score"), "threshold": v.get("threshold"),
                            "pass": v.get("pass")})
            return out
        e, _, rs = ref.partition("/")
        return list(((self.evals.get(e) or {}).get("records") or {}).get(rs) or [])

    def shape(self, name: str, b: dict[str, Any], rows: list[dict[str, Any]]) -> Any:
        if b["type"] == "table":
            out = []
            for r in rows[: b.get("maxRows", 1000)]:
                row = {}
                for f, spec in b["fields"].items():
                    src, opts = (spec, {}) if isinstance(spec, str) else (spec["field"], spec)
                    row[f] = self.wrap(r.get(src), f"{name}.{f}", opts)
                out.append(row)
            return out
        if "columns" in b:
            cols = list(b["columns"])
            mrows = {str(r.get(b["row"])): {c: self.wrap(r.get(f), name, b) for c, f in b["columns"].items()} for r in rows}
        else:
            cols, mrows = [], {}
            for r in rows:
                c = str(r.get(b["column"]))
                cols += [c] if c not in cols else []
                mrows.setdefault(str(r.get(b["row"])), {})[c] = self.wrap(r.get(b["value"]), name, b)
        return {"columns": cols, "rows": mrows}


def _plain(v: Any) -> Any:
    if isinstance(v, Missing):
        return None
    if isinstance(v, Value):
        return v.raw
    if isinstance(v, list | tuple):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


def num(ref: Any, ctx: dict[str, Any], params: dict[str, Any]) -> float | None:
    if ref is None:
        return None
    if isinstance(ref, dict) and "param" in ref:
        return float(params[ref["param"]])
    if isinstance(ref, dict) and "binding" in ref:
        v = ctx[ref["binding"]]
        return None if isinstance(v, Missing) else float(unwrap(v))
    return float(ref)


def verdict_label(v: Any, thr: float | None, direction: str | None) -> str:
    if thr is None or isinstance(v, Missing) or direction not in ("higher_is_better", "lower_is_better"):
        return ""
    ok = unwrap(v) <= thr if direction == "lower_is_better" else unwrap(v) >= thr
    return "PASS" if ok else "FAIL"


def _boxplot_markdown(blk: dict[str, Any], rows: list[dict[str, Any]], esc: Any) -> str:
    groups: dict[str, list[float]] = {}
    n_na: dict[str, int] = {}
    for r in rows:
        g = str(unwrap(r[blk["x"]])) if not isinstance(r[blk["x"]], Missing) else "(no group)"
        groups.setdefault(g, [])
        y = r[blk["y"]]
        if isinstance(y, Missing):
            n_na[g] = n_na.get(g, 0) + 1
        else:
            groups[g].append(float(unwrap(y)))
    out = ["| Group | n | N/A | Min | Median | Max |", "|---|---:|---:|---:|---:|---:|"]
    for g, ys in groups.items():
        stats = [f"{f(ys):.3f}".rstrip("0").rstrip(".") for f in (min, statistics.median, max)] if ys else ["", "", ""]
        out.append(f"| {esc(g)} | {len(ys)} | {n_na.get(g, 0)} | " + " | ".join(stats) + " |")
    return "\n".join(out) + "\n"


def _chart_num(v: Any, where: str) -> float | None:
    if isinstance(v, Missing):
        return None
    raw = v.raw if isinstance(v, Value) else v
    if raw is None:
        return None
    if not isinstance(raw, bool | int | float):
        raise SpecError(f"{where}: {raw!r} is not a number")
    return float(raw)  # a boolean charts as 0 or 1; its text stays yes/no


def resolve_viz(blk: dict[str, Any], ctx: dict[str, Any], params: dict[str, Any],
                bindings: dict[str, Any], directions: dict[str, str | None]) -> dict[str, Any]:
    """The seam between bindings and drawing: everything a chart renderer needs, as plain JSON
    (schemas/resolved-viz-v1alpha1.schema.json). Verdict colors come from threshold + direction here;
    the renderer never sees a binding, a template or a host."""
    t, name, vid = blk["type"], blk["data"], blk["id"]
    b = bindings[name]
    direction = blk.get("direction") or directions.get(name) or b.get("direction")
    if direction == "mixed":
        if t in ("radar", "radial"):
            raise SpecError(f"viz {vid!r}: {t} axes mix higher_is_better and lower_is_better (from the bundle)")
        direction = None
    p: dict[str, Any] = {
        "id": vid, "type": t, "title": blk.get("title", vid), "caption": blk.get("caption"), "alt": blk.get("alt"),
        "direction": direction, "threshold": num(blk.get("threshold"), ctx, params), "range": blk.get("range"),
        "display": b.get("display"), "precision": b.get("precision"),
        "options": {k: blk[k] for k in ("orientation", "fill", "palette", "show_values", "x_label", "y_label") if k in blk},
    }
    if "midpoint" in blk:
        p["options"]["midpoint"] = num(blk["midpoint"], ctx, params)
    data = ctx[name]
    if t == "heatmap":
        cols = [] if isinstance(data, Missing) else data["columns"]
        rows = [] if isinstance(data, Missing) else data["rows"]
        p["matrix"] = {"columns": cols, "rows": [
            {"label": str(r), "cells": [{"value": _chart_num(cells.get(c), f"{vid} [{r}, {c}]"), "text": NA if isinstance(cells.get(c, Missing("", "")), Missing) else str(cells[c])}
                                        for c in cols]} for r, cells in (rows.items() if rows else [])]}
    elif t == "boxplot":
        fields = b["fields"]
        ys = fields[blk["y"]]
        opts = ys if isinstance(ys, dict) else {}
        p["display"], p["precision"] = opts.get("display"), opts.get("precision")
        samples = [] if isinstance(data, Missing) else data
        p["samples"] = [{"x": "(no group)" if isinstance(r[blk["x"]], Missing) else str(unwrap(r[blk["x"]])),
                         "y": _chart_num(r[blk["y"]], f"{vid} {blk['y']}")} for r in samples]
    else:
        pts = [] if isinstance(data, Missing) else [
            {"label": str(lbl), "value": _chart_num(v, f"{vid} [{lbl}]"), "text": NA if isinstance(v, Missing) else str(v)} for lbl, v in data]
        if blk.get("sort", "none") != "none" and t in ("bar", "radial"):
            have = sorted((q for q in pts if q["value"] is not None), key=lambda q: q["value"], reverse=blk["sort"] == "desc")
            pts = have + [q for q in pts if q["value"] is None]
        p["points"] = pts
    return p


def viz_to_markdown(blk: dict[str, Any], ctx: dict[str, Any], params: dict[str, Any],
                    bindings: dict[str, Any], directions: dict[str, str | None], plain_head: bool = False) -> str:
    """Degraded Markdown rendering (format.markdown.viz: table). HTML/PDF charts are the renderer's job."""
    esc = lambda s: MD_ESCAPE_RE.sub(r"\\\1", str(s))  # noqa: E731
    head = (f"**{esc(blk['title'])}**\n\n" if "title" in blk else "") if plain_head else f"**Figure: {esc(blk.get('title', blk['id']))}** ({blk['type']})\n\n"
    if blk["type"] == "summary_cards":
        out = ["| Metric | Value | Threshold | Status |", "|---|---:|---:|---|"]
        for c in blk["cards"]:
            v = ctx[c["value"]]
            thr = num(c.get("threshold"), ctx, params)
            b = bindings[c["value"]]
            direction = c.get("direction") or directions.get(c["value"]) or b.get("direction")
            shown = fmt(thr, b.get("display"), b.get("precision")) if thr is not None else ""
            out.append(f"| {esc(c['label'])} | {v} | {shown} | {verdict_label(v, thr, direction)} |")
        return head + "\n".join(out) + "\n"
    data = ctx[blk["data"]]
    if isinstance(data, Missing):
        return head + f"{data}\n"
    if blk["type"] in ("radar", "radial") and directions.get(blk["data"]) == "mixed":
        raise SpecError(f"viz {blk['id']!r}: radar axes mix higher_is_better and lower_is_better (from the bundle)")
    if blk["type"] == "boxplot":
        return head + _boxplot_markdown(blk, data, esc)
    if blk["type"] in ("radar", "radial", "bar", "line"):
        thr = num(blk.get("threshold"), ctx, params)
        rows = data
        if blk.get("sort", "none") != "none":
            rows = sorted(data, key=lambda lv: float("inf") if isinstance(lv[1], Missing) else unwrap(lv[1]), reverse=blk["sort"] == "desc")
        out = ["| Label | Value |", "|---|---:|"] + [f"| {esc(lbl)} | {v} |" for lbl, v in rows]
        b = bindings[blk["data"]]
        tail = f"\n\nThreshold: {fmt(thr, b.get('display'), b.get('precision'))}\n" if thr is not None else "\n"
        return head + "\n".join(out) + tail
    if blk["type"] == "heatmap":
        cols = data["columns"]
        out = ["| | " + " | ".join(map(esc, cols)) + " |", "|---|" + "---:|" * len(cols)]
        out += [f"| {esc(r)} | " + " | ".join(str(cells.get(c, "")) for c in cols) + " |" for r, cells in data["rows"].items()]
        return head + "\n".join(out) + "\n"
    if blk["type"] == "table":
        cols = blk.get("columns") or [{"field": f} for f in data[0]]
        rows = data
        if "sort_by" in blk:
            f, rev = blk["sort_by"]["field"], blk["sort_by"].get("order") == "desc"
            rows = sorted(rows, key=lambda r: (isinstance(r[f], Missing), unwrap(r[f]) if not isinstance(r[f], Missing) else 0), reverse=rev)
        status_field, pass_when = blk.get("status_field"), blk.get("status_pass_when", True)
        out = ["| " + " | ".join(esc(c.get("label", c["field"])) for c in cols) + " |",
               "|" + "|".join("---:" if c.get("align") == "right" else "---" for c in cols) + "|"]
        for r in rows:
            cells = []
            for c in cols:
                v = r[c["field"]]
                if c["field"] == status_field and not isinstance(v, Missing):
                    cells.append("PASS" if bool(unwrap(v)) == pass_when else "FAIL")
                else:
                    cells.append(esc(v) if isinstance(v, Value) else str(v))
            out.append("| " + " | ".join(cells) + " |")
        return head + "\n".join(out) + "\n"
    return head


def render_text(text: str, spec_name: str, inputs: list[str], out_format: str, overrides: dict[str, str]) -> tuple[str | bytes, Report]:
    rep, fm, bindings, tmpl, blocks = validate_text(text)
    if rep.errors:
        raise SpecError("spec is invalid:\n  " + "\n  ".join(rep.errors))

    rs = fm["reportspec"]
    marker = rs.get("missing_marker", "data unavailable")
    raw_params = fm.get("params", {})
    params = {k: param_value(v) for k, v in raw_params.items()}
    for k, v in overrides.items():
        if k not in raw_params:
            raise SpecError(f"--param {k}: not declared in params")
        if isinstance(raw_params[k], dict) and raw_params[k].get("overridable") is False:
            raise SpecError(f"--param {k}: parameter is not overridable")
        t = param_type(raw_params[k])
        params[k] = float(v) if t == "number" else v.lower() in ("1", "true", "yes") if t == "boolean" else v

    bundle = build_bundle(inputs)
    for w in bundle["warnings"]:
        rep.warn(f"bundle: {w}")
    ctx, log, directions = Resolver(bundle, marker, rep).resolve(bindings, rs.get("on_missing", "marker"))

    digest = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    report = {
        "title": fm["title"],
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spec_name": rs.get("name") or spec_name.removesuffix(".md").removesuffix(".report"),
        "spec_version": fm["version"],
        "spec_digest": digest[:19],
    }
    s, r = bundle.get("subject") or {}, bundle.get("run") or {}
    subject = Fields("subject", marker, {k: Value(v) for k, v in s.items()})
    run = Fields("run", marker, {k: Value(v) for k, v in r.items() if k not in ("producer", "context")})
    if r.get("producer"):
        run["producer"] = Value(r["producer"]["name"])
        if r["producer"].get("version"):
            run["producer_version"] = Value(r["producer"]["version"])
    run["context"] = Fields("run.context", marker, {k: Value(v) for k, v in (r.get("context") or {}).items() if v is not None})

    env = make_env(marker)
    md = env.from_string(tmpl).render(**ctx, meta=meta_of(fm), params=params, report=report, subject=subject, run=run)
    by_id = {b["id"]: b for b in blocks}
    md_raw = md
    md = VIZ_TOKEN_RE.sub(lambda m: viz_to_markdown(by_id[m.group(1)], ctx, params, bindings, directions).rstrip("\n"), md_raw)
    md = re.sub(r"\n{3,}", "\n\n", md)

    payloads: dict[str, dict[str, Any]] = {}
    html_doc: str | None = None
    if out_format in ("html", "pdf", "docx"):
        html_doc = _render_html(md_raw, by_id, ctx, params, bindings, directions, fm, report, bundle, rep, payloads, out_format)
    if out_format == "markdown":
        return md, rep
    manifest = {
        "manifest_version": "v1alpha1",
        "report": report | {"spec_digest": digest},
        "hosts": host_namespaces(fm),
        "sources": bundle["sources"],
        "subject": bundle.get("subject"),
        "run": bundle.get("run"),
        "params": {"effective": params, "overrides": overrides},
        "bindings": log,
        "viz": [{"id": b["id"], "type": b["type"], "data": b.get("data"),
                 "payload_digest": ("sha256:" + hashlib.sha256(json.dumps(payloads[b["id"]], sort_keys=True, separators=(",", ":")).encode()).hexdigest()) if b["id"] in payloads else None}
                for b in blocks],
        "warnings": rep.warnings,
        "markdown": md,
    }
    rep.manifest = manifest
    if html_doc is not None:
        if out_format in ("html", "docx"):
            return html_doc, rep
        from reportspec_html import html_to_pdf
        try:
            return html_to_pdf(html_doc), rep
        except RuntimeError as e:
            raise SpecError(str(e)) from e
    return json.dumps(manifest, indent=2, default=str), rep


def _render_html(md_raw: str, by_id: dict[str, dict[str, Any]], ctx: dict[str, Any], params: dict[str, Any],
                 bindings: dict[str, Any], directions: dict[str, str | None], fm: dict[str, Any], report: dict[str, Any],
                 bundle: dict[str, Any], rep: Report, payloads: dict[str, dict[str, Any]], out_format: str) -> str | bytes:
    """Charts become inline SVG figures (PNG in DOCX); tables and summary cards stay Markdown tables with PASS/FAIL badges."""
    from reportspec_charts import ChartError, render_payload
    from reportspec_html import FIG_TOKEN, build_html, figure_html

    validator = Draft202012Validator(json.loads(RESOLVED_SCHEMA.read_text()))
    figs: dict[str, Any] = {}

    def place(m: re.Match[str]) -> str:
        blk = by_id[m.group(1)]
        if blk["type"] not in CHART_TYPES:
            return viz_to_markdown(blk, ctx, params, bindings, directions, plain_head=True).rstrip("\n")
        payload = resolve_viz(blk, ctx, params, bindings, directions)
        errs = [f"/{'/'.join(map(str, e.path))}: {e.message}" for e in validator.iter_errors(payload)]
        if errs:
            raise SpecError(f"viz {blk['id']!r}: resolved payload is invalid:\n  " + "\n  ".join(errs[:5]))
        try:
            figs[blk["id"]] = render_payload(payload)
        except ChartError as e:
            raise SpecError(f"viz {blk['id']!r}: {e}") from e
        payloads[blk["id"]] = payload
        return FIG_TOKEN.format(blk["id"])

    md_html = re.sub(r"\n{3,}", "\n\n", VIZ_TOKEN_RE.sub(place, md_raw))
    order = re.findall(r"@@RS-FIG:([a-z][a-z0-9-]*)@@", md_html)
    html_figs = {vid: figure_html(order.index(vid) + 1, vid, payloads[vid]["type"], payloads[vid]["title"], payloads[vid]["caption"],
                                  figs[vid].svg, figs[vid].alt, figs[vid].note) for vid in order}
    opts = (fm.get("format") or {}).get("pdf" if out_format == "pdf" else out_format)
    opts = opts if isinstance(opts, dict) else {}
    evidence = {k: report[k] for k in ("spec_name", "spec_version", "spec_digest", "generated_at")} | {"sources": bundle["sources"], "warnings": rep.warnings}
    if out_format == "docx":
        from reportspec_docx import DocxError, build_docx
        try:
            return build_docx(md_html, {vid: {"number": order.index(vid) + 1, "title": payloads[vid]["title"], "caption": payloads[vid]["caption"],
                                              "note": figs[vid].note, "alt": figs[vid].alt, "svg": figs[vid].svg} for vid in order}, fm, evidence, toc=bool(opts.get("toc")))
        except DocxError as e:
            raise SpecError(str(e)) from e
    page = {"letter": "Letter", "a4": "A4"}[opts.get("page_size", "letter")] + (" landscape" if opts.get("orientation") == "landscape" else "")
    return build_html(md_html, html_figs, fm, report, evidence, toc=bool(opts.get("toc")), page=page)


# --- Conformance -------------------------------------------------------------------


def run_conformance(root: Path) -> int:
    """Each case is a directory with case.yaml; see conformance/README.md for the keys."""
    failures = skipped = 0
    cases = sorted(p.parent for p in root.glob("*/case.yaml"))
    for case_dir in cases:
        case = load_yaml((case_dir / "case.yaml").read_text())
        if "pandoc" in case.get("requires", []) and not shutil.which("pandoc"):
            print(f"SKIP  {case_dir.name}: needs pandoc")
            skipped += 1
            continue
        text = (case_dir / case.get("spec", "spec.report.md")).read_text(encoding="utf-8")
        exp = case["expect"]
        problems: list[str] = []
        rep, *_ = validate_text(text)
        want_valid = exp.get("validate", "valid") == "valid"
        if want_valid != (not rep.errors):
            problems.append(f"validate: expected {exp.get('validate', 'valid')}, got {rep.errors or 'valid'}")
        for needle in exp.get("errors_contain", []):
            if not any(needle in e for e in rep.errors):
                problems.append(f"no error containing {needle!r} in {rep.errors}")
        for needle in exp.get("warnings_contain", []):
            if not any(needle in w for w in rep.warnings):
                problems.append(f"no warning containing {needle!r} in {rep.warnings}")
        if "render" in exp:
            inputs = [str((case_dir / i).resolve()) if ":" not in i else f"{i.split(':', 1)[0]}:{(case_dir / i.split(':', 1)[1]).resolve()}"
                      for i in case.get("inputs", [])]
            try:
                fmt_out = case.get("format", "markdown")
                md, rrep = render_text(text, case_dir.name, inputs, fmt_out, {k: str(v) for k, v in (case.get("params") or {}).items()})
                if fmt_out == "docx":
                    import io
                    import zipfile
                    z = zipfile.ZipFile(io.BytesIO(md))  # type: ignore[arg-type]
                    xml = z.read("word/document.xml").decode("utf-8")
                    media = [n for n in z.namelist() if n.startswith("word/media/")]
                    for needle in exp.get("docx_contains", []):
                        if needle not in xml:
                            problems.append(f"docx does not contain {needle!r}")
                    for needle in exp.get("docx_excludes", []):
                        if needle in xml:
                            problems.append(f"docx contains {needle!r}")
                    if "docx_media" in exp and len(media) != exp["docx_media"]:
                        problems.append(f"docx has {len(media)} images, expected {exp['docx_media']}")
                if fmt_out == "html":
                    for needle in exp.get("html_contains", []):
                        if needle not in md:
                            problems.append(f"html does not contain {needle!r}")
                    for needle in exp.get("html_excludes", []):
                        if needle in md:
                            problems.append(f"html contains {needle!r}")
                for needle in exp.get("render_warnings_contain", []):
                    if not any(needle in w for w in rrep.warnings):
                        problems.append(f"no render warning containing {needle!r} in {rrep.warnings}")
                if exp["render"] != "ok":
                    problems.append("render: expected failure, got success")
                for needle in exp.get("markdown_contains", []):
                    if needle not in md:
                        problems.append(f"markdown does not contain {needle!r}")
                for needle in exp.get("markdown_excludes", []):
                    if needle in md:
                        problems.append(f"markdown contains {needle!r}")
            except (SpecError, MissingValueError) as e:
                if exp["render"] == "ok":
                    problems.append(f"render failed: {e}")
                elif exp.get("render_error_contains", "") not in str(e):
                    problems.append(f"render error {str(e)!r} lacks {exp['render_error_contains']!r}")
        failures += bool(problems)
        print(f"{'FAIL' if problems else 'PASS'}  {case_dir.name}: {case.get('description', '')}")
        for p in problems:
            print(f"      {p}")
    print(f"\n{len(cases) - failures - skipped}/{len(cases) - skipped} cases passed" + (f", {skipped} skipped" if skipped else ""))
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    a = ap.parse_args()

    if a.cmd == "conformance":
        return run_conformance(a.dir)
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
        if isinstance(out, bytes) and not a.output:
            print(f"failed: --format {a.format} needs -o OUTPUT.{a.format}", file=sys.stderr)
            return 2
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
    except (SpecError, MissingValueError) as e:
        print(f"failed: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
