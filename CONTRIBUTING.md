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
./scripts/check.sh
```

That runs five gates — `lint`, `format`, `types`, `tests`, `tests-bare` — and
you can run one at a time with `./scripts/check.sh types`. CI calls the same
script for each of its steps, so there is one place a command is written down
and the two cannot drift apart.

`tests-bare` is `pytest --no-external-tools`, and it is the gate worth knowing
about. ForgeLab shells out to FreeCAD and `kicad-cli` for ground truth; neither
is a pip dependency, both are installed on developer machines, and neither is
present in CI. Without this gate the code paths taken when a tool is *missing*
never run locally — which is exactly how a mechanical `preview_render` came to
raise the wrong exception type past a green local suite and break all four CI
interpreters. Run it before pushing anything that touches an optional external
tool.

ForgeLab's component library names footprints as **KiCad 9 and later** spell
them, and CI installs KiCad 9 for that reason. Older libraries still work: the
exporter handles the pre-9 `fp_text` spelling of a designator, and a footprint it
cannot find falls back to synthesized copper with a warning rather than a
failure. `tests/fixtures/legacy_footprints/` is a KiCad 7-era footprint kept
precisely so that path is exercised on a machine that has only a modern KiCad —
it caught the version of this feature that left every designator reading
`REF**`.

That flag hides KiCad's **footprint libraries** as well as its binaries, by
pointing `FORGELAB_KICAD_FOOTPRINT_DIR` at an empty directory. It has to: the
libraries are found by filesystem path rather than on `PATH`, so hiding
`kicad-cli` alone would leave the exporter still embedding real footprints while
CI, which has neither, took the synthesized branch nobody had run. Anything that
touches `forgelab/footprints.py` or `forgelab/formats/kicad_library.py` needs
both halves of this gate.

`./scripts/verify-install.sh` is the sixth gate, and it is not part of
`check.sh` because it is slow: it performs a *real* install into a throwaway
HOME against stub agent CLIs, talks to the resulting server over stdio, and
upgrades a git-URL install across two commits. Run it when you touch anything
under `scripts/`, `forgelab/cli.py`, or the packaging — the suite asserts what
the installers *say*, and this asserts what they do. It is what catches an MCP
registration scoped to one directory, an extra the installer forgot so a tool
fails on clean machines only, and an install that does not move when the source
does. CI runs it as its own job.

## Releasing

```bash
./scripts/release.sh patch      # or minor, major, or an explicit 0.2.0
./scripts/release.sh patch --push
```

**The version is not written down anywhere.** `hatch-vcs` derives it from the
git tag, so `git tag v0.1.0` *is* the version bump — a literal in `pyproject.toml`
would be a second copy to forget, which is exactly the state this replaced. In
between tags the build reports `0.1.1.dev47+g3919e7e`, which truthfully says
"47 commits past 0.1.0, not a release".

So `release.sh` exists for the parts a tag does not do by itself: it refuses to
tag a dirty tree, a branch other than `main`, a failing `check.sh`, a failing
`verify-install.sh`, or a CHANGELOG whose `[Unreleased]` section is empty. Then
it moves that section under a dated version heading, fixes the comparison links,
commits, and tags.

Version numbers follow [semver](https://semver.org/): `patch` for fixes,
`minor` for backwards-compatible additions (a new MCP tool, a new exporter),
`major` for a breaking change to the IR or a public API. `SPEC_VERSION` in
`forgelab/spec/version.py` is a *separate* number for the document format and
moves only when the schema does.

A test that needs one of those tools declares it, rather than computing a skip
condition of its own:

```python
from external_tools import requires_freecad


@requires_freecad
def test_the_part_builds():
    assert verify_document(document)["verified"]
```

## Adding an importer or exporter

This is the highest-leverage contribution. Each tool plugs in via a base class:

- Importers subclass `forgelab.importers.base.Importer`, set `tool_name`, and
  implement `to_ir(source: bytes) -> ForgeDocument`.
- Exporters subclass `forgelab.exporters.base.Exporter`, set `tool_name`, and
  implement `from_ir(document: ForgeDocument) -> bytes`.

Register new classes in `forgelab/core/pipeline.py:default_registry`. Importers
and exporters must depend on `forgelab.spec` and `forgelab.formats` only — never
on each other and never on `forgelab.core`. Shared file-format primitives (such
as the S-expression parser) live in `forgelab.formats`.

## Spec changes

The IR lives in `forgelab/spec/`. Any change to `ForgeDocument` is a spec change:
bump `SPEC_VERSION` in `forgelab/spec/version.py` (major bump for breaking
changes) and note it in `CHANGELOG.md`.

## Commit style

Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `build:`, `refactor:`.

## Code of Conduct

Be excellent to each other. Harassment is not tolerated.
