# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Image textures on threed materials, and the UV coordinates they need.**
  Every material was a flat PBR colour, so no surface could carry real detail —
  wood grain, brushed metal, woven fabric. Two additions close that:
  `Primitive.uvs` (a flat `[u, v]` array, one pair per position, packed like
  `positions`) and `Material.base_color_texture` (a path to an image, resolved
  relative to the document's directory the way an OBJ's companion `.mtl` is).
  Both are optional and both default to absent.

  Neither grammar was assumed. **glTF** was taken from the Khronos 2.0 schemas:
  `baseColorFactor` is specified as a "linear multiplier for the sampled texels
  of the base color texture", so colour and texture **multiply** and a textured
  material keeps its factor; `images` accepts `uri` XOR `bufferView`, with
  `mimeType` required only alongside the latter, so the image goes in as a
  self-describing base64 data URI — one self-contained `.gltf`, matching how
  geometry already travels. Exports now carry `images`/`samplers`/`textures`,
  a `baseColorTexture: {index}` (texCoord omitted, since 0 is the default), and
  a `TEXCOORD_0` VEC2/FLOAT accessor beside `POSITION`.

  **Blender** was taken from `glTF-Blender-IO`, Blender's own glTF add-on, and
  it turned up two things worth stating:
  - **V is flipped.** glTF puts the UV origin at the top-left, Blender at the
    bottom-left, and the importer converts with `u,v -> u,1-v`
    (`uvs_gltf_to_blender`). The `blender_script` exporter applies the same
    flip; without it every texture would land mirrored vertically against the
    `.gltf` export of the same document.
  - **The node graph depends on the colour.** A white `base_color` links the
    Image Texture's Color straight into Base Color; anything else goes through
    a `ShaderNodeMix` in `RGBA`/`MULTIPLY` mode, whose colour sockets must be
    addressed **by index** (6, 7, result 2) because its `A`/`B`/`Result` names
    are shared with float sockets. Both branches are copied from what Blender's
    importer builds, so a ForgeLab script and an imported `.gltf` of the same
    document produce the same material.

  Also: a mesh carrying an authored unwrap no longer takes the
  `primitive_cube_add` shortcut in the Blender exporter — rebuilding a
  cube-shaped mesh as a Blender primitive would have silently substituted
  Blender's default UV layout for the authored one.

  New `check_threed` validation (wired into `validate_document` alongside the
  hardware and mechanical checks): a textured material on a primitive with no
  `uvs` is an **error** naming both — glTF would have no `TEXCOORD_0` to point
  at and Blender would fall back to generated coordinates, i.e. a wrong render
  rather than a failure. It also catches a primitive naming a material that is
  not a material node id. UVs without a texture are not flagged; an unused
  unwrap is harmless.

  New worked example `examples/threed/textured_crate.forge.json` with a small
  committed placeholder texture (`examples/threed/textures/wood_planks.png`,
  741 bytes, plus the deterministic script that generates it). It is a unit
  crate with cube-projection UVs — 6 faces × 4 unshared corners = 24 vertices,
  each face spanning the full image — and the generator asserts every face
  winds outward. Verified live in both exports: the glTF carries the sampler,
  texture, `baseColorTexture` and a 24-count TEXCOORD_0 accessor whose embedded
  bytes compare equal to the PNG on disk, and the Blender script parses and
  emits the `ShaderNodeTexImage` + UV-layer wiring.

  **Untextured documents export byte-for-byte unchanged** in both formats. The
  pinned SHA-256s were captured by checking out the pre-change commit and
  hashing there, not read off the new code.

  Exporters gained `base_dir` (mirroring `Importer.base_dir`), which
  `export_document` sets from `document_path`; it is only needed to resolve a
  texture. One scoping limit, stated rather than papered over: the glTF
  **importer** reads UVs back but not texture references — an embedded image
  does not carry the original file path, and inventing one would break the
  round-trip in a different way.

- **`boolean` nodes in the mechanical domain — union, cut and common between
  two independently-built solids.** This closes a structural gap: every other
  mechanical feature works inside one body's own sketch/pad/pocket/loft/revolve
  chain, so two separately-modelled solids could not be combined at all. A
  `boolean` node takes `operation` (`union`/`cut`/`common`), a `base` and a list
  of `tools`, each naming a whole body or a single solid feature.

  The FreeCAD grammar was probed live before anything was written, and it is
  not what the name suggests:
  - **`Part::Boolean` cannot be instantiated** — it is an abstract base class
    (`addObject` answers "not a document object type"). The concrete types are
    `Part::MultiFuse` (union), `Part::MultiCommon` (common) and `Part::Cut`.
    The first two carry one `Shapes` link list (base first, then the tools);
    `Part::Cut` carries a `Base`/`Tool` pair.
  - **There is no `Part::MultiCut`**, so union and common take any number of
    tools in one operation while `cut` takes exactly one. The model rejects a
    multi-tool cut with a message pointing at chaining instead of silently
    dropping tools.
  - **Inputs are not consumed.** They stay real document objects — each
    operand's `InList` points at the boolean, and FreeCAD's own ViewProvider
    nests them under the result and switches them off. The exporter mirrors
    that: operands (and, for a whole body, the features it renders through)
    are hidden, the result is shown.
  - **A boolean result is a `Compound`, never a `Solid`**, even holding exactly
    one solid — pinned by a test, since any downstream `ShapeType == "Solid"`
    check would be wrong.
  - **Link scope, found the hard way.** Linking a pad that lives inside a
    `PartDesign::Body` makes every recompute log `Link(s) to object(s) '...' go
    out of the allowed scope`; so does putting the boolean outside the
    `App::Part` holding its bodies. Operands naming a feature are therefore
    lifted to the body that owns them (the body *is* the solid — what FreeCAD's
    own Part ▸ Boolean does), and the boolean joins that part's `Group`. A test
    asserts the phrase never appears in FreeCAD's output.

  `check_mechanical` validates that `base` and every id in `tools` resolve to
  real nodes, and warns when a `cut`'s tool cannot reach its base. That
  heuristic earns its place: **FreeCAD reports no error for a degenerate
  boolean** — an empty intersection, or a cut that removes everything or
  nothing, recomputes to a valid, "Up-to-date" compound with zero solids and
  volume 0. The check is deliberately coarse: it compares axis-aligned
  bounding boxes estimated from the parametric description (a pad is its
  sketch's extent extruded along the plane normal, a body is the union of its
  pads, a boolean derives from its own inputs) and warns only when the boxes do
  not touch at all. Operands whose extent cannot be derived that way — loft,
  sweep, revolve, fillet, shell — yield no box and the check passes rather than
  guessing, so it never raises a false alarm.

  New worked example `examples/mechanical/bracket_with_boss.forge.json`: a
  60 × 40 × 8 mm base plate and an r9 × 23 mm cylindrical boss, each built in
  its own body, with the boss sunk 3 mm into the plate so the union has a real
  overlap to subtract. Verified live in FreeCAD 1.1 — one valid solid,
  bounding box 60 × 40 × 28, volume **24289.38 mm³**, checked both against
  FreeCAD's own computed intersection (`plate.Shape.common(boss.Shape)`:
  19200 + 5852.787 − 763.407) and independently against the closed form, so a
  wrong answer cannot satisfy both.

- **`arc` sketch geometry in the mechanical domain.** Sketches could draw only
  `line` and `circle`, so a rounded rectangle, a slot or any filleted 2D
  outline had no direct expression — a real build worked around it by cutting a
  circle pocket. `SketchGeometry` now takes `geo_type: "arc"` with `center`,
  `radius`, `start_angle` and `end_angle` in **degrees counter-clockwise from
  +X**, sweeping counter-clockwise from start to end. That is FreeCAD's own
  Sketcher convention, verified against FreeCAD 1.1 rather than assumed: arcs
  were built through `Part.ArcOfCircle`, saved, and the resulting
  `Document.xml` read back. The exporter emits the grammar that file uses —
  `Part::GeomArcOfCircle` holding `<ArcOfCircle Center* Normal* AngleXU Radius
  StartAngle EndAngle/>`, angles in radians — and reproduces FreeCAD's own
  normalization (start wrapped into `[0, 2π)`, end pushed past it so the sweep
  stays positive), so `(-90, 0)` and `(270, 360)` serialize identically, as
  FreeCAD does.

  An arc is an *open* curve, so `check_mechanical`'s profile-closure check now
  traces loops through lines and arcs together, using an arc's two computed
  endpoints as its connection points. The pairing is also now **undirected**:
  a FreeCAD arc always sweeps counter-clockwise, so in a clockwise-traced
  outline an arc's `start` is the point the traversal leaves by, and the old
  end-meets-start rule would have rejected a perfectly closed profile for the
  direction its arcs are obliged to have. Nothing that used to pass now fails.

  New worked example `examples/mechanical/rounded_rect_plate.forge.json` — a
  60 × 40 × 6 mm plate with 8 mm rounded corners, 4 straight edges plus 4
  corner arcs. Verified live in FreeCAD 1.1: it recomputes clean into 8 edges
  (4 `LineSegment`, 4 `ArcOfCircle`), volume **14070.372 mm³** — exactly
  `60·40·6 − (4−π)·8²·6` — in a bounding box of exactly 60 × 40 × 6 at the
  origin. The bounding box is the part that pins the angle convention; a
  wrong one still closes the loop but moves the corners.

  Adding two fields to `SketchGeometry` widens every sketch geometry dict by
  `start_angle`/`end_angle` (0.0 for lines and circles), so
  `examples/mechanical/box-with-hole.forge.json` was regenerated from its
  `.FCStd`; the diff is those fields and nothing else. Archives written before
  arcs existed still read back unchanged — the codec defaults both to 0.

### Fixed
- **The `blender_script` exporter produced different bytes on different Python
  versions.** CI went red on Python 3.11 for three untextured examples
  (`organic_handle`, `space_station`, `torii_gate`) that passed on the 3.14
  development machine — the same documents, the same code, different output.

  The cause was not ordering, timestamps or hash randomisation (all ruled out:
  output is stable across repeated runs and across `PYTHONHASHSEED` values).
  The primitive detectors averaged vertex coordinates with the builtin `sum()`,
  and **CPython 3.12 changed `sum()` over floats to Neumaier compensated
  summation** ([gh-100425](https://github.com/python/cpython/issues/100425)).
  A cylinder's centre that came out as exactly `0.0` on 3.12+ came out as
  `6.27e-17` on 3.11; the exporter writes `repr()` of those floats directly
  into the generated script, so the export bytes were a function of the
  interpreter version. Measured on the real examples: of 192 centroids, the
  builtin `sum()` misses the correctly-rounded value 98 times on 3.11 and never
  on 3.14 — which is exactly why the bug was invisible locally.

  Averaging now goes through `math.fsum`, which is correctly rounded by
  definition and so has no version- or platform-dependent freedom. Verified by
  generating every example on CPython 3.11.15 (CI's exact patch version,
  installed locally) and 3.14.5 and diffing: **byte-identical**. The pinned
  byte-identity SHAs are unchanged — they were the correctly-rounded values all
  along, so the fix corrects the arithmetic rather than re-pinning the hashes.

  `tests/test_export_determinism.py` guards the property directly, checking the
  mean against exact `Fraction` arithmetic and against reordering, plus asserting
  generated scripts embed no memory addresses, home paths or timestamps.
- **The preview renderer carried the same latent summation bug.**
  `preview/render.py`'s `_compose` multiplied affine transforms with a naive
  three-term dot product per matrix cell, and those cells place the vertices the
  renderer rasterises — so a naive `sum()` would have made preview pixels depend
  on the interpreter for the same gh-100425 reason. The example transforms did
  not happen to trip it, but a realistic rotation×coordinate triple rounds one
  ULP apart (`-0.7498234660057697` naive on 3.11 vs the correctly-rounded
  `-0.7498234660057698`), so this was a real second instance, not a hypothetical.
  `_compose` now sums through `math.fsum`; fixed before it could pin a
  version-dependent raster. `test_export_determinism.py` gains matching coverage
  (an exact `Fraction` oracle over every example composition, the divergent
  triple as a direct property, and order-independence over random transforms);
  confirmed byte-stable on CPython 3.11.15 and 3.14.5.
- **CI could hide which interpreters a failure affects.** The matrix ran with
  GitHub's default `fail-fast`, so the 3.11 failure above cancelled the 3.12 job
  and left it impossible to tell whether the bug was 3.11-only. Set
  `fail-fast: false`, and extended the matrix to `3.13` and `3.14` so every
  version `requires-python = ">=3.11"` promises is actually tested — the gap
  between CI's oldest-two and the 3.14 development machine is what let this
  reach `main`.
- **The Arduino Uno board's last two DRC warning categories.**
  `kicad-cli pcb drc --refill-zones` on the routed, poured, through-hole Uno
  now reports **zero `silk_over_copper` (was 12) and zero `hole_to_hole`
  (was 2)**. Two real causes, both fixed at the source:
  - The KiCad exporter emitted a bare `(property "Reference" ...)`, which KiCad
    places at the footprint origin — the middle of the pad row on a centred
    part. References now carry an explicit `(at ...)`, `(layer "F.SilkS")` and
    font, offset clear of the pads the way the KiCad library footprints do
    (`(at 0 -2.38 0)` on a 2.54mm header), and stepped further out when the
    default spot would cross a *neighbouring* part's copper on a densely
    auto-placed board. `Value` moves to `F.Fab`, a fabrication layer that
    cannot collide with copper at all — again matching the libraries.
  - `route_board` dropped a via wherever a path changed layer, including on a
    through-hole pad of the same net whose plated barrel already joins the
    layers. Such vias are now suppressed: a second drill hole beside the pad's
    own bought nothing and tripped the drill-to-drill rule. The Uno loses one
    via (25 → 24) and no connectivity — same nets routed, same pours.

  After both fixes the **only** violations KiCad reports on that board are 24
  `lib_footprint_*` warnings: ForgeLab's synthesized footprints do not
  byte-match the installed KiCad libraries. That is a separate footprint-fidelity
  question, not a board defect, and it is not fixed here.

  Note: reference-designator placement changes every KiCad export, SMD included,
  so the pinned all-SMD byte-identity SHA was deliberately re-pinned once.

### Added
- **Through-hole / drill support in the hardware domain.** `Pad` gains an
  optional `drill` (`{diameter}` round, `{oval: [w, h]}` slot, `plated` true by
  default); omitting it is SMD — the unchanged default, proven byte-identical by
  a pinned SHA of the all-SMD blinky export, the same guard the glTF alphaMode
  fix used. A drilled pad exports as a real through-hole pad in both formats: in
  KiCad as `thru_hole`/`np_thru_hole` with `(drill ...)` / `(drill oval ...)`
  and `(layers "*.Cu" "*.Mask")`, and in the Gerber/Excellon drill file as a
  hole per through-hole pad (round holes flashed, oval drills as `G85` slots)
  grouped by diameter alongside vias. **All grammar verified against real KiCad
  10.0.3 footprint files** (a top-of-pad `(drill ...)` on `*.Cu`+`*.Mask`, not a
  guess) and round-tripped through `kicad-cli`. The bundled library's genuinely
  through-hole parts (all `PinHeader-*`, the ICSP header, the JST connector)
  carry real drill diameters from their `.kicad_mod` files; `check_fabrication`
  validates each drill against the fab's `min_drill_size`.
  - **This resolves the +5V-plane connectivity gap the zone work exposed.**
    Real before/after on the Arduino Uno (headers made through-hole): the +5V
    `B.Cu` pour now connects straight to its through-hole pads, so
    `kicad-cli pcb drc --refill-zones` goes from **10 `isolated_copper`
    warnings to 0** with still zero errors — no "Update Footprints from Library"
    step needed. The router now treats a through-hole pad as copper on both
    layers (else a `B.Cu` track shorts against the pad's back-side copper — 18
    real shorts caught by kicad-cli) and keeps tracks a board-edge clearance
    inside the outline (else edge-clearance errors). Those two correctness fixes
    drop the Uno auto-route from 25 to ~21 signal nets — an honest trade for a
    DRC-error-clean, edge-clean board. The two cosmetic warning categories the
    larger pads introduced (silk-over-copper, same-net hole-to-hole) are fixed
    under **Fixed** above. The SMD crystal and reset button in the example keep
    their real SMD footprints and are untouched.
- **Copper zones / pours in the hardware domain.** A new `zone` node type
  (net, layer, boundary polygon, clearance, min_thickness) expresses filled
  copper planes — the way every real 2-layer board carries power and ground,
  which previously had no representation at all (the Arduino Uno build left GND
  and +5V unrouted for lack of one). The KiCad exporter emits real `(zone ...)`
  pours whose grammar was verified against actual KiCad 10 output — an unfilled
  boundary that KiCad fills itself (a solid `connect_pads` connection, so a
  plane never produces starved-thermal errors); ForgeLab does not reimplement
  KiCad's fill. Polygon points are Y-flipped through the same Y-up→Y-down
  pinning as every other coordinate.
  - **`route_board` now auto-pours** a genuinely pour-shaped power/ground net
    (more than 5 pads, spanning at least half the board in one axis and 15% of
    its area) that the maze router can't trace, instead of failing it: it moves
    from `nets_failed` into a new `nets_poured` list and gains a `zone`. The
    largest plane goes on `F.Cu` (connecting its SMD pads immediately), the next
    on `B.Cu`. Signal nets that merely lost to congestion are left in
    `nets_failed` untouched. On the Arduino Uno, GND and +5V are now poured
    rather than failed — verified live end to end, with `kicad-cli pcb drc
    --refill-zones` reporting **zero error-level copper violations** on the
    export (the pours fill, connect their F.Cu pads, and short nothing).
  - **`check_fabrication` validates zones** conservatively against the fab's
    spacing rules — pour clearance/min_thickness below the fab minimums,
    same-layer different-net boundary overlaps, and foreign copper lying outside
    a pour but within clearance of its boundary (copper *inside* the boundary is
    poured around, not flagged). The heuristic thresholds were adjusted after
    live testing: `auto_place` packs parts into a band, collapsing one axis of
    even a real ground net, so a strict both-axes span rule rejected the very
    nets it was meant to catch. `check_gerber_completeness` now warns that the
    Gerber exporter does not render pours yet.
- **Standalone Codex CLI installer** — `scripts/install-codex.sh`, a one-line
  `curl | bash` that fully sets ForgeLab up for Codex with no prior install:
  it runs the new generic `scripts/install.sh` (venv at `~/.forgelab/venv`,
  `forgelab[mcp,agent]`, `~/forgelab-output`, PATH setup — all idempotent, so
  running the Claude Code and Codex one-liners on the same machine reuses the
  same install), then registers the server via `codex mcp add`.
  `scripts/install-claude-code.sh` is now a thin wrapper over the same
  `install.sh` plus `claude mcp add`; the README's Codex section is a single
  one-liner and no longer assumes a prior ForgeLab install. The Hermes and
  OpenClaw README prompts now start from the same `install.sh` one-liner
  instead of describing a manual clone, and both were verified live:
  `list_domains` returns all three domains over `streamable-http` on port
  8001 and over stdio.

- **README "Updating" section** documenting `forgelab update`, live-verified
  before writing: a venv deliberately pinned to a pre-fix commit (MCP server
  binding port 8000 despite `--port 8001`) picked up the fix with a single
  `forgelab update` (rebinding 8001), and both client registrations survived
  untouched — Claude Code reported the server Connected afterwards, since
  every client points at the same `~/.forgelab/venv` path.

### Fixed
- **`forgelab-mcp --port` (and `--host`) were accepted and silently
  ignored** whenever auth was disabled — which is the default. Found by
  live-verifying the README's Hermes prompt: `forgelab-mcp --transport
  streamable-http --port 8001` actually bound FastMCP's default port 8000.
  The unauthenticated `create_server` branch now passes `host`/`port`
  through, the CLI test asserts the server *receives* the port (not just
  that argparse parses it), and the served port was re-verified live on
  8001.
- **A real bug that silently broke every translucent material in glTF export,
  found by importing an export into Blender:** the exporter wrote a
  material's base-color alpha into `baseColorFactor` but never set
  `alphaMode`, and per the glTF 2.0 spec the default `OPAQUE` mode makes
  compliant viewers ignore that alpha entirely — a glass material with alpha
  0.3 imported into Blender (File → Import → glTF 2.0) rendered as solid
  opaque blue. Any threed document with glass, water, or any other
  translucent material was exporting broken glTF. The exporter now emits
  `alphaMode: "BLEND"` whenever base-color alpha < 1.0 and still leaves
  `alphaMode` unset for fully opaque materials (glTF's `OPAQUE` default is
  correct there — opaque output is byte-for-byte unchanged, verified against
  the re-exported `space_station` example). `Material.base_color` also now
  accepts `[r, g, b]` as shorthand for `[r, g, b, 1.0]` (fully opaque),
  mirroring the `[x, y]` → `[x, y, 0]` shorthand of `Component.at`.
  Regression-tested: alpha 0.3 → explicit `BLEND`, alpha 1.0 and RGB-only →
  no `alphaMode` key, and the translucent value survives the import → export
  round-trip.
- **A real correctness/trust bug that could produce shorted boards, found by
  running KiCad's own DRC on a routed export: `route_board` placed vias as
  dimensionless grid points (on top of foreign pads and other vias), and
  `check_fabrication` reported `passed: true` anyway because it only checked
  track-vs-track clearance.** Reproduced before the fix: `kicad-cli pcb drc`
  on the auto-placed, auto-routed Arduino Uno example reported **199 shorting
  items** (tracks over foreign pads, vias on pads — including a via landing
  on a +5V pad — via pairs overlapping) plus 221 clearance and 53 drill-hole
  violations, while `check_fabrication` said `passed: true`. After the fix
  the same pipeline yields **zero copper violations of any kind** under
  `kicad-cli pcb drc` (KiCad 10.0.3; the only remaining reports are
  footprint-library bookkeeping with no copper meaning), and
  `check_fabrication` correctly fails the old broken output with 216
  distinct errors. The fix, in layers:
  - **Router — vias are real copper now:** a layer-agnostic via-legality
    plane forbids a layer change wherever the via's `via_diameter` barrel
    would come within `clearance` of another net's pad copper, routed tracks
    or committed vias (edge-to-edge, exact point-to-rectangle distance), and
    keeps a 0.25mm drill-to-drill wall between via holes of *any* net. A net
    with no legal via location fails cleanly into `nets_failed` — never an
    unsafe via.
  - **Router/placement — pads are real copper now:** the same DRC run
    exposed a sibling of the via bug: size-less pads (all 119 pads of the
    Uno example) were routed/packed as dimensionless points while both
    exporters render 1.6×1.6mm copper for them, and that fixed default even
    overlaps its own neighbours on fine-pitch parts. There is now a single
    shared source of truth in `forgelab.spec.hardware`: a pitch-aware
    `pad_default_size` (`min(1.6, min_pitch − 0.3)`, floored at 0.3mm) and a
    shared `pad_grid_offset` fallback grid, used identically by the KiCad
    exporter, the Gerber exporter, `auto_place` (bounding boxes now cover pad
    copper, not centre points), `route_board` (pads obstruct their real
    rendered rectangle plus clearance plus half a track width) and
    `check_fabrication`. Contested grid cells where two nets' clearance
    zones overlap are now blocked for everyone instead of handed to the
    later pad.
  - **`check_fabrication` — real geometric collision checks:** via-to-pad,
    via-to-via, pad-to-pad, and (beyond the original report, because the DRC
    run showed they were the *largest* short category) track-to-pad and
    track-to-via clearance across nets, with exact rotated-rectangle/circle
    distances measured against the same copper the exporters render.
    Same-net contact (e.g. via-in-pad) stays legal. Messages state the gap,
    name both nets, and say "short circuit" when copper overlaps.
  - **Default routing grid changed 0.2mm → 0.15mm**, re-tuned against honest
    obstacles: 0.15 routes 25/32 Uno nets in ~4s (0.2 manages only 17 —
    0.8mm-pitch QFP escape corridors don't survive 0.2mm quantization; 0.1
    drops to 20 at twice the runtime) and divides the default
    track_width + clearance (0.45mm) exactly.
  - **Tests (686 total, 14 new):** property-style checks across 8 seeded
    crossing-net boards that every routed via keeps clearance to foreign
    pads and vias (plus a vacuity guard proving the boards actually via);
    the two confirmed-real regression fixtures (a via on a +5V pad, two vias
    0.1mm apart on different nets) plus track-over-pad and the same-net
    via-in-pad legality case; the Uno integration test now asserts the
    routed board passes `check_fab_rules`; and a kicad-cli-gated integration
    test asserts the routed Uno export stays free of copper DRC violations.
    One pre-existing fixture in `test_check_fab_rules_validates_routed_geometry`
    turned out to contain exactly this class of short (a 0.8mm via
    overlapping a parallel track 0.45mm away) — the fixture was corrected,
    not the check.

### Changed
- **The hardware IR's Y-axis convention is now pinned and enforced: Y-up,
  origin at the board outline's lower-left corner, rotation counterclockwise**
  — resolving the ambiguity flagged by the health audit, where KiCad output
  (Y-down), Gerber output (Y-up) and `calculate_board_layout`'s documented
  lower-left origin only agreed by accident. The convention is normative in
  `forgelab.spec.hardware` (module + Board/Component/Pad/Track/Via
  docstrings). Consequences, each explicit and commented rather than
  incidental:
  - The **KiCad exporter now really flips Y** (it previously passed IR values
    through verbatim — the audit's "confirm the flip" turned out to be "add
    the flip"): absolute Y is mirrored about the outline's vertical centre
    (`y_file = ymin + ymax − y_ir`, pure negation without an outline),
    pad-local Y offsets are negated, rotation angles pass through (CCW on
    screen in both frames). The **KiCad importer applies the exact inverse**
    (with 6-decimal rounding so round-trips stay byte-identical), and
    `examples/hardware/blinky.forge.json` was regenerated with the flipping
    importer.
  - The **Gerber exporter passes IR coordinates through unchanged** —
    RS-274X/Excellon are natively Y-up — now stated explicitly in its module
    docstring as a deliberate no-flip.
  - The shared **rotation formula switched from the Y-down to the standard
    Y-up CCW form** (`(1, 0)` at 90° → `(0, 1)`) in `forgelab.layout` and the
    Gerber exporter; last release's rotation tests were updated to the pinned
    convention.
  - New `tests/test_y_axis_convention.py` pins concrete numbers on both
    sides: a component at IR `(10, 5)` on a 20mm-tall board must land at
    KiCad `(10, 15)` and Gerber `X10000000Y6000000` — a frame regression in
    either exporter now fails immediately. 672 tests green.

### Added
- **`check_gerber_completeness` MCP tool** (36 tools total). Health-audit
  finding: the Gerber pre-flight shipped as a library function only, so
  agents could not actually call it before `export_document(tool='gerber')`
  despite the README describing that workflow. Now exposed as
  `check_gerber_completeness(document_path, fab='jlcpcb')` (scope
  `forge:read`).

### Fixed
- **Component rotation is now honored consistently across the hardware
  pipeline** (health-audit finding). The KiCad exporter passes `at: [x, y,
  rotation]` through and KiCad rotates footprint pads natively — but the
  Gerber exporter, the maze router, and the placement/bounds footprint bbox
  all ignored the rotation, so a board with a rotated component (e.g.
  imported from KiCad) produced Gerber copper, routed tracks, and bounds
  checks that disagreed with KiCad's own rendering. All three now rotate pad
  offsets with KiCad's convention (positive = counterclockwise on screen in
  the shared Y-down frame): the router attaches copper at real rotated pad
  positions, `component_bbox` rotates offsets (locked obstacles and the
  board-outline containment check are rotation-aware; movable parts still
  pack at rotation 0), and the Gerber exporter rotates flashes and swaps
  rectangular/oval aperture dimensions at 90/270. A rectangular pad at a
  non-multiple-of-90 angle cannot be expressed as a standard Gerber aperture,
  so Gerber export refuses it with an actionable error instead of emitting
  copper KiCad would render elsewhere (circle pads rotate at any angle).
- **`critique_render` no longer leaks `LLMOutputError`** on a pure-prose
  vision response: the fallback JSON extractor *raises* rather than
  returning `None`, so the `is None` guard was dead code and the internal
  exception escaped. Non-JSON responses now raise the intended
  `ValueError("vision model did not return parseable critique JSON: ...")`.
- **Malformed `.forge.project` files now raise a clear `ValueError`**
  (`"project '...' is not a valid ForgeLab project: ..."`) instead of a raw
  pydantic `ValidationError` escaping `load_project`/`export_project`.
- **`check_fabrication`'s description undersold itself**: it also validates
  actually-routed track/via geometry (widths, via sizes, copper clearance),
  not just declared design rules — the docstring now says so.
- **README staleness**: the project-status paragraph still listed Gerber
  among the "scaffolded stubs" after the real RS-274X exporter shipped; it
  now correctly scopes the stub to Gerber *import*. Tool/test counts
  refreshed (36 tools, 669 tests).

### Audit notes (2026-07-04 health audit, no code change needed)
- Cross-exporter consistency verified numerically on the routed Arduino Uno:
  KiCad segments/vias and Gerber draws/flashes/drills agree exactly (184
  F.Cu segments, 44 vias, 119 pad flashes each).
- Edge cases verified green: zero-component and one-component boards through
  place → route → Gerber; 1-profile loft and 0-degree revolve rejected with
  actionable errors; 360-degree revolve valid; missing project documents
  reported per-document without aborting; empty patch arrays are no-ops;
  `generate_bom` handles zero components and pad-less/net-less parts.
- Performance at moderate scale (72 components / 40 nets / 90x70mm):
  `auto_place` <0.01s, `route_board` ~4.7s, Gerber export <0.01s — no
  quadratic blowup. The dense random netlist routes 19/40, consistent with
  the documented basic-router scope.

### Added
- **Real Gerber (RS-274X) export** — the missing final step of the hardware
  pipeline: `export_document(tool='gerber', output_path='board_gerbers.zip')`
  now writes a fab-ready zip (pure stdlib) containing F/B copper (routed
  tracks, via annulars, flashed pad apertures with correct C/R/O aperture
  definitions), F/B soldermask (pad openings with 0.05mm/side expansion), F/B
  silkscreen (reference designators in a built-in stroke font), the Edge.Cuts
  outline, and an Excellon drill file with one plated hole per via. Every
  layer carries a proper `%FSLAX46Y46*%`/`%MOMM*%` header, and the output is
  verified in tests with **gerbonara, a real Gerber parser** (new dev
  dependency): each layer parses, the full layer stack is recognized, and the
  routed Arduino Uno exports end-to-end with drill count matching the
  router's vias. New `check_gerber_completeness` pre-flight (validation
  module) re-runs the fab-rule checks and warns when a board has no routed
  tracks. The ForgeLab pad model has no through-hole concept (pads are SMD),
  so the drill file contains via holes only. Full workflow: build →
  `auto_place` → `route_board` → `check_fabrication` →
  `export_document(tool='gerber')`.

### Fixed
- **`list_formats` no longer overclaims.** Audit findings: `altium`,
  `fusion360`, `unreal`, native `blender`, and (until now) `gerber` were
  registered stubs whose import/export methods only raise
  `NotImplementedError`, yet `list_formats` reported `import: true, export:
  true` for all of them because the registry reported *registration*, not
  capability. (`unreal` is a plain stub, not a glTF alias — no description
  needed correcting, it needed to stop reporting true.) Importer/Exporter
  base classes gained an `implemented` flag; stubs set it False and
  `list_formats` now reports `altium`/`fusion360`/`unreal`/`blender` as
  `{import: false, export: false}` and `gerber` as export-only. The stubs
  stay registered so explicitly calling them still raises their helpful
  errors (e.g. blender's pointer to glTF).
- **Codex CLI install instructions** in the README's "Install in 30 seconds"
  section: a one-line `codex mcp add forgelab ...` pointing Codex at the
  existing `~/.forgelab/venv` stdio server (assumes ForgeLab itself is
  already installed), with `/mcp` as the in-session verification step.
- **Routing escape channels in automatic placement**: `auto_place` (and
  `place_components`) now keeps large components — keepout-inclusive
  footprint over an absolute 50mm², which catches QFPs/QFNs/modules but not
  passives or headers — a configurable `large_component_inset` away from
  every board edge, preserving the routing escape channels that flush corner
  packing destroyed. Smaller parts pack flush as before, and the
  zero-overlap/in-bounds guarantees, locked-component behavior and failure
  message are unchanged. Both defaults were chosen empirically against
  `route_board` on the Arduino Uno example rather than assumed: a
  board-relative 5% threshold catches nothing on a board that size (a QFP is
  1.8% of it) while over-triggering on tiny boards, and a 3mm inset actually
  reshuffled congestion for the worse (20 routed); the shipped 50mm² + 5mm
  defaults lift the routed count from 22 to 25 of 32 multi-pad nets.
- **Render-critique loop for the threed domain** — two new MCP tools (35
  total) that let an agent see and iteratively fix what it built without
  Blender installed. `preview_render(document_path, output_path, views=3)`
  (forge:read; new `forgelab[preview]` extra — matplotlib + numpy, pure pip,
  no system dependencies) walks the object graph composing transforms onto
  mesh triangles and renders a flat-shaded multi-angle PNG (front-3/4, side,
  rear-3/4; Y-up remapped for display; baked geometry only — Blender modifier
  stacks show their base meshes). `critique_render(render_path, intent,
  reference_image_path=None)` (forge:generate; same ANTHROPIC_API_KEY +
  `agent`-extra gating as `analyze_image`, injectable client) asks the vision
  model to judge the render against the intent and returns structured JSON:
  `matches_intent`, `score` 0-10, `issues` (severity/description/likely
  cause) and actionable `suggested_changes`, tolerating fenced/prose-wrapped
  responses. Deliberately two primitives, not an orchestrated loop — the
  calling agent drives render → critique → `patch_document` → re-render.
  `generation_status` now reports `preview_render`/`critique_render`
  availability alongside the existing booleans.
- **`revolve` node type in the mechanical domain** (Part workbench, alongside
  loft/sweep/fillet/shell): spin a closed 2D profile sketch around a global
  X/Y/Z axis — with partial-revolve support via `angle` (degrees, default
  360) — for axially-symmetric organic shapes like knobs, caps and
  bottle-like grips. The FreeCAD exporter emits a native `Part::Revolution`
  (Source/Axis/Base/Angle verified against FreeCAD 1.1); validation checks
  that the profile reference resolves, the angle is in (0, 360], and the
  profile stays on one side of the revolution axis (crossing it
  self-intersects; touching it is allowed — and required to close a solid
  profile). New worked example `examples/mechanical/rounded_knob.forge.json`
  (a rounded control knob), live-verified in FreeCAD: recomputes clean with
  the exact analytic volume (3099.7mm³). The mechanical system prompt now
  teaches loft-for-asymmetric vs revolve-for-symmetric shape selection.
- **Board-outline containment check** in hardware validation: `check_hardware`
  (and therefore `validate_document`) now fails — hard error, same tier as an
  undefined net reference — when any component's pad footprint extends outside
  the board outline, instead of the problem being discovered after opening
  KiCad. Footprints are sized with the same pad-bounding-box logic the
  auto-placer uses, and the error message names the fix:
  `Run auto_place to fix automatically.` Boards with no outline (already a
  warning) and components with no positioned pads are skipped gracefully.
- **Basic autorouting for the hardware domain** — KiCad exports can now carry
  real copper traces, not just a placed netlist. `forgelab/layout/routing.py`
  implements a pure-Python, zero-dependency 2-layer grid-based maze router
  (Lee's algorithm): the board outline is discretized at a configurable
  resolution (default 0.2mm), pads become fixed cells, F.Cu/B.Cu are two grid
  planes joined by vias at a cost penalty, and nets are routed shortest-span
  first so constrained connections go in before long ones block them.
  Multi-pin nets (GND/VCC) route as a minimum spanning tree, with later pads
  connecting into the net's existing copper. Unroutable nets are reported in
  `nets_failed` rather than failing the whole board. Two new IR node types —
  `track` (net, layer, start, end, width) and `via` (at, net, size, drill) —
  are emitted by the KiCad exporter as real `(segment ...)`/`(via ...)`
  S-expressions, and `check_fabrication` now validates the actually-routed
  geometry (track widths, via sizes, copper-to-copper clearance) against the
  fab profile, not just the declared design rules. New MCP tool
  **`route_board(document_path, output_path, grid_resolution=0.2, layers=2)`**
  (forge:generate scope) completes the hardware workflow: build → `auto_place`
  → `route_board` → `validate_document` → `export_document(tool='kicad')`.
  Honest scoping: this is a basic router for simple-to-moderate boards, not a
  commercial autorouter — on the Arduino Uno example it routes 22 of 32
  multi-pad nets in ~2s, with the rest (a corner-packed fine-pitch QFP's
  escapes and the highest-fanout power nets) reported for manual routing.

### Changed
- The Blender script exporter (`tool='blender_script'`) now generates a
  product-render scene rather than a bare viewport. Every script gains: a World
  shader with a procedural daylight **Sky Texture** (Hosek-Wilkie, with a
  Preetham fallback; sun elevation 45°, rotation 30°, strength 1.0) standing in
  for an HDRI; render settings (1920×1080,
  denoising via `scene.cycles.use_denoising`); a `PREVIEW` flag at the top —
  `True` uses EEVEE at 64 samples for speed, `False` uses **CYCLES** at 128
  samples for quality; an 85mm camera positioned at a 3/4 product angle
  (azimuth 45°, elevation 30°) at a distance scaled to the scene bounds; a large
  light-grey ground plane (roughness 0.8) just below the lowest geometry; and a
  closing `bpy.ops.render.render(write_still=True)` that writes
  `<script>_render.png` so running the script also produces a render.

### Fixed
- A hardware component `at` of `[x, y]` is now accepted as shorthand for
  `[x, y, 0]` (an implicit zero rotation) instead of failing validation, so the
  KiCad exporter places such components at rotation 0 rather than raising.

### Added
- Automatic component placement for the hardware domain
  (`forgelab/layout/placement.py`): a pure-Python shelf/row packing algorithm
  sizes each component from its pad bounding box plus a keepout margin
  (default 0.5mm), sorts largest-first, and packs rows left-to-right inside
  the board outline — guaranteeing zero overlap and zero components outside
  the board (the live layout bugs). Components gain an optional
  `locked: true` prop: a locked component keeps its position and the others
  pack around it as an obstacle. New MCP tool (forge:generate)
  `auto_place(document_path, output_path, keepout=0.5)` writes the placed
  document (rotation reset to 0) and returns
  `{placed, components_placed, components_locked, board_utilization}`;
  when the components cannot fit it returns a clear
  "Cannot fit N components on a board of WxH mm" error instead of an
  overlapping layout, and a missing board outline errors clearly.
- Blender modifier stack support in the threed domain: object nodes gain an
  optional ordered `modifiers` list (`subsurf`, `bevel`, `boolean`,
  `solidify`) and the Blender script exporter compiles it to native
  `obj.modifiers.new(...)` calls in stack order, so agents describe
  organic/smooth geometry as primitives + modifiers and Blender's own modifier
  evaluation computes the real result when the script runs. Boolean modifiers
  resolve their `target` node id to the bpy object created earlier in the
  script — objects are emitted in dependency (topological) order, a dependency
  cycle raises a clear error, and the consumed target is hidden from render
  and viewport. Composes with primitive detection: cube/cylinder + `subsurf` +
  `bevel` is the canonical smooth-organic pattern. New worked example
  `examples/threed/organic_handle.forge.json` (cylinder + subsurf + bevel,
  thumb-rest carved by a boolean-difference sphere) ships as a second threed
  few-shot alongside space_station. glTF export ignores `modifiers` (nothing
  is baked).
- Part-workbench feature support in the mechanical domain: four new node types
  — `loft` (blend a solid through ordered profile sketches; `ruled` and
  `closed` flags), `sweep` (drive a profile sketch along a path sketch;
  `frenet` flag), `fillet` (round a target feature's edges at a radius;
  `edges` optional — omitted means every edge, resolved analytically at export
  time), and `shell` (hollow a target solid to a wall `thickness`;
  `faces_to_remove` lists 1-based face indices to leave open). The FreeCAD
  exporter emits the matching native objects (`Part::Loft`, `Part::Sweep`,
  `Part::Fillet` with its binary `FilletEdges` archive entry, and
  `Part::Thickness` with a negative offset — the FreeCAD convention for
  hollowing inward, verified against FreeCAD 1.1); the exporter writes only
  the parametric description and FreeCAD's own OpenCASCADE kernel computes the
  real NURBS geometry on recompute. Constraint validation checks loft profile
  count (>= 2), positive fillet radius / shell thickness, and that every
  profile/path/target reference resolves. New worked example
  `examples/mechanical/organic_grip.forge.json` (smooth handle: four stacked
  circular profiles lofted then filleted) is referenced from the mechanical
  system prompt as the canonical organic-shape pattern.
- Fabrication rule validation (`forgelab/validation/fabrication.py`): named PCB
  fab profiles (`jlcpcb`, `pcbway`, `oshpark`) and `check_fab_rules(document,
  fab='jlcpcb')`, which validates a hardware document's `design_rules` (trace
  width, via diameter, via drill, and — when present — the optional `drill_size`)
  and board-outline size envelope against the profile and returns
  `{fab, passed, errors, warnings}`. Two MCP tools
  (forge:read): `check_fabrication(document_path, fab='jlcpcb')` and
  `list_fab_profiles()`. `validate_document` also runs the default (`jlcpcb`)
  fab check on any hardware board with `design_rules` and surfaces violations as
  warnings (not errors, since the target fab may differ).
- Design history tracking for documents and projects. The write tools
  (`patch_document`, `export_document`, `export_project`, `update_project`) append
  a timestamped entry to a `.forge.history` JSON array beside the file they touch
  (newest last, capped at 100 entries; best-effort — a failed history write never
  blocks the tool). Two new MCP tools (forge:read): `get_history(path)` returns
  the last 20 entries with a per-entry summary (empty when no history exists yet),
  and `get_project_summary(project_path)` returns a quick status — name,
  documents, shared dimensions, last-modified timestamp, export count, total
  changes — without loading any document.
- Hardware engineering-rule validation (`forgelab/validation/hardware.py`,
  `check_hardware`), run automatically inside `validate_document` for hardware
  documents alongside the mechanical checks. Warnings (non-fatal): an LED with no
  series current-limiting resistor, a power net (VCC/3V3/5V/VBUS/VDD) with no
  decoupling capacitor, a capacitor whose voltage rating is under 2× the supply
  inferred from a net name, and a board with no outline. Error (fatal): a
  component pad referencing a net not in the net list. Non-hardware documents
  return no findings.
- Three environmental sensors in the component library: DHT22 (4-pin 2.54mm
  SIP), BME280 (LGA-8) and SCD40 (DFN-10), under a new **Sensors** category.
- Component library (`forgelab/components/`): 32 pre-built hardware component
  definitions across six categories (microcontrollers, regulators, USB, sensors,
  passives, connectors) so agents reference known-good parts instead of
  inventing footprints. Each definition pairs a real KiCad footprint with
  datasheet-accurate pad positions — TQFP/QFP parts (ATmega328P, ATmega2560)
  use the same deterministic geometry as `calculate_pad_positions`; everything
  else carries hand-specified positions. Two MCP tools (forge:read):
  `list_components` returns all names grouped by category, and `get_component`
  returns a part's full definition (`value`, `footprint`, `description`, `pads`)
  ready to merge with a reference/layer/position into a hardware `component`
  node.
- `generate_bom` MCP tool (forge:read): extracts a bill of materials from a
  hardware document. Walks `component` nodes, pulling each one's reference,
  value, footprint, and the unique net names connected to its pads, then groups
  identical parts (same value + footprint) and sums quantities. `format='json'`
  (default) returns `{total_components, unique_parts, bom}` with comma-joined
  references and the union of nets per group; `format='csv'` returns a CSV string
  with a `Quantity, References, Value, Footprint` header. `list_formats` now notes
  `bom` as an export-only output.
- ForgeLab **projects**: a `.forge.project` JSON container (a new file type, not
  a domain document) that ties several domain documents together with a flat
  `shared` dimension table — a single source of truth every linked document can
  be checked against, so a board outline's width can inform an enclosure's inner
  width. Four MCP tools: `create_project` (forge:read) writes a project and
  infers `board_width`/`board_height` from any linked hardware document's board
  outline; `load_project` (forge:read) summarizes the shared dimensions and each
  linked document's domain, node count, and validation status without returning
  document contents; `update_project` (forge:export) changes shared dimensions
  and optionally re-validates every document and re-checks constraints;
  `export_project` (forge:export) exports all linked documents to their native
  formats in one call (default tool per domain — hardware→kicad,
  mechanical→freecad, threed→gltf — overridable per document via `tools`).
  Cross-domain constraints are informational for now: violations are reported
  but never block an export.
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
