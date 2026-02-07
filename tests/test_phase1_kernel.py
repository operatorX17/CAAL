from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from caal.kernel.contracts import Event, TraceContext
from caal.kernel.event_store import SQLiteEventStore
from caal.kernel.projector import project_state
from caal.tools.python_tools import PythonToolRunner
from caal.tools.tool_catalog import InMemoryToolCatalog, ToolMetadata
from caal.tools.tool_gate import AllowlistToolGate


def test_event_store_append_and_query() -> None:
    store = SQLiteEventStore(":memory:")
    event = Event(
        event_id=uuid4(),
        session_id="session-1",
        timestamp=datetime.utcnow(),
        type="USER_MESSAGE_RECEIVED",
        payload={"text": "hello"},
        trace=TraceContext(span_id="span-1"),
    )
    store.append(event)
    events = store.list_by_session("session-1")
    assert len(events) == 1
    assert events[0].event_id == event.event_id
    assert events[0].payload["text"] == "hello"


def test_projection_pending_actions_clear() -> None:
    session_id = "session-1"
    events = [
        Event(
            event_id=uuid4(),
            session_id=session_id,
            timestamp=datetime.utcnow(),
            type="TOOL_PLANNED",
            payload={"tool_name": "uppercase"},
            trace=TraceContext(),
        ),
        Event(
            event_id=uuid4(),
            session_id=session_id,
            timestamp=datetime.utcnow(),
            type="TOOL_SUCCEEDED",
            payload={"tool_name": "uppercase"},
            trace=TraceContext(),
        ),
    ]
    state = project_state(events)
    assert state["pending_actions"] == []


def test_tool_runner_idempotency(tmp_path) -> None:
    call_count = {"uppercase": 0, "lowercase": 0}

    def counting_upper(payload: dict) -> dict:
        call_count["uppercase"] += 1
        return {"text": payload.get("text", "").upper()}

    def counting_lower(payload: dict) -> dict:
        call_count["lowercase"] += 1
        return {"text": payload.get("text", "").lower()}

    db_path = tmp_path / "tools.db"
    runner = PythonToolRunner(
        {"uppercase": counting_upper, "lowercase": counting_lower},
        db_path=str(db_path),
    )
    result_one = runner.run_tool(
        tool_name="uppercase",
        tool_input={"text": "hello"},
        context={},
        session_id="session-1",
        idempotency_key="key-1",
    )
    result_two = runner.run_tool(
        tool_name="uppercase",
        tool_input={"text": "hello"},
        context={},
        session_id="session-1",
        idempotency_key="key-1",
    )
    runner_restart = PythonToolRunner(
        {"uppercase": counting_upper, "lowercase": counting_lower},
        db_path=str(db_path),
    )
    result_three = runner_restart.run_tool(
        tool_name="uppercase",
        tool_input={"text": "hello"},
        context={},
        session_id="session-1",
        idempotency_key="key-1",
    )
    result_other_tool = runner.run_tool(
        tool_name="lowercase",
        tool_input={"text": "HELLO"},
        context={},
        session_id="session-1",
        idempotency_key="key-1",
    )
    result_other_session = runner.run_tool(
        tool_name="uppercase",
        tool_input={"text": "hello"},
        context={},
        session_id="session-2",
        idempotency_key="key-1",
    )

    assert result_one.output == {"text": "HELLO"}
    assert result_two.output == {"text": "HELLO"}
    assert result_three.output == {"text": "HELLO"}
    assert result_other_tool.output == {"text": "hello"}
    assert result_other_session.output == {"text": "HELLO"}
    assert call_count["uppercase"] == 2
    assert call_count["lowercase"] == 1


def test_tool_gate_allowlist() -> None:
    catalog = InMemoryToolCatalog(
        {
            "uppercase": ToolMetadata(
                name="uppercase", description="Uppercase tool", version="1.0"
            )
        }
    )
    gate = AllowlistToolGate({"tool_use": ["uppercase"]})
    state = {"intent": "tool_use"}
    enabled = gate.enabled_tools(context={}, installed_tools=catalog.list_installed(), state=state)
    assert enabled == ["uppercase"]
