---
title: Case
version: 0.1.0
reportspec:
  version: v1alpha1
  bindings:
    acc: { metric: suite/acc, display: percent }
    asr: suite/asr
---
acc={{ acc }} asr={{ asr | default("none") }} subject={{ subject.name }} run={{ run.id }}
