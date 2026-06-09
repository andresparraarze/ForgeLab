# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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

### Changed
- `SPEC_VERSION` bumped to `0.2.0` (additive hardware vocabulary; backward
  compatible — version compatibility remains major-based).
- Importers/exporters may now depend on `forgelab.formats` (shared neutral
  format primitives) in addition to `forgelab.spec`.

[Unreleased]: https://github.com/forgelab/forgelab/commits/main
