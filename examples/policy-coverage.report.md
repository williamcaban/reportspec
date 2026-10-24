---
title: Agent Policy Coverage and Attack Path
subtitle: Which policy clauses address which risks, how an attack gets through, and what each defense buys
description: Showcase report for the edge bundling, force-directed graph and parallel coordinates charts. All values are synthetic.
version: 1.0.0
authors: [William Caban]
date: 2026-10-24
tags: [demo, policy-coverage, attack-flow, synthetic-data]
lang: en

format:
  html: default
  pdf:
    page_size: letter
  markdown: default
  json: default

reportspec:
  version: v1alpha1
  audience: executive
  bindings:
    # A network is two tables: one row per node (id, name, group) and one row per link (from, to).
    # JSONL reserves the keys `label` and `source` on a line, so the records use `name`, `from` and `to`
    policy_nodes:
      records: coverage/nodes
      fields: { id: id, label: name, group: group }
    policy_links:
      records: coverage/links
      fields: { source: from, target: to }

    flow_nodes:
      records: attack/nodes
      fields: { id: id, label: name, group: group }
    flow_links:
      records: attack/links
      fields: { source: from, target: to }

    # One row per agent configuration; latency_p95 is null for the sandbox run (not measured)
    configs:
      records: configs/scores
      fields:
        config: config
        task_utility:        { field: task_utility,        display: percent, precision: 0 }
        attack_success_rate: { field: attack_success_rate, display: percent, precision: 0 }
        policy_coverage:     { field: policy_coverage,     display: percent, precision: 0 }
        false_refusals:      { field: false_refusals,      display: percent, precision: 0 }
        latency_p95:         { field: latency_p95,         display: number,  precision: 1 }
---

# {{ meta.title }}

**Agent:** {{ subject.name | code }} · **Run:** {{ run.id | code }} · **Generated:** {{ report.generated_at }}

> Every value in this report is synthetic. It shows what three chart types add to a report: how a policy maps to risks, how an attack moves, and how several measurements compare at once.

## 1. Policy to risk mapping

Each curve joins a policy clause to a risk it addresses. Clauses and risks sit on one circle, grouped by policy section and risk category, and curves between groups are pulled together so shared routes read as bands. **A risk with no curve ending on it is not covered by any clause.** Here that is prompt injection.

```reportspec-viz
id: policy-risk-bundle
type: bundle
title: Policy clauses and the risks they address
data: policy_links
source: source
target: target
nodes: policy_nodes
```

## 2. Attack path

A prompt-injection attack that ends in credential exfiltration, with the controls that interrupt it. Arrows point from an attack step to the next step, or to the risk it realizes; a control points at the step it blocks. The layout is computed from the links, so position carries no meaning: follow the arrows.

```reportspec-viz
id: attack-flow
type: graph
title: Attack flow and the controls that interrupt it
data: flow_links
source: source
target: target
nodes: flow_nodes
```

## 3. What each defense buys

Each line is one agent configuration and each vertical axis is one measurement on its own scale. Axes where lower is better are flipped, so a line near the top is good on every axis. The sandbox run has no latency measurement: its line stops at the previous axis and is not drawn through zero.

```reportspec-viz
id: config-parallel
type: parallel
title: Four agent configurations across five measurements
data: configs
series: config
axes: [task_utility, attack_success_rate, policy_coverage, false_refusals, latency_p95]
lower_is_better: [attack_success_rate, false_refusals, latency_p95]
```

The exact values behind the lines:

```reportspec-viz
id: config-table
type: table
data: configs
columns:
  - { field: config, label: Configuration }
  - { field: task_utility, label: Task utility, align: right }
  - { field: attack_success_rate, label: Attack success, align: right }
  - { field: policy_coverage, label: Policy coverage, align: right }
  - { field: false_refusals, label: False refusals, align: right }
  - { field: latency_p95, label: "p95 latency (s)", align: right }
```
