# ReportSpec host profile: ASAGO

**Status:** DRAFT, a proposal for the ASAGO community · **Core spec:** [../README.md](../README.md) · **Related:** [ASAGO-ADR-0001](https://github.com/asago-ai/architecture-decision-records/blob/main/architecture-decision-records/ASAGO-ADR-0001-asago-server.md) (server; leaves report generation to a separate ADR)

This profile covers how ASAGO would host ReportSpec: its adapters, an API that fits ADR-0001's stateless design, and its host namespace. Repos were checked on 2026-10-20: `midojo` 337470f, `asago-examples` b79020d, `architecture-decision-records` main.

## Why ASAGO needs it

ASAGO's goal is a traceable chain from policy to production: policy → risks → scenarios → tests → evidence → controls. Today each step makes its own report:

| Component | Report today |
|---|---|
| Policy Mapper | `risk-extraction.html`, made by injecting JSON into an HTML template (`__REPORT_DATA__`), plus an annotation view |
| MiDojo | Rich terminal table; `results.json`; evaluation records on the running control-plane server |
| Garak via EvalHub | EvalHub results (and an EvalHub ReportSpec report, once that ships) |

No component can produce the document a CISO or risk officer asks for: "these are the risks in our policy, this is how the agent did against them, and here is the evidence". A shared spec makes that one file ([`agent-redteam.report.md`](../examples/agent-redteam.report.md)), rendered from all three outputs.

## Adapter: `midojo`

Input: `results.json` written by `midojo-run` (`src/midojo/orchestrator.py`): `{run_id, suite_name, utility, security, security_reason}`. The keys of `utility` and `security` are `"<user_task>,<injection_task>"`.

| results.json | Bundle |
|---|---|
| `suite_name` | evaluation `id: midojo.<suite>`, `label: MiDojo <suite>`, `source: midojo`; `run.context.midojo_suite` |
| `run_id` | `run.id`, `run.producer.name = midojo` |
| `utility` | `metrics.utility_rate` (higher is better) over all pairs |
| `security` (`true` = attack succeeded, `null` = payload never reached the agent) | `metrics.attack_success_rate` (lower is better) over **reached pairs only**, as MiDojo's own table computes it; `pairs`, `pairs_attacked`, `pairs_not_reached` |
| per-pair values | `records.pairs[] {user_task, injection_task, task_completed, attack_succeeded, reason}`; `attack_succeeded` is null for N/A |
| none | `verdict {metric: attack_success_rate, score, threshold: null, pass: null}`. MiDojo doesn't judge pass/fail; the report compares against a locked param (`asr_ceiling`) |

With the published 18-pair weather run, this reproduces MiDojo's own figures: utility 94.4% and attack success 33.3%, with 9 N/A pairs. Conformance case 02 checks it.

Possible later additions: the server's per-evaluation records (agent input/output, tool calls, sandbox observations) as more `records` sets, once MiDojo exposes them in a file rather than only on the running control plane.

## Adapter: `asago-risk-extraction`

Input: the Policy Mapper's `risk-extraction.json` (`version: "0.3"`).

| risk-extraction.json | Bundle |
|---|---|
| `eval.policy`, or the first `source_documents` file name | evaluation `id: policy-mapper.<policy>`; `run.context.policy`, `run.context.policy_document` |
| `risks[]` | `records.risks[] {risk_id, risk_name, taxonomy, confidence, grounding, section, page, mitigations}` (mitigations = count) |
| per-taxonomy counts | `records.taxonomies[] {taxonomy, risks, high_confidence}` |
| counts | `metrics.risks_extracted`, `risks_high_confidence`, `taxonomies`, `mitigations_linked` (distinct action ids) |
| `eval` (only when run against a ground-truth annotation) | `metrics.precision`, `recall`, `f1`, `risks_expected`, `risks_matched`; `records.taxonomy_scores`; `verdict {metric: f1, pass: eval.pass}` |
| `metadata.model`, `version` | `attributes.model`, `attributes.schema_version` |
| `chunks`, `llm_calls`, `retrieval_stats`, `token_usage` | dropped. Too large and too internal for a report; candidates for a debug profile |

The Policy Mapper reports undefined precision or recall as `null` "so they can't be mistaken for a genuine 0.0". The core's missing-data rule enforces the same thing in templates.

**Subject.** A risk extraction is about a policy, not about the system under test, so this adapter sets no `subject`. The policy goes into `run.context` instead. The subject comes from whichever input evaluates the system (MiDojo's agent or EvalHub's model), or from a caller-built bundle.

## API: stateless, data in and data out

ADR-0001 makes the ASAGO server stateless: the caller owns orchestration and storage, and each endpoint returns versioned JSON in a light envelope. ReportSpec fits that without change. The spec and the inputs travel in the request, and the evidence manifest comes back.

```text
POST /v1/reportspecs:validate     body: the .report.md (text/markdown)
POST /v1/bundles                  { inputs: [{adapter?, payload}] }            → envelope(ResultsBundle)
POST /v1/reports:render           { spec: "<.report.md>", inputs: [{adapter?, payload}] | bundle,
                                    params: {}, formats: [markdown, html, json] } → envelope(manifest + outputs)
```

Envelope fields are illustrative, following ADR-0001's "separate version metadata for the envelope and payload schema", which "identifies the producer and its component release":

```json
{ "envelope_version": "1", "producer": { "component": "report-renderer", "release": "0.1.0" },
  "payload_schema": "reportspec.evidence-manifest/v1alpha1", "payload": { "manifest_version": "v1alpha1", "…": "…" } }
```

| ADR-0001 rule | How this API meets it |
|---|---|
| Stateless, no retained run state | Spec and inputs arrive in each call; nothing is stored |
| Components independently usable | `bundles` and `reports:render` work without a prior call to another component; the renderer is also a Python package and CLI |
| Versioned contracts, separate from the component release | `reportspec/v1alpha1`, `results-bundle/v1alpha1` and `evidence-manifest/v1alpha1` are versioned on their own |
| Invalid input or unsupported version → 4xx | Spec validation errors and unknown adapters return 4xx, with reasons that contain no result data |
| Evaluation execution is out of scope | The renderer only reads results, including EvalHub job JSON the caller fetched |

## Host namespace: `asago:`

```yaml
asago:
  pipeline: [policy-mapper, midojo, evalhub]   # illustrative: which component outputs the report expects
```

Nothing in the core depends on it. A caller or UI can use it to check that a pipeline produced every input before calling `reports:render`.

## Proposed next step: ASAGO-ADR-0002 "Report generation"

ADR-0001 deliberately deferred this. An ADR in the existing template would cover:

- **What:** adopt ReportSpec as ASAGO's report format; add a stateless render endpoint and Python package.
- **Goals:** one report across components; the same spec renders on EvalHub; evidence manifest with source digests.
- **Non-goals:** storing reports or specs (the caller owns storage); computing verdicts; a dashboard.
- **Alternatives:** keep per-component HTML templates (no cross-component report); an ASAGO-only template language (forks authors and tooling from EvalHub); a BI tool (fails the "no transforms" and offline requirements).
- **Security:** results are untrusted input (agent outputs, injected payloads, policy text); the template sandbox, escaping and conformance cases 05, 06 and 12 apply.
- **Open:** where the shared spec repo lives (core open question 1), and whether MiDojo and the Policy Mapper emit bundles natively (core open question 2).
