---
title: Case
version: 0.1.0
reportspec:
  version: v1alpha1
  bindings:
    two:
      items:
        - { metric: suite/acc, label: A }
        - { metric: suite/acc, label: B }
---
```reportspec-viz
id: r
type: radar
data: two
```
