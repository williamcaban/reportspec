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

PDF output needs Pango (`dnf install pango`, `brew install pango`) and DOCX output needs `pandoc`. If you would rather not install anything, use the [container](#run-it-in-a-container).

## Run it

ReportSpec runs in two ways. Both give the same output.

### Command line

Clone the repository for the examples, then render a report from one Markdown file and one JSONL file:

```bash
git clone https://github.com/williamcaban/reportspec && cd reportspec
reportspec render examples/model-release.report.md \
  --input examples/inputs/model-release.jsonl --format pdf -o out/model-release.pdf
```

Use `--format html` or `--format docx` for the other outputs. Each run also writes `<name>.manifest.json`, the evidence record. Other commands:

```bash
reportspec validate examples/safety-compliance.report.md        # check a template without rendering
reportspec bundle --input examples/inputs/midojo-results.json   # show the normalized results
reportspec conformance conformance/                             # run the 34 conformance cases
```

All options are in the [command line reference](docs/cli.md). From a clone you can also use `uv run reportspec …`.

### Run it in a container

The image carries everything (Pango, pandoc, fonts, locked dependencies), runs offline and read-only, and needs no Python on your machine. There is no published image yet, so build it once from a clone:

```bash
podman build -t reportspec .                       # Fedora 43, Python 3.14. Add --build-arg PY=313 for Fedora 42, Python 3.13
```

Docker works the same way: `docker build -f Containerfile -t reportspec .`. Then run any command from above after the image name. The examples are inside the image:

```bash
podman run --rm reportspec conformance conformance
```

To render your own files, mount a folder and write the output there:

```bash
mkdir -p work && cp my.report.md results.jsonl work/
podman run --rm --network none --read-only --tmpfs /tmp -v "$PWD/work:/work:Z" reportspec \
  render /work/my.report.md --input /work/results.jsonl --format pdf -o /work/report.pdf
```

[Running in a container](docs/container.md) has the details: Docker and Linux file ownership, the build arguments, OpenShift, and what is inside the image.

## Example output

Rendered samples checked into the repository, so you can see the result without installing anything:

| Report | Template and results | What it shows |
|---|---|---|
| [Model release readiness (PDF)](examples/output/model-release.pdf), [HTML](examples/output/model-release.html), [DOCX](examples/output/model-release.docx) | [template](examples/model-release.report.md), [JSONL](examples/inputs/model-release.jsonl) | Every chart type, from one JSONL file. Synthetic data |
| [Safety compliance brief (PDF)](examples/output/safety-compliance.pdf) | [template](examples/safety-compliance.report.md), [EvalHub job](examples/inputs/evalhub-job.json) | One EvalHub collection run for a compliance reader |
| [Agent red-team report (PDF)](examples/output/agent-redteam.pdf), [DOCX](examples/output/agent-redteam.docx) | [template](examples/agent-redteam.report.md), [three native inputs](examples/inputs/) | Policy Mapper risks, MiDojo red team and EvalHub results in one report |
| [Quickstart (PDF)](examples/output/quickstart.pdf) | [template](examples/quickstart.report.md), [JSONL](examples/inputs/quickstart.jsonl) | The smallest useful report, used in the [tutorial](docs/tutorial.md) |

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

**Get started**
- [Tutorial: your first report](docs/tutorial.md): a JSONL file and a template to a rendered report, step by step
- [Writing JSONL results](docs/jsonl.md): how to produce a results file for your template
- [Parameters](docs/parameters.md): declare, lock, use and override report settings

**Reference**
- [Writing a report template](docs/authoring.md): front matter, template language, missing data, charts
- [Results, adapters and bindings](docs/results-and-bindings.md): how a template refers to results
- [Command line](docs/cli.md): commands, options, exit codes
- [Running in a container](docs/container.md): build and run the image
- [Output and conformance](docs/output-and-conformance.md): the evidence manifest and the 34 conformance cases

**Background**
- [Concepts and design](docs/concepts.md): why it exists and how the layers fit
- [Hosts](docs/hosts/README.md): using it from [EvalHub](docs/hosts/evalhub.md) and [ASAGO](docs/hosts/asago.md)

**Project**
- [Roadmap](docs/roadmap.md): what is planned, what is verified, open questions and quality requirements

From a clone, `uv run pytest` runs the tests.

## License

Apache-2.0 (see [LICENSE](LICENSE)). The fonts in `src/reportspec/fonts/` (SIL OFL 1.1) and the icons in `src/reportspec/icons/` (CC BY 4.0) keep their own licenses; [NOTICE](NOTICE) lists them with the provenance of the example inputs.
