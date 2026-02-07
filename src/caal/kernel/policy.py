from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol

from caal.tools.tool_catalog import ToolMetadata


class ApprovalPolicy(Protocol):
    def requires_approval(
        self,
        tool_metadata: ToolMetadata,
        context: Dict[str, Any],
        state: Dict[str, Any],
    ) -> bool:
        ...


@dataclass
class SideEffectApprovalPolicy:
    def requires_approval(
        self,
        tool_metadata: ToolMetadata,
        context: Dict[str, Any],
        state: Dict[str, Any],
    ) -> bool:
        return tool_metadata.side_effect


class MemoryPolicy(Protocol):
    def should_commit(
        self,
        proposal: Dict[str, Any],
        context: Dict[str, Any],
        state: Dict[str, Any],
    ) -> bool:
        ...


@dataclass
class AllowAllMemoryPolicy:
    def should_commit(
        self,
        proposal: Dict[str, Any],
        context: Dict[str, Any],
        state: Dict[str, Any],
    ) -> bool:
        return True
