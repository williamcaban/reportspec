# ReportSpec documentation

ReportSpec v1alpha1 is a proof of concept (POC), not the final or an adopted design. Start with the [README](../README.md) for install and a first report.

| Page | Read it to |
|---|---|
| [Tutorial: your first report](tutorial.md) | Go from a JSONL file and a template to a rendered report, step by step |
| [Parameters](parameters.md) | Declare parameters, lock them, use them in a template, override them with `--param` |
| [Writing JSONL results](jsonl.md) | Produce a results file for your template, line by line |
| [Concepts and design](concepts.md) | Understand why one spec serves two projects, the three layers, and the design decisions |
| [Writing a report template](authoring.md) | Write a `.report.md`: front matter, template language, missing data, visualization blocks |
| [Results, adapters and bindings](results-and-bindings.md) | Feed results in (JSONL, EvalHub, MiDojo, Policy Mapper) and refer to them from a template |
| [Command line](cli.md) | Look up commands and output formats |
| [Output and conformance](output-and-conformance.md) | See the evidence manifest and the 34 conformance cases |
| [Render service](service.md) | Run the optional HTTP API and playground; endpoints, errors, limits, security |
| [Running in a container](container.md) | Build and run the Fedora image offline and read-only |
| [Hosts](hosts/README.md) | Integrate with a host: [EvalHub](hosts/evalhub.md), [ASAGO](hosts/asago.md) |
| [Development](development.md) | Set up a self-contained environment, run tests and lint, understand CI |
| [Roadmap](roadmap.md) | See what is planned, what is verified, the open questions and the chart quality requirements |

## Reference files

| File | What it is |
|---|---|
| [`reportspec-v1alpha1.schema.json`](../src/reportspec/schemas/reportspec-v1alpha1.schema.json) | JSON Schema (2020-12) for the front matter. `#/$defs/vizBlock` validates each viz block |
| [`results-bundle-v1alpha1.schema.json`](../src/reportspec/schemas/results-bundle-v1alpha1.schema.json) | The ResultsBundle: the host-neutral results model that bindings resolve against |
| [`resolved-viz-v1alpha1.schema.json`](../src/reportspec/schemas/resolved-viz-v1alpha1.schema.json) | The payload a chart renderer receives: bindings resolved, text formatted. The seam between the spec and any drawing library |
| [`examples/`](../examples/) | Report templates and [native inputs](../examples/inputs/) (provenance in each file's `_comment`); [rendered samples](../examples/output/) |
| [`conformance/`](../conformance/README.md) | 34 cases every implementation must pass |
| [`src/reportspec/`](../src/reportspec/) | The package: `core.py` (validator, bundler, renderer, conformance runner), `cli.py`, `service/` (optional HTTP service), `charts.py`, `htmlout.py`, `docxout.py`, `fontset.py`. Proof-of-concept implementation, not product code |
| [fonts](../src/reportspec/fonts/README.md), [icons](../src/reportspec/icons/README.md) | Vendored Red Hat Text/Mono (OFL) and Font Awesome Free status icons (CC BY 4.0), with provenance and font policy |
| [`Containerfile`](../Containerfile), `uv.lock` | Fedora Python image with every dependency pinned and hash-checked |
