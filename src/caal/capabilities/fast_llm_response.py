from __future__ import annotations

from typing import Any, Dict


class FastLLMResponse:
    def execute(self, state: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        user_text = context.get("latest_user_text", "")
        input_metadata = context.get("input_metadata", {}) or {}
        suppress_typing = self._should_suppress_typing(input_metadata)
        response_text = self._resolve_response_text(user_text, input_metadata, suppress_typing)
        proposed_memory_updates = []
        if "i prefer " in user_text.lower():
            preference = user_text.lower().split("i prefer ", 1)[1].strip()
            if preference:
                proposed_memory_updates.append({"preference": preference})
        return {
            "state_patch": {},
            "messages": [
                {
                    "type": "text",
                    "text": response_text,
                    "metadata": {"mode": "fast", "suppress_typing": suppress_typing},
                }
            ],
            "proposed_memory_updates": proposed_memory_updates,
        }

    def _resolve_response_text(
        self,
        user_text: str,
        input_metadata: Dict[str, Any],
        allow_override: bool,
    ) -> str:
        override_text = self._extract_override_text(input_metadata)
        if override_text and allow_override:
            return override_text
        if user_text:
            return f"Fast response: {user_text}"
        return "Fast response ready."

    def _extract_override_text(self, input_metadata: Dict[str, Any]) -> str | None:
        for key in (
            "quick_response_text",
            "response_text",
            "reply_text",
            "button_text",
            "title",
            "text",
        ):
            value = input_metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("button_reply", "list_reply", "interactive"):
            value = input_metadata.get(key)
            if isinstance(value, dict):
                for nested_key in ("title", "text", "id"):
                    nested_value = value.get(nested_key)
                    if isinstance(nested_value, str) and nested_value.strip():
                        return nested_value.strip()
        return None

    def _should_suppress_typing(self, input_metadata: Dict[str, Any]) -> bool:
        if input_metadata.get("suppress_typing") is True:
            return True
        if input_metadata.get("fast_response") or input_metadata.get("quick_reply"):
            return True
        message_type = str(input_metadata.get("message_type", "")).lower()
        interaction_type = str(input_metadata.get("interaction_type", "")).lower()
        return message_type in {"button", "buttons", "interactive", "list", "quick_reply"} or (
            interaction_type in {"button", "list", "quick_reply"}
        )
