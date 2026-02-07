from __future__ import annotations

from typing import Any, Dict, Iterable

from caal.kernel.contracts import Event


INITIAL_STATE: Dict[str, Any] = {
    "intent": None,
    "step": None,
    "entities": {},
    "pending_actions": [],
    "confidence": 0.0,
    "tool_context": {"installed_tools": [], "enabled_tools": []},
    "execution": {"approval": None, "tool_calls": {}},
}


def project_state(events: Iterable[Event]) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "intent": None,
        "step": None,
        "entities": {},
        "pending_actions": [],
        "confidence": 0.0,
        "tool_context": {"installed_tools": [], "enabled_tools": []},
        "execution": {"approval": None, "tool_calls": {}},
    }
    for event in events:
        if event.type == "ROUTE_DECIDED":
            state["intent"] = event.payload.get("intent", state["intent"])
            state["step"] = event.payload.get("step", state["step"])
            state["confidence"] = event.payload.get("confidence", state["confidence"])
        if event.type == "TOOL_PLANNED":
            pending = state.get("pending_actions", [])
            pending.append(event.payload)
            state["pending_actions"] = pending
        if event.type == "TOOL_SUCCEEDED":
            state["pending_actions"] = []
        if event.type == "TOOL_FAILED":
            state["pending_actions"] = []
        if event.type == "TOOL_RETRY_EXHAUSTED":
            state["pending_actions"] = []
        if event.type == "HUMAN_APPROVAL_REQUESTED":
            state["execution"]["approval"] = {
                "approval_id": event.payload.get("approval_id"),
                "tool_name": event.payload.get("tool_name"),
                "tool_call_id": event.payload.get("tool_call_id"),
                "status": "requested",
                "requested_at": event.timestamp.isoformat(),
                "decision_at": None,
            }
        if event.type == "HUMAN_APPROVAL_DECISION":
            approval = state["execution"].get("approval") or {}
            approval["status"] = event.payload.get("decision")
            approval["decision_at"] = event.timestamp.isoformat()
            state["execution"]["approval"] = approval
        if event.type == "EXECUTION_PAUSED":
            state["step"] = "paused"
            approval = state["execution"].get("approval") or {}
            approval["status"] = "paused"
            state["execution"]["approval"] = approval
        if event.type == "EXECUTION_RESUMED":
            state["step"] = "resumed"
            approval = state["execution"].get("approval") or {}
            approval["status"] = "resumed"
            state["execution"]["approval"] = approval
        if event.type == "STATE_SNAPSHOT":
            snapshot = event.payload.get("state")
            if isinstance(snapshot, dict):
                state = snapshot
        if event.type == "TOOL_CATALOG_UPDATED":
            state["tool_context"]["installed_tools"] = event.payload.get(
                "installed_tools", state["tool_context"]["installed_tools"]
            )
        if event.type == "TOOL_GATE_EVALUATED":
            state["tool_context"]["enabled_tools"] = event.payload.get(
                "enabled_tools", state["tool_context"]["enabled_tools"]
            )
        if event.type in {
            "TOOL_DISPATCHED",
            "TOOL_STARTED",
            "TOOL_SUCCEEDED",
            "TOOL_FAILED",
            "TOOL_RETRY_SCHEDULED",
            "TOOL_RETRY_EXHAUSTED",
        }:
            tool_call_id = event.payload.get("tool_call_id")
            if tool_call_id:
                state["execution"]["tool_calls"][tool_call_id] = {
                    "tool_name": event.payload.get("tool_name"),
                    "attempt": event.payload.get("attempt"),
                    "status": event.type.lower(),
                }
    return state
