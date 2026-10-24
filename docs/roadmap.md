# Roadmap

ReportSpec is a proof of concept (POC) at v1alpha1: not final, not adopted by EvalHub or ASAGO, and without a release. This page lists what is planned, what has been checked, and where to find the open questions and the chart quality requirements. Nothing here is a commitment to a date.

## Planned

| Item | What it adds |
|---|---|
| **Render service hardening** | The [standalone render service](service.md) exists as a proof of concept. Still to do: TLS and real authentication (today: a shared bearer token behind your own gateway), rate limiting, load testing, a long-running job mode for large reports, and a published container image |
| **First release** | A tagged `v0.1.0` and publication on PyPI, so `pip install reportspec` works. Until then, install from GitHub |
| **More diagram types for attack material** | `graph`, `bundle` and `parallel` exist. Not built: a `tree` chart for attack trees (Vega has tree layouts built in), a layered layout for ordered attack flows (Vega has no layered graph layout, so the adapter would compute positions), import of STIX 2.1 Attack Flow files, and showing Gherkin scenarios. The [ASAGO-ADR-0002 draft](https://github.com/asago-ai/architecture-decision-records/pull/2) review asks for these |
| **Interactive HTML** | Hover and tooltips in the HTML report with `vega-embed`. PDF and DOCX stay static |
| **Automated visual QA** | The font audit already runs in CI. Next: golden-image comparison of rendered pages, in a container image pinned by digest. Requirements: [VISUAL-QA.md](../VISUAL-QA.md) |
| **MLflow adapter** | Read metrics and run history from MLflow ([EvalHub page](hosts/evalhub.md#adapter-mlflow-planned)) |
| **Reproducible output** | Honor `SOURCE_DATE_EPOCH` so two renders of the same inputs are byte-identical; today only `generated_at` differs |
| **Base image pin** | Reference the Fedora base image by digest, not tag |
| **WOFF2 fonts** | Smaller HTML (about 60%), once the Red Hat font license allows it |
| **ASAGO-ADR-0002 draft** | ASAGO has its own [draft ADR for a report generator](https://github.com/asago-ai/architecture-decision-records/pull/2). Next: settle how ReportSpec relates to it and what it would need (adapters for the Scenario Generator and Artifact Generator, an envelope adapter, a public Python API). See the [ASAGO page](hosts/asago.md#the-asago-adr-0002-draft) |

## Not yet verified

- Linux x86_64 containers (CI runs on x86_64 now, so this is covered going forward; the manual checks were aarch64)
- Windows
- DOCX in Microsoft Word (checked in Quick Look and by reading the XML)
- CJK and right-to-left labels
- The render service under load, behind a real gateway, and from browsers other than Chromium (the playground was checked in Chromium only)
- Plain `pip install` and `uv tool install` from GitHub (`uvx` and `uv pip` were checked)

## More detail

- [Status and open questions](status.md): what has been verified and by what, plus ten undecided design questions
- [VISUAL-QA.md](../VISUAL-QA.md): what "the chart looks right" means, 21 requirements and how each is checked
- [Hosts](hosts/README.md): proposals for EvalHub and ASAGO that are not implemented
