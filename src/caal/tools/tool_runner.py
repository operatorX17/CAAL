from __future__ import annotations

from typing import Any, Dict

from caal.kernel.contracts import ToolResult


class ToolRunner:
    def run_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        context: Dict[str, Any],
        session_id: str,
        idempotency_key: str,
    ) -> ToolResult:
        raise NotImplementedError
