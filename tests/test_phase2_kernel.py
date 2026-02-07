from __future__ import annotations

from datetime import datetime
import time
from uuid import uuid4

from caal.adapters.chat.adapter import handle_chat_message
from caal.kernel.async_executor import ImmediateExecutor
from caal.kernel.contracts import NormalizedInputEvent, TraceContext
from caal.kernel.event_store import SQLiteEventStore
from caal.kernel.kernel import Kernel
from caal.kernel.projector import project_state
from caal.kernel.policy import SideEffectApprovalPolicy
from caal.kernel.retry_policy import RetryPolicy
from caal.kernel.streaming import EventBus
from caal.tools.python_tools import PythonToolRunner, uppercase_tool
from caal.tools.tool_catalog import InMemoryToolCatalog, ToolMetadata
from caal.tools.tool_gate import AllowlistToolGate


def _build_kernel(
    store: SQLiteEventStore,
    tools: dict,
    catalog: InMemoryToolCatalog,
    event_bus: EventBus | None = None,
) -> Kernel:
    gate = AllowlistToolGate(
        {"tool_use": list(tools.keys()), "default": list(tools.keys())}
    )
    runner = PythonToolRunner(tools, db_path=":memory:")
    return Kernel(
        event_store=store,
        tool_catalog=catalog,
        tool_gate=gate,
        tool_runner=runner,
        async_executor=ImmediateExecutor(),
        approval_policy=SideEffectApprovalPolicy(),
        retry_policy=RetryPolicy(max_attempts=2, base_backoff_ms=1),
        event_bus=event_bus,
    )


def test_human_approval_pause_and_resume() -> None:
    store = SQLiteEventStore(":memory:")
    catalog = InMemoryToolCatalog(
        {
            "uppercase": ToolMetadata(
                name="uppercase",
                description="Uppercase tool",
                version="1.0",
                side_effect=True,
            )
        }
    )
    kernel = _build_kernel(store, {"uppercase": uppercase_tool}, catalog)
    response = handle_chat_message(
        kernel,
        user_id="user-1",
        session_id="session-1",
        text="please run tool",
        metadata={"tool_name": "uppercase", "tool_input": {"text": "hello"}},
    )
    event_types = [event["type"] for event in response["emitted_events"]]
    assert "HUMAN_APPROVAL_REQUESTED" in event_types
    assert "EXECUTION_PAUSED" in event_types
    approval_event = next(
        event for event in response["emitted_events"] if event["type"] == "HUMAN_APPROVAL_REQUESTED"
    )
    approval_id = approval_event["payload"]["approval_id"]
    projected = project_state(store.list_by_session("session-1"))
    approval_state = projected["execution"]["approval"]
    assert approval_state["approval_id"] == approval_id
    assert approval_state["status"] == "paused"

    approval_input = NormalizedInputEvent(
        event_id=uuid4(),
        timestamp=datetime.utcnow(),
        user_id="approver",
        session_id="session-1",
        channel="api",
        type="human_input",
        payload={"metadata": {"approval_id": approval_id, "decision": "approved"}},
        trace=TraceContext(span_id=str(uuid4())),
    )
    approval_response = kernel.handle(approval_input, context={})
    approval_events = [event.type for event in approval_response.emitted_events]
    assert "HUMAN_APPROVAL_DECISION" in approval_events
    assert "EXECUTION_RESUMED" in approval_events
    assert "TOOL_DISPATCHED" in approval_events


def test_async_retry_flow() -> None:
    store = SQLiteEventStore(":memory:")
    attempts = {"count": 0}

    def flaky_tool(payload: dict) -> dict:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("fail once")
        return {"text": "ok"}

    catalog = InMemoryToolCatalog(
        {
            "flaky": ToolMetadata(
                name="flaky",
                description="Flaky tool",
                version="1.0",
                side_effect=False,
            )
        }
    )
    kernel = _build_kernel(store, {"flaky": flaky_tool}, catalog)
    response = handle_chat_message(
        kernel,
        user_id="user-1",
        session_id="session-2",
        text="run flaky",
        metadata={"tool_name": "flaky", "tool_input": {}},
    )
    types = [event["type"] for event in response["emitted_events"]]
    assert "TOOL_DISPATCHED" in types
    history_types = [event.type for event in store.list_by_session("session-2")]
    assert "TOOL_RETRY_SCHEDULED" in history_types
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        history_types = [event.type for event in store.list_by_session("session-2")]
        if "TOOL_SUCCEEDED" in history_types:
            break
        time.sleep(0.01)
    assert "TOOL_SUCCEEDED" in history_types
    projected = project_state(store.list_by_session("session-2"))
    attempts = {entry["attempt"] for entry in projected["execution"]["tool_calls"].values()}
    assert {1, 2}.issubset(attempts)


def test_streaming_event_order() -> None:
    store = SQLiteEventStore(":memory:")
    catalog = InMemoryToolCatalog(
        {
            "uppercase": ToolMetadata(
                name="uppercase",
                description="Uppercase tool",
                version="1.0",
                side_effect=False,
            )
        }
    )
    bus = EventBus()
    kernel = _build_kernel(store, {"uppercase": uppercase_tool}, catalog, event_bus=bus)

    with kernel.handle_stream("session-3") as stream_one, kernel.handle_stream("session-4") as stream_two:
        handle_chat_message(
            kernel,
            user_id="user-1",
            session_id="session-3",
            text="stream it",
            metadata={"tool_name": "uppercase", "tool_input": {"text": "hello"}},
        )
        handle_chat_message(
            kernel,
            user_id="user-2",
            session_id="session-4",
            text="stream it too",
            metadata={"tool_name": "uppercase", "tool_input": {"text": "bye"}},
        )
        stream_one.close()
        stream_two.close()
        streamed_one = [event for event in stream_one]
        streamed_two = [event for event in stream_two]

    assert all(event.session_id == "session-3" for event in streamed_one)
    assert all(event.session_id == "session-4" for event in streamed_two)
    assert streamed_one[0].type == "USER_MESSAGE_RECEIVED"
    assert streamed_two[0].type == "USER_MESSAGE_RECEIVED"


def test_memory_propose_and_commit() -> None:
    store = SQLiteEventStore(":memory:")
    catalog = InMemoryToolCatalog({})
    kernel = _build_kernel(store, {}, catalog)
    response = handle_chat_message(
        kernel,
        user_id="user-1",
        session_id="session-4",
        text="I prefer tea",
    )
    event_types = [event["type"] for event in response["emitted_events"]]
    assert "MEMORY_PROPOSED_UPDATE" in event_types
    assert "MEMORY_COMMITTED" in event_types
