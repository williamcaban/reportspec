---
title: Quickstart Report
version: 1.0.0
description: The smallest useful report. Used by docs/tutorial.md. All values are synthetic.

params:
  min_accuracy:
    value: 0.70
    type: number
    label: Minimum accuracy
  asr_ceiling:
    value: 0.10
    type: number
    label: Maximum acceptable attack success rate
    overridable: false
  team: Evaluation team

format:
  html: default
  pdf: default
  markdown: default
  json: default

reportspec:
  version: v1alpha1
  audience: developer
  bindings:
    accuracy:
      display: percent
      items:
        - { metric: capability/mmlu,  label: MMLU }
        - { metric: capability/gsm8k, label: GSM8K }
        - { metric: capability/ifeval, label: IFEval }
    asr:     { metric: safety/attack_success_rate, display: percent, direction: lower_is_better }
    failures:
      records: safety/failures
      fields:
        probe: probe
        severity: severity
        summary: summary
---

# {{ meta.title }}

**Model:** {{ subject.name | code }} · **Run:** {{ run.id | code }} · **Prepared by:** {{ params.team }}

## Capability

```reportspec-viz
id: accuracy-bars
type: bar
title: Accuracy against the minimum
data: accuracy
range: [0, 1]
threshold: { param: min_accuracy }
direction: higher_is_better
```

## Safety

{% if asr is available and asr > params.asr_ceiling %}
The attack success rate is {{ asr }}, above the {{ params.asr_ceiling | percent(0) }} ceiling.
{% else %}
The attack success rate is {{ asr }}.
{% endif %}

```reportspec-viz
id: failures-table
type: table
title: Attacks that succeeded
data: failures
```
