# Writing a report template

Everything an author needs: front matter, the template language, how missing data behaves, and the visualization blocks.

## Front matter conventions

| Practice | Precedent | ReportSpec rule |
|---|---|---|
| `---` on line 1, closed by `---` or `...` | Jekyll, Pandoc | Required. No BOM. YAML only |
| Common document keys at top level | Pandoc/Quarto (`title`, `subtitle`, `author`, `date`, `lang`), Jekyll/Hugo (`tags`, `description`) | `title`, `subtitle`, `description`, `version` (SemVer, required), `authors`, `date`, `tags`, `lang` |
| Front matter exposed to the body | Jekyll `page.*`, Quarto `{{< meta >}}` | Document keys are readable as `meta.*` |
| Parameterized reports | R Markdown and Quarto `params:` | `name: default`, or `{value, type, label, choices, overridable}` |
| Per-output options | Quarto `format:` | `html`, `pdf`, `markdown`, `json`; a key's presence enables that output |
| Tool keys namespaced so tools coexist | Jekyll, Hugo and Pandoc ignore keys they don't own | Core keys under `reportspec:`. **Any other top-level mapping is a host namespace**: excluded from `meta.*`, ignored by other hosts, validated only by its owner. An unknown top-level *scalar* is rejected, which catches typos such as `subtitel:` |
| Slug from the filename | Jekyll/Hugo | `reportspec.name` defaults to the file slug |
| Dates are plain strings, strict YAML | (deviation, security) | No timestamp coercion, no aliases, no duplicate keys |

The binding-level display hint is called `display` so it can't be confused with Quarto's `format:`.

## Template language (restricted Jinja-like subset)

The spec defines the subset itself and does not say "Jinja2", so it stays a documented contract and not a side effect of one library. The reference implementation is Python 3.13+ on Jinja2's sandbox, with an AST allowlist that enforces the subset.

| Allowed | Not allowed |
|---|---|
| `{{ expr }}`, `{% if/elif/else %}`, `{% for x in y [if cond] %}` with `loop.*`, `{% set x = ... %}` | `include`, `import`, `extends`, `block`, `macro`, `call`, `filter` blocks, `with`, block `set` |
| Comparisons, `and/or/not`, arithmetic, literals, `~` concat | Any function or method call, including `range()` and `.items()` |
| Filters: `round int float abs default upper lower title capitalize trim length join sort first last min max replace truncate` plus `percent number status code` | Any other filter, including `safe` |
| Tests: `is available`, `is missing`, `defined none number string true false eq ne lt le gt ge in even odd divisibleby` | Attribute or item access starting with `_` |

Registration-time checks: unknown names; unknown `meta.`/`params.`/`report.`/`subject.`/`run.` keys; unknown table fields on loop variables; viz blocks inside `{% for %}`.

**Escaping.** Every `{{ }}` output is Markdown-escaped. Results are untrusted content: Garak prompts, MiDojo agent outputs, and policy text quoted as evidence can carry `<script>`, image beacons (`![](http://attacker/…)`) that a PDF renderer would fetch, or `{{ }}` text. All of these come out inert, and rendering is single-pass. Use `{{ v | code }}` for code spans. Raw HTML in the body is not rendered.

## Missing data: printable, never comparable

With `on_missing: marker` (the default), an unresolved value prints the marker (*data unavailable*). **Any comparison, truth test, arithmetic or iteration on it fails the render.** If missing evaluated as false instead, `{% if asr > 0.1 %}FAIL{% else %}PASS{% endif %}` would print PASS for a run that never measured ASR.

```jinja
{% if truthfulness is available and truthfulness < params.safety_floor %}   ✓ guard, short-circuits
{% if truthfulness < params.safety_floor %}                                 ✗ render fails if missing
```

This matters more with ASAGO data. MiDojo reports an attack as **N/A** when the payload never reached the agent, and its README says plainly that N/A "is not a security pass". The `midojo` adapter maps N/A to null, so `attack_succeeded` is missing for those pairs. `{% for p in pairs if p.attacked %}` fails the render, and `{% for p in pairs if p.attacked is available and p.attacked %}` is the correct form (conformance case 20). The Policy Mapper follows the same convention: it reports undefined precision or recall as `null`, shown as "—", "so they can't be mistaken for a genuine 0.0".

- The validator **warns** on unguarded `if`/`for` uses of optional bindings.
- `required: true` fails the render when that binding is missing. `on_missing: fail` makes every binding required.
- `default:` makes a scalar never-missing. Use it sparingly in compliance reports.
- A wildcard or record set that matches nothing counts as missing, not as an empty list.
- A series from `items` stays available if at least one item resolved.

## Visualization blocks

Fenced code blocks with the info string `reportspec-viz`, whose YAML body is validated against `#/$defs/vizBlock`. A fence ending in `-viz` with any other name (such as the old `evalhub-viz`) gets a warning.

| Type | `data` binding | Type-specific options |
|---|---|---|
| `radar` | series | `range`, `fill`, `threshold`, `direction`. 3 to 12 axes. A missing axis breaks the polygon and is labelled N/A |
| `radial` | series | `range`, `threshold`, `direction`, `sort`. Radial bars, up to 8 items; N/A leaves an empty track |
| `boxplot` | table (one row per sample) | `x` (group field), `y` (numeric field), `range`, `threshold`, `direction`, axis labels. Quartiles are computed by the chart; null samples are counted as N/A |
| `bar` | series | `orientation`, `range`, `threshold`, `direction`, `sort`, `palette`, axis labels |
| `line` | series (order kept) | `range`, `threshold`, `direction`, axis labels |
| `heatmap` | matrix | `range`, `palette` (sequential/diverging), `midpoint`, `direction`, `show_values` |
| `table` | table | `columns[]`, `sort_by`, `status_field` + `status_pass_when` (set `false` for fields where true is bad, like `attack_succeeded`), `sortable` |
| `summary_cards` | none; each card's `value` is a scalar | `cards[] {label, value, display, precision, threshold, direction}` |

Resolution and drawing are separate. The host resolves a block against the bundle into a [resolved payload](../src/reportspec/schemas/resolved-viz-v1alpha1.schema.json) (plain JSON, values and text already formatted, verdict inputs already evaluated), and a chart renderer turns that payload into SVG. The reference renderer builds Vega-Lite specs with Altair for `bar`, `line`, `heatmap` and `boxplot`, and Vega specs for `radar` and `radial`, all rendered through `vl-convert` with external data loading disabled. A host can swap the renderer without touching a template. What a figure must look like is [VISUAL-QA.md](../VISUAL-QA.md). Every chart adds a figure number, a caption note (threshold, direction, N/A count) and generated alt text.

Rules: no template syntax inside a fence; no colors (`palette` states intent, the renderer owns colors); thresholds are a literal, `{param: x}` or `{binding: x}`; a block may sit inside `{% if %}` but not inside `{% for %}`; `format.markdown.viz: table` renders each block as a GFM table for CI and PR comments.
