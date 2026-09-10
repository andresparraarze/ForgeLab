"""KiCad's installed footprint libraries, as a read-only lookup.

ForgeLab names real KiCad footprints (``Resistor_SMD:R_0603_1608Metric``). Until
this module existed it also *invented* their copper — square pads from a shared
default — so a board claimed a library part while carrying geometry that was not
it. KiCad noticed: ``lib_footprint_mismatch`` on every footprint of the Arduino
Uno example, and, where the invented pads collapsed onto the footprint origin, a
real short between two nets.

The fix is to stop inventing and read the actual ``.kicad_mod``. Nothing is
vendored — the files come from the user's own KiCad install, which is also why
there is no redistribution question to answer.

KiCad is an OPTIONAL dependency, exactly like FreeCAD next door: ``available()``
reports whether libraries were found, ``resolve()`` returns ``None`` rather than
raising when a footprint is absent, and the exporter falls back to synthesizing
copper (and says so) when a lookup fails.

Neutral, like its neighbours: standard library plus this package's own
S-expression parser, no ``forgelab.spec`` import, no knowledge of the IR.

Where the libraries live, in the order tried:

0. ``FORGELAB_KICAD_FOOTPRINT_DIR``, which *replaces* discovery rather than
   adding to it — for pointing ForgeLab at a vendored or house library, and for
   reproducing on a KiCad machine what a machine without KiCad does.
1. ``KICAD*_FOOTPRINT_DIR`` in the environment. KiCad versions this variable
   (``KICAD10_FOOTPRINT_DIR``), so any digits are accepted rather than a fixed
   name; a newer install therefore needs no change here.
2. The platform's default install location.
3. ``.pretty`` directories named by an ``fp-lib-table`` — global or per-user.
   This is the only route that finds third-party libraries the user has added.
"""

from __future__ import annotations

import os
import platform
import re
from functools import lru_cache
from pathlib import Path

from forgelab.formats.sexpr import SExprError, parse

#: Suffix of a footprint library directory, and of one footprint inside it.
LIBRARY_SUFFIX = ".pretty"
FOOTPRINT_SUFFIX = ".kicad_mod"

#: Overrides discovery entirely when set (see the module docstring).
FORGELAB_OVERRIDE = "FORGELAB_KICAD_FOOTPRINT_DIR"

#: ``KICAD10_FOOTPRINT_DIR``, ``KICAD9_FOOTPRINT_DIR``, ... — the digits are the
#: major version, so this matches whatever the installed KiCad exports.
_ENV_RE = re.compile(r"^KICAD\d*_FOOTPRINT_DIR$")

#: Where a stock install puts the footprints, per platform. Checked in order;
#: globs cover the versioned directory Windows and macOS installers create.
_PLATFORM_DEFAULTS: dict[str, tuple[str, ...]] = {
    "Linux": (
        "/usr/share/kicad/footprints",
        "/usr/local/share/kicad/footprints",
        "/app/share/kicad/footprints",  # Flatpak
        "/var/lib/flatpak/app/org.kicad.KiCad/current/active/files/share/kicad/footprints",
    ),
    "Darwin": (
        "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
        "~/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
    ),
    "Windows": (
        r"C:\Program Files\KiCad\*\share\kicad\footprints",
        r"C:\Program Files (x86)\KiCad\*\share\kicad\footprints",
    ),
}

#: Config roots that may hold an ``fp-lib-table``. The per-user one is where a
#: third-party library the user installed gets registered.
_TABLE_LOCATIONS: tuple[str, ...] = (
    "~/.config/kicad/*/fp-lib-table",
    "~/Library/Preferences/kicad/*/fp-lib-table",
    "~/AppData/Roaming/kicad/*/fp-lib-table",
    "/usr/share/kicad/template/fp-lib-table",
    "/usr/local/share/kicad/template/fp-lib-table",
)

_UNAVAILABLE = (
    "KiCad's footprint libraries were not found. Install KiCad "
    "(https://www.kicad.org/download/) so ForgeLab can embed real footprint "
    "geometry; without them it synthesizes approximate pads instead."
)


def _expand(pattern: str) -> list[Path]:
    """Every existing directory matching a ``~``/glob pattern, sorted."""
    expanded = os.path.expanduser(pattern)
    if any(ch in expanded for ch in "*?["):
        root = Path(expanded).anchor or "."
        relative = expanded[len(root) :] if root != "." else expanded
        return sorted(p for p in Path(root).glob(relative) if p.exists())
    path = Path(expanded)
    return [path] if path.exists() else []


def _env_roots() -> list[Path]:
    """Footprint roots named by a ``KICAD*_FOOTPRINT_DIR`` environment variable."""
    roots: list[Path] = []
    for name, value in os.environ.items():
        if _ENV_RE.match(name) and value:
            roots.extend(_expand(value))
    return roots


def _platform_roots() -> list[Path]:
    roots: list[Path] = []
    for pattern in _PLATFORM_DEFAULTS.get(platform.system(), ()):
        roots.extend(_expand(pattern))
    return roots


def _table_roots() -> list[Path]:
    """``.pretty`` parents named by any ``fp-lib-table`` that can be resolved.

    A table entry's ``uri`` may be absolute, or written against a KiCad
    environment variable (``${KICAD10_FOOTPRINT_DIR}/Resistor_SMD.pretty``). The
    variable form is substituted from the environment when it is set and from
    the platform default when it is not — which is what KiCad itself does, since
    it ships that variable with a built-in default rather than writing it to
    config.
    """
    substitutions = {}
    for name, value in os.environ.items():
        if _ENV_RE.match(name) and value:
            substitutions[name] = value
    fallback = _platform_roots()

    roots: list[Path] = []
    for pattern in _TABLE_LOCATIONS:
        for table in _expand(pattern):
            for uri in _table_uris(table):
                text = uri
                for name, value in substitutions.items():
                    text = text.replace(f"${{{name}}}", value)
                match = re.search(r"\$\{(KICAD\d*_FOOTPRINT_DIR)\}", text)
                if match:
                    # Unset variable: try the platform default in its place.
                    for root in fallback:
                        candidate = Path(text.replace(match.group(0), str(root)))
                        if candidate.exists():
                            roots.append(candidate.parent)
                    continue
                candidate = Path(os.path.expanduser(text))
                if candidate.suffix == LIBRARY_SUFFIX and candidate.exists():
                    roots.append(candidate.parent)
    return roots


def _table_uris(table: Path) -> list[str]:
    """The ``uri`` of every ``(lib ...)`` in an fp-lib-table, or [] if unreadable.

    A malformed or unreadable table is not an error worth propagating: it only
    means one discovery route found nothing, and the others still run.
    """
    try:
        tree = parse(table.read_text(encoding="utf-8"))
    except (OSError, SExprError, UnicodeDecodeError):
        return []
    uris: list[str] = []
    for entry in tree:
        if not (isinstance(entry, list) and entry and str(entry[0]) == "lib"):
            continue
        for field in entry:
            if isinstance(field, list) and len(field) > 1 and str(field[0]) == "uri":
                uris.append(str(field[1]))
    return uris


@lru_cache(maxsize=1)
def library_roots() -> tuple[Path, ...]:
    """Directories that contain ``<name>.pretty`` footprint libraries.

    Deduplicated, first occurrence winning, so an explicit environment variable
    takes precedence over the platform default.
    """
    override = os.environ.get(FORGELAB_OVERRIDE)
    candidates = (
        # Deliberately authoritative: an override that finds nothing means
        # "no libraries", which is how a machine without KiCad is reproduced.
        _expand(override)
        if override is not None
        else [*_env_roots(), *_platform_roots(), *_table_roots()]
    )
    seen: dict[Path, None] = {}
    for root in candidates:
        # A directory holding no .pretty library is not a footprint root, just a
        # directory. Keeping it would make `available()` answer yes on a machine
        # where nothing can actually be resolved.
        if any(root.glob(f"*{LIBRARY_SUFFIX}")):
            seen.setdefault(root.resolve(), None)
    return tuple(seen)


def available() -> bool:
    """Whether any footprint library was found on this machine."""
    return bool(library_roots())


def reset_cache() -> None:
    """Forget everything discovered, so a changed environment is seen again."""
    library_roots.cache_clear()
    resolve.cache_clear()
    load.cache_clear()
    pad_geometry.cache_clear()
    courtyard_bbox.cache_clear()


@lru_cache(maxsize=4096)
def resolve(lib_id: str) -> Path | None:
    """Path to the ``.kicad_mod`` for ``"Library:Footprint"``, or ``None``.

    ``None`` covers every "cannot use the real thing" case — no KiCad, no such
    library, no such footprint, or an id that is not in ``lib:name`` form — so
    callers have a single fallback branch rather than four.
    """
    if not lib_id or ":" not in lib_id:
        return None
    library, _, name = lib_id.partition(":")
    if not library or not name or "/" in name or "\\" in name or ".." in name:
        return None
    for root in library_roots():
        candidate = root / f"{library}{LIBRARY_SUFFIX}" / f"{name}{FOOTPRINT_SUFFIX}"
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1024)
def load(lib_id: str) -> list | None:
    """Parsed ``(footprint ...)`` tree for ``lib_id``, or ``None`` if unusable.

    An unreadable or malformed file returns ``None`` rather than raising: a
    corrupt library entry should downgrade one footprint to synthesized copper,
    not fail the whole export.
    """
    path = resolve(lib_id)
    if path is None:
        return None
    try:
        tree = parse(path.read_text(encoding="utf-8"))
    except (OSError, SExprError, UnicodeDecodeError):
        return None
    if not (isinstance(tree, list) and tree and str(tree[0]) == "footprint"):
        return None
    return tree


def _field(node: list, tag: str) -> list | None:
    for item in node:
        if isinstance(item, list) and item and str(item[0]) == tag:
            return item
    return None


@lru_cache(maxsize=1024)
def pad_geometry(lib_id: str) -> tuple[dict, ...] | None:
    """Every copper pad of ``lib_id``, in ForgeLab's Y-up footprint-local frame.

    The exporter embeds the library footprint verbatim, but the layout and
    validation tools reason about pad copper as plain numbers — where it is, how
    big, whether it is drilled. Handing them the same real geometry the exporter
    emits is what keeps the two consistent: a router that believes a 0603 pad is
    a 1.3mm square while the board carries the library's 0.8x0.95 rectangle will
    happily route copper through it.

    Keys per pad: ``number``, ``at`` (x, y), ``size`` (w, h), ``rotation``,
    ``shape``, ``drill`` (diameter or None), ``oval`` ([w, h] or None),
    ``plated``, and ``layers``. ``None`` when the footprint cannot be read.
    """
    tree = load(lib_id)
    if tree is None:
        return None
    pads: list[dict] = []
    for node in tree:
        if not (isinstance(node, list) and node and str(node[0]) == "pad"):
            continue
        at = _field(node, "at")
        size = _field(node, "size")
        if at is None or size is None or len(at) < 3 or len(size) < 3:
            continue
        drill_node = _field(node, "drill")
        diameter: float | None = None
        oval: list[float] | None = None
        if drill_node is not None:
            rest = [x for x in drill_node[1:] if not isinstance(x, list)]
            if rest and str(rest[0]) == "oval" and len(rest) >= 3:
                oval = [float(rest[1]), float(rest[2])]
            elif rest:
                diameter = float(rest[0])
        layers_node = _field(node, "layers")
        pad_type = str(node[2]) if len(node) > 2 else "smd"
        pads.append(
            {
                "number": str(node[1]) if len(node) > 1 else "",
                # KiCad footprint-local Y is down; the IR's is up.
                "at": [float(at[1]), -float(at[2]) + 0.0],
                "size": [float(size[1]), float(size[2])],
                "rotation": float(at[3]) if len(at) > 3 else 0.0,
                "shape": str(node[3]) if len(node) > 3 else "rect",
                "drill": diameter,
                "oval": oval,
                "plated": pad_type != "np_thru_hole",
                "layers": [str(x) for x in layers_node[1:]] if layers_node else [],
            }
        )
    return tuple(pads)


#: Graphic nodes a footprint body is drawn with. Coordinates live in ``start``,
#: ``end``, ``center``, ``mid`` and ``pts``/``xy`` depending on the shape.
_GRAPHIC_TAGS = frozenset(
    {"fp_line", "fp_rect", "fp_arc", "fp_circle", "fp_poly", "fp_curve", "fp_text"}
)
_POINT_TAGS = frozenset({"start", "end", "center", "mid", "at", "xy"})


def _points(node: list) -> list[tuple[float, float]]:
    """Every (x, y) inside one graphic node, however the shape spells them."""
    found: list[tuple[float, float]] = []
    for item in node:
        if not isinstance(item, list) or not item:
            continue
        tag = str(item[0])
        if tag in _POINT_TAGS and len(item) >= 3:
            try:
                found.append((float(item[1]), float(item[2])))
            except (TypeError, ValueError):
                continue
        else:
            found.extend(_points(item))
    return found


@lru_cache(maxsize=1024)
def courtyard_bbox(lib_id: str) -> tuple[float, float, float, float] | None:
    """Extents of ``lib_id``'s courtyard, in the Y-up footprint-local frame.

    The courtyard is the footprint's own statement of how much board it needs —
    body included, not just copper — and KiCad's ``courtyards_overlap`` rule is
    exactly "two of these intersect". A placer that reserves only the pad
    bounding box packs parts closer than their bodies allow: correct-looking
    until the real footprints arrive, then a boardful of overlap errors.

    ``None`` when the footprint has no courtyard or cannot be read, in which
    case callers fall back to the pad extents.
    """
    tree = load(lib_id)
    if tree is None:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for node in tree:
        if not (isinstance(node, list) and node and str(node[0]) in _GRAPHIC_TAGS):
            continue
        layer = _field(node, "layer")
        if layer is None or not any("CrtYd" in str(x) for x in layer[1:]):
            continue
        for x, y in _points(node):
            xs.append(x)
            # KiCad footprint-local Y is down; the IR's is up.
            ys.append(-y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))
