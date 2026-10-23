---
title: Case
version: 0.1.0
reportspec:
  version: v1alpha1
  bindings:
    hits: { records: redteam/hits, fields: { probe: probe, output: output } }
---
{% for h in hits %}
- {{ h.probe }} {{ h.output }}
{% endfor %}
