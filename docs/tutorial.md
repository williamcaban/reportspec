# Tutorial: your first report

This walks through one small report from start to finish: the results file, the template, running it, and reading what comes out. Every command and output below was run against the files in `examples/`.

You need `reportspec` installed (see the [README](../README.md#install)) and a clone of the repository for the example files:

```bash
git clone https://github.com/williamcaban/reportspec && cd reportspec
```

## The three pieces

| Piece | File | Written by |
|---|---|---|
| Results | [`examples/inputs/quickstart.jsonl`](../examples/inputs/quickstart.jsonl) | Your evaluation tool or script. One JSON object per line |
| Template | [`examples/quickstart.report.md`](../examples/quickstart.report.md) | You. Markdown with a YAML header |
| Run | the `reportspec` command | You, or a CI job |

The template never reads the results file directly. It names values (`capability/mmlu`), and `reportspec` looks them up in a normalized copy of the results, the **ResultsBundle**. That is why the same template works with JSONL, EvalHub or ASAGO output. See [Concepts](concepts.md).

## 1. The results file

Nine lines, one JSON object each:

```jsonl
{"subject": {"kind": "model", "name": "demo-7b"}, "run": {"id": "run-42"}}
{"evaluation": "capability", "label": "Capability suite", "source": "demo-harness"}
{"evaluation": "capability", "metric": "mmlu", "value": 0.71, "direction": "higher_is_better"}
{"evaluation": "capability", "metric": "gsm8k", "value": 0.58, "direction": "higher_is_better"}
{"evaluation": "capability", "metric": "ifeval", "value": null, "direction": "higher_is_better"}
{"evaluation": "safety", "label": "Safety probes", "source": "demo-harness"}
{"evaluation": "safety", "metric": "attack_success_rate", "value": 0.14, "direction": "lower_is_better"}
{"evaluation": "safety", "set": "failures", "probe": "promptinject", "severity": "high", "summary": "Hijacked the system prompt"}
{"evaluation": "safety", "set": "failures", "probe": "dan", "severity": "medium", "summary": "Role-play jailbreak"}
```

- Line 1 says what was evaluated (`subject`) and which run produced it (`run`).
- `evaluation` groups lines. This file has two groups, `capability` and `safety`.
- A line with `metric` and `value` is one number. `"value": null` means "not measured" and shows as N/A, never as zero.
- A line with `set` is one row of a table called `failures`.

[Writing JSONL results](jsonl.md) has the full format.

## 2. The template

A template has three parts: a YAML header, Markdown text with `{{ }}` placeholders, and `reportspec-viz` blocks for charts and tables.

```markdown
---
title: Quickstart Report
version: 1.0.0

params:                       # values the reader can change
  min_accuracy: { value: 0.70, type: number, label: Minimum accuracy }
  asr_ceiling:  { value: 0.10, type: number, overridable: false }
  team: Evaluation team

reportspec:
  version: v1alpha1
  bindings:                   # names the body can use, each pointing into the results
    accuracy:
      display: percent
      items:
        - { metric: capability/mmlu,  label: MMLU }
        - { metric: capability/gsm8k, label: GSM8K }
        - { metric: capability/ifeval, label: IFEval }
    asr:      { metric: safety/attack_success_rate, display: percent, direction: lower_is_better }
    failures: { records: safety/failures, fields: { probe: probe, severity: severity, summary: summary } }
---

# {{ meta.title }}

**Model:** {{ subject.name | code }} · **Prepared by:** {{ params.team }}

```reportspec-viz
id: accuracy-bars
type: bar
data: accuracy
range: [0, 1]
threshold: { param: min_accuracy }
direction: higher_is_better
```

{% if asr is available and asr > params.asr_ceiling %}
The attack success rate is {{ asr }}, above the {{ params.asr_ceiling | percent(0) }} ceiling.
{% endif %}
```

(Shortened. The real file has a second chart and a table block.) Read it in this order:

1. **`params`** declares settings. [Parameters](parameters.md) explains the forms and how to override them.
2. **`bindings`** gives each name a source. `metric: capability/mmlu` means "the metric `mmlu` in the evaluation `capability`". `items` builds a list from several metrics. `records: safety/failures` points at the `set` lines. More in [Results, adapters and bindings](results-and-bindings.md).
3. **The body** is Markdown. `{{ asr }}` prints a bound value, and `{% if %}` blocks are conditions.
4. **`reportspec-viz`** blocks draw the charts from a binding (`data: accuracy`). Options are in [Writing a report template](authoring.md#visualization-blocks).

Note the guard `asr is available and asr > …`. If `asr` were missing, comparing it would fail the render on purpose, so a metric that was never measured cannot read as a pass. See [Missing data](authoring.md#missing-data-printable-never-comparable).

## 3. Check the template

```bash
reportspec validate examples/quickstart.report.md
```

```text
valid
```

`validate` needs no results. It catches unknown names, bad options and unguarded comparisons (as warnings). Run it while you edit.

## 4. See the normalized results

```bash
reportspec bundle --input examples/inputs/quickstart.jsonl
```

This prints the ResultsBundle as JSON: the two evaluations, their metrics (with `"value": null` for `ifeval`), and the `failures` rows. It is the quickest way to see exactly which names your template can refer to.

## 5. Render it

Markdown prints to the terminal, which is handy for a first look:

```bash
reportspec render examples/quickstart.report.md --input examples/inputs/quickstart.jsonl --format markdown
```

```text
# Quickstart Report

**Model:** `demo-7b` · **Run:** `run-42` · **Prepared by:** Evaluation team

## Capability

**Figure: Accuracy against the minimum** (bar)

| Label | Value |
|---|---:|
| MMLU | 71.0% |
| GSM8K | 58.0% |
| IFEval | *data unavailable* |

Threshold: 70.0%

## Safety

The attack success rate is 14.0%, above the 10% ceiling.
...
```

IFEval is `null` in the file, so it prints *data unavailable*. The 14.0% is above the 10% ceiling, so the `{% if %}` text appeared.

For a real document, pick a format and an output file:

```bash
reportspec render examples/quickstart.report.md --input examples/inputs/quickstart.jsonl --format html -o out/quickstart.html
reportspec render examples/quickstart.report.md --input examples/inputs/quickstart.jsonl --format pdf  -o out/quickstart.pdf
reportspec render examples/quickstart.report.md --input examples/inputs/quickstart.jsonl --format docx -o out/quickstart.docx
```

| Format | Notes |
|---|---|
| `markdown` | Charts become tables. Prints to stdout unless you pass `-o` |
| `json` | The evidence manifest (see [Output and conformance](output-and-conformance.md)) |
| `html` | One self-contained file: inline charts, fonts and CSS, no network |
| `pdf` | Needs Pango. Red Hat fonts are embedded |
| `docx` | Needs `pandoc`. Editable in Word |

HTML, PDF and DOCX also write `quickstart.manifest.json` next to the report. It records the template digest, the SHA-256 of every input file, the effective parameters and every resolved value.

## 6. Change a parameter

```bash
reportspec render examples/quickstart.report.md --input examples/inputs/quickstart.jsonl --format markdown \
  --param min_accuracy=0.5 --param team="Red team"
```

The threshold line now reads `Threshold: 50.0%` and the byline says *Prepared by: Red team*. Overrides are recorded in the manifest. `asr_ceiling` is `overridable: false`, so this fails:

```bash
reportspec render ... --param asr_ceiling=0.5
# failed: --param asr_ceiling: parameter is not overridable      (exit code 2)
```

## 7. Use your own results

1. Make your tool print JSONL ([Writing JSONL results](jsonl.md)). Start with `reportspec bundle --input yours.jsonl` to check it.
2. Copy `quickstart.report.md`, change the `bindings` to your evaluation and metric names, and edit the body.
3. `reportspec validate`, then `reportspec render`.
4. Several result files can feed one report: repeat `--input`. Evaluation ids must be unique across them.

## When something fails

| You see | Cause and fix |
|---|---|
| `failed: results.jsonl line 2: invalid JSON: …` | A line is not valid JSON. The line number is exact |
| `failed: line 1: a line without 'evaluation' may only hold subject, run or verdict` | You forgot `"evaluation": "<group>"` on a metric line |
| A table cell or chart shows *data unavailable* | The name in `metric:` does not exist in the results (check spelling with `reportspec bundle`), or the value is `null` |
| `warning: … uses optional binding 'x' without an 'is available' guard` | Write `{% if x is available and x > … %}` |
| Render fails with a comparison on a missing value | The same, but the value really was missing. Guard it, or mark the binding `required: true` to fail early with a clear message |
| `failed: --param x: not declared in params` | Declare `x` under `params:` first |
| `failed: results.dat is not valid JSON: Extra data …` | The file is JSONL but not named `.jsonl`. Use `--input jsonl:results.dat` |
| PDF fails with an error about `libpango` or `libgobject` | Install Pango (`dnf install pango`, `brew install pango`, `apt install libpango-1.0-0 libpangoft2-1.0-0`) |
| `failed: pandoc not found on PATH; DOCX output needs it` | Install `pandoc` |
