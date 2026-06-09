"""Registry mapping tool names to importer/exporter classes."""

from forgelab.core.errors import UnknownToolError
from forgelab.exporters.base import Exporter
from forgelab.importers.base import Importer


class Registry:
    """Holds importer/exporter classes keyed by tool name."""

    def __init__(self) -> None:
        self._importers: dict[str, type[Importer]] = {}
        self._exporters: dict[str, type[Exporter]] = {}

    def register_importer(self, importer: type[Importer]) -> None:
        self._importers[importer.tool_name] = importer

    def register_exporter(self, exporter: type[Exporter]) -> None:
        self._exporters[exporter.tool_name] = exporter

    def get_importer(self, tool_name: str) -> type[Importer]:
        try:
            return self._importers[tool_name]
        except KeyError:
            raise UnknownToolError(f"No importer registered for tool {tool_name!r}") from None

    def get_exporter(self, tool_name: str) -> type[Exporter]:
        try:
            return self._exporters[tool_name]
        except KeyError:
            raise UnknownToolError(f"No exporter registered for tool {tool_name!r}") from None
