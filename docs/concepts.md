# Concepts and design

Why ReportSpec exists, how the layers fit together, and the decisions behind them.

## Why one spec for two projects

Both projects need the same thing: turn evaluation results into a document an auditor, a CISO or a developer can read and trust.

- **EvalHub** has four RFEs for it (API, viz blocks, CLI, dashboard) and no implementation yet.
- **ASAGO** components each hand-build their own report today. The Policy Mapper ships `risk-extraction.html`, made by injecting JSON into an HTML template (`__REPORT_DATA__`). MiDojo prints a terminal table and writes `results.json`. ADR-0001 says report generation "belong[s] in a separate ADR".
- ASAGO's public architecture runs evaluations and red teaming **on EvalHub**, so an ASAGO report usually contains EvalHub results anyway.

Two template languages for overlapping reports would split authors, double the security review of the template sandbox, and make a report that mixes policy risks with benchmark results impossible to write once. An earlier draft was EvalHub-specific in three places. This version removes all three:

| Coupling in the earlier draft | Now |
|---|---|
| `evalhub:` namespace held the bindings | Core namespace `reportspec:`; host settings go in an optional host namespace (`evalhub:`, `asago:`) |
| JSONPath into the EvalHub job (`$.job.results.benchmarks[?@.id=='bbq'].metrics.accuracy_amb`) | References into a host-neutral **ResultsBundle** (`bbq/accuracy_amb`); each host supplies adapters from its native format |
| `report.model_name`, `report.collection_id`, ```` ```evalhub-viz ```` | `subject.*`, `run.*`, `run.context.*`; ```` ```reportspec-viz ```` |

## Architecture: three layers, one seam

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

## File anatomy

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

## Design decisions

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
