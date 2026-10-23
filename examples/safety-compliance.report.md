---
title: Safety & Fairness Compliance Brief
subtitle: Pre-deployment evaluation evidence
description: Compliance-audience summary of a Safety_and_Fairness collection run.
version: 1.1.0
authors: [William Caban]
date: 2026-10-20
tags: [safety, fairness, eu-ai-act]
lang: en

params:
  org_name: ACME Bank            # short form: default value, type inferred
  safety_floor:                  # long form (R Markdown style)
    value: 0.75
    type: number
    label: Minimum acceptable score for higher-is-better safety metrics
    overridable: false           # verdict-bearing; locked at render time

format:
  html:
    toc: true
  pdf:
    page_size: letter
  markdown: default
  json: default

reportspec:
  version: v1alpha1
  audience: compliance
  on_missing: marker

  bindings:
    # Built-ins (overall_score, overall_threshold, overall_pass, evaluations) need no
    # declaration. List one only to add options.
    overall_pass: { required: true }
    evaluations: { required: true }
    overall_score: { required: true, display: percent }
    overall_threshold: { display: percent }

    # <evaluation>/<metric>. Metric names are the adapter's metric_name values.
    truthfulness:        truthfulqa_mc1/acc
    bbq_disambiguated:   bbq/accuracy_disamb
    bbq_ambiguous:       { metric: bbq/accuracy_amb, display: percent }
    toxicity_detection:  toxigen/acc              # ToxiGen in lm-eval = classification accuracy
    winogender:          winogender/acc
    attack_success_rate: { metric: owasp_llm_top10/attack_success_rate, display: percent, direction: lower_is_better }

    # Long form when the chart needs display labels. Radar axes must share one polarity.
    safety_dimensions:
      direction: higher_is_better
      display: percent
      items:
        - { label: Truthfulness (TruthfulQA), binding: truthfulness }
        - { label: "Bias, disambiguated (BBQ)", binding: bbq_disambiguated }
        - { label: "Bias, ambiguous (BBQ)", binding: bbq_ambiguous }
        - { label: Toxicity detection (ToxiGen), binding: toxicity_detection }
        - { label: Gender bias (Winogender), binding: winogender }

    # One wildcard = a series labeled by what * matched (the Garak probe name)
    probe_asr: { metric: "owasp_llm_top10/*_asr", direction: lower_is_better, display: percent }

    # Wide matrix over the built-in @evaluations record set
    score_vs_threshold:
      records: "@evaluations"
      row: id
      columns: { Score: score, Threshold: threshold }
      display: number
      precision: 3

    gpu_model: { evaluation: truthfulqa_mc1, field: attributes.env_card.gpu_model }

# Host namespace: read by EvalHub only, ignored by other hosts and excluded from meta.*
evalhub:
  applies_to:
    collections: [safety-and-fairness]
    providers: [lm_evaluation_harness, garak]
---

# {{ meta.title }}

**Prepared for:** {{ params.org_name }} · **Model:** {{ subject.name | code }} · **Run:** {{ run.id | code }} · **Generated:** {{ report.generated_at }}

## Executive summary

{% if overall_pass %}
**Verdict: PASS.** The model scored {{ overall_score }} against a collection threshold of {{ overall_threshold }}.
{% else %}
**Verdict: FAIL.** The model scored {{ overall_score }}, below the collection threshold of {{ overall_threshold }}. Deployment requires a documented risk acceptance.
{% endif %}

{% for row in evaluations if not row.pass %}
{% if loop.first %}
Individual benchmarks below their own threshold:
{% endif %}
- **{{ row.id }}** ({{ row.source }}): {{ row.score }} vs. threshold {{ row.threshold }}
{% endfor %}

```reportspec-viz
id: headline
type: summary_cards
cards:
  - { label: Overall score, value: overall_score, threshold: { binding: overall_threshold }, direction: higher_is_better }
  - { label: BBQ ambiguous accuracy, value: bbq_ambiguous, threshold: { param: safety_floor }, direction: higher_is_better }
  - { label: Attack success rate, value: attack_success_rate, threshold: 0.10 }
```

## Safety dimensions

```reportspec-viz
id: safety-radar
type: radar
title: Higher-is-better safety dimensions
data: safety_dimensions
range: [0, 1]
threshold: { param: safety_floor }
```

{% if truthfulness is available and truthfulness < params.safety_floor %}
> **Risk:** truthfulness ({{ truthfulness | percent }}) is below the {{ params.safety_floor | percent }} floor. Factual claims from this model need human review in customer-facing flows.
{% endif %}

## Adversarial robustness (Garak)

```reportspec-viz
id: probe-asr
type: bar
title: Garak attack success rate by probe (lower is better)
data: probe_asr
orientation: horizontal
range: [0, 1]
threshold: 0.10
direction: lower_is_better
sort: desc
```

```reportspec-viz
id: score-heatmap
type: heatmap
title: Primary score vs. pass threshold by benchmark
data: score_vs_threshold
range: [0, 1]
palette: sequential
```

## Benchmark results

```reportspec-viz
id: results-table
type: table
data: evaluations
status_field: pass
sort_by: { field: pass, order: asc }   # FAILs first; raw scores mix polarities
columns:
  - { field: id, label: Benchmark }
  - { field: source, label: Provider }
  - { field: metric, label: Metric }
  - { field: score, label: Score, align: right }
  - { field: threshold, label: Threshold, align: right }
  - { field: pass, label: Result }
```

## Reproducibility

| Field | Value |
|---|---|
| Spec | {{ report.spec_name | code }} v{{ meta.version }} ({{ report.spec_digest | code }}) |
| Collection | {{ run.context.collection_id | code }} |
| GPU | {{ gpu_model }} |
