---
title: Case
version: 0.1.0
reportspec:
  version: v1alpha1
  bindings:
    rates:
      display: percent
      items:
        - { metric: suite/acc, label: "<script>alert(1)</script>" }
        - { metric: suite/asr, label: Attack rate }
---
```reportspec-viz
id: rates-bar
type: bar
data: rates
range: [0, 1]
```
