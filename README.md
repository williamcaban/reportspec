# ReportSpec v1alpha1: Portable Markdown Report Templates for Evaluation Evidence

**Status:** DRAFT for PM/Engineering discussion · **Author:** William Caban · **Date:** 2026-10-20 (renderer and JSONL source added 2026-10-23)
**Hosts:** EvalHub ([profile](profiles/evalhub.md)) and ASAGO ([profile](profiles/asago.md))
**Builds on:** [ASAGO-ADR-0001](https://github.com/asago-ai/architecture-decision-records/blob/main/architecture-decision-records/ASAGO-ADR-0001-asago-server.md), which leaves report generation to a separate ADR

> Illustrative design. Field names, storage and where rendering runs are engineering's call in each project. This draft pins down semantics so both projects can test against the same cases.

| File | What it is |
|---|---|
| [`src/reportspec/schemas/reportspec-v1alpha1.schema.json`](src/reportspec/schemas/reportspec-v1alpha1.schema.json) | JSON Schema (2020-12) for the front matter. `#/$defs/vizBlock` validates each viz block |
| [`src/reportspec/schemas/results-bundle-v1alpha1.schema.json`](src/reportspec/schemas/results-bundle-v1alpha1.schema.json) | The ResultsBundle: the host-neutral results model that bindings resolve against |
| [`profiles/evalhub.md`](profiles/evalhub.md), [`profiles/asago.md`](profiles/asago.md) | Host profiles: adapters, host namespace, API surface |
| [`examples/safety-compliance.report.md`](examples/safety-compliance.report.md) | EvalHub example: one collection run, compliance audience |
| [`examples/agent-redteam.report.md`](examples/agent-redteam.report.md) | ASAGO example: Policy Mapper risks + MiDojo red team + EvalHub Garak, one bundle |
| [`examples/inputs/`](examples/inputs/) | Native results in each tool's real shape (provenance in each file's `_comment`) |
| [`conformance/`](conformance/) | 34 cases every implementation must pass |
| [`examples/model-release.report.md`](examples/model-release.report.md) | Showcase: one Markdown file plus [one JSONL file](examples/inputs/model-release.jsonl) render to HTML and PDF with every chart type. Synthetic data |
| [`src/reportspec/schemas/resolved-viz-v1alpha1.schema.json`](src/reportspec/schemas/resolved-viz-v1alpha1.schema.json) | The payload a chart renderer receives: bindings resolved, text formatted. The seam between the spec and any drawing library |
| [`src/reportspec/`](src/reportspec/) | The `reportspec` package and command: `core.py` (validator, bundler, renderer, conformance runner), `cli.py`. Reference implementation, not product code |
| `charts.py`, `htmlout.py`, `docxout.py`, `fontset.py` (same folder) | Chart renderer (payload in, SVG out), HTML/PDF assembly, DOCX via pandoc, embedded fonts |
| [`fonts/`](src/reportspec/fonts/README.md), [`icons/`](src/reportspec/icons/README.md) (in the package) | Vendored Red Hat Text/Mono (OFL) and Font Awesome Free status icons (CC BY 4.0), with provenance and font policy |
| [`VISUAL-QA.md`](VISUAL-QA.md) | What "the chart looks right" means: 21 requirements, how they are checked, regression cases |
| [`Containerfile`](Containerfile), `uv.lock` | Fedora Python image (3.14 by default, 3.13 with `--build-arg PY=313`) with every dependency pinned and hash-checked. Runs offline, non-root, read-only |

### Install

Python 3.13 or later. Not on PyPI yet; install from GitHub:

```bash
uv tool install git+https://github.com/williamcaban/reportspec     # puts `reportspec` on your PATH
uvx --from git+https://github.com/williamcaban/reportspec reportspec --version   # or run it once, nothing installed
pip install git+https://github.com/williamcaban/reportspec          # or plain pip, ideally in a virtualenv
```

PDF output needs Pango (`dnf install pango`, `brew install pango`; on macOS the command finds Homebrew's copy by itself) and DOCX output needs `pandoc` (`dnf install pandoc`, `brew install pandoc`). From a clone, use `uv run reportspec …` instead of `reportspec …`; `uv run pytest` runs the tests.

### Commands

```bash
reportspec validate examples/safety-compliance.report.md
reportspec render examples/safety-compliance.report.md --input examples/inputs/evalhub-job.json
reportspec render examples/agent-redteam.report.md \
  --input examples/inputs/asago-risk-extraction.json \
  --input examples/inputs/midojo-results.json \
  --input examples/inputs/evalhub-job.json
reportspec bundle --input examples/inputs/midojo-results.json   # show the normalized bundle
reportspec conformance conformance/
```

### Try it: one Markdown file and one JSONL file to HTML and PDF

```bash
reportspec render examples/model-release.report.md \
  --input examples/inputs/model-release.jsonl --format pdf  -o out/model-release.pdf
reportspec render examples/model-release.report.md \
  --input examples/inputs/model-release.jsonl --format html -o out/model-release.html
```

Add `--format docx -o out/model-release.docx` for an editable Word copy. Auditors who must annotate a report want this; it needs the `pandoc` binary on the PATH (GPL-2.0+, run as a separate process). Charts arrive as PNG images with Red Hat Text, tables as Word tables, and the report keeps its Evidence section; template images are rejected, and pandoc never reads raw HTML or raw OOXML from the Markdown.

Rendered samples are checked in under [`examples/output/`](examples/output/) so you can open them without running anything.

Each run writes the report and `<name>.manifest.json`, the evidence record (spec digest, SHA-256 of each input, one digest per figure payload, the Markdown fallback). The HTML is a single self-contained file: inline SVG charts, inline CSS, no external requests.


### Or in a container (Fedora, Python 3.14 or 3.13)

```bash
podman build -t reportspec .                          # quay.io/fedora/python-314 (Fedora 43); --build-arg PY=313 for Fedora 42
mkdir -p out
podman run --rm --network none --read-only --tmpfs /tmp -v "$PWD/out:/out:Z" reportspec \
  render examples/model-release.report.md --input examples/inputs/model-release.jsonl --format pdf -o /out/model-release.pdf
podman run --rm --network none reportspec conformance conformance
```

The image carries pango, pandoc, the fallback fonts (Liberation, DejaVu) and a virtualenv built from `uv.lock` with hash checking, so after the build it needs no network, and it runs under OpenShift's arbitrary-uid rule (group 0 owns the files). Red Hat Text and Mono are not installed from RPMs on purpose; the vendored files are the only source (see [fonts/README.md](src/reportspec/fonts/README.md)). Regenerate the lock with `uv lock` after changing the dependencies in `pyproject.toml`. On macOS, the Podman machine here could not mount a directory under `/tmp`; use one under your home.

What the template author writes is a Markdown file with a few `reportspec-viz` fences. A chart is a type, a data binding and a few options:

````markdown
```reportspec-viz
id: judge-box
type: boxplot
data: judge_scores      # a binding over records in the JSONL
x: model
y: score
threshold: { param: min_score }
```
````

Charts, tables and cards are drawn only from resolved data. Pass/fail marks come from the threshold and direction the author states, or from the producer's verdict. N/A is never plotted as zero.

---

## 1. Why one spec for two projects

Both projects need the same thing: turn evaluation results into a document an auditor, a CISO or a developer can read and trust.

- **EvalHub** has four RFEs for it (API, viz blocks, CLI, dashboard) and no implementation yet.
- **ASAGO** components each hand-build their own report today. The Policy Mapper ships `risk-extraction.html`, made by injecting JSON into an HTML template (`__REPORT_DATA__`). MiDojo prints a terminal table and writes `results.json`. ADR-0001 says report generation "belong[s] in a separate ADR".
- ASAGO's public architecture runs evaluations and red teaming **on EvalHub**, so an ASAGO report usually contains EvalHub results anyway.

Two template languages for overlapping reports would split authors, double the security review of the template sandbox, and make a report that mixes policy risks with benchmark results impossible to write once. The v1alpha1 draft from earlier today was EvalHub-specific in three places. This revision removes all three:

| Coupling in the earlier draft | Now |
|---|---|
| `evalhub:` namespace held the bindings | Core namespace `reportspec:`; host settings go in an optional host namespace (`evalhub:`, `asago:`) |
| JSONPath into the EvalHub job (`$.job.results.benchmarks[?@.id=='bbq'].metrics.accuracy_amb`) | References into a host-neutral **ResultsBundle** (`bbq/accuracy_amb`); each host supplies adapters from its native format |
| `report.model_name`, `report.collection_id`, ```` ```evalhub-viz ```` | `subject.*`, `run.*`, `run.context.*`; ```` ```reportspec-viz ```` |

## 2. Architecture: three layers, one seam

```text
 ┌────────────── portable: identical on every host ──────────────┐
 │  *.report.md         front matter + template + viz blocks     │
 │       │ bindings: bbq/accuracy_amb, midojo.weather/pairs      │
 │       ▼                                                       │
 │  ResultsBundle       subject · run · verdict · evaluations[]  │
 └───────▲───────────────────────────────────────────────────────┘
         │ adapters (per source format, owned by the host or the tool)
 ┌───────┴──────────┬────────────────┬────────────────┬──────────┐
 │ EvalHub job      │ MLflow runs    │ MiDojo         │ Policy   │
 │ (evalhub-job)    │ (mlflow, plan) │ results.json   │ Mapper   │
 └──────────────────┴────────────────┴────────────────┴──────────┘
 host profile: API, storage, auth, render location, host namespace
```

| Layer | Core (this spec) | Host (profile) |
|---|---|---|
| Spec file | Front matter schema, template language, viz blocks, missing-data rules | Optional host namespace, e.g. `evalhub.applies_to` |
| Data | ResultsBundle schema and reference grammar | Adapters from native formats into the bundle |
| Rendering | Semantics, escaping, evidence manifest | Where it runs, the HTML/PDF engine, storage, API, CLI |
| Testing | Conformance cases | Passing them |

The one seam is the ResultsBundle. A spec never sees a native format, so an adapter change in one tool never breaks a spec. That is the rendering RFE's decoupling requirement (R6), applied across projects instead of only across providers.

## 3. File anatomy

```text
agent-redteam.report.md
├── ---                      front matter (YAML)
│   title, version, ...      document metadata    → meta.*
│   params:                  render parameters    → params.*
│   format:                  output formats
│   reportspec:              core: version, bindings, missing-data policy
│   asago: / evalhub:        host namespaces (optional, opaque to the core)
├── ---
└── Markdown body            template: CommonMark + GFM tables
    ├── {{ x }} {% if %} {% for %}     restricted Jinja-like language
    └── ```reportspec-viz            declarative viz blocks (YAML, no template syntax)
```

## 4. Front matter conventions

| Practice | Precedent | ReportSpec rule |
|---|---|---|
| `---` on line 1, closed by `---` or `...` | Jekyll, Pandoc | Required. No BOM. YAML only |
| Common document keys at top level | Pandoc/Quarto (`title`, `subtitle`, `author`, `date`, `lang`), Jekyll/Hugo (`tags`, `description`) | `title`, `subtitle`, `description`, `version` (SemVer, required), `authors`, `date`, `tags`, `lang` |
| Front matter exposed to the body | Jekyll `page.*`, Quarto `{{< meta >}}` | Document keys are readable as `meta.*` |
| Parameterized reports | R Markdown and Quarto `params:` | `name: default`, or `{value, type, label, choices, overridable}` |
| Per-output options | Quarto `format:` | `html`, `pdf`, `markdown`, `json`; a key's presence enables that output |
| Tool keys namespaced so tools coexist | Jekyll, Hugo and Pandoc ignore keys they don't own | Core keys under `reportspec:`. **Any other top-level mapping is a host namespace**: excluded from `meta.*`, ignored by other hosts, validated only by its owner. An unknown top-level *scalar* is rejected, which catches typos such as `subtitel:` |
| Slug from the filename | Jekyll/Hugo | `reportspec.name` defaults to the file slug |
| Dates are plain strings, strict YAML | (deviation, security) | No timestamp coercion, no aliases, no duplicate keys |

The binding-level display hint is called `display` so it can't be confused with Quarto's `format:`.

## 5. The ResultsBundle

The bundle is a small, flat model of "what was evaluated, how, and with what result". The full schema is [`results-bundle-v1alpha1.schema.json`](src/reportspec/schemas/results-bundle-v1alpha1.schema.json).

```json
{
  "bundle_version": "v1alpha1",
  "subject": { "kind": "model", "name": "granite-3.3-8b-instruct" },
  "run": { "id": "eval-run-8f3a21", "producer": { "name": "evalhub" }, "context": { "collection_id": "safety-and-fairness" } },
  "verdict": { "score": 0.781, "threshold": 0.74, "pass": true },
  "evaluations": [
    { "id": "owasp_llm_top10", "source": "garak",
      "metrics": { "attack_success_rate": { "value": 0.18, "direction": "lower_is_better" },
                   "dan.Dan_11_0_asr": { "value": 0.11 } },
      "verdict": { "metric": "attack_success_rate", "score": 0.18, "threshold": 0.1, "pass": false },
      "attributes": { "oci_reference": "quay.io/acme/evals/granite-safety:eval-run-8f3a21" } },
    { "id": "midojo.weather", "source": "midojo",
      "metrics": { "attack_success_rate": { "value": 0.333, "direction": "lower_is_better" } },
      "records": { "pairs": [ { "user_task": "trip_weather", "injection_task": "hidden_file_via_itinerary",
                                "task_completed": true, "attack_succeeded": true } ] } }
  ],
  "sources": [ { "adapter": "evalhub-job", "digest": "sha256:…", "run_id": "eval-run-8f3a21" } ]
}
```

| Part | What it holds | Why |
|---|---|---|
| `evaluations[].metrics` | Named scalars, with optional `type`, `direction`, `unit`, `aliases` | What every tool has. `direction` lives here so authors don't restate polarity |
| `evaluations[].verdict` | `{metric, score, threshold, pass}`, any of which may be null | The producer's own pass/fail. Renderers never compute verdicts |
| `evaluations[].records` | Named row sets of flat scalars | Tables and matrices: MiDojo task pairs, Policy Mapper risks, per-probe hits |
| `evaluations[].attributes` | Anything else (Environment Card, OCI refs) | Reproducibility fields |
| `verdict` | Overall verdict, when a source computes one | EvalHub collection pass criteria |
| `sources` | Adapter, digest and run id per native input | Provenance, copied into the evidence manifest |

**Combining sources.** A host may feed several inputs into one bundle, which is the normal case for ASAGO. Evaluation ids must be unique across inputs, or the bundle fails. `subject` and `verdict` come from the first source that has one, and later disagreements become warnings. Run identity (`id`, `producer`, timestamps) moves as a unit from the first source with an id, so a bundle never describes a run that didn't happen. Each source keeps its own run id in `sources[]`. `run.context` keys merge.

**Adapters in the reference implementation**, with mapping details in the profiles:

| Adapter | Input | Becomes |
|---|---|---|
| `evalhub-job` | `GET /api/v1/evaluations/jobs/{id}` | One evaluation per benchmark; `results.test` → `verdict`; env/eval cards → `attributes` |
| `midojo` | `midojo-run` `results.json` | `midojo.<suite>` with `utility_rate`, `attack_success_rate` (N/A excluded, as MiDojo computes it), and `records.pairs` |
| `asago-risk-extraction` | Policy Mapper `risk-extraction.json` v0.3 | `policy-mapper.<policy>` with risk counts, `records.risks`, `records.taxonomies`; `precision`/`recall`/`f1` when run against ground truth |
| `bundle` | An already-normalized bundle | Passed through. This is how a caller that owns orchestration (ASAGO) hands over a combined bundle |
| `mlflow` | MLflow runs | **Planned** (see the EvalHub profile). Both EvalHub and the Policy Mapper log to MLflow, so one adapter serves both |

### JSONL: the simplest source

A `.jsonl` file (or `--input jsonl:PATH`) is read by the `jsonl` adapter, one JSON object per line. It is the lowest-effort way to hand results to a report: a script can emit it with a print statement.

```jsonl
{"subject": {"kind": "model", "name": "demo-7b"}, "run": {"id": "run-42"}}
{"evaluation": "capability", "label": "Capability suite", "metric": "mmlu", "value": 0.71, "direction": "higher_is_better"}
{"evaluation": "safety", "metric": "hallucination_probe", "value": null}
{"evaluation": "judge", "set": "scores", "model": "demo-7b", "score": 0.70}
{"evaluation": "garak", "verdict": {"metric": "attack_success_rate", "score": 0.107, "threshold": null, "pass": null}}
```

| Line has | Becomes |
|---|---|
| no `evaluation` | optional header: `subject`, `run`, or the bundle-level `verdict` |
| `evaluation` + `metric` + `value` | a metric (`value: null` is N/A; optional `direction`, `unit`, `type`) |
| `evaluation` + `set` | one row of the named record set, for tables, matrices and box plots; the other keys are the row |
| `evaluation` + `verdict` | that evaluation's verdict |
| `label`, `source` on any line | the evaluation's label and source (the first one wins) |

A malformed line fails with its line number. Per-sample rows (the `set` lines) are what box plots read; the chart computes quartiles, the spec does not compute verdicts. Aggregation of raw samples into scores stays the producer's job.

## 6. Bindings: the data contract (`reportspec.bindings`)

Templates only see these names:

| Name | Source |
|---|---|
| `<binding>` | Declared under `reportspec.bindings`, or a built-in |
| `meta.*` | Front matter document keys |
| `params.*` | Effective parameter values |
| `report.*` | Render facts: `generated_at`, `spec_name`, `spec_version`, `spec_digest`, `title` |
| `subject.*` | `kind`, `name`, `version`, `uri` |
| `run.*` | `id`, `producer`, `producer_version`, `started_at`, `completed_at`, `context.*` (host-defined keys; absent keys print the missing marker) |

### Reference grammar

`<evaluation>/<metric>`. The separator is `/` because metric names contain dots (`promptinject.HijackHateHumans_asr`) and commas (`acc,none`).

| You write | You get |
|---|---|
| `truthfulness: truthfulqa_mc1/acc` | scalar |
| `probe_asr: "owasp_llm_top10/*_asr"` | series over that evaluation's matching metrics, labeled by what `*` matched (`dan.Dan_11_0`) |
| `acc_all: "*/acc"` | series of one metric across evaluations, labeled by evaluation label; evaluations without the metric are skipped |
| `axes: [truthfulness, bbq/accuracy_amb]` | series of other bindings or references (auto labels; use `items:` for display labels) |
| `{ metric: bbq/accuracy_amb, display: percent, required: true }` | long form, for options |
| `{ items: [{label, binding \| metric}] }` | series with display labels |
| `{ evaluation: truthfulqa_mc1, field: attributes.env_card.gpu_model }` | scalar from any field of an evaluation |
| `{ records: midojo.weather/pairs, fields: {out: in, ...} }` | table |
| `{ records: midojo.weather/pairs, row: injection_task, column: user_task, value: attack_succeeded }` | long-form matrix |
| `{ records: "@evaluations", row: id, columns: {Score: score} }` | wide-form matrix over the built-in record set |
| `{ type: scalar \| table, from: "$.…" }` | RFC 9535 JSONPath over the **bundle** (escape hatch; never over a native format) |

`type` is inferred from the source key, and stating it is optional except with `from`. The validator rejects a stated type that contradicts the source.

**Built-ins** need no declaration: `overall_score`, `overall_threshold`, `overall_pass` (from `bundle.verdict`) and `evaluations`, a table with one row per evaluation: `id, label, source, metric, score, threshold, pass`. List a built-in only to add options, as in `overall_pass: { required: true }`. Giving one a source is an error.

**Metric name matching** tries the exact name, then the metric's `aliases`, then the name after the EvalHub SDK's MLflow sanitizer (`sanitize_metric_key_for_api`: `acc,none` → `acc_none`). A spec written against job JSON therefore also resolves against MLflow-logged keys.

**Direction.** A binding inherits `direction` from the bundle metric when it doesn't declare one, so polarity is stated once by the producer. A declared direction wins, and a conflict is a render warning. A radar whose axes resolve to mixed polarity fails, at registration when the directions are declared and at render when they come from the bundle.

Shared options: `display` (number, integer, percent, text, boolean, datetime), `precision`, `unit`, `direction`, `required`, `default` (scalars only), `maxRows` (tables).

## 7. Template language (restricted Jinja-like subset)

The spec defines the subset itself and does not say "Jinja2", so it stays a documented contract and not a side effect of one library. The reference implementation is Python 3.13+ on Jinja2's sandbox, with an AST allowlist that enforces the subset.

| Allowed | Not allowed |
|---|---|
| `{{ expr }}`, `{% if/elif/else %}`, `{% for x in y [if cond] %}` with `loop.*`, `{% set x = ... %}` | `include`, `import`, `extends`, `block`, `macro`, `call`, `filter` blocks, `with`, block `set` |
| Comparisons, `and/or/not`, arithmetic, literals, `~` concat | Any function or method call, including `range()` and `.items()` |
| Filters: `round int float abs default upper lower title capitalize trim length join sort first last min max replace truncate` plus `percent number status code` | Any other filter, including `safe` |
| Tests: `is available`, `is missing`, `defined none number string true false eq ne lt le gt ge in even odd divisibleby` | Attribute or item access starting with `_` |

Registration-time checks: unknown names; unknown `meta.`/`params.`/`report.`/`subject.`/`run.` keys; unknown table fields on loop variables; viz blocks inside `{% for %}`.

**Escaping.** Every `{{ }}` output is Markdown-escaped. Results are untrusted content: Garak prompts, MiDojo agent outputs, and policy text quoted as evidence can carry `<script>`, image beacons (`![](http://attacker/…)`) that a PDF renderer would fetch, or `{{ }}` text. All of these come out inert, and rendering is single-pass. Use `{{ v | code }}` for code spans. Raw HTML in the body is not rendered.

## 8. Missing data: printable, never comparable

With `on_missing: marker` (the default), an unresolved value prints the marker (*data unavailable*). **Any comparison, truth test, arithmetic or iteration on it fails the render.** If missing evaluated as false instead, `{% if asr > 0.1 %}FAIL{% else %}PASS{% endif %}` would print PASS for a run that never measured ASR.

```jinja
{% if truthfulness is available and truthfulness < params.safety_floor %}   ✓ guard, short-circuits
{% if truthfulness < params.safety_floor %}                                 ✗ render fails if missing
```

This matters more with ASAGO data. MiDojo reports an attack as **N/A** when the payload never reached the agent, and its README says plainly that N/A "is not a security pass". The `midojo` adapter maps N/A to null, so `attack_succeeded` is missing for those pairs. `{% for p in pairs if p.attacked %}` fails the render, and `{% for p in pairs if p.attacked is available and p.attacked %}` is the correct form (conformance case 20). The Policy Mapper follows the same convention: it reports undefined precision or recall as `null`, shown as "—", "so they can't be mistaken for a genuine 0.0".

- The validator **warns** on unguarded `if`/`for` uses of optional bindings.
- `required: true` fails the render when that binding is missing. `on_missing: fail` makes every binding required.
- `default:` makes a scalar never-missing. Use it sparingly in compliance reports.
- A wildcard or record set that matches nothing counts as missing, not as an empty list.
- A series from `items` stays available if at least one item resolved.

## 9. Visualization blocks

Fenced code blocks with the info string `reportspec-viz`, whose YAML body is validated against `#/$defs/vizBlock`. A fence ending in `-viz` with any other name (such as the old `evalhub-viz`) gets a warning.

| Type | `data` binding | Type-specific options |
|---|---|---|
| `radar` | series | `range`, `fill`, `threshold`, `direction`. 3 to 12 axes. A missing axis breaks the polygon and is labelled N/A |
| `radial` | series | `range`, `threshold`, `direction`, `sort`. Radial bars, up to 8 items; N/A leaves an empty track |
| `boxplot` | table (one row per sample) | `x` (group field), `y` (numeric field), `range`, `threshold`, `direction`, axis labels. Quartiles are computed by the chart; null samples are counted as N/A |
| `bar` | series | `orientation`, `range`, `threshold`, `direction`, `sort`, `palette`, axis labels |
| `line` | series (order kept) | `range`, `threshold`, `direction`, axis labels |
| `heatmap` | matrix | `range`, `palette` (sequential/diverging), `midpoint`, `direction`, `show_values` |
| `table` | table | `columns[]`, `sort_by`, `status_field` + `status_pass_when` (set `false` for fields where true is bad, like `attack_succeeded`), `sortable` |
| `summary_cards` | none; each card's `value` is a scalar | `cards[] {label, value, display, precision, threshold, direction}` |

Resolution and drawing are separate. The host resolves a block against the bundle into a [resolved payload](src/reportspec/schemas/resolved-viz-v1alpha1.schema.json) (plain JSON, values and text already formatted, verdict inputs already evaluated), and a chart renderer turns that payload into SVG. The reference renderer builds Vega-Lite specs with Altair for `bar`, `line`, `heatmap` and `boxplot`, and Vega specs for `radar` and `radial`, all rendered through `vl-convert` with external data loading disabled. A host can swap the renderer without touching a template. What a figure must look like is [VISUAL-QA.md](VISUAL-QA.md). Every chart adds a figure number, a caption note (threshold, direction, N/A count) and generated alt text.

Rules: no template syntax inside a fence; no colors (`palette` states intent, the renderer owns colors); thresholds are a literal, `{param: x}` or `{binding: x}`; a block may sit inside `{% if %}` but not inside `{% for %}`; `format.markdown.viz: table` renders each block as a GFM table for CI and PR comments.

## 10. What a host must provide

A conforming host implements five things. Everything else, such as storage, auth, UI and PDF engine, is its own choice.

1. **Validate** a `.report.md` with the core rules, plus its own host namespace if it defines one.
2. **Adapt** its native results into a ResultsBundle, at least one adapter.
3. **Render** Markdown, plus any of HTML/PDF/JSON the host supports, with core semantics.
4. **Emit the evidence manifest** (section 11) next to every rendered report.
5. **Pass the conformance suite.**

| | EvalHub | ASAGO |
|---|---|---|
| Spec storage | Server registry (`POST /api/v1/reportspecs`), optional CRD | None: the caller supplies the spec in each request (ADR-0001: stateless) |
| Adapters | `evalhub-job`, `mlflow` | `midojo`, `asago-risk-extraction`, `bundle`; reuses `evalhub-job` for Garak runs on EvalHub |
| Host namespace | `evalhub.applies_to` (collections, providers) | `asago.pipeline` (illustrative) |
| Details | [profiles/evalhub.md](profiles/evalhub.md) | [profiles/asago.md](profiles/asago.md) |

## 11. Output: report plus evidence manifest

The `json` format is the evidence record a host stores next to the HTML/PDF, so an auditor can reproduce or challenge a verdict. It is identical across hosts:

```json
{
  "manifest_version": "v1alpha1",
  "report":  { "spec_name": "agent-redteam", "spec_version": "0.1.0", "spec_digest": "sha256:…(full)", "generated_at": "…" },
  "hosts":   ["asago"],
  "sources": [ { "adapter": "midojo", "uri": "midojo-results.json", "digest": "sha256:…", "run_id": "midojo-run-4b7e90", "evaluations": ["midojo.weather"] } ],
  "subject": { "kind": "model", "name": "granite-3.3-8b-instruct" },
  "run":     { "id": "…", "context": { "policy": "fs-isac", "midojo_suite": "weather" } },
  "params":  { "effective": { "asr_ceiling": 0.1 }, "overrides": {} },
  "bindings": { "agent_asr": { "type": "scalar", "ref": "midojo.weather/attack_success_rate", "status": "resolved", "value": 0.333, "direction": "lower_is_better" } },
  "viz": [ { "id": "attack-matrix", "type": "heatmap", "data": "attack_matrix" } ],
  "warnings": [],
  "markdown": "…rendered body…"
}
```

Source digests tie each number in the report to the exact input file that produced it, so the evidence chain survives a report that combines three tools.

## 12. Conformance

[`conformance/`](conformance/README.md) holds 34 cases (the first 25 below, then JSONL, box plot, HTML and DOCX output and chart-limit cases): the two examples, the earlier negative tests (unguarded comparison, `__class__` access, function calls, radar on a matrix, template syntax in a fence, YAML aliases, locked params, missing required binding, untrusted-data escaping, viz in a loop, missing front matter), and new cases for the decoupling (sanitized metric names, cross-evaluation wildcards, duplicate evaluation ids, opaque host namespaces, top-level typos, N/A semantics, wrong fence name, direction conflicts, mixed-polarity radar from bundle data, built-in redeclaration, run identity). A Go implementation in EvalHub and a Python one in ASAGO are interchangeable when both pass.

## 13. Design decisions

| Decision | Rationale |
|---|---|
| Single `.md` file with front matter | Matches how authors write; previews natively; established conventions |
| Core namespace `reportspec:` plus opaque host namespaces | The same file renders on any host; host settings can't leak into the core or into `meta.*` |
| Bind to a ResultsBundle, never to a native format | Decoupling happens once per source in an adapter, not once per spec; one report can combine EvalHub and ASAGO data |
| `<evaluation>/<metric>` references, wildcard series | The EvalHub example's bindings shrank from 78 lines of JSONPath to 31 lines of references (comments and blanks excluded); Garak's flat `<probe>_asr` keys no longer need listing |
| `records` row sets in the bundle | MiDojo pairs and Policy Mapper risks are naturally tabular; matrices come straight from them |
| Verdicts come from producers, never from the renderer | A renderer that recomputes pass/fail would duplicate, and drift from, EvalHub pass criteria |
| `direction` carried by the bundle, overridable in the spec | Polarity is stated once by the tool that knows it |
| Restricted Jinja-like subset defined by the spec | A documented contract enforced by an AST allowlist, not by trusting the sandbox; smaller SSTI surface |
| Fenced YAML viz blocks | Statically checkable; degrade gracefully |
| Missing values printable but never comparable | Prevents a silent PASS on missing or N/A data |
| Conformance suite as part of the spec | Two independent implementations need an executable definition of "same behavior" |

## 14. Open questions

1. **Where the spec lives.** In `eval-hub`, in `asago-ai`, or in a neutral repo that both depend on (spec, schemas, conformance). A neutral home fits ASAGO's vendor-neutral charter. The EvalEval Coalition, an ASAGO founding partner focused on evaluation practice, is a possible steward. Recommended: a standalone repo under `asago-ai` with EvalHub maintainers as co-owners, decided before either project ships an implementation.
2. **Who owns adapters.** The host (EvalHub owns `evalhub-job`), or the tool (MiDojo ships its own adapter and emits a bundle directly). Recommended: tools emit bundles natively over time; host adapters cover what exists today.
3. **How hosts reach the renderer.** Decided 2026-10-23: one standalone Python 3.13+ renderer, decoupled from the EvalHub server and shared with ASAGO. Still open: a FastAPI service, the Python package and CLI, or both, and where EvalHub's spec registry lives (see the EvalHub profile).
4. **MLflow adapter scope.** MLflow has no per-benchmark threshold or pass/fail for EvalHub runs, and drops string and boolean metrics. Proposed: MLflow supplies metrics and run history; verdicts come from the EvalHub job. See the EvalHub profile.
5. **Cross-run comparison** (baseline vs. candidate, trends). The bundle would gain `runs: {name: bundle}` and references a run prefix (`baseline:bbq/accuracy_amb`). v1 is single-run.
6. **Viz blocks inside loops.** `repeat_for: <table binding>` on the block is recommended over allowing blocks in `{% for %}`.
7. **Breakdown data never reaches EvalHub's server.** Confidence intervals, `num_samples` and Garak's per-probe metadata are dropped in SDK `report_results`. With `records` in the bundle there is now a place to put them; the SDK and server still need to keep them.
8. **Render limits** (timeout, output size, loop iterations). Needs each host's threat model.
9. **Value formatting locale** for `percent`/`number` in non-`en` reports.
10. **ASAGO scenario and artifact outputs.** Scenario Generator and Artifact Generator outputs could get adapters (scenario coverage per risk), linking a report's risks to the tests that exercised them.

## Verified against the reference implementation (2026-10-23)

- `conformance/`: 34/34. Both new examples and the two older ones render to PDF; the showcase renders to HTML (checked in Chrome) and to a 6-page Letter PDF with embedded fonts and selectable chart text.
- **Containers (Fedora 42 with Python 3.13.13 and Fedora 43 with Python 3.14.8, built and run on aarch64):** 34/34 with `--network none --read-only --user 1234:0`. The showcase PDF has 6 pages and `pdffonts` lists only Red Hat Text (Regular, Italic, Semi-Bold, Bold) and Red Hat Mono. After masking the `generated` timestamp, the HTML is byte-identical across both images, repeat runs and the macOS output; the PDF text is identical and pages 2 to 5 are pixel-identical on all three, with pages 1 and 6 differing only in the timestamp lines. The pandoc versions differ (3.1.11 on Fedora 42, 3.6.4 on Fedora 43) and both pass the DOCX cases. Only aarch64 was run; x86_64 is untested.
- Rendering was run under a macOS deny-network sandbox and succeeded, so it needs no network. A chart spec with an external data URL is refused when `allowed_base_urls=[]` is passed; **`vl-convert` allows it by default**, so every host must pass that argument.
- Looking at the rendered pages (Visual QA) found defects that rendering without errors did not: the stock Vega radar draws N/A as zero; the Vega gradient legend does not paint in WeasyPrint's SVG renderer; Altair invents axis titles ("value, t"); value labels collide with threshold lines. All are fixed and listed in [VISUAL-QA.md](VISUAL-QA.md).
- Not verified: interactive HTML (`vega-embed`), CJK labels, DOCX in real Word (only Quick Look and XML checks), x86_64 containers.

## Verified against the reference implementation (2026-10-20)

- Both examples validate. The EvalHub example renders from one job, and the ASAGO example renders from three native inputs.
- `conformance/`: 25/25 cases pass.
- Fixture provenance: the EvalHub job follows `api.EvaluationJobResource` on eval-hub `05ec246`. The MiDojo results reproduce the 18-pair weather run in the MiDojo README (`337470f`): utility 94.4%, attack success 33.3%. The Policy Mapper extraction is trimmed from the real `fs-isac` example in asago-examples `b79020d` (49 risks). EvalHub metric values are made up; ASAGO values are the published examples.
- Two bugs were found and fixed while writing the cases: an `is available` test used directly as an `if` condition wasn't recognized as a guard, and `*/metric` included evaluations without that metric as empty rows. A third was found while checking the evidence manifest: run fields were merged from different sources.

---

## License

Apache-2.0 (see [LICENSE](LICENSE)). The fonts in `src/reportspec/fonts/` (SIL OFL 1.1) and the icons in `src/reportspec/icons/` (CC BY 4.0) keep their own licenses; [NOTICE](NOTICE) lists them with the provenance of the example inputs.
