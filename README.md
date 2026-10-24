# ReportSpec

Write a report as one Markdown file, hand it results as JSON or JSONL, and get a Markdown, JSON, HTML, PDF or DOCX report with charts, plus an evidence manifest that ties every number to the input that produced it.

ReportSpec is built for AI evaluation evidence: [EvalHub](docs/hosts/evalhub.md) benchmark runs, [ASAGO](docs/hosts/asago.md) red-team and policy-risk results, or any tool that can print JSONL. The same template renders the same report on every host.

> **This is a proof of concept (POC).** It is not the final design and it has not been adopted by EvalHub, ASAGO or any other project; neither project has committed to it. It exists to test whether one Markdown template and one portable results format can serve more than one evaluation product, and to give engineers something concrete to try, criticize and replace. The spec is v1alpha1, so field names, file formats and the command line may change without notice, and there is no release yet. Do not build on it as a stable interface.

- **Portable.** Templates bind to a host-neutral results model, never to a tool's native format.
- **Safe with untrusted data.** Results can carry hostile text, so every value is escaped and the template language is a small allowlisted subset.
- **Honest about gaps.** Missing data prints as "data unavailable" and can never be compared, so a metric that was never measured cannot show as PASS.
- **Self-contained.** HTML is one file with inline charts and fonts; rendering needs no network.

## Three ways to run it

All three run the same renderer and give the same output. Pick the one that fits where you work:

| Way | Use it when | Go to |
|---|---|---|
| **Command line** | You have Python 3.13+ and want to render from a terminal, a script or CI | [Install](#install) and [Command line](#command-line) below; [CLI reference](docs/cli.md) |
| **Container** | You want no Python or system libraries on the machine, or need an offline, read-only run | [Container](#container) below; [full guide](docs/container.md) |
| **HTTP service** (optional) | A program should call an API instead of running a command | [Render service](#http-service-optional) below; [full guide](docs/service.md) |

## Install

Python 3.13 or later. Not on PyPI yet; install from GitHub:

```bash
uv tool install git+https://github.com/williamcaban/reportspec     # puts `reportspec` on your PATH
uvx --from git+https://github.com/williamcaban/reportspec reportspec --version   # or run once, nothing installed
pip install git+https://github.com/williamcaban/reportspec          # or plain pip, ideally in a virtualenv
```

PDF output needs Pango (`dnf install pango`, `brew install pango`) and DOCX output needs `pandoc`. If you would rather not install anything, use the [container](docs/container.md).

## Run it

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

### Container

The image carries everything (Pango, pandoc, fonts, locked dependencies) and runs offline and read-only, with no Python on your machine. There is no published image yet, so build it once from a clone, then put any command from above after the image name:

```bash
podman build -t reportspec .
podman run --rm reportspec conformance conformance
```

[Running in a container](docs/container.md) covers the build arguments (Fedora and Python versions), Docker, rendering your own files, file ownership on Linux, OpenShift, and what is inside the image.

### HTTP service (optional)

A standalone, stateless render service for programs that would rather call an API than run a command. It is not tied to EvalHub, ASAGO or any other product, and nothing else needs it. Install the extra and start it:

```bash
pip install "reportspec[service] @ git+https://github.com/williamcaban/reportspec"
reportspec serve --playground          # http://127.0.0.1:8000, API docs at /docs, playground at /
```

[Render service](docs/service.md) has the endpoints, a `curl` example, the web playground, errors, limits and security notes. The container image includes the service too.

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
- [Render service](docs/service.md): the optional HTTP API and playground
- [Output and conformance](docs/output-and-conformance.md): the evidence manifest and the 34 conformance cases

**Background**
- [Concepts and design](docs/concepts.md): why it exists and how the layers fit
- [Hosts](docs/hosts/README.md): using it from [EvalHub](docs/hosts/evalhub.md) and [ASAGO](docs/hosts/asago.md)

**Project**
- [Roadmap](docs/roadmap.md): what is planned, what is verified, open questions and quality requirements
- [Development](docs/development.md): set up a self-contained development environment, run the tests

## License

- **Code:** Apache-2.0, see [LICENSE](LICENSE).
- **Fonts** (`src/reportspec/fonts/`): Red Hat Text and Mono, SIL OFL 1.1, redistributed unmodified.
- **Icons** (`src/reportspec/icons/`): Font Awesome Free status icons, CC BY 4.0.
- **Example inputs:** some are derived from third-party projects and taxonomies.
- [NOTICE](NOTICE) lists the fonts, icons and example-input provenance with their licenses.
