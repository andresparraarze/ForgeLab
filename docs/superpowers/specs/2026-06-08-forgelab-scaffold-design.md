# ForgeLab — Repository Scaffold Design

**Date:** 2026-06-08
**Status:** Approved
**Scope:** Initial open-source repository scaffold (structure, spec backbone, stubs, one working slice, tooling).

## Vision

ForgeLab is a universal design interchange format and compiler — the **LLVM of design**. It
defines a JSON-based universal intermediate representation (IR) that sits between AI agents and
design software. Any design tool can *import* its native files into ForgeLab IR, any tool can
*export* ForgeLab IR back to its native format, and AI agents operate **entirely** in ForgeLab
JSON without ever touching proprietary formats.

The format is JSON-based on purpose: it must be natively emittable by any LLM or AI agent
without special training.

**Launch domains:**
- **Hardware** — KiCad, Altium, Gerber
- **Mechanical CAD** — Fusion 360, FreeCAD
- **3D / Game** — Blender, Unreal Engine

## Goals (this scaffold)

- A serious-from-day-one open source repo: README, Apache 2.0 LICENSE, CONTRIBUTING, CHANGELOG.
- Well-organized single `forgelab` package with clear submodule boundaries.
- A real (minimal) spec backbone using Pydantic v2, including spec versioning.
- One working end-to-end slice so the repo is not dead on arrival.
- Standard tooling: Ruff, Pyright, Pytest, GitHub Actions CI.

## Non-Goals (this scaffold)

- Full importer/exporter implementations for any tool (these are documented stubs).
- A complete IR covering every domain primitive.
- Transform-pass implementations beyond the pipeline scaffold.

## Architecture

Single installable `forgelab` package with submodules:

```
forgelab/
├── spec/        # The IR definition: Pydantic v2 models, JSON Schema export, versioning
├── core/        # Compiler engine: registry, validation, transform pipeline, import→IR→export
├── importers/   # tool → IR   (base.Importer ABC + hardware/ mechanical/ threed/ stubs)
├── exporters/   # IR → tool   (base.Exporter ABC + matching domain stubs)
├── sdk/         # AI SDK: ergonomic helpers for agents to build/read/transform IR
└── api/         # FastAPI app: /validate /import /export /transform /spec endpoints
```

Repo-level layout:

```
ForgeLab/
├── forgelab/                 # the package (above)
├── tests/                    # pytest suite
├── examples/                 # sample IR docs per domain
├── docs/                     # documentation
├── .github/workflows/ci.yml  # lint + typecheck + test
├── pyproject.toml            # package metadata + ruff/pyright/pytest config
├── README.md
├── LICENSE                   # Apache 2.0
├── CONTRIBUTING.md
└── CHANGELOG.md
```

### Module boundaries

- `importers` and `exporters` depend on `spec` only — never on each other.
- `core` orchestrates: it owns the registry and the import → validate → transform → export pipeline.
- `api` and `sdk` are thin layers over `core`.
- Each launch domain (hardware / mechanical / threed) is an independently addable plugin.

### Data flow

```
native file → Importer (registered by tool name) → ForgeDocument (validated against spec)
            → optional transform passes (core) → Exporter (registered by tool name) → native file
```

A **registry** in `core` maps tool names to importer/exporter classes so domains plug in without
modifying the core.

## The Spec Backbone (real, minimal)

`spec` defines a real but minimal Pydantic v2 model so validation actually runs:

- **`ForgeDocument`** — root model. Required field: **`forgelab_version: str`** so every document
  declares which spec version it conforms to (long-term compatibility). Plus `meta` (document
  metadata: name, generator, etc.), `domain` (enum: `hardware` | `mechanical` | `threed`), and a
  generic `nodes` graph.
- **`Node`** — generic graph node with `id`, `type`, `props`, and optional `children`/edges. This
  is intentionally generic; domain-specific node vocabularies are layered on later.
- **Spec version constant** — `SPEC_VERSION` exported from `spec`, used to stamp/validate
  `forgelab_version`. Documents with an unknown major version are rejected by the validator.
- **JSON Schema export** — a helper to emit JSON Schema from the Pydantic models (so the spec is
  consumable outside Python).

## The Working Slice

To prove the pipeline is alive:

1. `spec.ForgeDocument` is a real Pydantic model with `forgelab_version`.
2. `core.validate(doc)` actually validates a dict/JSON against the spec and checks the version.
3. `examples/hardware/blinky.forge.json` is a real sample document that validates.
4. `POST /validate` on the FastAPI app validates a posted document live.
5. Importers, exporters, and transforms are documented ABCs + domain stubs raising
   `NotImplementedError` with clear messages.

## Tooling

- **Ruff** — lint + format config in `pyproject.toml`.
- **Pyright** — type checking config.
- **Pytest** — `tests/` with passing tests: spec validation (valid + invalid + version mismatch)
  and an API smoke test via FastAPI `TestClient`.
- **GitHub Actions CI** — runs ruff, pyright, and pytest on push/PR.

## Testing Strategy

- Spec: valid document passes; missing/invalid `forgelab_version` fails; unknown domain fails.
- Core: `validate()` happy path + error path; registry register/lookup.
- API: `/validate` returns 200 for a valid doc, 422/400 for an invalid one; `/spec` returns the
  schema; health endpoint returns ok.
- Stubs: importer/exporter base ABCs instantiate via concrete stubs that raise
  `NotImplementedError`.

## Error Handling

- Validation errors surface as structured messages (Pydantic `ValidationError` mapped to a clean
  API error response).
- Version incompatibility raises a dedicated `IncompatibleVersionError`.
- Unregistered tool names raise a clear `UnknownToolError` from the registry.
