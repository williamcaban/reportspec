# ReportSpec host profile: ASAGO

**Status:** DRAFT, a proposal from a proof of concept for the ASAGO community. ASAGO has not adopted it · **Docs:** [index](../README.md) · **Implemented:** the `midojo` and `asago-risk-extraction` adapters, and the standalone [render service](../service.md) (not specific to ASAGO). **Proposals, not implemented:** an ASAGO-server form of that API, and how ReportSpec relates to the ASAGO-ADR-0002 draft · **Related:** [ASAGO-ADR-0001](https://github.com/asago-ai/architecture-decision-records/blob/main/architecture-decision-records/ASAGO-ADR-0001-asago-server.md) (server; leaves report generation to a separate ADR) and the [ASAGO-ADR-0002 draft "Reporting"](https://github.com/asago-ai/architecture-decision-records/pull/2) (ASAGO's own design for a report generator, an open pull request)

This profile covers how ASAGO would host ReportSpec: its adapters, how its stateless API fits ADR-0001, how it compares with the ADR-0002 draft, and its host namespace. Repos were checked on 2026-10-20: `midojo` 337470f, `asago-examples` b79020d, `architecture-decision-records` main. The ADR-0002 draft (pull request 2, open since 2026-10-16) was read on 2026-10-24; it is a draft and may change. Nobody on the ASAGO side has reviewed this page.

## Why ASAGO needs it

ASAGO's goal is a traceable chain from policy to production: policy → risks → scenarios → tests → evidence → controls. Today each step makes its own report:

| Component | Report today |
|---|---|
| Policy Mapper | `risk-extraction.html`, made by injecting JSON into an HTML template (`__REPORT_DATA__`), plus an annotation view |
| MiDojo | Rich terminal table; `results.json`; evaluation records on the running control-plane server |
| Garak via EvalHub | EvalHub results (and an EvalHub ReportSpec report, once that ships) |

No component can produce the document a CISO or risk officer asks for: "these are the risks in our policy, this is how the agent did against them, and here is the evidence". A shared spec makes that one file ([`agent-redteam.report.md`](../../examples/agent-redteam.report.md)), rendered from all three outputs.

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

**What exists.** The standalone [render service](../service.md) (`reportspec serve`) is not tied to ASAGO. Its endpoints are `POST /v1/validate`, `/v1/bundle` and `/v1/render`. A request carries the template and the results as JSON; the response is the document itself (PDF, HTML, DOCX or Markdown), with the template's digest in a header; `format: json` returns the evidence manifest. A result input can be a native document, such as a Policy Mapper `risk-extraction.json` or a MiDojo `results.json`, and the adapter is detected. It returns documents, not ADR-0001 envelopes.

**What does not exist.** An ASAGO-server form of it: an endpoint inside the Asago Server, taking ADR-0001 envelopes and returning one. Whether that is built, and with what request shape, depends on the ADR-0002 discussion below.

How the existing service lines up with ADR-0001:

| ADR-0001 rule | How the service meets it |
|---|---|
| Stateless, no retained run state | Template and results arrive in each call, and nothing is stored. Details of an unexpected failure go to the server log |
| Components independently usable | `/v1/bundle` and `/v1/render` need no prior call to another component; the renderer is also a Python package and a command line |
| Versioned contracts, separate from the component release | `reportspec/v1alpha1`, `results-bundle/v1alpha1` and `evidence-manifest/v1alpha1` are versioned on their own. Payload schema versions of the ASAGO components are not checked (see below) |
| Invalid input or unsupported version → 4xx | Template errors and unknown adapters return 4xx (`invalid_request`, `unknown_adapter`, `invalid_input`), with reasons that contain no result data. An unsupported *payload* version is not detected |
| Evaluation execution is out of scope | The renderer only reads results, including EvalHub job JSON the caller fetched |

## Host namespace: `asago:`

```yaml
asago:
  pipeline: [policy-mapper, midojo, evalhub]   # illustrative: which component outputs the report expects
```

Nothing in the core depends on it. A caller or UI can use it to check that a pipeline produced every input before calling `/v1/render`.

## The ASAGO-ADR-0002 draft

ADR-0001 left report generation to a separate ADR, and ASAGO has started one: [ASAGO-ADR-0002 "Reporting"](https://github.com/asago-ai/architecture-decision-records/pull/2). The draft defines a stateless **Report Generator**, released as a versioned Python package and exposed through the Asago Server. It takes an ordered list of versioned component envelopes (Policy Mapper, Scenario Generator, Artifact Generator), validates their payload schema versions, and returns a PDF, HTML or Markdown report, standalone for one envelope or combined for several. Its content is decided by component-specific handlers in code, with a PatternFly HTML template for presentation.

ReportSpec is a different way to meet the same goals, not an extension of that design: the content comes from a Markdown template bound to a results bundle, and the per-component logic shrinks to an adapter. The table compares them as the draft stands. "Gap" means ReportSpec does not do it today.

| The draft (or its first review) asks for | ReportSpec today |
|---|---|
| A versioned Python package that components can import for their standalone report | A package and CLI exist, but there is no release and no documented public Python API. **Gap** |
| PDF, HTML or Markdown, chosen per request | Also DOCX and JSON. One format per request |
| Component-aware handling of Policy Mapper, Scenario Generator and Artifact Generator payloads | An adapter for Policy Mapper `risk-extraction` 0.3. **Gap:** none for Scenario Generator or Artifact Generator, whose payloads I have not seen. The `midojo` adapter covers a component the draft does not list |
| Envelopes with an envelope version and a payload schema version; reject the whole request on an unsupported one | Adapters are detected by the shape of the document. The Policy Mapper adapter records the payload `version` but does not check it. **Gap:** no envelope adapter and no compatibility matrix |
| A combined report across steps, joined by the identifiers payloads declare, reporting references that do not resolve | Several inputs combine into one bundle. **Gap:** bindings cannot join one record set to another, so an adapter would have to emit joined (denormalized) records. `graph` and `bundle` charts that draw links between records and count unresolved ends are in review ([#9](https://github.com/williamcaban/reportspec/pull/9)) |
| Everything a report renders travels inline in the payload, so the generator needs no files or network | True of ReportSpec: adapters read only what the request carries, and rendering fetches nothing |
| Stateless; nothing persisted | Stateless. Check what the server log can contain before promising "never logged" |
| Single-file HTML that reads offline; online extras only on request | HTML is one file with inline charts and fonts and no network use. Interactive extras are on the [roadmap](../roadmap.md) |
| PDF without a heavy dependency | No headless browser: WeasyPrint and Pango for PDF, pandoc only for DOCX, and `/v1/capabilities` reports which formats a server can produce |
| HTML that conforms to PatternFly, with replaceable presentation templates | Not done: its own CSS and the Red Hat fonts, no PatternFly tokens. The template is the report spec, which sets content and layout together; there is no separate presentation theme. **Gap** |
| A size limit or an attachment option for large reports | A request size limit (5 MB by default) and attachment responses |
| Templates are trusted assets | The service takes a template in every request, a larger attack surface. An ASAGO endpoint should serve templates by name from its own configuration, or require authentication for a template in the request |
| Not a generic JSON-to-report converter | Adapters accept only known formats, but the JSONL and `bundle` adapters are generic by design, so that a new producer needs no code |

Two parts of the draft are outside what this repository can address: the Asago Server endpoint, and the choice of PatternFly.

If ASAGO prefers to build on ReportSpec, the changes the ADR text would need are small: name the renderer, say that adapters (not handlers) carry the per-component logic and the compatibility matrix, and keep the draft's rules on statelessness, inline payloads and rejecting unsupported versions. Whether to do that is ASAGO's decision.

**Open:** where the shared spec repository lives ([open question 1](../status.md#open-questions)), whether MiDojo and the Policy Mapper emit bundles natively ([open question 2](../status.md#open-questions)), and whether ASAGO wants templates in code (the draft) or in Markdown (ReportSpec).
