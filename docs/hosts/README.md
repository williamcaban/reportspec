# Hosts

A host is a product that runs ReportSpec. Any host can also call the standalone [render service](../service.md), which is not tied to a particular one. The core spec is host-neutral; each host adds adapters, a namespace and an API. Host pages: [EvalHub](evalhub.md), [ASAGO](asago.md).

## What a host must provide

A conforming host implements five things. Everything else, such as storage, auth, UI and PDF engine, is its own choice.

1. **Validate** a `.report.md` with the core rules, plus its own host namespace if it defines one.
2. **Adapt** its native results into a ResultsBundle, at least one adapter.
3. **Render** Markdown, plus any of HTML/PDF/JSON the host supports, with core semantics.
4. **Emit the evidence manifest** ([output and conformance](../output-and-conformance.md)) next to every rendered report.
5. **Pass the conformance suite.**

| | EvalHub | ASAGO |
|---|---|---|
| Spec storage | Server registry (`POST /api/v1/reportspecs`), optional CRD | None: the caller supplies the spec in each request (ADR-0001: stateless) |
| Adapters | `evalhub-job`, `mlflow` | `midojo`, `asago-risk-extraction`, `bundle`; reuses `evalhub-job` for Garak runs on EvalHub |
| Host namespace | `evalhub.applies_to` (collections, providers) | `asago.pipeline` (illustrative) |
| Details | [evalhub.md](evalhub.md) | [asago.md](asago.md) |
