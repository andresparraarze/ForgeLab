# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- OBJ and STL importers for the threed domain, so agents can bring in existing
  geometry instead of modelling from scratch. `import_file(file_path=...,
  tool='obj')` parses Wavefront OBJ (stdlib only): `v`/`f` with quad and n-gon
  fan triangulation, `o`/`g` groups as separate mesh+object node pairs,
  `mtllib`/`usemtl` with the companion `.mtl` resolved from the file's directory
  (`Kd`→base color, `Ns`→roughness, `Pm`→metallic, `d`/`Tr`→alpha), and a
  default grey material when none is defined. `tool='stl'` parses both ASCII and
  binary STL into a single mesh with a default material, naming it from the
  binary header / ASCII solid / filename. Both register import-only and enable
  OBJ→IR→glTF/Blender-script round-trips. `import_file` gained a `file_path`
  parameter (preferred over inline `content`; required for OBJ's sibling `.mtl`).
- Blender Python script export for the threed domain: `export_document` with
  `tool='blender_script'` compiles a document into a runnable `.py` that rebuilds
  the scene with Blender's native API (`bpy`) instead of glTF triangle soup.
  Material nodes become Principled BSDF materials; meshes whose geometry matches
  a box, axis-aligned cylinder, or sphere are emitted as `primitive_cube_add` /
  `primitive_cylinder_add` / `primitive_uv_sphere_add` (others fall back to raw
  `from_pydata` meshes); object transforms are applied as quaternion→matrix. The
  script clears the default scene, names it from `meta.name`, parents everything
  under a Y-up→Z-up root, and adds a camera plus three-point lighting so the
  scene renders immediately. Run it via Text Editor → Run Script or a Blender MCP
  `execute_blender_code` call. New `forgelab.exporters.threed.BlenderScriptExporter`,
  registered as `blender_script` and reported by `list_formats`.
- Six canonical example documents under `examples/`, one to three per domain, so
  agents have high-quality few-shot references: `hardware/blinky_led` and
  `hardware/arduino_uno` (a full Arduino Uno clone with real TQFP-32/SOIC-16 pad
  geometry from `calculate_pad_positions`), `mechanical/motor_mount` (NEMA17
  mount plate) and `mechanical/enclosure` (PCB box with mounting bosses), and
  `threed/space_station` and `threed/torii_gate`. Every example validates
  cleanly, exports to its native format, carries an explanatory
  `meta.description`, and (for mechanical) passes the constraint sanity checks
  with no warnings. New `examples/README.md` tabulates each example and what it
  demonstrates.
- `analyze_image` MCP tool (`forge:generate`) that turns a photo into a starting
  ForgeLab document. `analyze_image(image_path, domain, hints='')` reads an image
  (`.png`/`.jpg`/`.jpeg`/`.gif`/`.webp`), sends it to the Anthropic vision model
  (`claude-sonnet-4-6`) with a domain-specific prompt, and returns a partial
  document skeleton: visible components/geometry/structure are extracted,
  unreadable values are reasonable estimates, and estimated nodes' ids are
  suffixed `-estimated`. This enables a photo → analyze → refine → validate →
  export flow. It shares `generate_document`'s requirements (`ANTHROPIC_API_KEY`
  + the `agent` extra); `generation_status` now reports both tools' availability
  via `generate_document` and `analyze_image` booleans.
- `verify_sync` MCP tool (`forge:read`) so agents can check whether a native
  file is still in sync with the ForgeLab document that generated it before
  patching. On export, each exporter now embeds a SHA256 of the source document:
  KiCad as a `(property "forgelab_hash" "<hash>")`, glTF as
  `asset.extras.forgelab_hash`, and FreeCAD as a `Hash` attribute on the
  `ForgeLab.Document.xml` sidecar's root element. `verify_sync(document_path,
  native_path)` reads the embedded hash, recomputes the hash of the current
  `.forge.json`, and returns `{in_sync, document_hash, native_hash, native_path,
  document_path}` plus a `recommendation` to re-import when they differ.
  `patch_document` gained optional `native_path` and `force` parameters: when
  `native_path` is given it runs the sync check first and refuses to patch an
  out-of-sync document (writing nothing) unless `force=true`. New
  `forgelab.sync` module (pure standard library).
- Mechanical-domain constraint sanity checks that run as part of
  `validate_document`, so agents get clear errors before FreeCAD opens instead
  of a silent recompute failure. New `forgelab.validation` module
  (`check_mechanical`, pure standard library) checks sketch line-loop closure
  (warning), positive pad length unless through-all (error), pocket depth within
  the material built by the body's pads unless through-all (error), positive
  circle radius (error), and body-reference consistency (error). The
  `validate_document` response now carries an optional `warnings` list;
  warnings keep `valid` true, errors make it false. The checks are mechanical
  only — hardware and threed documents are skipped.
- Context projection layers so agents receive only the data a task needs. New
  `forgelab.projection` module with a pure `project(document, level)` returning a
  plain dict at one of four levels: `metadata` (version/domain/meta + node counts
  by type, no node data), `topology` (a simplified node list — hardware
  components with reference/value/footprint and pad net names but no pad
  coordinates; threed objects with name/mesh-ref/transform but no mesh geometry;
  mechanical features as id/type/prop-key-names), `geometry` (full
  mesh/pad/sketch geometry, stripping material definitions, scene hierarchy and
  board constraints), and `full`. `load_document` and `validate_document` gained
  an optional `projection`; `export_document` gained one with a twist — it runs
  the full export but returns only the projected view (not the export bytes), so
  the agent gets a lightweight confirmation. The stripping happens inside
  ForgeLab; stripped fields never leave. New `get_projection_schema(domain,
  projection)` tool describes what each level includes/excludes so agents can
  pick a level without trial and error.
- RFC 6902 JSON Patch support for iterative editing, so agents mutate a
  `.forge.json` on disk without re-emitting the whole document. New
  `forgelab.patch` module implements JSON Pointer (RFC 6901) and JSON Patch
  (RFC 6902) from scratch — pure standard library, no new runtime dependency —
  with the full op set (add, remove, replace, move, copy, test) and a `diff`
  that round-trips (`apply(a, diff(a, b)) == b`). Two new MCP tools expose it:
  `patch_document` (`forge:export`) applies a patch and validates-before-writing
  by default, supports in-place or `output_path` writes, and returns
  `{patched, document_path, nodes_changed, valid}`; `diff_documents`
  (`forge:read`) returns the patch transforming document A into B so agents can
  inspect a change without loading either file fully.
- New `forgelab.calc` module + five MCP tools (all `forge:read`, read/compute
  only, pure Python with no dependencies) so agents offload deterministic design
  math instead of computing it inline and making arithmetic mistakes:
  `calculate_pad_positions` (DIP/SOIC/SOP/QFP pad offsets, single or dual row,
  configurable pitch/count), `calculate_polygon` (regular-polygon vertex list for
  prisms, octagonal pads, circle approximations), `calculate_rotation_matrix` (a
  glTF `[x, y, z, w]` quaternion about a principal axis for threed rotation
  fields), `calculate_trace_width` (IPC-2221 trace width in mm), and
  `calculate_board_layout` (a margin-aware grid of component placements).
- MCP server: file-path inputs to keep large documents out of the agent's
  context window. `validate_document` and `export_document` now accept a
  `document_path` to a `.forge.json` on disk as an alternative to the inline
  `document` object — ForgeLab reads the file itself. A bare filename resolves
  against `FORGELAB_OUTPUT_DIR` (the same place `export_document` writes), so an
  agent can write a document to disk, then `validate_document(document_path=…)`
  and `export_document(document_path=…, output_path=…)` with zero large JSON in
  context. The inline-`document` form is unchanged.
- MCP server: new `load_document` tool reads a `.forge.json` and returns only its
  metadata — `domain`, `name`, `forgelab_version`, `node_count`, and
  `nodes_by_type` (counts per type, including nested children) — so an agent can
  verify a saved document without re-serializing the whole thing into context.
- MCP server: new `generation_status` tool reports whether `generate_document`
  is usable on this server (needs both `ANTHROPIC_API_KEY` set and the `agent`
  extra installed) without calling it. When unavailable it returns a `reason`
  and an `alternative` telling the agent to build against the schema
  (`get_domain_schema` + `get_prompt`) and validate once — so agents can skip a
  wasted `generate_document` round trip that would only fail.

### Changed
- SDK prompts: each domain's `system_prompt` now instructs the agent to build
  the complete document in a single pass — consult the schema first, assemble
  every node and prop, then call `validate_document` once — rather than
  iterating with repeated validation calls. Surfaced to external agents through
  the MCP `get_prompt` tool.
- threed domain: `system_prompt` (via `get_prompt`) and the `mesh`/`material`
  reference field descriptions in the JSON schema (via `get_domain_schema`) now
  state explicitly that references must use the target node's `id`, not its
  display `name`, with a `mat_red` (id) vs `vermilion` (name) example — so
  agents stop referencing materials/meshes by name.
- threed domain: documented the **Y-up** coordinate convention (matching glTF's
  native axis) in the spec, the glTF exporter, and `system_prompt` (via
  `get_prompt`). Agents are now told to author height on the Y axis, not Z —
  a Z-up document gets double-converted by Blender's Y-up→Z-up importer and
  lands tipped 90°. The exporter already passes coordinates straight through
  (no rotation); the fix is making the contract explicit so geometry imports
  upright.
- `export_document`: the `output_path` description now tells agents to prefer a
  bare filename (e.g. `"castle.gltf"`) so output lands in the configured
  `FORGELAB_OUTPUT_DIR`, and to pass an absolute path only when writing
  elsewhere — agents were passing absolute paths and bypassing the configured
  directory.

### Fixed
- KiCad exporter: the PCB file-format version is now always written as an
  unquoted integer date stamp (e.g. `(version 20221018)`), never a quoted
  semantic version like `(version "7.0")` which live KiCad rejects. The exporter
  maps known application versions (`6.0`–`9.0`) to their format date, passes
  through bare integer date stamps, and falls back to the canonical `20221018`
  when the `kicad_version` field is missing or unrecognized.
- KiCad exporter: pads no longer stack at the footprint origin. Every pad was
  emitted with `(at 0 0)`, so a multi-pin part (e.g. a 29-pad HTSSOP-28) visually
  collapsed onto a single point. The `Pad` model gained an optional `at` ([x, y]
  offset from the footprint origin) plus optional `size`/`shape`; the exporter
  now emits each pad's real `at` when provided, and when it is omitted spreads
  pads on a centred deterministic grid so they never overlap. The importer reads
  pad `at`/`size`/`shape` back (round-trip stable). `system_prompt('hardware')`
  (via `get_prompt`) and the `Pad.at` JSON-schema description (via
  `get_domain_schema`) now tell agents to set each pad's physical offset.
- glTF exporter: a `mesh`/`material` reference that doesn't match a node id
  (commonly a display name used by mistake) now raises a clear error naming the
  bad reference and listing the valid ids, instead of a cryptic `KeyError` that
  silently failed the export. Surfaced through `export_document` as
  `export failed for 'gltf': ...`.
- Blender export: the unimplemented-`.blend` error now tells the agent to use
  `tool='gltf'` instead (Blender imports glTF natively), rather than a bare
  "not implemented" that left the agent to discover the alternative by trial.
- FreeCAD exporter: the body container is now visible on open (`Visibility=true`
  in `GuiDocument.xml`) alongside its tip feature, matching FreeCAD's normal
  PartDesign display state — the body node is no longer greyed-out requiring a
  click of the eye icon. The body shows the tip's fully-cut solid (verified in
  FreeCAD 1.1: the body renders the holed solid, not the bare base plate);
  intermediate features, sketches and origin datums stay hidden.
- FreeCAD exporter: a through-all pocket now actually cuts when `reversed` is
  not set. `Type=1` (ThroughAll) was already correct and the `Length` is ignored
  by FreeCAD for ThroughAll; the real cause was direction — a ThroughAll pocket
  cuts one way, so when its sketch sat on the far side of the solid it removed
  nothing (the bore left the plate volume unchanged). Through-all pockets are now
  emitted with `Midplane=true` so they cut symmetrically through everything
  regardless of pad direction. Features that arrive with `length=0` also get a
  part-scaled fallback length so the `Length` property is never `0`. Validated in
  FreeCAD 1.1: a 60×30×10 (18000mm³) plate with an unreversed through-bore now
  recomputes to 15989.4mm³.
- FreeCAD exporter: the generated `GuiDocument.xml` now makes **only** the body's
  tip feature (the last solid in the chain — typically the final pocket) visible,
  hiding the body container, intermediate features, sketches and origin datums.
  Previously the body container was also marked visible, which could leave the
  part rendering as the bare base plate with the pocket cuts not shown until
  visibility was reset by hand in the Python console; showing only the tip makes
  the complete holed solid appear after a single recompute. The `GuiDocument`
  also now carries an isometric orthographic camera framed to the part's bounding
  box, so the part fits the view on open instead of starting off-screen.
- FreeCAD exporter: a Pad/Pocket `profile` now resolves when it references its
  sketch by the sketch's label/name (or is stale in a single-sketch body), not
  only by exact node id. Previously such a feature wrote an empty `Profile`
  link, so FreeCAD reported "<feature> no object linked" on open and built no
  solid. The profile is resolved by node id, then sketch label, then the sole
  sketch of the feature's body — the same lookup used for body references.
- FreeCAD exporter: a sketch now keeps its `AttachmentSupport` (and lands in its
  body's group) when its `body` is referenced by the body's label or left blank
  in a single-body part — not only when it exactly matches the body's node id.
  Previously such a sketch silently lost its datum-plane attachment, so it never
  oriented and the feature failed to build. The body is now resolved by node id,
  then by label, then (in a single-body part) the sole body. The `plane` value
  was always carried through correctly via the sidecar; the missing link was
  body resolution, not the plane.
- FreeCAD exporter: exported `.FCStd` files now render the solid shaded instead
  of wireframe-only. Previously no `GuiDocument.xml` view providers were written,
  so FreeCAD's defaults hid every solid and showed only the sketches as
  wireframe. The exporter now generates a `GuiDocument.xml` that makes each body
  and its tip feature visible (shaded "Flat Lines") and hides intermediate
  features, sketches, and origin datums (validated in FreeCAD 1.1's GUI). Note:
  the files carry no precomputed OpenCASCADE shapes, so a single **Refresh**
  (`Ctrl+R`) on open builds the geometry and resolves the Pad/Pocket `Profile`
  links — no manual `touch()` required.
- FreeCAD exporter: nodes nested via `Node.children` are no longer dropped.
  Agents express the part→body→feature hierarchy either as a flat node list or
  by nesting children; the exporter only iterated top-level `document.nodes`, so
  a nested document exported just the `App::Part` and its origin (`Count=9`) and
  silently omitted every `PartDesign::Body` / `Sketcher::SketchObject` /
  `PartDesign::Pad` / `PartDesign::Pocket`. Added `ForgeDocument.walk()` /
  `Node.walk()` (depth-first, pre-order) and the exporter now walks the whole
  tree. Flattening is lossless for the mechanical domain (body/part/feature
  relationships live in node props, not the tree shape).
- Installer: the PATH export now persists in new zsh sessions on Arch/
  EndeavourOS. zsh relocates its dotfiles via `$ZDOTDIR` (commonly
  `~/.config/zsh`), so writing to a bare `~/.zshrc` left the export in a file
  zsh never reads — users had to `source ~/.zshrc` every session. The installer
  now asks zsh where its dotfiles live and writes to `$ZDOTDIR/.zshrc`
  (interactive shells) and `$ZDOTDIR/.zprofile` (login shells: terminal
  emulators run as login shells, SSH, display managers), falling back to
  `$HOME` when `$ZDOTDIR` is unset or zsh is absent.
- FreeCAD exporter: every sketch with a body now emits `AttachmentSupport`
  regardless of how its plane is spelled. The attachment was gated on the plane
  being the exact string `XY_Plane`/`XZ_Plane`/`YZ_Plane`, so an agent writing
  `"XY"`, `"Front"`, `"Top"`, or leaving it blank produced an unattached sketch
  that never oriented and whose geometry never rendered. Plane names are now
  normalized (`XY`/`Top`→XY, `XZ`/`Front`→XZ, `YZ`/`Right`→YZ, unknown→XY).
  Added a `motor-mount` example (vertical flange on the XZ plane via the short
  `"XZ"` spelling); validated with FreeCAD 1.1 — plain recompute builds all
  solids and the flange orients vertically.
- FreeCAD exporter: sketches on non-XY datum planes (XZ/YZ) now orient
  correctly. Each body emits its own `App::Origin` and every sketch attaches to
  the body's datum plane via `AttachmentSupport` + `MapMode` (FlatFace) —
  FreeCAD ignores a plain `Placement` on an in-body sketch, which had left all
  sketches flat in XY and made pocket/pad profiles appear unlinked. Rotations
  are now written in the axis-angle form FreeCAD actually reads (a hardcoded
  `A="0"` had silently flattened every non-identity rotation). Validated with
  FreeCAD 1.1: a vertical-face pocket recomputes and cuts on plain open.
- FreeCAD importer recovers a sketch's datum plane from `AttachmentSupport`
  when reading genuine FreeCAD files.
- `forgelab update` now passes `--force-reinstall --no-cache-dir` to pip, so
  it always pulls the latest code from git instead of reporting "Requirement
  already satisfied" when the version string is unchanged.
- Exported FCStd objects are now marked `Touched="1"`, so FreeCAD rebuilds
  all geometry on a plain open + recompute — previously nothing rendered until
  every object was manually touched (live-testing report: features appeared
  missing because no shape was ever computed).
- FreeCAD exporter now writes genuine FreeCAD-schema `.FCStd` files that open
  directly in FreeCAD (validated with FreeCAD 1.1: all objects restore and
  recompute, pocket cut verified by volume). Real `App::Part`/`App::Origin`/
  `PartDesign::Body`/`Sketcher::SketchObject` (GeomLineSegment/GeomCircle)/
  `PartDesign::Pad`/`PartDesign::Pocket` serialization plus a minimal
  `GuiDocument.xml`; shapes recompute on load (no `.brp` files needed). The IR
  round-trip identity is preserved via a `ForgeLab.Document.xml` sidecar.
- FreeCAD importer now also reads genuine FreeCAD-authored files (canonical
  subset; Origin helpers and unmodeled object types are skipped) in addition
  to the sidecar and legacy ForgeLab-dialect files.
- AI SDK JSON Schema now pins `forgelab_version` to the installed
  `SPEC_VERSION` (`const`), so models cannot invent versions like "1.0".
- Mechanical FreeCAD export no longer raises `KeyError` when optional IR
  fields (e.g. a body's `part`) are omitted — props are validated through the
  domain models first, filling defaults.
- KiCad 9 compatibility (live-testing fixes): design rules moved from
  `(setup ...)` into a `(net_class Default ...)` block with `(add_net ...)`
  entries (importer reads both, so old boards still import); every exported pad
  now carries required `(at 0 0)` and `(size 1.6 1.6)` fields; board-outline
  `gr_line` uses `(stroke (width ...) (type solid))` instead of the
  pre-KiCad-6 bare `(width ...)`. Verified with `kicad-cli pcb export svg`
  (exit 0). `examples/hardware/blinky.kicad_pcb` regenerated at format
  version 20240108.
- glTF exporter now also exports object nodes nested as children of the scene
  node (previously only top-level objects were emitted; nested ones were
  silently dropped).
- `system_prompt()` states the installed `SPEC_VERSION` and `few_shot()`
  rewrites its example's `forgelab_version` to it, so agents never copy a
  stale hardcoded version from shipped example files.

### Added
- `forgelab update` CLI command: upgrades the `~/.forgelab` install from
  GitHub and prints the new spec version.
- One-command agent setup: `scripts/install-claude-code.sh` (one-line Claude
  Code installer), a `forgelab init` CLI that registers the MCP server with
  Claude Code or prints the config for Hermes/OpenClaw/other agents, and
  copy-paste bootstrap prompts in `docs/agent-bootstrap.md`.
- `export_document` gained an optional `output_path` (writes the exported file
  to disk and returns its path) and the `FORGELAB_OUTPUT_DIR` default output
  directory for multi-MCP workflows.
- MCP server (`forgelab/mcp/`): exposes ForgeLab as MCP tools over stdio (local)
  and OAuth-protected Streamable HTTP (remote) using the official MCP SDK. Tools:
  `validate_document`, `get_domain_schema`, `get_prompt`, `list_domains`,
  `list_formats` (`forge:read`); `export_document`, `import_file`
  (`forge:export`); `generate_document` (`forge:generate`, returns a clear error
  when `ANTHROPIC_API_KEY` is unset). Reuses the `forgelab.auth` module as the
  resource-server verifier. Run with `forgelab-mcp --transport stdio|streamable-http`.
  Optional `[mcp]` extra.
- `Registry.tool_names()` read accessor reporting per-tool import/export availability.
- Shared OAuth 2.0 auth module (`forgelab/auth/`): pluggable token verification
  (built-in dev HS256 issuer + external JWKS/RS256 verifier), a self-contained
  dev authorization server supporting `client_credentials` and
  `authorization_code`+PKCE(S256) with RFC 8414 discovery, and a FastAPI
  `require_auth(*scopes)` dependency. Scopes: `forge:read`, `forge:export`,
  `forge:generate`. Optional `[auth]` extra.
- REST API endpoints `/validate` (`forge:read`) and `/export/{tool}`
  (`forge:export`) are now scope-protected; `/health` and `/spec` stay public.
  Auth is off by default (`FORGELAB_AUTH_ENABLED=false`).
- Mechanical CAD domain: typed vocabulary (`forgelab/spec/mechanical.py` —
  Part/Body/Sketch/SketchGeometry/Constraint/Pad/Pocket/Placement), a stdlib-only
  FCStd codec (`forgelab/formats/fcstd.py`), real FreeCAD `.FCStd`
  importer/exporter with an IR-level round-trip guarantee, and a box-with-hole
  example.
- Mechanical domain registered in the AI SDK (`domain_schema`/`system_prompt`/
  `few_shot`/`validate_llm_output` now support `"mechanical"`).
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
- `SPEC_VERSION` bumped to `0.5.0` (additive hardware, 3D, AI-SDK, then
  mechanical vocabularies; root model unchanged; backward compatible —
  compatibility remains major-based). Example `.forge.json` files regenerated.
- `forgelab.importers.mechanical` and `forgelab.exporters.mechanical` are now
  packages (FreeCAD implemented; Fusion 360 native stubs preserved).
- Importers/exporters may now depend on `forgelab.formats` (shared neutral
  format primitives) in addition to `forgelab.spec`.
- `forgelab.importers.threed` and `forgelab.exporters.threed` are now packages
  (glTF implemented; Blender/Unreal native stubs preserved).

[Unreleased]: https://github.com/forgelab/forgelab/commits/main
