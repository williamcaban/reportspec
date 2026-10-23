# Results, adapters and bindings

How native results become a ResultsBundle, and how a template refers to the values in it.

## The ResultsBundle

The bundle is a small, flat model of "what was evaluated, how, and with what result". The full schema is [`results-bundle-v1alpha1.schema.json`](../src/reportspec/schemas/results-bundle-v1alpha1.schema.json).

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

**Adapters in the reference implementation**, with mapping details in the [host pages](hosts/README.md):

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

## Bindings: the data contract (`reportspec.bindings`)

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
