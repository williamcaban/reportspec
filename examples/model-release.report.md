---
title: Model Release Readiness
subtitle: demo-assistant-7b, capability, safety and red-team evidence in one report
description: Showcase report. One Markdown file plus one JSONL results file renders to HTML and PDF with every chart type. All values are synthetic.
version: 1.0.0
authors: [William Caban]
date: 2026-10-23
tags: [demo, release-gate, synthetic-data]
lang: en

params:
  min_score:
    value: 0.75
    type: number
    label: Minimum score on capability benchmarks
  asr_ceiling:
    value: 0.10
    type: number
    label: Maximum acceptable attack success rate
    overridable: false
  gate_floor: 0.80

format:
  html:
    toc: true
  pdf:
    toc: true
    page_size: letter
  markdown: default
  json: default

reportspec:
  version: v1alpha1
  audience: executive
  on_missing: marker

  bindings:
    # Built-ins (the producer's own verdict). The report formats them; it never recomputes them.
    overall_score:     { display: percent, precision: 1 }
    overall_threshold: { display: percent, precision: 1 }
    overall_pass:      {}

    asr:               { metric: garak/attack_success_rate, display: percent, direction: lower_is_better }
    best_trend:        { metric: trend/run_6, display: percent }

    # A series from an explicit list of metrics
    capability:
      display: percent
      items:
        - { metric: capability/truthfulqa,    label: TruthfulQA }
        - { metric: capability/mmlu,          label: MMLU }
        - { metric: capability/gsm8k,         label: GSM8K }
        - { metric: capability/arc_challenge, label: ARC-Challenge }
        - { metric: capability/hellaswag,     label: HellaSwag }
        - { metric: capability/ifeval,        label: IFEval }

    # A series from a wildcard: labels come from what the * matched, in file order
    trend:             { metric: "trend/run_*", display: percent }
    probe_asr:         { metric: "garak/*_asr", display: percent, direction: lower_is_better }

    # hallucination_probe is null in the data: it renders as N/A, never as zero
    safety_profile:
      display: percent
      items:
        - { metric: safety/bbq,                  label: Bias (BBQ) }
        - { metric: safety/toxigen,              label: Toxicity (ToxiGen) }
        - { metric: safety/pii_resistance,       label: PII resistance }
        - { metric: safety/jailbreak_resistance, label: Jailbreak resistance }
        - { metric: safety/refusal_calibration,  label: Refusal calibration }
        - { metric: safety/hallucination_probe,  label: Hallucination probe }

    release_gates:
      display: percent
      items:
        - { metric: gates/safety_gate,   label: Safety gate }
        - { metric: gates/coverage_gate, label: Coverage gate }
        - { metric: gates/latency_slo,   label: Latency SLO }
        - { metric: gates/cost_budget,   label: Cost budget }
        - { metric: gates/red_team_gate, label: Red-team gate }

    # Tables of records
    probe_by_model:
      records: garak/matrix
      row: probe
      column: model
      value: asr
      display: percent
    judge_scores:
      records: judge/scores
      required: true
      fields:
        model: model
        score: { field: score, precision: 3 }
    findings:
      records: garak/findings
      fields:
        id: id
        severity: severity
        probe: probe
        summary: summary
---

# {{ meta.title }}

**Model:** {{ subject.name | code }} · **Run:** {{ run.id | code }} · **Generated:** {{ report.generated_at }}

> Every number in this report is synthetic. It exists to show what one Markdown template and one JSONL file produce.

## 1. Summary

```reportspec-viz
id: headline
type: summary_cards
cards:
  - { label: Overall score, value: overall_score, threshold: { binding: overall_threshold }, direction: higher_is_better }
  - { label: Attack success rate, value: asr, threshold: { param: asr_ceiling }, direction: lower_is_better }
  - { label: Latest training run, value: best_trend }
```

{% if overall_pass is available %}
The producer's overall verdict is **{{ overall_pass | status }}**: {{ overall_score }} against a threshold of {{ overall_threshold }}.
{% endif %}
{% if asr is available and asr > params.asr_ceiling %}
The Garak attack success rate of {{ asr }} is above the {{ params.asr_ceiling | percent(0) }} ceiling, so the red-team gate does not pass.
{% endif %}

## 2. Capability

```reportspec-viz
id: capability-bars
type: bar
title: Benchmark scores against the minimum
data: capability
range: [0, 1]
threshold: { param: min_score }
direction: higher_is_better
orientation: horizontal
```

```reportspec-viz
id: trend-line
type: line
title: Accuracy across training runs
data: trend
range: [0.5, 0.8]
threshold: { param: min_score }
direction: higher_is_better
x_label: Training run
```

## 3. Safety

The hallucination probe was not run for this release. It shows as **N/A**, and N/A is not a pass.

```reportspec-viz
id: safety-radar
type: radar
title: Safety profile
data: safety_profile
range: [0, 1]
```

```reportspec-viz
id: probe-asr
type: bar
title: Garak attack success rate by probe
data: probe_asr
range: [0, 0.3]
threshold: { param: asr_ceiling }
direction: lower_is_better
orientation: horizontal
sort: desc
```

```reportspec-viz
id: probe-matrix
type: heatmap
title: Attack success rate by probe and model
data: probe_by_model
range: [0, 1]
direction: lower_is_better
```

## 4. Judge scores

```reportspec-viz
id: judge-box
type: boxplot
title: LLM-as-judge score distribution
data: judge_scores
x: model
y: score
range: [0, 1]
threshold: { param: min_score }
direction: higher_is_better
y_label: Judge score
```

## 5. Release gates

```reportspec-viz
id: gates-radial
type: radial
title: Release gates
data: release_gates
range: [0, 1]
threshold: { param: gate_floor }
direction: higher_is_better
```

## 6. Findings

{% for f in (findings if findings is available else []) if f.severity == "high" %}
{% if loop.first %}
High-severity findings need an owner before release:

{% endif %}
- **{{ f.id }}** ({{ f.probe }}): {{ f.summary }}
{% endfor %}

```reportspec-viz
id: findings-table
type: table
title: All findings
data: findings
columns:
  - { field: id, label: ID }
  - { field: severity, label: Severity }
  - { field: probe, label: Probe }
  - { field: summary, label: Summary }
```

Finding F-03 contains `<script>` in its summary on purpose: result text is untrusted, so it is shown as text and never interpreted.
