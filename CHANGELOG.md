# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- AI SDK (`forgelab/sdk/`): `domain_schema()` tight per-domain JSON Schema,
  `system_prompt()`/`few_shot()` prompt templates, `validate_llm_output()` for
  cleaning and validating raw LLM output, and `ForgeAgent` (Claude-backed,
  configurable model, natural language -> validated `ForgeDocument`).
- `Scene` model in the 3D vocabulary; `LLMOutputError` in the core error
  hierarchy; optional `agent` extra (`pip install "forgelab[agent]"`).
- Initial scaffold: `spec` IR models (`ForgeDocument`, `Node`, `Domain`) with a
  required `forgelab_version` field and major-version compatibility checks.
- `core` compiler: `validate()`, tool registry, and transform pipeline.
- Importer/exporter base ABCs plus stubs for KiCad, Altium, Gerber, Fusion 360,
  FreeCAD, Blender, and Unreal Engine.
- AI SDK helpers: `new_document`, `load`, `dump`.
- FastAPI compiler-as-a-service: `/health`, `/spec`, `/validate`, `/export/{tool}`.
- JSON Schema export of the IR.
- Tooling: Ruff, Pyright, Pytest, and GitHub Actions CI.
- KiCad PCB importer and exporter with a verified IR-level round-trip
  (components, nets, and board constraints preserved).
- Typed hardware spec vocabulary (`Component`, `Pad`, `Net`, `BoardLayer`,
  `OutlineSegment`, `DesignRules`, `BoardConstraints`) serialized into the
  generic Node graph.
- `forgelab.formats` package with a zero-dependency S-expression parser/writer.
- Real `examples/hardware/blinky.kicad_pcb` board.
- 3D / game domain: typed `threed` vocabulary (`Material`, `Mesh`, `Primitive`,
  `Transform`, `Object3D`) serialized into the generic Node graph, with scene
  hierarchy expressed via `Node.children`.
- glTF importer and exporter (`tool_name="gltf"`) with a verified IR-level
  `.gltf` round-trip; mesh geometry is fully decoded into JSON arrays (no opaque
  buffers). Registered in the default pipeline registry.
- glTF accessor/buffer codec in `forgelab.formats` (zero-dependency,
  base64-embedded buffers).
- Real `examples/threed/cube.gltf` (red cube) and its generated `cube.forge.json`.

### Changed
- `SPEC_VERSION` bumped to 0.4.0; example `.forge.json` files regenerated.
- `SPEC_VERSION` bumped to `0.3.0` (additive hardware then 3D vocabularies; root
  model unchanged; backward compatible — compatibility remains major-based).
- Importers/exporters may now depend on `forgelab.formats` (shared neutral
  format primitives) in addition to `forgelab.spec`.
- `forgelab.importers.threed` and `forgelab.exporters.threed` are now packages
  (glTF implemented; Blender/Unreal native stubs preserved).

[Unreleased]: https://github.com/forgelab/forgelab/commits/main
