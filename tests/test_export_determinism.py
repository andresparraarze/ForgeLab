"""The blender_script exporter must emit the same bytes on every interpreter.

The exporter writes ``repr()`` of computed floats straight into the generated
script, so any float it computes is part of the output bytes. That makes the
export only as reproducible as its arithmetic.

The trap this file guards is real and cost a red CI run: the primitive
detectors averaged coordinates with the builtin ``sum()``, and CPython 3.12
changed ``sum()`` over floats to Neumaier compensated summation (gh-100425).
Python 3.11 therefore computed a cylinder's centre as ``6.27e-17`` where 3.12+
computed ``0.0``, and the byte-identity pins passed locally while failing on
CI's 3.11 runner.

``math.fsum`` is correctly rounded by definition, so it gives the same answer on
every version and platform. These tests pin that property rather than pinning
whichever value one interpreter happens to produce.

Note on coverage: on 3.12+ the builtin ``sum()`` is accurate enough that these
tests pass even without the fix -- the defect is only observable on 3.11. That
is not a reason to weaken them; CI runs 3.11, which is where they bite.
"""

import json
import math
import random
from fractions import Fraction
from pathlib import Path

import pytest

from forgelab.core import validate
from forgelab.exporters.threed import BlenderScriptExporter
from forgelab.exporters.threed.blender_script import (
    _detect_cylinder,
    _detect_sphere,
    _mean,
    _points,
    _unique,
)
from forgelab.spec import NODE_MESH, Mesh

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples/threed"
_NAMES = ["space_station", "torii_gate", "cube", "organic_handle", "textured_crate"]


def _exact_mean(values: list[float]) -> float:
    """The correctly-rounded mean: sum exactly as rationals, then divide once.

    This is the oracle ``math.fsum(values) / len(values)`` is required to match
    -- an exact sum rounded to float, then one IEEE-754 division.
    """
    return float(sum(Fraction(v) for v in values)) / len(values)


def _all_unique_point_sets() -> list[list[tuple[float, float, float]]]:
    sets = []
    for name in _NAMES:
        doc = validate(json.loads((_EXAMPLES / f"{name}.forge.json").read_text()))
        for node in doc.nodes:
            if node.type != NODE_MESH:
                continue
            for prim in Mesh.model_validate(node.props).primitives:
                uniq = _unique(_points(prim.positions))
                if uniq:
                    sets.append(uniq)
    return sets


def test_mean_is_the_correctly_rounded_mean_over_all_example_geometry():
    """The averaging helper must agree with exact rational arithmetic.

    The builtin ``sum()`` fails this on Python 3.11 for 98 of these coordinate
    sets, which is precisely the CI failure this file exists to prevent.
    """
    checked = 0
    for uniq in _all_unique_point_sets():
        for axis in (0, 1, 2):
            values = [p[axis] for p in uniq]
            assert _mean(values) == _exact_mean(values)
            checked += 1
    assert checked > 100, f"oracle only exercised {checked} coordinate sets"


def test_mean_does_not_depend_on_the_order_its_values_arrive_in():
    """Naive left-to-right summation is order-dependent; a correct mean is not."""
    rng = random.Random(1234)
    for uniq in _all_unique_point_sets():
        if len(uniq) < 2:
            continue
        for axis in (0, 1, 2):
            values = [p[axis] for p in uniq]
            reference = _mean(values)
            for _ in range(8):
                shuffled = list(values)
                rng.shuffle(shuffled)
                assert _mean(shuffled) == reference


def test_mean_matches_fsum_not_naive_summation():
    """A direct, self-contained statement of the contract.

    24 points evenly spaced on a circle: naive summation leaves a different
    rounding residue than the correctly-rounded sum on Python 3.11.
    """
    values = [1.35 * math.cos(2 * math.pi * i / 24) for i in range(24)]
    assert _mean(values) == math.fsum(values) / len(values)
    assert _mean(values) == _exact_mean(values)


@pytest.mark.parametrize("name", _NAMES)
def test_detected_primitive_centres_are_correctly_rounded(name):
    """End-to-end: the centre a detector reports lands on the exact value.

    These centres are written verbatim into the generated script's
    ``Matrix.Translation(...)``, so a wrong rounding here is a byte difference.
    """
    doc = validate(json.loads((_EXAMPLES / f"{name}.forge.json").read_text()))
    for node in doc.nodes:
        if node.type != NODE_MESH:
            continue
        for prim in Mesh.model_validate(node.props).primitives:
            points = _points(prim.positions)
            if len(points) < 8:
                continue
            desc = _detect_cylinder(points) or _detect_sphere(points)
            if desc is None:
                continue
            uniq = _unique(points)
            expected = tuple(_exact_mean([p[axis] for p in uniq]) for axis in (0, 1, 2))
            assert desc["center"] == expected


@pytest.mark.parametrize("name", _NAMES)
def test_repeated_exports_of_one_document_are_byte_identical(name):
    """Same-process stability -- rules out ordering and identity leaks."""
    doc = validate(json.loads((_EXAMPLES / f"{name}.forge.json").read_text()))
    outputs = {BlenderScriptExporter().from_ir(doc) for _ in range(5)}
    assert len(outputs) == 1


@pytest.mark.parametrize("name", _NAMES)
def test_generated_scripts_embed_no_environment_state(name):
    """No timestamps, absolute build paths, or ``id()``-style memory addresses.

    Any of these would make the output depend on when or where it was produced.
    """
    doc = validate(json.loads((_EXAMPLES / f"{name}.forge.json").read_text()))
    src = BlenderScriptExporter().from_ir(doc).decode()
    assert "0x" not in src  # repr of an object at a memory address
    assert str(Path.home()) not in src
    for banned in ("datetime", "time.time", "Generated on", "uuid"):
        assert banned not in src
