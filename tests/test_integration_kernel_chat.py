from __future__ import annotations

import time
from pathlib import Path

from caal.kernel.event_store import SQLiteEventStore
from caal.kernel.projector import project_state
from caal.kernel.service import reset_kernel_service
from caal.kernel.runtime import handle_kernel_chat_request


def test_kernel_chat_integration(tmp_path: Path, monkeypatch) -> None:
    event_db = tmp_path / "events.db"
    tool_db = tmp_path / "tools.db"
    monkeypatch.setenv("CAAL_KERNEL_CHAT", "1")
    monkeypatch.setenv("CAAL_EVENT_DB_PATH", str(event_db))
    monkeypatch.setenv("CAAL_TOOL_DB_PATH", str(tool_db))
    reset_kernel_service()

    payload = {
        "user_id": "user-1",
        "session_id": "session-1",
        "text": "run flaky",
        "metadata": {"tool_name": "flaky", "tool_input": {"key": "demo"}},
    }
    session_id, events, response = handle_kernel_chat_request(**payload)

    event_types = [event["type"] for event in events]
    assert "USER_MESSAGE_RECEIVED" in event_types
    assert "ROUTE_DECIDED" in event_types
    assert "TOOL_PLANNED" in event_types
    assert "TOOL_DISPATCHED" in event_types
    assert "TOOL_FAILED" in event_types
    assert "TOOL_RETRY_SCHEDULED" in event_types

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        store = SQLiteEventStore(str(event_db))
        history = store.list_by_session(session_id)
        history_types = [event.type for event in history]
        if "TOOL_SUCCEEDED" in history_types:
            break
        time.sleep(0.01)
    assert "TOOL_SUCCEEDED" in history_types

    projected = project_state(history)
    assert projected["execution"]["tool_calls"]

    replay_state = project_state(history)
    assert replay_state == projected
