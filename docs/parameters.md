# Parameters

Parameters are the settings of a report that a reader may want to change without editing the template: a minimum score, a threshold, a team name. They are declared in the front matter under `params:` and used in the body and in charts. This page follows the R Markdown and Quarto convention.

## Declaring a parameter

Two forms. Use the short form when a default is enough:

```yaml
params:
  team: Evaluation team        # string
  safety_floor: 0.7            # number
  show_details: true           # boolean
```

Use the long form to add metadata or restrictions:

```yaml
params:
  min_accuracy:
    value: 0.70                # required: the default
    type: number               # string | number | boolean (inferred from value when omitted)
    label: Minimum accuracy    # human-readable name
    description: Benchmarks below this fail the capability gate.
    choices: [0.6, 0.7, 0.8]   # optional: allowed values
    overridable: false         # optional, default true
```

| Key | Meaning |
|---|---|
| `value` | The default. Required in the long form |
| `type` | `string`, `number` or `boolean`. Inferred from the default when omitted |
| `label`, `description` | For people reading the template or a UI built on it |
| `choices` | Allowed values. The default must be one of them, and so must any override |
| `overridable` | `false` locks the value. The CLI refuses to change it |

Names are lowercase snake_case (`min_accuracy`, not `MinAccuracy` or `min-accuracy`), up to 63 characters, and cannot be a reserved word: `meta`, `params`, `report`, `subject`, `run`, `loop`, `true`, `false`, `none`, `missing`. A template can declare at most 64 parameters.

**Lock what the report's meaning depends on.** The example templates set `asr_ceiling` to `overridable: false`, because a compliance reader should not find a different ceiling than the one the template's author signed off. Leave presentation settings (a team name, a title) overridable.

## Using a parameter

In the body, as `params.<name>`:

```markdown
Prepared by {{ params.team }}.

{% if asr is available and asr > params.asr_ceiling %}
Above the {{ params.asr_ceiling | percent(0) }} ceiling.
{% endif %}
```

In a chart or card as a threshold, which keeps the drawn line and the text in step:

```yaml
threshold: { param: min_accuracy }
```

Referring to a parameter that is not declared is a validation error (`reportspec validate` catches it).

## Overriding at render time

```bash
reportspec render report.md --input results.jsonl --param min_accuracy=0.8 --param team="Red team"
```

`--param NAME=VALUE` can be repeated. The text is converted to the declared type:

| Type | Accepted |
|---|---|
| `number` | Anything Python reads as a float: `0.5`, `1e-3`, `80` |
| `boolean` | `true`, `yes`, `1` or `false`, `no`, `0` (any case) |
| `string` | Taken as is |

Mistakes are one-line errors with exit code 2, never a traceback:

| Command | Message |
|---|---|
| `--param nope=1` | `--param nope: not declared in params` |
| `--param asr_ceiling=0.5` (locked) | `--param asr_ceiling: parameter is not overridable` |
| `--param min_accuracy=abc` | `--param min_accuracy: 'abc' is not a number` |
| `--param team=c` (with `choices: [a, b]`) | `--param team: 'c' is not one of ['a', 'b']` |
| `--param oops` | `reportspec: error: --param expects NAME=VALUE, got 'oops'` |

## Where parameters are recorded

The evidence manifest (`<name>.manifest.json`, or `--format json`) has both the effective values and the overrides:

```json
"params": { "effective": { "min_accuracy": 0.5, "asr_ceiling": 0.1, "team": "Evaluation team" },
            "overrides": { "min_accuracy": "0.5" } }
```

So a reader of a rendered report can tell whether someone moved a threshold.

## Parameters are not results

A parameter is an input the author or reader chooses. A result comes from the evaluation and goes through the JSONL file or another adapter. Do not put measured values in `params`, and do not recompute a pass/fail from a parameter when the producer already gave a verdict. See [Concepts](concepts.md).
