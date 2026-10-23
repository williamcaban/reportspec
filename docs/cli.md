# Command line

For installation see the [README](../README.md#install).

Options for `render`: `--input PATH` (repeatable; `jsonl:PATH` or another adapter name as a prefix forces a format), `--format markdown|json|html|pdf|docx`, `-o FILE`, `--param NAME=VALUE` (repeatable; see [Parameters](parameters.md)). Exit code 0 is success. `validate` exits 1 when the template has errors. Any other failure (bad template at render time, bad input, bad `--param`, missing file, failed conformance case setup) exits 2 with a one-line message.

`reportspec serve` starts the optional [render service](service.md) (`--host`, `--port`, `--playground`, `--no-docs`); it needs `pip install "reportspec[service]"`.

## Commands

```bash
reportspec validate examples/safety-compliance.report.md
reportspec render examples/safety-compliance.report.md --input examples/inputs/evalhub-job.json
reportspec render examples/agent-redteam.report.md \
  --input examples/inputs/asago-risk-extraction.json \
  --input examples/inputs/midojo-results.json \
  --input examples/inputs/evalhub-job.json
reportspec bundle --input examples/inputs/midojo-results.json   # show the normalized bundle
reportspec conformance conformance/
```

## One Markdown file and one JSONL file to HTML, PDF or DOCX

```bash
reportspec render examples/model-release.report.md \
  --input examples/inputs/model-release.jsonl --format pdf  -o out/model-release.pdf
reportspec render examples/model-release.report.md \
  --input examples/inputs/model-release.jsonl --format html -o out/model-release.html
```

Add `--format docx -o out/model-release.docx` for an editable Word copy. Auditors who must annotate a report want this; it needs the `pandoc` binary on the PATH (GPL-2.0+, run as a separate process). Charts arrive as PNG images with Red Hat Text, tables as Word tables, and the report keeps its Evidence section; template images are rejected, and pandoc never reads raw HTML or raw OOXML from the Markdown.

Rendered samples are checked in under [`examples/output/`](../examples/output/) so you can open them without running anything.

Each run writes the report and `<name>.manifest.json`, the evidence record (spec digest, SHA-256 of each input, one digest per figure payload, the Markdown fallback). The HTML is a single self-contained file: inline SVG charts, inline CSS, no external requests.
