from __future__ import annotations

from typing import Any, Dict, Iterable, List

from caal.tools.tool_catalog import ToolMetadata


class ToolGate:
    def enabled_tools(
        self,
        context: Dict[str, Any],
        installed_tools: Iterable[ToolMetadata],
        state: Dict[str, Any],
    ) -> List[str]:
        raise NotImplementedError


class AllowlistToolGate(ToolGate):
    def __init__(self, allowlist: Dict[str, List[str]] | None = None) -> None:
        self._allowlist = allowlist or {}

    def enabled_tools(
        self,
        context: Dict[str, Any],
        installed_tools: Iterable[ToolMetadata],
        state: Dict[str, Any],
    ) -> List[str]:
        session_allowlist = context.get("allowed_tools")
        if session_allowlist is None:
            intent = state.get("intent") or "default"
            session_allowlist = self._allowlist.get(intent, [])
        installed_names = {tool.name for tool in installed_tools}
        return [name for name in session_allowlist if name in installed_names]
