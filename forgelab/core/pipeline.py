"""The ForgeLab compiler pipeline: import -> validate -> transform -> export.

This wires the registry to the bundled domain stubs and provides a transform
hook. Transform passes are callables ``ForgeDocument -> ForgeDocument``; the
default pipeline is the identity (no passes), ready for real passes later.
"""

from collections.abc import Callable, Sequence

from forgelab.core.registry import Registry
from forgelab.exporters.hardware import AltiumExporter, GerberExporter, KiCadExporter
from forgelab.exporters.mechanical import FreeCADExporter, Fusion360Exporter
from forgelab.exporters.threed import BlenderExporter, GltfExporter, UnrealExporter
from forgelab.importers.hardware import AltiumImporter, GerberImporter, KiCadImporter
from forgelab.importers.mechanical import FreeCADImporter, Fusion360Importer
from forgelab.importers.threed import BlenderImporter, GltfImporter, UnrealImporter
from forgelab.spec import ForgeDocument

TransformPass = Callable[[ForgeDocument], ForgeDocument]

_IMPORTERS = [
    KiCadImporter,
    GltfImporter,
    AltiumImporter,
    GerberImporter,
    Fusion360Importer,
    FreeCADImporter,
    BlenderImporter,
    UnrealImporter,
]
_EXPORTERS = [
    KiCadExporter,
    GltfExporter,
    AltiumExporter,
    GerberExporter,
    Fusion360Exporter,
    FreeCADExporter,
    BlenderExporter,
    UnrealExporter,
]


def default_registry() -> Registry:
    """Return a Registry pre-populated with the bundled domain stubs."""
    reg = Registry()
    for imp in _IMPORTERS:
        reg.register_importer(imp)
    for exp in _EXPORTERS:
        reg.register_exporter(exp)
    return reg


def transform(document: ForgeDocument, passes: Sequence[TransformPass] = ()) -> ForgeDocument:
    """Apply transform passes in order. With no passes this is the identity."""
    for p in passes:
        document = p(document)
    return document
