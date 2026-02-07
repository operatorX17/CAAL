from __future__ import annotations

from typing import Any, Dict


class FastLLMResponse:
    def execute(self, state: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        user_text = context.get("latest_user_text", "")
        response_text = f"Fast response: {user_text}" if user_text else "Fast response ready."
        proposed_memory_updates = []
        if "i prefer " in user_text.lower():
            preference = user_text.lower().split("i prefer ", 1)[1].strip()
            if preference:
                proposed_memory_updates.append({"preference": preference})
        return {
            "state_patch": {},
            "messages": [{"type": "text", "text": response_text, "metadata": {"mode": "fast"}}],
            "proposed_memory_updates": proposed_memory_updates,
        }
