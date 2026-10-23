---
title: Case
version: 0.1.0
reportspec:
  version: v1alpha1
  bindings:
    s: "*/acc"
---
{% for e in evaluations %}
```reportspec-viz
id: b
type: bar
data: s
```
{% endfor %}
