---
title: Case
version: 0.1.0
reportspec:
  version: v1alpha1
  bindings:
    missing_metric: arc/f1
---
{% if missing_metric < 0.5 %}low{% endif %}
