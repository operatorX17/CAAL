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
        if self._is_quick_reply(metadata):
            return {
                "route": "FAST",
                "intent": metadata.get("intent", "quick_reply"),
                "step": metadata.get("step", "respond"),
                "confidence": metadata.get("confidence", 0.8),
            }
        if metadata.get("tool_name"):
            return {
                "route": "TOOL",
                "intent": metadata.get("intent", "tool_use"),
                "step": metadata.get("step", "tool_execution"),
                "confidence": 0.7,
            }
        return {"route": "FAST", "intent": "chat", "step": "respond", "confidence": 0.6}

    def _is_quick_reply(self, metadata: Dict[str, Any]) -> bool:
        if metadata.get("fast_response") or metadata.get("quick_reply"):
            return True
        message_type = str(metadata.get("message_type", "")).lower()
        if message_type in {"button", "buttons", "interactive", "list", "quick_reply"}:
            return True
        interaction_type = str(metadata.get("interaction_type", "")).lower()
        if interaction_type in {"button", "list", "quick_reply"}:
            return True
        for key in ("button_reply", "list_reply", "interactive", "button", "list"):
            if key in metadata:
                return True
        return False
