# ForgeLab

**The LLVM of design.** ForgeLab is a universal design interchange format and
compiler that lets AI agents create, read, and transform design files across
tools and domains — without ever touching proprietary file formats.

ForgeLab defines a JSON-based **intermediate representation (IR)** that sits
between AI agents and design software. Any tool can *import* into ForgeLab IR;
any tool can *export* from it. Agents operate entirely in ForgeLab JSON.

```
native file ──import──▶ ForgeLab IR ──transform──▶ ForgeLab IR ──export──▶ native file
                          ▲                                        │
                          └──────────── AI agents ─────────────────┘
                                   (pure JSON, no proprietary formats)
```

## Why JSON?

The IR is JSON so it is **natively emittable by any LLM or AI agent** with no
special training. Every document declares a `forgelab_version` so tools can
reason about long-term compatibility.

## Launch domains

| Domain         | Tools (targeted)       |
| -------------- | ---------------------- |
| Hardware       | KiCad, Altium, Gerber  |
| Mechanical CAD | Fusion 360, FreeCAD    |
| 3D / Game      | Blender, Unreal Engine |

> Importers and exporters for these tools are scaffolded as stubs today. The
> spec, validator, pipeline, SDK, and API are real and working.

## Install

```bash
pip install -e ".[dev,api]"
```

## Quickstart (SDK)

```python
from forgelab.sdk import new_document, dump, load

doc = new_document(domain="hardware", name="blinky")
text = dump(doc)          # JSON an agent can emit/consume
restored = load(text)     # validated back into a ForgeDocument
```

## Quickstart (API)

```bash
uvicorn forgelab.api.app:app --reload
```

| Method | Path             | Purpose                          |
| ------ | ---------------- | -------------------------------- |
| GET    | `/health`        | Liveness + spec version          |
| GET    | `/spec`          | ForgeDocument JSON Schema        |
| POST   | `/validate`      | Validate a ForgeLab document     |
| POST   | `/export/{tool}` | Export IR to a tool (stub → 501) |

## Repository layout

```
forgelab/
├── spec/        # IR models (Pydantic v2), versioning, JSON Schema export
├── core/        # validate(), registry, compiler pipeline, errors
├── importers/   # tool → IR  (base ABC + domain stubs)
├── exporters/   # IR → tool  (base ABC + domain stubs)
├── sdk/         # AI agent helpers
└── api/         # FastAPI compiler-as-a-service
```

## Status

Pre-alpha (v0.1). The IR, validation, pipeline, SDK, and API work end-to-end;
tool importers/exporters are stubs awaiting contribution.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues: implement an importer
or exporter for one tool against the `Importer`/`Exporter` base classes.

## License

[Apache 2.0](LICENSE).
