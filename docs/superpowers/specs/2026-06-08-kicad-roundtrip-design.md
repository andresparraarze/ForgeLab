# KiCad Round-Trip Importer/Exporter — Design

**Date:** 2026-06-08
**Status:** Approved
**Scope:** A working `.kicad_pcb` → ForgeDocument → `.kicad_pcb` round-trip that preserves
all components, nets, and board constraints. Includes the typed hardware spec layer, a shared
S-expression format primitive, a real example board, and round-trip tests.

## Context

- ForgeLab is already scaffolded: generic `ForgeDocument`/`Node` spec, `core.validate()`, registry +
  pipeline, importer/exporter ABCs, and KiCad/Altium/Gerber **stubs**.
- **KiCad's Python API (`pcbnew`) is not available** in this environment, and no KiCad binaries are
  installed. We therefore parse the `.kicad_pcb` **S-expression** text format directly.
- The `.kicad_pcb` format is an S-expression tree: a top-level `(kicad_pcb …)` containing
  `(version …)`, `(generator …)`, `(general …)`, `(paper …)`, `(layers …)`, `(setup …)`,
  zero or more `(net code "name")`, zero or more `(footprint …)`, and board graphics including
  `Edge.Cuts` outline lines.

## Goals

- Import a real `.kicad_pcb` into a `ForgeDocument`.
- Export a `ForgeDocument` back to a **functional** `.kicad_pcb` (re-parseable; preserves components,
  nets, and board constraints — not required to be byte- or pixel-perfect).
- Extend the spec with a typed hardware vocabulary that serializes into the generic Node graph.
- Prove the round-trip with deterministic tests that do not require KiCad.

## Non-Goals

- Schematic (`.kicad_sch`) import/export.
- Pixel-perfect / byte-perfect file reproduction.
- Real KiCad validation via `kicad-cli` (not installable here).
- Altium and Gerber implementations (remain stubs).
- A network `/import` API endpoint (not requested).

## Architecture

### Module restructure

`forgelab/importers/hardware.py` becomes a package `forgelab/importers/hardware/`; same for
`forgelab/exporters/hardware/`. Each package `__init__.py` re-exports `KiCadImporter`,
`AltiumImporter`, `GerberImporter` (importers) / `KiCadExporter`, `AltiumExporter`, `GerberExporter`
(exporters) so `forgelab/core/pipeline.py`'s existing imports keep working unchanged. The
Altium/Gerber stubs move verbatim into `altium.py` / `gerber.py` within each package.

### New shared format primitive: `forgelab/formats/`

A generic, zero-dependency S-expression module `forgelab/formats/sexpr.py`:

- `parse(text: str) -> SExpr` — tokenize and parse into a nested structure. Atoms are `str`
  (bare symbols/strings) and `float`/`int` (numbers); lists are Python `list`. Quoted strings keep
  their value; bare symbols are distinguished from quoted strings via a `Symbol(str)` wrapper so the
  writer can re-quote correctly.
- `dumps(tree: SExpr, *, indent: int = 2) -> str` — serialize back to S-expression text with
  reasonable indentation and correct quoting. Output need not match KiCad's exact whitespace;
  KiCad re-parses regardless.
- `SExprError(ValueError)` — raised on malformed input.

**Boundary rule change.** Previously importers/exporters depended on `forgelab.spec` only. S-expr
parsing is a neutral format primitive needed by both sides; placing it under `importers/` would make
the exporter depend on the importer. The rule becomes:

> Importers and exporters depend on `forgelab.spec` and `forgelab.formats` only — never on each
> other, and never on `forgelab.core`.

This keeps importer↔exporter independence intact (they share only the neutral primitive, the way
both could share the stdlib `json`). The pattern generalizes to future Blender/Fusion 360 format
primitives.

### Spec extension: `forgelab/spec/hardware.py`

Typed Pydantic models (Pydantic v2, `extra="forbid"` except where noted):

- `Pad` — `number: str`, `net: str` (net name; `""` when unconnected).
- `Component` — `reference: str`, `value: str`, `footprint: str` (library id, e.g.
  `Resistor_SMD:R_0603_1608Metric`), `layer: str`, `at: list[float]` (`[x, y, rotation]`,
  length 3), `pads: list[Pad]`, `uuid: str | None`.
- `Net` — `code: int`, `name: str`.
- `BoardLayer` — `ordinal: int`, `canonical_name: str`, `layer_type: str` (e.g. `signal`,
  `user`), `user_name: str | None`.
- `OutlineSegment` — `start: list[float]` (`[x, y]`), `end: list[float]` (`[x, y]`).
- `DesignRules` — `clearance: float`, `track_width: float`, `via_diameter: float`,
  `via_drill: float`.
- `BoardConstraints` — `kicad_version: str`, `generator: str`, `layers: list[BoardLayer]`,
  `outline: list[OutlineSegment]`, `design_rules: DesignRules`.
- Node-type constants: `NODE_COMPONENT = "component"`, `NODE_NET = "net"`, `NODE_BOARD = "board"`.

These models **serialize into the generic Node graph**, keeping the core IR universal:

| Concept     | Node representation                                              |
| ----------- | --------------------------------------------------------------- |
| Component   | `Node(id=reference, type="component", props=Component dump)`     |
| Net         | `Node(id="net:<code>", type="net", props=Net dump)`             |
| Board       | `Node(id="board", type="board", props=BoardConstraints dump)`   |

A `ForgeDocument` for a board has `nodes = [board_node, *net_nodes, *component_nodes]`.

The importer constructs the typed models and dumps them into `node.props`; the exporter rebuilds
them with `Model.model_validate(node.props)`. The typed models are the **shared contract** between
importer and exporter — neither imports the other.

`forgelab/spec/__init__.py` re-exports the new models and node-type constants.

## Data Flow

### Import (`KiCadImporter.to_ir(source: bytes) -> ForgeDocument`)

1. Decode bytes (UTF-8) and `sexpr.parse`.
2. Validate the root is `(kicad_pcb …)`; else raise `KiCadParseError(SExprError)`.
3. Read `version` and `generator` → `BoardConstraints.kicad_version/generator`.
4. Read `(layers …)` → `list[BoardLayer]`.
5. Read `(setup …)` design-rule fields (`clearance`, `trace_width`/`track_width`, via sizes) →
   `DesignRules` (with sensible defaults if a field is absent).
6. Read `Edge.Cuts` graphics (`gr_line`/`gr_rect` with `(layer "Edge.Cuts")`) → `OutlineSegment`s
   (a `gr_rect` expands to four segments).
7. Read each `(net code "name")` → `Net`.
8. Read each `(footprint …)`: library id, `(layer …)`, `(at x y [rot])`, the `Reference` and
   `Value` properties, `(uuid …)`, and each `(pad number … (net code "name"))` → `Component` with
   `Pad`s (pad net resolved to the net **name**).
9. Build `ForgeDocument(forgelab_version=SPEC_VERSION, domain=hardware,
   meta=DocumentMeta(name=…, generator="forgelab-kicad"),
   nodes=[board_node, *net_nodes, *component_nodes])`.

`meta.name` is taken from the board if available, else `"board"`.

### Export (`KiCadExporter.from_ir(document: ForgeDocument) -> bytes`)

1. Find the single `type=="board"` node → `BoardConstraints`; if absent, use defaults
   (version, generator `forgelab`, standard 2-layer stack, empty outline, default design rules).
2. Collect `type=="net"` nodes → `Net`s (sorted by code); ensure net code 0 `""` exists.
3. Collect `type=="component"` nodes → `Component`s.
4. Build the S-expr tree in canonical order:
   `(kicad_pcb (version …) (generator forgelab) (general (thickness 1.6))
   (paper "A4") (layers …) (setup (pad_to_mask_clearance 0) …rules…)
   (net …)* (footprint …)* (Edge.Cuts gr_line …)*)`.
   Pad `(net code "name")` is emitted by resolving the pad's net **name** back to its code from the
   net table (unknown/empty name → code 0).
5. `sexpr.dumps` → encode UTF-8 → bytes.

The exported file is **functional**: a complete `kicad_pcb` with header, layers, setup, nets,
footprints, and outline.

## Round-Trip Guarantee and Testing

Because KiCad is unavailable, correctness is proven at the IR level plus structural checks:

- **Semantic round-trip:** `doc1 = import(bytes)`; `text = export(doc1)`; `doc2 = import(text)`;
  assert `doc1 == doc2` (Pydantic structural equality over the whole document).
- **Preservation:** component count, net count, and every pad→net association in `doc2` match
  `doc1`; the board outline segment count and design rules match.
- **Validity:** `sexpr.parse(export(doc1))` succeeds and the root is `(kicad_pcb …)`.

Test files (TDD, one behavior per test):

- `tests/test_sexpr.py` — tokenize/parse/dumps; quoted vs bare symbols; nested lists; numbers;
  `parse(dumps(x)) == x` for sample trees; malformed input raises `SExprError`.
- `tests/test_spec_hardware.py` — each hardware model validates; `at` must be length 3; round-trip
  `Model.model_validate(model.model_dump())`.
- `tests/test_kicad_importer.py` — import `examples/hardware/blinky.kicad_pcb`; assert the board
  node, the expected nets, and the R1/D1 components with correct value/footprint/pads.
- `tests/test_kicad_exporter.py` — export a constructed document; assert the text re-parses and
  contains the expected `footprint`/`net` entries.
- `tests/test_kicad_roundtrip.py` — the full semantic round-trip + preservation + validity checks
  on the real blinky board.

### Stub-test update

`tests/test_stubs.py` currently asserts `KiCadImporter().to_ir(b"")` and
`KiCadExporter().from_ir(doc)` raise `NotImplementedError`. KiCad is now implemented, so those
checks switch to `AltiumImporter`/`AltiumExporter` (still stubs). The `tool_name` assertions remain
(KiCad/FreeCAD/Blender). `KiCadImporter().to_ir(b"")` now raises `KiCadParseError` (a `ValueError`),
which a new importer test covers.

## Examples

- Add hand-written `examples/hardware/blinky.kicad_pcb`: a minimal but valid KiCad PCB with
  R1 (`Resistor_SMD:R_0603_1608Metric`, value `330R`) and D1 (`LED_SMD:LED_0805_2012Metric`,
  value `RED`), nets `GND` / `+3V3` / `LED_A`, an `Edge.Cuts` rectangle outline, a 2-layer stack,
  and a `(setup …)` with clearance/track/via rules.
- Regenerate `examples/hardware/blinky.forge.json` by importing the `.kicad_pcb` so it reflects the
  typed-node structure and keeps `tests/test_examples.py` green. The regenerated document is stamped
  `forgelab_version = "0.2.0"`.

## Spec Version

Additive hardware vocabulary (no change to the `ForgeDocument` root shape) → minor bump
`SPEC_VERSION` `0.1.0` → `0.2.0`. Backward compatible: `is_compatible` is major-based, so existing
`0.1.0` documents still validate. Update `CHANGELOG.md`.

## Error Handling

- Malformed S-expression → `SExprError` (from `formats.sexpr`).
- Non-`kicad_pcb` root or structurally invalid board → `KiCadParseError(SExprError)` defined in the
  importer module (importers do not import `core`).
- Export of a document with no board node uses documented defaults rather than failing.
- Pad referencing an unknown net name on export resolves to net code 0.

## File Structure Summary

Created:
- `forgelab/formats/__init__.py`, `forgelab/formats/sexpr.py`
- `forgelab/spec/hardware.py`
- `forgelab/importers/hardware/__init__.py`, `kicad.py`, `altium.py`, `gerber.py`
- `forgelab/exporters/hardware/__init__.py`, `kicad.py`, `altium.py`, `gerber.py`
- `examples/hardware/blinky.kicad_pcb`
- `tests/test_sexpr.py`, `test_spec_hardware.py`, `test_kicad_importer.py`,
  `test_kicad_exporter.py`, `test_kicad_roundtrip.py`

Modified:
- `forgelab/spec/__init__.py` (export hardware models), `forgelab/spec/version.py` (0.2.0)
- `tests/test_stubs.py` (KiCad no longer a stub)
- `examples/hardware/blinky.forge.json` (regenerated)
- `CHANGELOG.md`, `CONTRIBUTING.md` (boundary rule wording)

Deleted:
- `forgelab/importers/hardware.py`, `forgelab/exporters/hardware.py` (replaced by packages)
