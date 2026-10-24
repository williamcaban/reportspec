---
title: Case
version: 0.1.0
reportspec:
  version: v1alpha1
  bindings:
    nodes: { records: net/nodes, fields: { id: id, label: name, group: group } }
    nodes_no_group: { records: net/nodes, fields: { id: id, label: name } }
    links: { records: net/links, fields: { source: from, target: to } }
    scores:
      records: net/scores
      fields:
        config: config
        utility: { field: utility, display: percent, precision: 0 }
        asr: { field: asr, display: percent, precision: 0 }
        latency: { field: latency, display: number, precision: 1 }
---

```reportspec-viz
id: g
type: graph
data: links
source: source
target: target
nodes: nodes
```

```reportspec-viz
id: b
type: bundle
data: links
source: source
target: target
nodes: nodes
```

```reportspec-viz
id: p
type: parallel
data: scores
series: config
axes: [utility, asr, latency]
lower_is_better: [asr]
```
