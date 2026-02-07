from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str
    version: str
    side_effect: bool = False


class ToolCatalog:
    def list_installed(self) -> List[ToolMetadata]:
        raise NotImplementedError


class InMemoryToolCatalog(ToolCatalog):
    def __init__(self, tools: Dict[str, ToolMetadata]) -> None:
        self._tools = tools

    def list_installed(self) -> List[ToolMetadata]:
        return list(self._tools.values())
