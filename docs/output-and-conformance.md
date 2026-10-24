# Output and conformance

What a render produces and how an implementation proves it behaves the same.

## Output: report plus evidence manifest

The `json` format is the evidence record a host stores next to the HTML/PDF, so an auditor can reproduce or challenge a verdict. It is identical across hosts:

```json
{
  "manifest_version": "v1alpha1",
  "report":  { "spec_name": "agent-redteam", "spec_version": "0.1.0", "spec_digest": "sha256:…(full)", "generated_at": "…" },
  "hosts":   ["asago"],
  "sources": [ { "adapter": "midojo", "uri": "midojo-results.json", "digest": "sha256:…", "run_id": "midojo-run-4b7e90", "evaluations": ["midojo.weather"] } ],
  "subject": { "kind": "model", "name": "granite-3.3-8b-instruct" },
  "run":     { "id": "…", "context": { "policy": "fs-isac", "midojo_suite": "weather" } },
  "params":  { "effective": { "asr_ceiling": 0.1 }, "overrides": {} },
  "bindings": { "agent_asr": { "type": "scalar", "ref": "midojo.weather/attack_success_rate", "status": "resolved", "value": 0.333, "direction": "lower_is_better" } },
  "viz": [ { "id": "attack-matrix", "type": "heatmap", "data": "attack_matrix" } ],
  "warnings": [],
  "markdown": "…rendered body…"
}
```

Source digests tie each number in the report to the exact input file that produced it, so the evidence chain survives a report that combines three tools.

## Conformance

[`conformance/`](../conformance/README.md) holds 46 cases (the first 25 below, then JSONL, box plot, HTML and DOCX output, chart-limit, and graph, bundle and parallel-coordinates cases): the two examples, the earlier negative tests (unguarded comparison, `__class__` access, function calls, radar on a matrix, template syntax in a fence, YAML aliases, locked params, missing required binding, untrusted-data escaping, viz in a loop, missing front matter), and new cases for the decoupling (sanitized metric names, cross-evaluation wildcards, duplicate evaluation ids, opaque host namespaces, top-level typos, N/A semantics, wrong fence name, direction conflicts, mixed-polarity radar from bundle data, built-in redeclaration, run identity). Two independent implementations are interchangeable when both pass.
