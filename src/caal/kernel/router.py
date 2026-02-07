from __future__ import annotations

from typing import Any, Dict

from caal.kernel.contracts import NormalizedInputEvent


class Router:
    def route(self, event: NormalizedInputEvent, state: Dict[str, Any]) -> Dict[str, Any]:
        metadata = event.payload.get("metadata", {})
        forced_route = metadata.get("route")
        if forced_route in {"FAST", "TOOL", "CAPABILITY"}:
            return {
                "route": forced_route,
                "intent": metadata.get("intent"),
                "step": metadata.get("step"),
                "confidence": metadata.get("confidence", 0.5),
            }
        if metadata.get("tool_name"):
            return {
                "route": "TOOL",
                "intent": metadata.get("intent", "tool_use"),
                "step": metadata.get("step", "tool_execution"),
                "confidence": 0.7,
            }
        return {"route": "FAST", "intent": "chat", "step": "respond", "confidence": 0.6}
