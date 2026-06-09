from pathlib import Path

from forgelab.formats import parse

FIXTURE = (
    Path(__file__).resolve().parent.parent / "examples" / "hardware" / "blinky.kicad_pcb"
)


def test_fixture_parses_as_kicad_pcb():
    tree = parse(FIXTURE.read_text())
    assert tree[0] == "kicad_pcb"
