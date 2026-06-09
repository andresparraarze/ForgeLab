# Contributing to ForgeLab

Thanks for helping build the universal design interchange format!

## Development setup

```bash
git clone https://github.com/forgelab/forgelab
cd forgelab
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,api]"
```

## Workflow

1. Create a branch off `main`.
2. Write tests first (we use TDD). Tests live in `tests/`.
3. Implement until green.
4. Run the full check suite locally before pushing.

## Checks (must pass)

```bash
ruff check .          # lint
ruff format --check . # formatting
pyright               # type checking
pytest                # tests
```

CI runs all of these on every push and pull request.

## Adding an importer or exporter

This is the highest-leverage contribution. Each tool plugs in via a base class:

- Importers subclass `forgelab.importers.base.Importer`, set `tool_name`, and
  implement `to_ir(source: bytes) -> ForgeDocument`.
- Exporters subclass `forgelab.exporters.base.Exporter`, set `tool_name`, and
  implement `from_ir(document: ForgeDocument) -> bytes`.

Register new classes in `forgelab/core/pipeline.py:default_registry`. Importers
and exporters must depend on `forgelab.spec` only — never on each other.

## Spec changes

The IR lives in `forgelab/spec/`. Any change to `ForgeDocument` is a spec change:
bump `SPEC_VERSION` in `forgelab/spec/version.py` (major bump for breaking
changes) and note it in `CHANGELOG.md`.

## Commit style

Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `build:`, `refactor:`.

## Code of Conduct

Be excellent to each other. Harassment is not tolerated.
