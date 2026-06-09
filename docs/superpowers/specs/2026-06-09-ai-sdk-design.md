# ForgeLab AI SDK — Design

**Date:** 2026-06-09
**Status:** Approved
**Spec bump:** 0.3.0 → 0.4.0

## Goal

Make ForgeLab natively usable by AI agents and LLMs. ForgeLab already has a
generic IR, typed domain vocabularies (hardware, 3D), two end-to-end
round-trips, and a thin SDK (`new_document`/`load`/`dump`). This adds the layer
that turns a natural-language request into a validated, ready-to-compile
`ForgeDocument`:

1. A **tight per-domain JSON Schema** an LLM can be constrained to, so it emits
   valid ForgeLab JSON without hallucinating field names.
2. **Prompt templates** (system prompt + few-shot) retrievable by domain name,
   usable with any LLM (Claude, GPT, local Llama).
3. **`validate_llm_output()`** — cleans messy LLM text, parses, validates, and
   returns a clean `ForgeDocument` or raises a clear error explaining exactly
   what the model got wrong.
4. A **`ForgeAgent`** helper that wraps the Anthropic API so a developer can
   build a design agent in under 10 lines.

## Non-goals (YAGNI)

- No multi-provider client wrappers (OpenAI/Gemini/etc.). Only the
  schema + prompt path is provider-portable; the agent helper is Anthropic-only.
- No streaming, batching, or custom retry logic beyond the Anthropic SDK's
  built-in retries.
- The agent does **not** wrap export-to-tool. It returns a `ForgeDocument`; the
  caller chains the existing exporter. This keeps the SDK decoupled from the
  importer/exporter layer.
- No `strict: true` structured-output enforcement (the 3D schema is recursive
  via `object` children, which strict mode disallows). Forced tool-use plus
  Pydantic validation is the robust path.

## Architecture

Four focused modules under `forgelab/sdk/`, each depending only on
`forgelab.spec` and `forgelab.core` — never on `forgelab.importers` or
`forgelab.exporters`. This preserves the agent's decoupling from the tool layer.

```
forgelab/sdk/
├── __init__.py      # existing new_document/load/dump + re-export the new surface
├── schema.py        # DOMAIN_VOCAB registry + domain_schema(domain)
├── prompts.py       # system_prompt(domain), few_shot(domain)
├── validation.py    # validate_llm_output(raw, domain=None) + LLMOutputError
└── agent.py         # ForgeAgent
```

### Single source of truth: the `DOMAIN_VOCAB` registry

One registry maps each `(domain, node_type)` to its Pydantic vocab model. Both
the schema builder and the deep validator read from it, so they never drift:

```python
DOMAIN_VOCAB: dict[str, dict[str, type[BaseModel]]] = {
    "hardware": {
        NODE_BOARD: BoardConstraints,
        NODE_NET: Net,
        NODE_COMPONENT: Component,
    },
    "threed": {
        NODE_SCENE: Scene,        # new model — see Spec changes
        NODE_MATERIAL: Material,
        NODE_MESH: Mesh,
        NODE_OBJECT: Object3D,
    },
}
```

The node→model mapping mirrors exactly what the importers emit:
hardware `board`→`BoardConstraints`, `net`→`Net`, `component`→`Component`;
3D `scene`→`Scene`, `material`→`Material`, `mesh`→`Mesh`, `object`→`Object3D`.

### 1. `schema.py` — `domain_schema(domain) -> dict`

Builds a `ForgeDocument`-shaped JSON Schema specialized for one domain:

- `forgelab_version`, `meta` carried from the envelope.
- `domain` pinned to a `const` (e.g. `"hardware"`).
- `nodes[]` is a **discriminated union on `.type`**: one variant per node type in
  the domain's `DOMAIN_VOCAB` entry. Each variant pins `type` to a `const` and
  sets `props` to that vocab model's own JSON Schema (exact field names/types).
- 3D `object` nodes carry recursive, object-only `children` via `$ref`/`$defs`.

Implementation: define per-domain Pydantic "view" models (a discriminated union
of typed node models) and emit `model_json_schema()`, so the schema stays in
lock-step with the vocab models. Unknown domain raises `KeyError` with the list
of valid domains.

### 2. `prompts.py` — retrievable templates

- `system_prompt(domain) -> str`: explains what ForgeLab is, the IR envelope
  (`forgelab_version`/`domain`/`meta`/`nodes`), the domain's node types and their
  fields, and instructs the model to emit **only** valid ForgeLab JSON.
- `few_shot(domain) -> list[tuple[str, str]]`: a small set of
  `(user_request, assistant_json)` examples. The assistant JSON is loaded from
  the real `examples/` files (`blinky.forge.json`, `cube.forge.json`) so every
  shipped example is guaranteed valid — a test asserts each round-trips through
  `validate_llm_output`.

Both raise a clear error on an unknown domain. These are pure data — usable by
any LLM, decoupled from the agent.

### 3. `validation.py` — `validate_llm_output(raw, domain=None) -> ForgeDocument`

Pipeline:

1. **Clean.** Strip Markdown code fences (```` ```json … ``` ````), and extract
   the first balanced top-level JSON object from any surrounding prose.
2. **Parse.** `json.loads`. Failure → `LLMOutputError` quoting the JSON error +
   position.
3. **Structural + version validation.** Run `core.validate()` to get a generic
   `ForgeDocument` and enforce the spec major-version compatibility check.
4. **Deep per-node validation.** For each node, look up its vocab model by
   `(document.domain, node.type)` in `DOMAIN_VOCAB` and re-validate
   `node.props` through it; recurse into `object` children. Unknown node type or
   a Pydantic field error → `LLMOutputError` naming the node id, the offending
   field, and the expected shape.
5. If `domain` was passed, assert `document.domain == domain`, else
   `LLMOutputError`.

Returns the **generic `ForgeDocument`** (what exporters consume). New error type
`LLMOutputError(ForgeError)` lives in `forgelab/core/errors.py` next to the
existing hierarchy, so SDK consumers catch one base `ForgeError`.

### 4. `agent.py` — `ForgeAgent`

```python
class ForgeAgent:
    def __init__(self, *, model: str = "claude-opus-4-8",
                 client: Any | None = None,
                 max_tokens: int = 8192) -> None: ...
    def design(self, prompt: str, *, domain: str) -> ForgeDocument: ...
```

- `model` is a **configurable parameter** (default `"claude-opus-4-8"`) so
  developers can swap models.
- `anthropic` is **lazy-imported** inside `__init__` (or when first needed). If
  it is missing, raise a friendly `ImportError` telling the user to
  `pip install "forgelab[agent]"`. The `client` parameter allows injecting a
  pre-built (or stubbed) client — this is also how the tests avoid the network.
- `design()` calls `client.messages.create(model=..., max_tokens=...,
  system=system_prompt(domain), tools=[{name: "emit_forgelab", description: ...,
  input_schema: domain_schema(domain)}], tool_choice={"type": "tool", "name":
  "emit_forgelab"}, messages=[{"role": "user", "content": prompt}])`.
- It extracts the `tool_use` block, takes its parsed `.input`, and passes it
  through `validate_llm_output(..., domain=domain)` as the safety net before
  returning the `ForgeDocument`. If no `tool_use` block is present → clear error.

### The 10-line quickstart (README)

```python
from forgelab.sdk import ForgeAgent
from forgelab.exporters.hardware.kicad import KiCadExporter

agent = ForgeAgent()                                    # reads ANTHROPIC_API_KEY
doc = agent.design("a blinky LED board with one resistor and one LED",
                   domain="hardware")                   # NL -> validated ForgeDocument
with open("blinky.kicad_pcb", "wb") as f:
    f.write(KiCadExporter().from_ir(doc))               # -> real KiCad file
```

## Spec changes

- `SPEC_VERSION`: 0.3.0 → 0.4.0.
- Add `Scene(BaseModel)` to `forgelab/spec/threed.py` with a single field
  `name: str` (`extra="forbid"`). This is backward-compatible with the props the
  3D importer already emits (`{"name": scene_name}`) and gives every node type a
  backing model for the registry. Re-export from `forgelab/spec/__init__.py`.
- The 0.4.0 bump is major-compatible (still `0.x`), so existing documents keep
  validating; example `.forge.json` files are regenerated for freshness.

## Testing

All tests are offline — **no network calls**.

- `test_sdk_schema.py`: each domain's `domain_schema` has `domain` as a `const`,
  contains every node type for that domain, and each variant's `props`
  field names match the vocab model. Unknown domain raises.
- `test_sdk_prompts.py`: each domain returns a non-empty system prompt and ≥1
  few-shot example; every few-shot assistant JSON round-trips through
  `validate_llm_output`.
- `test_sdk_validation.py`: strips ```` ```json ```` fences and surrounding
  prose; parses a clean document; raises `LLMOutputError` with a useful message
  for (a) malformed JSON, (b) an unknown/hallucinated field, (c) an unknown node
  type, (d) a wrong `domain`, (e) an incompatible spec version.
- `test_sdk_agent.py`: a fake/stub client returns a canned `tool_use` block;
  asserts `ForgeAgent.design` sends the right model, forces `emit_forgelab` with
  the domain schema attached, and returns a validated `ForgeDocument`. A second
  test asserts a missing-`anthropic` path raises the friendly `ImportError`
  (simulated), and that a non-default `model` argument is honored.
- `test_spec.py`: `SPEC_VERSION == "0.4.0"`.

## Module boundary compliance

- `sdk/` depends on `forgelab.spec` and `forgelab.core` only.
- `agent.py` does **not** import any exporter; the README example chains the
  exporter in user code.
- `LLMOutputError` joins the existing `ForgeError` hierarchy in `core/errors.py`.

## Packaging

- New optional extra in `pyproject.toml`: `agent = ["anthropic>=0.40"]`. Core
  install stays dependency-light (Pydantic + FastAPI); schema/prompts/validation
  work with zero new dependencies.

## Documentation

- README: add the AI SDK quickstart (NL → compiled KiCad in ~10 lines), note the
  SDK surface, bump the spec badge to v0.4.0, refresh status/roadmap, and ensure
  the document is current and follows README best practices.
- CHANGELOG: Added (sdk schema/prompts/validation/agent, `Scene` model, `agent`
  extra); Changed (SPEC_VERSION → 0.4.0).
