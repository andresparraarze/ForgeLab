# Design: Blender / glTF 3D round-trip

**Date:** 2026-06-09
**Status:** Approved
**Spec bump:** 0.2.0 → 0.3.0

## Goal

Prove ForgeLab is genuinely multi-domain by adding the second domain — 3D / game
scenes — via a working **glTF** importer and exporter with a semantic round-trip
guarantee, mirroring the KiCad work. Import a `.gltf` scene into a ForgeDocument
(meshes, objects, materials, scene hierarchy), export back to `.gltf`, and prove
`import → export → import` is identity over the IR. The proof artifact is a cube
with a clearly visible red material.

## Decisions (approved)

1. **IR fidelity: decoded / semantic (mirror KiCad).** Import decodes glTF binary
   buffers/accessors into plain float and int arrays stored directly in the IR.
   Export re-encodes into a fresh, canonical `.gltf` with a single buffer. Agents
   see real geometry as JSON, never opaque base64 blobs.
2. **Format scope: `.gltf` only** — self-contained JSON with the binary buffer
   embedded as a base64 data URI. No `.glb` binary container in this pass. `.glb`
   is future work.
3. **Hierarchy via `Node.children`.** glTF node trees nest as `Node.children`
   (the first real use of that field — hardware is flat). Meshes and materials are
   flat top-level nodes (shared, id-referenced resources).
4. **Materials: PBR scalars only** — `baseColorFactor`, `metallicFactor`,
   `roughnessFactor`. Textures / normal maps are out of scope (future work).

## Architecture

Three layers, the same shape as the hardware domain.

### 1. Shared format primitive — `forgelab/formats/gltf.py`

Zero new dependencies (stdlib `json`, `base64`, `struct`). The neutral, mechanical
piece both importer and exporter share: the glTF **accessor/buffer codec**.

- `decode_accessor(gltf: dict, index: int) -> list[float | int]` — walks
  accessor → bufferView → buffer (base64 data URI), `struct.unpack`s into a flat
  Python list. Supports the component types and accessor types this domain needs
  (`VEC3` float positions, `SCALAR` integer indices).
- `BufferBuilder` — accumulates float (`VEC3`) and int (`SCALAR`) arrays, then
  emits a single base64-embedded buffer plus the `bufferViews` and `accessors`
  it created (with correct `min`/`max`, `componentType`, `count`, `target`).
- Constants: `FLOAT = 5126`, `UNSIGNED_INT = 5125`, `ARRAY_BUFFER = 34962`,
  `ELEMENT_ARRAY_BUFFER = 34963`, plus type strings `"VEC3"` / `"SCALAR"`.
- `GltfError(ValueError)` for malformed input.

This preserves the boundary rule: importers/exporters depend on `forgelab.spec`
and `forgelab.formats` only — never on each other, never on `forgelab.core`.

### 2. Typed vocabulary — `forgelab/spec/threed.py`

Mirrors `hardware.py`: node-type constants plus Pydantic models with
`extra="forbid"`. Models serialize into the generic `Node` graph via
`model_dump()` and are rebuilt with `model_validate(node.props)`.

Node-type constants:

```python
NODE_SCENE = "scene"
NODE_OBJECT = "object"
NODE_MESH = "mesh"
NODE_MATERIAL = "material"
```

Models:

- `Material(name: str, base_color: list[float], metallic: float = 1.0,
  roughness: float = 1.0)` — `base_color` is RGBA (length-4 validator).
- `Primitive(positions: list[float], indices: list[int], material: str = "")` —
  `positions` are flat xyz triples; `material` is a material **id** (`""` = none).
- `Mesh(name: str, primitives: list[Primitive])`.
- `Transform(translation: list[float], rotation: list[float], scale: list[float])`
  — length validators: translation 3, rotation 4 (quaternion), scale 3.
- `Object3D(name: str, transform: Transform, mesh: str = "")` — a glTF node;
  `mesh` references a mesh id (`""` = no mesh, e.g. a pure group/transform node).

### 3. IR mapping & determinism

Document node list order: `[scene, *materials, *meshes, *root objects]`.

- **Meshes & materials** are flat top-level nodes (shared, index-referenced
  resources, referenced by stable id).
- **Objects** form a tree via `Node.children`: a glTF node's child objects nest
  inside their parent's `Node.children`. Root objects (the scene's `nodes`) sit at
  the document top level.
- **Stable ids:** glTF arrays are index-based and items are often unnamed. Import
  assigns deterministic ids by array index when no usable name exists:
  `material_0`, `mesh_0`, `object_0`, … Export maps id → array index.
- **Determinism (the round-trip lever):** import walks glTF arrays in array order;
  export preserves document node order and rebuilds indices deterministically from
  it. Therefore `import → export → import` yields an equal ForgeDocument — the same
  guarantee KiCad gives via net-sorting + float normalization. Float values are
  written canonically (integral floats stay floats here, since glTF geometry is
  inherently floating point; exact decoded values are re-encoded).

### Importer — `forgelab/importers/threed/gltf.py`

`GltfImporter(Importer)`, `tool_name="gltf"`, `GltfParseError(GltfError)`.
`to_ir(source: bytes)` parses JSON, validates `asset.version`, reads materials →
meshes (decoding each primitive's POSITION + indices accessors) → the scene's node
tree (objects with transforms, mesh refs, nested children). Emits nodes
`[scene, *materials, *meshes, *root objects]`. Meta `name` from the scene name (or
`"scene"`), `generator="forgelab-gltf"`.

### Exporter — `forgelab/exporters/threed/gltf.py`

`GltfExporter(Exporter)`, `tool_name="gltf"`. `from_ir(document)` rebuilds a
canonical glTF: `asset`, `materials`, `meshes` (re-encoding positions/indices
through `BufferBuilder` into one buffer), `nodes` (objects, flattened tree with
`children` index lists), and one `scene`. Returns pretty-printed JSON bytes.

## Example + tests

- `examples/threed/cube.gltf` — a hand-written, spec-valid self-contained glTF:
  one cube mesh, one **clearly visible red** PBR material
  (`baseColorFactor ≈ [0.8, 0.1, 0.1, 1.0]`), one node, one scene, buffer embedded
  as a base64 data URI. Written so it opens correctly in any glTF viewer and the
  red is obvious.
- `examples/threed/cube.forge.json` — generated by the importer from `cube.gltf`.
- Tests (mirroring the KiCad suite):
  - `test_gltf_codec.py` — accessor decode/encode, `BufferBuilder`, malformed input.
  - `test_spec_threed.py` — model validation and validators.
  - `test_gltf_importer.py` — cube imports with expected mesh/material/object data.
  - `test_gltf_exporter.py` — IR exports to valid glTF.
  - `test_gltf_roundtrip.py` — `import → export → import` identity.

## Cross-cutting updates

- Spec bump `SPEC_VERSION` `0.2.0 → 0.3.0`.
- `forgelab/spec/__init__.py` — re-export threed models + node-type constants.
- `forgelab/formats/__init__.py` — re-export glTF codec symbols.
- `forgelab/importers/threed/__init__.py`, `forgelab/exporters/threed/__init__.py`
  — packages re-exporting the new classes.
- `README.md` — tool matrix: Blender import+export ✅; update spec badge to v0.3.0;
  add a 3D quickstart snippet; status/roadmap.
- `CHANGELOG.md` — 3D domain, glTF codec, spec bump.
- `tests/test_spec.py` — assert `SPEC_VERSION == "0.3.0"`.

## Out of scope (future work)

- `.glb` binary container.
- glTF textures, normal maps, samplers, images.
- Animations, skins, cameras, lights, sparse accessors.
- Non-triangle primitive modes.
- Blender `.blend` native format (glTF is the open interchange path).
