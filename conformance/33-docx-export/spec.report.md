---
title: Case
version: 0.1.0
reportspec:
  version: v1alpha1
  bindings:
    rates:
      display: percent
      items:
        - { metric: suite/acc, label: Accuracy }
        - { metric: suite/asr, label: Attack rate }
    rows: { records: hostile/rows, fields: { name: name, note: note } }
---
# Case

Results below are untrusted.

```reportspec-viz
id: rates-bar
type: bar
title: Rates
data: rates
range: [0, 1]
```

```reportspec-viz
id: rows-table
type: table
data: rows
```
