---
title: Case
version: 0.1.0
reportspec:
  version: v1alpha1
  bindings:
    hits: { records: redteam/hits, required: true, fields: { probe: probe, hit: hit } }
---
{% for h in hits if h.hit %}- {{ h.probe }}
{% endfor %}
