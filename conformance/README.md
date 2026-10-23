# ReportSpec conformance cases

Every implementation, whatever the host or language, must produce these outcomes. The proof-of-concept implementation is Python 3.13+. Run the proof-of-concept implementation with:

```bash
reportspec conformance .   # from a clone: uv run reportspec conformance .
```

Each case is a directory with a `case.yaml` and usually a `spec.report.md`:

```yaml
description: one line
spec: spec.report.md                 # default; may point at ../../examples/*.report.md
inputs: [../inputs/mini-bundle.json] # native results or bundles; prefix "adapter:" to skip detection
params: { name: value }              # render-time overrides
format: markdown | html | docx       # output format to render and check; default markdown
requires: [pandoc]                   # docx cases are skipped when pandoc is not installed
expect:
  validate: valid | invalid          # default valid
  errors_contain: [substring, ...]
  warnings_contain: [substring, ...]
  render: ok | fail                  # omit to skip rendering
  render_error_contains: substring
  render_warnings_contain: [substring, ...]
  markdown_contains: [substring, ...]
  markdown_excludes: [substring, ...]
  html_contains: [substring, ...]    # only when the case sets format: html
  html_excludes: [substring, ...]
  docx_contains: [substring, ...]    # searched in word/document.xml; docx_excludes likewise
  docx_media: N                      # number of embedded images
```

Error and warning matching is by substring of the proof-of-concept implementation's messages. Another implementation may word its messages differently: it must agree on valid or invalid, ok or fail, and on the rendered Markdown, and should map its messages to these cases in its own test suite.

`inputs/mini.jsonl` is the JSONL equivalent (null metrics, a null sample, a header line), and `inputs/bad.jsonl` is a malformed line.

`inputs/mini-bundle.json` is a synthetic bundle. It includes an MLflow-style sanitized key (`acc_none`), mixed metric polarities, an N/A record value, and hostile strings in record data.
