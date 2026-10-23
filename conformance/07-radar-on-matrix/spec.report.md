---
title: Case
version: 0.1.0
reportspec:
  version: v1alpha1
  bindings:
    m: { records: "@evaluations", row: id, columns: { Score: score } }
---
```reportspec-viz
id: r
type: radar
data: m
```
