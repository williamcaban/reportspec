# ReportSpec

Write a report as one Markdown file, hand it results as JSON or JSONL, and get a Markdown, JSON, HTML, PDF or DOCX report with charts, plus an evidence manifest that ties every number to the input that produced it.

ReportSpec is built for AI evaluation evidence: [EvalHub](docs/hosts/evalhub.md) benchmark runs, [ASAGO](docs/hosts/asago.md) red-team and policy-risk results, or any tool that can print JSONL. The same template renders the same report on every host.

**Status:** v1alpha1, a draft. The reference implementation is Python 3.13+. Field names and the API may change.

- **Portable.** Templates bind to a host-neutral results model, never to a tool's native format.
- **Safe with untrusted data.** Results can carry hostile text, so every value is escaped and the template language is a small allowlisted subset.
- **Honest about gaps.** Missing data prints as "data unavailable" and can never be compared, so a metric that was never measured cannot show as PASS.
- **Self-contained.** HTML is one file with inline charts and fonts; rendering needs no network.

## Install

Python 3.13 or later. Not on PyPI yet; install from GitHub:

```bash
uv tool install git+https://github.com/williamcaban/reportspec     # puts `reportspec` on your PATH
uvx --from git+https://github.com/williamcaban/reportspec reportspec --version   # or run once, nothing installed
pip install git+https://github.com/williamcaban/reportspec          # or plain pip, ideally in a virtualenv
```

PDF output needs Pango (`dnf install pango`, `brew install pango`) and DOCX output needs `pandoc`. A container image with both is described in [docs/container.md](docs/container.md).

## Quick start

Clone the repository for the examples, then render a showcase report from one Markdown file and one JSONL file:

```bash
git clone https://github.com/williamcaban/reportspec && cd reportspec
reportspec render examples/model-release.report.md \
  --input examples/inputs/model-release.jsonl --format pdf -o out/model-release.pdf
```

Use `--format html` or `--format docx` for the other outputs. Each run also writes `<name>.manifest.json`, the evidence record. Rendered samples are checked in under [`examples/output/`](examples/output/) if you want to look first.

Other commands:

```bash
reportspec validate examples/safety-compliance.report.md   # check a template without rendering
reportspec bundle --input examples/inputs/midojo-results.json   # show the normalized results
reportspec conformance conformance/                        # run the 34 conformance cases
```

## What a template looks like

A template is Markdown with YAML front matter, a restricted `{{ }}` template language, and a few `reportspec-viz` fences. A chart is a type, a data binding and a few options:

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

Results come in as JSONL, one object per line:

```jsonl
{"subject": {"kind": "model", "name": "demo-7b"}, "run": {"id": "run-42"}}
{"evaluation": "capability", "metric": "mmlu", "value": 0.71, "direction": "higher_is_better"}
{"evaluation": "safety", "metric": "hallucination_probe", "value": null}
```

Charts, tables and cards are drawn only from resolved data. Pass/fail marks come from the threshold and direction the author states, or from the producer's verdict. N/A is never plotted as zero. Chart types: `radar`, `radial`, `boxplot`, `bar`, `line`, `heatmap`, `table`, `summary_cards`.

## Documentation

New here? Follow the [tutorial](docs/tutorial.md). Then see [docs/](docs/README.md): [parameters](docs/parameters.md), [JSONL results](docs/jsonl.md), [concepts](docs/concepts.md), [writing a template](docs/authoring.md), [results and bindings](docs/results-and-bindings.md), [command line](docs/cli.md), [output and conformance](docs/output-and-conformance.md), [container](docs/container.md), [hosts](docs/hosts/README.md), [status and open questions](docs/status.md). Chart quality requirements are in [VISUAL-QA.md](VISUAL-QA.md).

From a clone, use `uv run reportspec …` in place of `reportspec …`, and `uv run pytest` to run the tests.

## License

Apache-2.0 (see [LICENSE](LICENSE)). The fonts in `src/reportspec/fonts/` (SIL OFL 1.1) and the icons in `src/reportspec/icons/` (CC BY 4.0) keep their own licenses; [NOTICE](NOTICE) lists them with the provenance of the example inputs.
