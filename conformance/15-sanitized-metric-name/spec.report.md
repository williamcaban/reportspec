---
title: Case
version: 0.1.0
reportspec:
  version: v1alpha1
  bindings:
    mmlu_acc: { metric: "mmlu/acc,none", display: percent }
---
MMLU {{ mmlu_acc }}
