# ForgeLab Mechanical CAD (FreeCAD) — Design

**Date:** 2026-06-09
**Status:** Approved
**Spec bump:** 0.4.0 → 0.5.0

## Goal

Add the third and final launch domain — Mechanical CAD — via a FreeCAD
`.FCStd` importer/exporter, proving the ForgeLab IR spans hardware (KiCad), 3D
(glTF), and mechanical (FreeCAD). Capture parts, bodies, parametric features
(extrusions, cuts), sketch dimensions, and assembly relationships, with an
IR-level round-trip identity guarantee. Wire the new domain into the AI SDK so
`domain_schema`/`system_prompt`/`few_shot`/`validate_llm_output` work for
`"mechanical"` out of the box.

## Format decision

Target **`.FCStd`** — a ZIP archive containing `Document.xml` — parsed entirely
with the standard library (`zipfile` + `xml.etree.ElementTree`). **No FreeCAD
installation is required**, satisfying the CI / ForgeLab Cloud constraint.

`.FCStd` is the only practical format that carries the requested semantics. STEP
(`.step`/`.stp`) is baked boundary-representation geometry plus product/assembly
structure — it has no parametric feature tree, no extrusion/cut features, and no
sketch dimensions, so it cannot represent "features (extrusions, cuts),
dimensions" as required. FreeCAD's `Document.xml` is a flat object graph
(`Objects` + `ObjectData`) that does carry exactly those concepts.

We model a **canonical subset** of that object graph. The opaque binary `.brp`
BREP shapes FreeCAD stores are **not** authored — we round-trip the parametric
feature tree, which is what carries parts/bodies/features/dimensions/assembly.

## Round-trip guarantee

`import → export → import == ForgeDocument` (identical IR), proven by tests —
exactly like the KiCad and glTF round-trips. The exporter writes a real `.FCStd`
ZIP with a canonical `Document.xml` we fully control. **FreeCAD-openability of
our output is best-effort / out of scope** for the strict guarantee (verifying it
would require FreeCAD in CI, contradicting the no-FreeCAD constraint; FreeCAD
would recompute geometry from the parametric tree on open).

## Non-goals (YAGNI)

- No STEP, no Fusion 360 (stays a stub).
- No fillet/chamfer/revolve/loft/pattern-array features.
- No constraint **solving** — sketch dimensions are stored values, not a solved
  system.
- No multi-level nested assemblies beyond simple Part→Body containment.
- No `GuiDocument.xml` styling/view data round-trip (a minimal `GuiDocument.xml`
  may be emitted for container validity but is not part of the IR).
- No authoring of binary OpenCASCADE `.brp` shapes.

## Architecture

Follows the established KiCad/glTF pattern exactly. The module boundary rule is
load-bearing: importers/exporters depend on `forgelab.spec` and
`forgelab.formats` ONLY — never on each other or `forgelab.core`.

```
forgelab/
├── formats/fcstd.py          # NEW shared neutral FCStd codec (zip + Document.xml)
├── spec/mechanical.py        # NEW typed mechanical vocabulary
├── importers/mechanical/     # stub module -> package
│   ├── __init__.py           # re-export FreeCADImporter, FreeCADParseError, Fusion360Importer
│   ├── freecad.py            # real FreeCADImporter
│   └── native.py             # Fusion360Importer stub (preserved)
└── exporters/mechanical/     # stub module -> package
    ├── __init__.py           # re-export FreeCADExporter, Fusion360Exporter
    ├── freecad.py            # real FreeCADExporter
    └── native.py             # Fusion360Exporter stub (preserved)
examples/mechanical/box-with-hole.FCStd + box-with-hole.forge.json
```

`core/pipeline.py` already imports `FreeCADImporter`/`Fusion360Importer` from
`forgelab.importers.mechanical` (and the exporter equivalents) and registers
them. Converting the stub **module** into a **package** that re-exports the same
names keeps those import paths valid, so `pipeline.py` needs no edit.

### Shared primitive — `forgelab/formats/fcstd.py`

The FCStd analog of `sexpr.py` / `gltf.py`. Neutral, zero-dependency
(stdlib only), used by both the importer and the exporter.

- `class FcstdError(ValueError)` — base codec error.
- `class FcObject` — a lightweight record: `name: str`, `obj_type: str`,
  `properties: dict[str, Any]`. (Plain class or dataclass.)
- `read_objects(data: bytes) -> list[FcObject]` — open the ZIP, read
  `Document.xml`, parse `<Objects>` (declares name+type, in order) joined with
  `<ObjectData>` (per-object `<Properties>`), decoding the property subset into
  Python values. Raises `FcstdError` on: not-a-zip, missing `Document.xml`,
  malformed XML, or an unsupported property type.
- `write_fcstd(objects: list[FcObject], *, program_version: str = "ForgeLab") -> bytes`
  — serialize the objects to a canonical `Document.xml` (matching `read_objects`)
  and return ZIP bytes (Document.xml + a minimal GuiDocument.xml for container
  validity).

**Property encoding (the subset we read/write):**

| Python value | FreeCAD property element |
| --- | --- |
| `float` | `App::PropertyFloat` / `PropertyLength` / `PropertyDistance` → `<Float value="…"/>` |
| `int` | `App::PropertyInteger` → `<Integer value="…"/>` |
| `bool` | `App::PropertyBool` → `<Bool value="true|false"/>` |
| `str` | `App::PropertyString` → `<String value="…"/>` |
| link (object name) | `App::PropertyLink`/`PropertyLinkSub` → `<Link value="…"/>` |
| placement | `App::PropertyPlacement` → position + quaternion attributes |
| sketch geometry list | custom `<GeometryList>` of `<Geo .../>` elements |
| constraint list | custom `<ConstraintList>` of `<Constraint .../>` elements |

Canonical float formatting (e.g. Python `repr(float)`) is used on write so a
re-read parses to the identical value — the determinism lever, analogous to
KiCad's integral-float collapse and glTF's float32 idempotence.

The mapping between generic `FcObject`s and the typed mechanical models lives in
the importer/exporter `freecad.py` files, **not** in the codec — the codec is
vocabulary-agnostic.

## Spec models — `forgelab/spec/mechanical.py`

Pydantic v2, every model `model_config = ConfigDict(extra="forbid")`, mirroring
`hardware.py` / `threed.py`. Node-type constants:

```python
NODE_PART = "part"
NODE_BODY = "body"
NODE_SKETCH = "sketch"
NODE_PAD = "pad"
NODE_POCKET = "pocket"
```

Models:

- `Placement` — `position: list[float]` (len 3, default `[0,0,0]`),
  `rotation: list[float]` (quaternion `[x,y,z,w]`, len 4, default `[0,0,0,1]`).
  Field validators enforce lengths (same idiom as `threed.Transform`).
- `Part` — `name: str`, `placement: Placement = Placement()`.
- `Body` — `name: str`, `part: str = ""` (link to Part id), `placement: Placement = Placement()`.
- `SketchGeometry` — `geo_type: str` (`"line"` | `"circle"`),
  `points: list[float] = []` (line: `[x1,y1,x2,y2]`), `center: list[float] = []`
  (circle: `[x,y]`), `radius: float = 0.0`. Validator: `line` requires
  `len(points)==4` and empty center; `circle` requires `len(center)==2` and empty
  points.
- `Constraint` — `ctype: str` (e.g. `DistanceX`, `DistanceY`, `Distance`,
  `Radius`, `Diameter`), `value: float`, `name: str = ""`.
- `Sketch` — `name: str`, `body: str = ""` (link), `plane: str = "XY_Plane"`,
  `placement: Placement = Placement()`, `geometry: list[SketchGeometry] = []`,
  `constraints: list[Constraint] = []`.
- `Pad` (extrusion) — `name: str`, `body: str = ""`, `profile: str = ""` (Sketch
  link), `length: float`, `reversed: bool = False`, `midplane: bool = False`.
- `Pocket` (cut/hole) — `name: str`, `body: str = ""`, `profile: str = ""`,
  `length: float = 0.0`, `through_all: bool = False`, `reversed: bool = False`,
  `midplane: bool = False`.

All re-exported from `forgelab/spec/__init__.py` (imports + `__all__`):
node constants + `Placement`, `Part`, `Body`, `SketchGeometry`, `Constraint`,
`Sketch`, `Pad`, `Pocket`.

## IR mapping (flat nodes + link refs)

The importer emits a flat, document-order node list. For the box-with-hole:

```
nodes (document order):
  Part   id="Part"    props={name, placement}
  Body   id="Body"    props={name, part:"Part", placement}
  Sketch id="Sketch"  props={name, body:"Body", plane:"XY_Plane",
                             geometry:[4 lines], constraints:[DistanceX 40, DistanceY 20]}
  Pad    id="Pad"     props={name, body:"Body", profile:"Sketch", length:10, ...}
  Sketch001 id="Sketch001" props={name, body:"Body", plane:<face>,
                             geometry:[circle r=4], constraints:[Radius 4]}
  Pocket id="Pocket"  props={name, body:"Body", profile:"Sketch001", through_all:true, ...}
```

Node `id` = FreeCAD object `name` (unique per document), `type` = node-type
constant, `props` = `model.model_dump()`. Assembly and feature relationships are
the link props (`body.part`, `sketch.body`, `pad.profile`, `pocket.profile`).

**Importer** (`importers/mechanical/freecad.py`): `FreeCADImporter(Importer)`,
`tool_name="freecad"`, `FreeCADParseError(FcstdError)`. `to_ir(source)` calls
`read_objects`, maps each `FcObject` by its `obj_type` to the matching mechanical
model (building `Part`/`Body`/`Sketch`/`Pad`/`Pocket`), and emits nodes in
document order. Meta `name` from the document/file, `generator="forgelab-freecad"`,
domain `MECHANICAL`. Unknown object types or malformed properties → `FreeCADParseError`.

**Exporter** (`exporters/mechanical/freecad.py`): `FreeCADExporter(Exporter)`,
`tool_name="freecad"`. `from_ir(document)` rebuilds each node's typed model via
`model_validate(node.props)`, converts to `FcObject`s in document order, and
calls `write_fcstd`. Canonical, deterministic output.

## AI SDK integration

Per the reviewer's requirement, register the mechanical domain so the SDK works
for it out of the box:

- `forgelab/sdk/schema.py` — add to `DOMAIN_VOCAB`:
  ```python
  "mechanical": {
      NODE_PART: Part,
      NODE_BODY: Body,
      NODE_SKETCH: Sketch,
      NODE_PAD: Pad,
      NODE_POCKET: Pocket,
  },
  ```
  (`SketchGeometry`, `Constraint`, `Placement` are nested sub-models, not node
  types — `domain_schema` hoists their `$defs` automatically and
  `validate_llm_output` validates them through their parent models. No registry
  entries for them.)
- `forgelab/sdk/prompts.py` — add to `_FEW_SHOT`:
  ```python
  "mechanical": ("a box with a through hole", "mechanical/box-with-hole.forge.json"),
  ```

This makes `domain_schema("mechanical")`, `system_prompt("mechanical")`,
`few_shot("mechanical")`, and `validate_llm_output(raw, domain="mechanical")`
work with no further changes. The existing AI SDK tests are parametrized — they
gain a `"mechanical"` case, so the few-shot example is round-trip-validated.

## Example & round-trip

1. A generation script builds the box-with-hole IR (using the spec models) and
   runs `FreeCADExporter` to produce `examples/mechanical/box-with-hole.FCStd`
   (a real ZIP + `Document.xml` conforming to our canonical subset — authored by
   our exporter rather than FreeCAD, the same honesty as the stdlib-built glTF
   cube).
2. `FreeCADImporter` reads it to produce `examples/mechanical/box-with-hole.forge.json`
   (the committed IR, stamped at spec 0.5.0).
3. Round-trip test: `FreeCADImporter().to_ir(FreeCADExporter().from_ir(doc)) == doc`,
   plus a stability check that a second export is byte-identical.

## Testing (all offline, no FreeCAD)

- `tests/test_fcstd_codec.py` — `read_objects`/`write_fcstd` round-trip; each
  property type encodes/decodes; error paths (not-a-zip, missing `Document.xml`,
  malformed XML, unsupported property) raise `FcstdError`.
- `tests/test_spec_mechanical.py` — model validation incl. node-type constants,
  `extra="forbid"`, and `SketchGeometry`/`Placement`/`Constraint` validators.
- `tests/test_freecad_importer.py` — imports the example; asserts node ids/types,
  link props, sketch geometry/constraints; malformed input → `FreeCADParseError`.
- `tests/test_freecad_exporter.py` — exports a built IR; asserts the FCStd bytes
  contain a valid `Document.xml` with the expected objects.
- `tests/test_freecad_roundtrip.py` — IR identity + export stability.
- `tests/test_spec.py` — `SPEC_VERSION == "0.5.0"`.
- `tests/test_stubs.py` — `Fusion360Importer`/`Fusion360Exporter` still raise
  `NotImplementedError`.
- `tests/test_examples.py` — the new example validates (existing example test
  picks it up).
- AI SDK tests (`test_sdk_schema.py`, `test_sdk_prompts.py`) parametrized to
  include `"mechanical"`.

## Documentation

- `README.md`: spec badge → v0.5.0; tool-support matrix gains Mechanical CAD
  FreeCAD ✅✅ (and Fusion 360 🚧 already present); a "Round-trip a FreeCAD model"
  quickstart under Quickstart (+ TOC anchor); Project status + Spec versioning →
  v0.5.0 and "three end-to-end round-trips"; roadmap (mechanical FreeCAD checked);
  repository-layout note that `formats/` now includes the FCStd codec. Ensure the
  README stays accurate and follows best practices.
- `CHANGELOG.md`: Added (mechanical vocabulary, FreeCAD importer/exporter, FCStd
  codec, box-with-hole example, mechanical wired into the AI SDK); Changed
  (`SPEC_VERSION` → 0.5.0; mechanical importers/exporters now packages).

## Module boundary compliance

- `importers/mechanical/` and `exporters/mechanical/` import only from
  `forgelab.spec` and `forgelab.formats` — never each other, never
  `forgelab.core`.
- The shared FCStd container/property codec lives in `forgelab/formats/fcstd.py`.
- `FreeCADParseError` derives from `formats.fcstd.FcstdError`.
