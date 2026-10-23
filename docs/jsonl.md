# Writing JSONL results

JSONL is the lowest-effort way to give ReportSpec results: one JSON object per line, so a script can emit it with `print(json.dumps(...))`. Name the file `.jsonl` and it is read by the `jsonl` adapter automatically. For any other extension use `--input jsonl:PATH`; without the prefix such a file is read as one JSON document and fails with `is not valid JSON`. Blank lines are skipped.

Start from the example for [`quickstart.report.md`](../examples/quickstart.report.md): [`examples/inputs/quickstart.jsonl`](../examples/inputs/quickstart.jsonl). The larger [`model-release.jsonl`](../examples/inputs/model-release.jsonl) pairs with [`model-release.report.md`](../examples/model-release.report.md) and uses every chart type.

## The five kinds of line

| Line | Becomes |
|---|---|
| `{"subject": {...}, "run": {...}}` | What was evaluated and which run. A line without `evaluation` may hold only `subject`, `run` and `verdict` |
| `{"verdict": {"score": 0.74, "threshold": 0.75, "pass": false}}` | The overall verdict, if your tool computes one |
| `{"evaluation": "capability", "metric": "mmlu", "value": 0.71}` | One metric |
| `{"evaluation": "judge", "set": "scores", "model": "a", "score": 0.7}` | One row of a table called `scores` |
| `{"evaluation": "garak", "verdict": {"metric": "attack_success_rate", "score": 0.14, "threshold": 0.1, "pass": false}}` | That evaluation's own verdict |

`evaluation` names a group of results (a benchmark, a tool, a suite). Lines with the same `evaluation` join the same group, in any order.

## Header: subject and run

```jsonl
{"subject": {"kind": "model", "name": "demo-7b", "version": "2026-10", "uri": "quay.io/acme/demo-7b"}, "run": {"id": "run-42", "started_at": "2026-10-23T09:00:00Z", "producer": {"name": "my-harness", "version": "1.2"}, "context": {"environment": "staging"}}}
```

Templates read these as `subject.name`, `run.id`, `run.context.environment` and so on. Keys you invent under `run.context` are yours; a template that refers to one the file lacks prints *data unavailable*.

## Metrics

```jsonl
{"evaluation": "capability", "metric": "mmlu", "value": 0.71, "direction": "higher_is_better"}
{"evaluation": "capability", "metric": "ifeval", "value": null, "direction": "higher_is_better"}
{"evaluation": "latency", "metric": "p95", "value": 412, "unit": "ms", "direction": "lower_is_better"}
```

| Key | Meaning |
|---|---|
| `metric`, `value` | Both required on a metric line. The value is a number, a boolean or a string |
| `value: null` | **Not measured.** Renders as N/A, is never drawn as zero, and cannot be compared in a template |
| `direction` | `higher_is_better` or `lower_is_better`. State it once here and charts and pass/fail marks use it, so templates do not repeat it |
| `unit` | Optional label such as `ms` |
| `type` | Optional: `numeric`, `boolean`, `categorical`, `array_ordered`, `array_unordered` or `time_series`. Inferred from the value (numbers and null are `numeric`, booleans `boolean`, strings `categorical`) |

Metric names can contain dots and commas (`dan.Dan_11_0_asr`, `acc,none`). The same metric given twice in one evaluation keeps the last value.

**Write null, not 0, when a test did not run.** A zero attack success rate reads as "perfectly safe". `null` reads as "unknown", which is the truth.

## Labels

```jsonl
{"evaluation": "capability", "label": "Capability suite", "source": "demo-harness"}
```

`label` is the display name of the group in tables and charts (the id is used if you omit it). `source` records the tool that produced it. Put them on any line of the group; the first one seen wins.

## Tables: `set` lines

Each line adds one row to a named table. Every key other than `evaluation`, `set`, `label` and `source` becomes a column:

```jsonl
{"evaluation": "judge", "set": "scores", "model": "demo-7b", "score": 0.70}
{"evaluation": "judge", "set": "scores", "model": "demo-7b", "score": 0.64}
{"evaluation": "judge", "set": "scores", "model": "other-13b", "score": 0.81}
```

Keep rows flat: strings, numbers, booleans and `null`, no nested objects. Use `set` lines for anything tabular (failed probes, per-task results) and for **box plots**, which want one row per sample so the chart can compute the quartiles. The renderer does not average samples into scores; if you want a score, emit it as a metric yourself.

## Verdicts

If your tool already decides pass or fail, say so. The report shows it and never recomputes it:

```jsonl
{"verdict": {"score": 0.74, "threshold": 0.75, "pass": false}}
{"evaluation": "garak", "verdict": {"metric": "attack_success_rate", "score": 0.107, "threshold": null, "pass": null}}
```

`pass: null` means "no judgement given". The template can then compare the score to one of its own [parameters](parameters.md).

## How lines map to a template

| JSONL | Template binding | Used as |
|---|---|---|
| `{"evaluation": "capability", "metric": "mmlu", ...}` | `{ metric: capability/mmlu }` | one number: `{{ mmlu }}` |
| the same, several metrics | `items: [{ metric: capability/mmlu, label: MMLU }, ...]` | a series for `bar`, `line`, `radar`, `radial` |
| several metrics, one pattern | `{ metric: "capability/*" }` | a series labelled by what `*` matched |
| `{"evaluation": "judge", "set": "scores", ...}` | `{ records: judge/scores, fields: {model: model, score: score} }` | a table, or the samples of a box plot |
| `{"evaluation": "m", "set": "pairs", "user": "a", "inj": "b", "hit": true}` | `{ records: m/pairs, row: inj, column: user, value: hit }` | a heatmap |
| the overall `verdict` line | built-ins `overall_score`, `overall_threshold`, `overall_pass` | no declaration needed |

The full reference grammar is in [Results, adapters and bindings](results-and-bindings.md#reference-grammar).

## Several files, one report

```bash
reportspec render report.md --input capability.jsonl --input redteam.jsonl --format pdf -o out/report.pdf
```

Evaluation ids must be unique across files, or the render fails. The first file with a `subject` or `run` supplies them, and a disagreement from a later file becomes a warning. JSONL files can be mixed with EvalHub, MiDojo and Policy Mapper files. Each input's SHA-256 goes into the evidence manifest.

## Check your file

```bash
reportspec bundle --input results.jsonl
```

prints the normalized bundle. A malformed file fails with the line number:

```text
failed: results.jsonl line 2: invalid JSON: Expecting value
failed: line 1: a line without 'evaluation' may only hold subject, run or verdict; found ['metric', 'value']
failed: line 5: metric 'mmlu' has no 'value'
```

## Generating JSONL from Python

```python
import json, sys

def emit(**row):
    print(json.dumps(row), file=sys.stdout)

emit(subject={"kind": "model", "name": "demo-7b"}, run={"id": "run-42"})
emit(evaluation="capability", label="Capability suite", source="my-harness")
for name, score in {"mmlu": 0.71, "gsm8k": 0.58}.items():
    emit(evaluation="capability", metric=name, value=score, direction="higher_is_better")
emit(evaluation="safety", metric="attack_success_rate", value=None, direction="lower_is_better")  # not run
```

`python run_evals.py > results.jsonl`, then `reportspec render report.md --input results.jsonl ...`.
