"""KiCad PCB (.kicad_pcb) exporter: ForgeLab IR -> S-expression text.

Rebuilds the typed hardware vocabulary from the IR node graph and emits a
complete, functional ``kicad_pcb`` S-expression. Depends only on
``forgelab.spec`` and ``forgelab.formats`` (never on importers/exporters/core).
"""

from __future__ import annotations

import math

from forgelab.exporters.base import Exporter
from forgelab.formats import Symbol, dumps
from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    Component,
    DesignRules,
    ForgeDocument,
    Net,
)

_DEFAULT_LAYERS = [
    [0, Symbol("F.Cu"), Symbol("signal")],
    [31, Symbol("B.Cu"), Symbol("signal")],
    [44, Symbol("Edge.Cuts"), Symbol("user")],
]


def _num(value: float) -> int | float:
    """Emit integral floats as ints so output matches KiCad's style."""
    return int(value) if float(value).is_integer() else float(value)


def _s(tag: str, *args: object) -> list:
    """Build an S-expression list headed by a bare ``tag`` symbol."""
    return [Symbol(tag), *args]


# KiCad stores a file-format version as a bare integer date stamp, never a
# quoted semantic version. Map known application versions to their format date
# and fall back to a known-good value for anything unrecognized or missing.
_DEFAULT_FORMAT_VERSION = 20221018
_SEMVER_TO_FORMAT = {
    "6.0": 20211014,
    "7.0": 20221018,
    "8.0": 20240108,
    "9.0": 20240108,
}


def _format_version(raw: str) -> int:
    """Normalize a kicad_version field to KiCad's unquoted integer date stamp."""
    text = (raw or "").strip()
    if text.isdigit():
        return int(text)
    if text in _SEMVER_TO_FORMAT:
        return _SEMVER_TO_FORMAT[text]
    major = text.split(".")[0]
    for semver, fmt in _SEMVER_TO_FORMAT.items():
        if semver.split(".")[0] == major:
            return fmt
    return _DEFAULT_FORMAT_VERSION


_PAD_GRID_PITCH = 2.0


def _grid_offset(index: int, total: int) -> tuple[float, float]:
    """Deterministic (x, y) for a pad that carries no explicit ``at``.

    Lays pads out on a centred square-ish grid so a multi-pin part never
    collapses onto the footprint origin. Purely a visual fallback — agents
    should supply real offsets via ``Pad.at`` when the package geometry is known.
    """
    cols = max(1, math.ceil(math.sqrt(total)))
    row, col = divmod(index, cols)
    rows = math.ceil(total / cols)
    x = (col - (cols - 1) / 2) * _PAD_GRID_PITCH
    y = (row - (rows - 1) / 2) * _PAD_GRID_PITCH
    return x, y


class KiCadExporter(Exporter):
    """Export ForgeLab IR to a KiCad PCB."""

    tool_name = "kicad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        board = self._board(document)
        nets = self._nets(document)
        components = self._components(document)
        name_to_code = {n.name: n.code for n in nets}

        tree: list = [Symbol("kicad_pcb")]
        tree.append(_s("version", _format_version(board.kicad_version)))
        tree.append(_s("generator", Symbol(board.generator)))
        tree.append(_s("general", _s("thickness", 1.6)))
        tree.append(_s("paper", "A4"))
        tree.append(self._layers_block(board))
        tree.append(self._setup_block(board.design_rules))
        for net in sorted(nets, key=lambda n: n.code):
            tree.append(_s("net", net.code, net.name))
        tree.append(self._net_class_block(board.design_rules, nets))
        for comp in components:
            tree.append(self._footprint(comp, name_to_code))
        for seg in board.outline:
            tree.append(
                _s(
                    "gr_line",
                    _s("start", _num(seg.start[0]), _num(seg.start[1])),
                    _s("end", _num(seg.end[0]), _num(seg.end[1])),
                    _s("stroke", _s("width", 0.1), _s("type", Symbol("solid"))),
                    _s("layer", "Edge.Cuts"),
                )
            )

        return dumps(tree).encode("utf-8")

    def _board(self, document: ForgeDocument) -> BoardConstraints:
        for node in document.nodes:
            if node.type == NODE_BOARD:
                return BoardConstraints.model_validate(node.props)
        return BoardConstraints(
            kicad_version="20240108",
            generator="forgelab",
            layers=[],
            outline=[],
            design_rules=DesignRules(
                clearance=0.2, track_width=0.25, via_diameter=0.8, via_drill=0.4
            ),
        )

    def _nets(self, document: ForgeDocument) -> list[Net]:
        nets = [Net.model_validate(n.props) for n in document.nodes if n.type == NODE_NET]
        if not any(n.code == 0 for n in nets):
            nets.insert(0, Net(code=0, name=""))
        return nets

    def _components(self, document: ForgeDocument) -> list[Component]:
        return [
            Component.model_validate(n.props) for n in document.nodes if n.type == NODE_COMPONENT
        ]

    def _layers_block(self, board: BoardConstraints) -> list:
        entries: list = [Symbol("layers")]
        if board.layers:
            rows = [
                [
                    layer.ordinal,
                    Symbol(layer.canonical_name),
                    Symbol(layer.layer_type),
                ]
                + ([layer.user_name] if layer.user_name else [])
                for layer in board.layers
            ]
        else:
            rows = [list(row) for row in _DEFAULT_LAYERS]
        entries.extend(rows)
        return entries

    def _setup_block(self, rules: DesignRules) -> list:
        # KiCad 9 rejects design-rule keys inside (setup ...); they live in
        # net classes instead (see _net_class_block).
        return _s("setup", _s("pad_to_mask_clearance", 0))

    def _net_class_block(self, rules: DesignRules, nets: list[Net]) -> list:
        block = _s(
            "net_class",
            "Default",
            "ForgeLab default net class",
            _s("clearance", _num(rules.clearance)),
            _s("trace_width", _num(rules.track_width)),
            _s("via_dia", _num(rules.via_diameter)),
            _s("via_drill", _num(rules.via_drill)),
        )
        for net in sorted(nets, key=lambda n: n.code):
            if net.name:
                block.append(_s("add_net", net.name))
        return block

    def _footprint(self, comp: Component, name_to_code: dict[str, int]) -> list:
        fp: list = [Symbol("footprint"), comp.footprint, _s("layer", comp.layer)]
        if comp.uuid is not None:
            fp.append(_s("uuid", comp.uuid))
        fp.append(_s("at", _num(comp.at[0]), _num(comp.at[1]), _num(comp.at[2])))
        fp.append(_s("property", "Reference", comp.reference))
        fp.append(_s("property", "Value", comp.value))
        total = len(comp.pads)
        for index, pad in enumerate(comp.pads):
            code = name_to_code.get(pad.net, 0)
            # Honor an explicit pad offset; otherwise spread pads on a grid so
            # a multi-pin part doesn't collapse onto the footprint origin.
            if pad.at is not None:
                x, y = pad.at[0], pad.at[1]
            else:
                x, y = _grid_offset(index, total)
            width, height = (pad.size[0], pad.size[1]) if pad.size else (1.6, 1.6)
            shape = pad.shape if pad.shape else "roundrect"
            fp.append(
                _s(
                    "pad",
                    pad.number,
                    Symbol("smd"),
                    Symbol(shape),
                    _s("at", _num(x), _num(y)),
                    _s("size", _num(width), _num(height)),
                    _s("layers", "F.Cu"),
                    _s("net", code, pad.net),
                )
            )
        return fp
