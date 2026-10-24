# Status, verification and open questions

ReportSpec is a v1alpha1 proof of concept (POC), not a final or adopted design. This page records what has been checked and what is still undecided.

## Verified on 2026-10-24: graph, bundle and parallel charts

Checked on macOS with Python 3.13.15 and `vl-convert` 1.9.0, not yet in the containers or in CI:

- `conformance/`: 46/46, including 12 new cases (35 to 46) for the three chart types. `pytest`: 91 passed, 4 skipped (the PDF tests, because Pango cannot be loaded inside the pytest process on this Mac; they run in CI). Four of the 19 new tests were mutation-checked: breaking the force-layout field reference, the fit to the frame, the axis flip or the Vega error handling each fails the matching test.
- The example report [`policy-coverage`](../examples/policy-coverage.report.md) renders to HTML and to a 4-page Letter PDF, whose `pdffonts` lists only Red Hat fonts. All three figures were looked at in the PDF, not only rendered without error.
- Found by looking and by stress tests, not by a failed render: Vega's force layout has no bounds and spilled a 25-node graph 260 px outside a 680 px frame, so the layout runs first, is read back from the scenegraph and is fitted to the frame (the 80-node limit stays inside it); a force with a wrong field reference draws every node at (0, 0) without an error; `linkpath` parameters are field names unless wrapped in `expr`, and inside `expr` the row is `datum.datum`; the JSONL keys `label` and `source` are reserved, so a link table with a `source` column drew nothing (the chart now says "No links to draw: 15 not drawable" instead of showing a blank).
- Determinism: the same payload gives a byte-identical SVG in repeat runs and in separate processes on this machine. Not checked across platforms or `vl-convert` versions.
- Not verified: the containers and CI with these examples (CI now renders the example to PDF and audits its fonts), the HTML in a browser, DOCX in real Word, graphs of 30 to 80 nodes beyond the generated ones (an 80-node random graph is a hairball, as expected; the limit is a ceiling, not a promise of legibility), CJK labels, label collisions in dense graphs.

## Verified on 2026-10-23

- `conformance/`: 34/34. Both new examples and the two older ones render to PDF; the showcase renders to HTML (checked in Chrome) and to a 6-page Letter PDF with embedded fonts and selectable chart text.
- **Containers (Fedora 42 with Python 3.13.13 and Fedora 43 with Python 3.14.8, built and run on aarch64):** 34/34 with `--network none --read-only --user 1234:0`. The showcase PDF has 6 pages and `pdffonts` lists only Red Hat Text (Regular, Italic, Semi-Bold, Bold) and Red Hat Mono. After masking the `generated` timestamp, the HTML is byte-identical across both images, repeat runs and the macOS output; the PDF text is identical and pages 2 to 5 are pixel-identical on all three, with pages 1 and 6 differing only in the timestamp lines. The pandoc versions differ (3.1.11 on Fedora 42, 3.6.4 on Fedora 43) and both pass the DOCX cases. Only aarch64 was run; x86_64 is untested.
- Rendering was run under a macOS deny-network sandbox and succeeded, so it needs no network. A chart spec with an external data URL is refused when `allowed_base_urls=[]` is passed; **`vl-convert` allows it by default**, so every host must pass that argument.
- Looking at the rendered pages (Visual QA) found defects that rendering without errors did not: the stock Vega radar draws N/A as zero; the Vega gradient legend does not paint in WeasyPrint's SVG renderer; Altair invents axis titles ("value, t"); value labels collide with threshold lines. All are fixed and listed in [VISUAL-QA.md](../VISUAL-QA.md).
- Not verified: interactive HTML (`vega-embed`), CJK labels, DOCX in real Word (only Quick Look and XML checks), x86_64 containers.

## Verified on 2026-10-20

- Both examples validate. The EvalHub example renders from one job, and the ASAGO example renders from three native inputs.
- `conformance/`: 25/25 cases pass.
- Fixture provenance: the EvalHub job follows `api.EvaluationJobResource` on eval-hub `05ec246`. The MiDojo results reproduce the 18-pair weather run in the MiDojo README (`337470f`): utility 94.4%, attack success 33.3%. The Policy Mapper extraction is trimmed from the real `fs-isac` example in asago-examples `b79020d` (49 risks). EvalHub metric values are made up; ASAGO values are the published examples.
- Two bugs were found and fixed while writing the cases: an `is available` test used directly as an `if` condition wasn't recognized as a guard, and `*/metric` included evaluations without that metric as empty rows. A third was found while checking the evidence manifest: run fields were merged from different sources.

## Open questions

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
