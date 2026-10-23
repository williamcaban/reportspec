# ReportSpec host profile: EvalHub

**Status:** DRAFT · **Core spec:** [../README.md](../README.md)

This profile covers what EvalHub adds around the portable core: its host namespace, its adapters, and its API. A spec that uses only the core renders the same on EvalHub and on ASAGO.

## Host namespace: `evalhub:`

```yaml
evalhub:
  applies_to:                      # advisory: which runs the dashboard offers this spec for
    collections: [safety-and-fairness]
    providers: [lm_evaluation_harness, garak]
  strict_applies_to: false         # true: reject runs outside applies_to instead of warning
```

The core ignores this block, and ASAGO never reads it. Applicability is a host concern because "collection" is an EvalHub concept.

## Adapter: `evalhub-job`

Input: `GET /api/v1/evaluations/jobs/{id}` (`api.EvaluationJobResource`), bare or wrapped as `{job: …}`. Checked against eval-hub `main` 05ec246 and the SDK on `main`, 2026-10-20.

| Job field | Bundle field | Notes |
|---|---|---|
| `model.name`, `model.url` | `subject {kind: model, name, uri}` | |
| `resource.id`, `resource.created_at` | `run.id`, `run.started_at`; `run.producer.name = evalhub` | |
| `collection.id`, `name`, `resource.tenant` | `run.context.collection_id`, `job_name`, `tenant` | Templates use `{{ run.context.collection_id }}` |
| `results.test {score, threshold, pass}` | `verdict` → built-ins `overall_*` | Collection-level pass criteria, computed by the server |
| `results.benchmarks[]` | one `evaluations[]` entry each, `id` = benchmark id, `source` = `provider_id` | |
| `benchmarks[].metrics` (flat `{name: value}`) | `metrics {name: {value, type}}` | `type` from `metrics_schema` when present |
| `benchmarks[].test {primary_score, primary_score_metric, threshold, pass}` | `evaluations[].verdict` | Feeds the built-in `evaluations` table |
| `artifacts['evalhub.env_card']`, `['evalhub.eval_card']` | `attributes.env_card`, `attributes.eval_card` | Dotted artifact keys become plain names so `field:` paths stay simple |
| `artifacts.oci_reference`, `oci_digest`, other artifacts | `attributes.oci_reference`, `oci_digest`, `attributes.artifacts` | |
| `mlflow_run_id`, `logs_path`, `benchmark_index` | `attributes.*` | |

**Direction.** The job JSON carries no polarity. The server-side adapter should fill `metrics[name].direction` from the provider config (`primary_score.lower_is_better` in `config/providers/*.yaml`), so specs stop restating it. The reference adapter can't see provider configs and leaves direction unset, which is why the example declares it on `attack_success_rate`.

**What the server doesn't store**, and so no adapter can produce:

| Lost where | What | Effect |
|---|---|---|
| SDK `report_results` (`callbacks.py`) flattens to `metrics[metric_name] = metric_value` | `confidence_interval`, `num_samples`, per-result `metadata` | No error bars; no per-sample tables |
| Garak adapter puts per-probe detail in `EvaluationResult.metadata` | Detector scores, AVID taxonomy, intent breakdown | No probe × detector heatmap. Per-probe ASR survives only as flat `<probe>_asr` metric keys, which the `owasp_llm_top10/*_asr` wildcard picks up |
| Server `EvaluationCard` (`pkg/cards/from_job.go`) | Derived from the job, not in OpenAPI | Nothing to bind beyond the job itself |

The bundle's `records` gives this data a destination. Keeping it is an SDK and server change, a dependency for the heatmap use case.

## Adapter: `mlflow` (planned)

From the SDK's `adapter/mlflow.py` and `callbacks.py` on `main`:

| MLflow | Bundle |
|---|---|
| One run per benchmark, `run_name = {job_id}_{benchmark_index}`, in experiment `job_spec.experiment_name` | One evaluation per run, `id` from param `benchmark_id` |
| Params `benchmark_id`, `provider_id`, `model_name`, `num_examples_evaluated`, `duration_seconds` | `id`, `source`, `subject.name`, `attributes.*` |
| Params `env_card.*`, `eval_card.*` (flattened; `key_packages` as JSON) | `attributes.env_card.*`, `attributes.eval_card.*` |
| Metrics, **numeric only**, keys passed through `sanitize_metric_key_for_api` (`acc,none` → `acc_none`), plus `overall_score` | `metrics`, with the original name unknown. References still match because matching falls back to the sanitized form (conformance case 15) |
| Tags from job tags | `run.context.*` |
| **No** threshold, per-benchmark pass, or collection verdict | `verdict` absent → `overall_pass` and the `evaluations` table's `pass` column print the missing marker |

Recommendation: render compliance reports from the EvalHub job (the system of record for verdicts) and use MLflow for metrics and **history across runs**, which is what it's good at and what trend charts need (core open question 5). The ASAGO Policy Mapper also logs to MLflow, so one `mlflow` adapter serves both hosts.

## API, CLI and CRD

The `.md` file is the canonical, digest-able artifact; wrappers carry it unchanged.

```text
POST /api/v1/reportspecs        Content-Type: text/markdown   (body = the file; validated on registration)
GET  /api/v1/reportspecs/{name}?version=1.1.0  → text/markdown | application/json (parsed front matter + source)
POST /api/v1/reports            { reportspec: name@version | inline source, run_id, formats, params,
                                  extra_inputs: [ResultsBundle] }      # optional: e.g. an ASAGO risk extraction
```

`extra_inputs` lets EvalHub render a mixed report, such as the core example `agent-redteam.report.md`, when the caller supplies the ASAGO part as a bundle. EvalHub doesn't need to understand MiDojo or Policy Mapper formats.

```yaml
# Optional GitOps form if engineering chooses a CRD
apiVersion: trustyai.opendatahub.io/v1alpha1
kind: ReportSpec
metadata: { name: safety-compliance }
spec:
  source: |
    ---
    title: Safety & Fairness Compliance Brief
    ...
```

CLI: `evalhub reportspec validate <file>` (offline), `evalhub report render -f <file> --run <id> [--input bundle.json] --dry-run`, `--param name=value` (rejected when `overridable: false`).

## Open questions specific to EvalHub

1. **Render location: decided (2026-10-23).** A standalone Python 3.13+ renderer, decoupled from the EvalHub server and shared with ASAGO: one implementation to secure instead of two. The EvalHub server does not port the template engine. How EvalHub reaches it (REST service, the SDK's `render_report`, or the CLI) is still open.
1a. **Spec registry location.** The sketch above puts `POST /api/v1/reportspecs` and an optional CRD in the EvalHub server. With an external renderer, either the server keeps storing the YAML and passes it to the renderer with each call, or the registry moves to the renderer service. The first keeps EvalHub's RFE-2755 scope and the second matches ASAGO's stateless model.
2. **Direction source of truth.** Filling direction from provider config in the server adapter (recommended), or adding `lower_is_better` to `metrics_schema` so it travels with results.
3. **Keeping breakdown data** (CIs, per-probe metadata) as `records`. This needs the SDK `report_results` change described above.
