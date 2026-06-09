"""KiCad PCB (.kicad_pcb) importer: S-expression text -> ForgeLab IR.

Parses the KiCad board file into the typed hardware vocabulary and stores each
component/net/board as a node in the generic IR graph. Depends only on
``forgelab.spec`` and ``forgelab.formats`` (never on importers/exporters/core).
"""

from __future__ import annotations

from typing import Any

from forgelab.formats import SExprError, parse
from forgelab.importers.base import Importer
from forgelab.spec import (
    NODE_BOARD,
    NODE_COMPONENT,
    NODE_NET,
    BoardConstraints,
    BoardLayer,
    Component,
    DesignRules,
    DocumentMeta,
    Domain,
    ForgeDocument,
    Net,
    Node,
    OutlineSegment,
    Pad,
)
from forgelab.spec.version import SPEC_VERSION


class KiCadParseError(SExprError):
    """Raised when a document is not a valid KiCad PCB."""


def _find_all(node: list, tag: str) -> list[list]:
    return [c for c in node if isinstance(c, list) and c and c[0] == tag]


def _find(node: list, tag: str) -> list | None:
    found = _find_all(node, tag)
    return found[0] if found else None


def _value(node: list, tag: str, default: Any = None) -> Any:
    child = _find(node, tag)
    if child is None or len(child) < 2:
        return default
    return child[1]


def _floats(values: list) -> list[float]:
    return [float(v) for v in values]


class KiCadImporter(Importer):
    """Import a KiCad PCB into ForgeLab IR."""

    tool_name = "kicad"

    def to_ir(self, source: bytes) -> ForgeDocument:
        try:
            tree = parse(source.decode("utf-8"))
        except SExprError as exc:
            raise KiCadParseError(str(exc)) from exc
        if not tree or tree[0] != "kicad_pcb":
            raise KiCadParseError("root element is not (kicad_pcb ...)")

        board = self._read_board(tree)
        nets = self._read_nets(tree)
        components = self._read_components(tree)

        nodes: list[Node] = [Node(id=NODE_BOARD, type=NODE_BOARD, props=board.model_dump())]
        for net in sorted(nets, key=lambda n: n.code):
            nodes.append(Node(id=f"net:{net.code}", type=NODE_NET, props=net.model_dump()))
        for comp in components:
            nodes.append(Node(id=comp.reference, type=NODE_COMPONENT, props=comp.model_dump()))

        return ForgeDocument(
            forgelab_version=SPEC_VERSION,
            domain=Domain.HARDWARE,
            meta=DocumentMeta(name="blinky", generator="forgelab-kicad"),
            nodes=nodes,
        )

    def _read_board(self, tree: list) -> BoardConstraints:
        version = str(_value(tree, "version", "20221018"))
        generator = str(_value(tree, "generator", "pcbnew"))

        layers: list[BoardLayer] = []
        layers_block = _find(tree, "layers")
        if layers_block is not None:
            for entry in layers_block[1:]:
                if isinstance(entry, list) and len(entry) >= 3:
                    layers.append(
                        BoardLayer(
                            ordinal=int(entry[0]),
                            canonical_name=str(entry[1]),
                            layer_type=str(entry[2]),
                            user_name=str(entry[3]) if len(entry) > 3 else None,
                        )
                    )

        setup = _find(tree, "setup") or []
        rules = DesignRules(
            clearance=float(_value(setup, "clearance", 0.2)),
            track_width=float(_value(setup, "trace_width", 0.25)),
            via_diameter=float(_value(setup, "via_diameter", 0.8)),
            via_drill=float(_value(setup, "via_drill", 0.4)),
        )

        outline: list[OutlineSegment] = []
        for line in _find_all(tree, "gr_line"):
            layer = _value(line, "layer")
            if layer != "Edge.Cuts":
                continue
            start = _find(line, "start")
            end = _find(line, "end")
            if start and end:
                outline.append(OutlineSegment(start=_floats(start[1:3]), end=_floats(end[1:3])))

        return BoardConstraints(
            kicad_version=version,
            generator=generator,
            layers=layers,
            outline=outline,
            design_rules=rules,
        )

    def _read_nets(self, tree: list) -> list[Net]:
        nets: list[Net] = []
        for net in _find_all(tree, "net"):
            if len(net) >= 3:
                nets.append(Net(code=int(net[1]), name=str(net[2])))
            elif len(net) == 2:
                nets.append(Net(code=int(net[1]), name=""))
        return nets

    def _read_components(self, tree: list) -> list[Component]:
        components: list[Component] = []
        for fp in _find_all(tree, "footprint"):
            footprint_id = str(fp[1]) if len(fp) > 1 else ""
            layer = str(_value(fp, "layer", "F.Cu"))
            uuid = _value(fp, "uuid")
            at_node = _find(fp, "at")
            at = _floats(at_node[1:4]) if at_node else [0.0, 0.0, 0.0]
            if len(at) == 2:
                at = [at[0], at[1], 0.0]

            reference = ""
            value = ""
            for prop in _find_all(fp, "property"):
                if len(prop) >= 3 and prop[1] == "Reference":
                    reference = str(prop[2])
                elif len(prop) >= 3 and prop[1] == "Value":
                    value = str(prop[2])

            pads: list[Pad] = []
            for pad in _find_all(fp, "pad"):
                number = str(pad[1]) if len(pad) > 1 else ""
                net_node = _find(pad, "net")
                net_name = str(net_node[2]) if net_node and len(net_node) >= 3 else ""
                pads.append(Pad(number=number, net=net_name))

            components.append(
                Component(
                    reference=reference,
                    value=value,
                    footprint=footprint_id,
                    layer=layer,
                    at=at,
                    pads=pads,
                    uuid=str(uuid) if uuid is not None else None,
                )
            )
        return components
