"""KiCad PCB (.kicad_pcb) exporter: ForgeLab IR -> S-expression text.

Rebuilds the typed hardware vocabulary from the IR node graph and emits a
complete, functional ``kicad_pcb`` S-expression. Depends only on
``forgelab.spec`` and ``forgelab.formats`` (never on importers/exporters/core).
"""

from __future__ import annotations

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


class KiCadExporter(Exporter):
    """Export ForgeLab IR to a KiCad PCB."""

    tool_name = "kicad"

    def from_ir(self, document: ForgeDocument) -> bytes:
        board = self._board(document)
        nets = self._nets(document)
        components = self._components(document)
        name_to_code = {n.name: n.code for n in nets}

        version: int | str = (
            int(board.kicad_version) if board.kicad_version.isdigit() else board.kicad_version
        )

        tree: list = [Symbol("kicad_pcb")]
        tree.append(_s("version", version))
        tree.append(_s("generator", Symbol(board.generator)))
        tree.append(_s("general", _s("thickness", 1.6)))
        tree.append(_s("paper", "A4"))
        tree.append(self._layers_block(board))
        tree.append(self._setup_block(board.design_rules))
        for net in sorted(nets, key=lambda n: n.code):
            tree.append(_s("net", net.code, net.name))
        for comp in components:
            tree.append(self._footprint(comp, name_to_code))
        for seg in board.outline:
            tree.append(
                _s(
                    "gr_line",
                    _s("start", _num(seg.start[0]), _num(seg.start[1])),
                    _s("end", _num(seg.end[0]), _num(seg.end[1])),
                    _s("layer", "Edge.Cuts"),
                    _s("width", 0.1),
                )
            )

        return dumps(tree).encode("utf-8")

    def _board(self, document: ForgeDocument) -> BoardConstraints:
        for node in document.nodes:
            if node.type == NODE_BOARD:
                return BoardConstraints.model_validate(node.props)
        return BoardConstraints(
            kicad_version="20221018",
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
        return _s(
            "setup",
            _s("pad_to_mask_clearance", 0),
            _s("clearance", _num(rules.clearance)),
            _s("trace_width", _num(rules.track_width)),
            _s("via_diameter", _num(rules.via_diameter)),
            _s("via_drill", _num(rules.via_drill)),
        )

    def _footprint(self, comp: Component, name_to_code: dict[str, int]) -> list:
        fp: list = [Symbol("footprint"), comp.footprint, _s("layer", comp.layer)]
        if comp.uuid is not None:
            fp.append(_s("uuid", comp.uuid))
        fp.append(_s("at", _num(comp.at[0]), _num(comp.at[1]), _num(comp.at[2])))
        fp.append(_s("property", "Reference", comp.reference))
        fp.append(_s("property", "Value", comp.value))
        for pad in comp.pads:
            code = name_to_code.get(pad.net, 0)
            fp.append(
                _s(
                    "pad",
                    pad.number,
                    Symbol("smd"),
                    Symbol("roundrect"),
                    _s("layers", "F.Cu"),
                    _s("net", code, pad.net),
                )
            )
        return fp
