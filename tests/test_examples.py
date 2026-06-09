import json
from pathlib import Path

from forgelab.core import validate

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_all_examples_validate():
    files = list(EXAMPLES.rglob("*.forge.json"))
    assert files, "expected at least one example document"
    for path in files:
        data = json.loads(path.read_text())
        validate(data)  # raises if invalid
