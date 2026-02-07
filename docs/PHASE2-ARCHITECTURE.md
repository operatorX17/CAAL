# Phase 2 Architecture — HITL, Async Tools, Streaming, Memory Policy

## Overview
Phase 2 adds four primitives used by future PersonaPlex and async tooling:
1) Human-in-the-loop interrupts and resume
2) Async tool execution with retry policy
3) Streaming event updates
4) Memory propose/commit policy owned by the Kernel

## Event Taxonomy (Phase 2 Additions)
- HITL: `HUMAN_APPROVAL_REQUESTED`, `HUMAN_APPROVAL_DECISION`, `EXECUTION_PAUSED`, `EXECUTION_RESUMED`
- Async: `TOOL_DISPATCHED`, `TOOL_RETRY_SCHEDULED`, `TOOL_RETRY_EXHAUSTED`
- Memory: `MEMORY_PROPOSED_UPDATE`, `MEMORY_COMMITTED`
- Streaming: events are published to the EventBus as appended (optional `STREAM_CHUNK_EMITTED`)
  - Streams are **session-scoped** and ordered by event sequence within a session.

## Sequence Diagrams (ASCII)

### HITL pause/resume
```
Adapter -> Kernel: NormalizedInputEvent(user_message)
Kernel -> EventStore: TOOL_PLANNED
Kernel -> EventStore: HUMAN_APPROVAL_REQUESTED
Kernel -> EventStore: EXECUTION_PAUSED
Kernel -> Adapter: response(paused, approval_id)

Adapter -> Kernel: NormalizedInputEvent(human_input approval)
Kernel -> EventStore: HUMAN_APPROVAL_DECISION
Kernel -> EventStore: EXECUTION_RESUMED
Kernel -> AsyncExecutor: dispatch tool
Kernel -> EventStore: TOOL_DISPATCHED
Worker -> EventStore: TOOL_SUCCEEDED/TOOL_FAILED
```

### Async tool execution + retries
```
Kernel -> EventStore: TOOL_PLANNED
Kernel -> EventStore: TOOL_DISPATCHED(attempt=1)
Worker -> EventStore: TOOL_FAILED
Kernel -> EventStore: TOOL_RETRY_SCHEDULED
Kernel -> EventStore: TOOL_DISPATCHED(attempt=2)
Worker -> EventStore: TOOL_SUCCEEDED
```

### Streaming events
```
Adapter subscribes to EventBus
Kernel appends events -> EventBus publishes events in order
Session stream filters by session_id and yields in seq order
Adapter streams session events to client
```

### Memory propose/commit
```
Capability -> Kernel: proposed_memory_updates
Kernel -> EventStore: MEMORY_PROPOSED_UPDATE
Kernel -> MemoryPolicy: should_commit
Kernel -> MemoryStore: commit_update (if approved)
Kernel -> EventStore: MEMORY_COMMITTED(applied=true/false)
```

## Projection notes
- Execution state includes approval metadata (`approval_id`, `tool_name`, `tool_call_id`, status, timestamps).
- Tool call status and attempts are tracked from tool lifecycle events.

## Local Demo (Async fail-then-succeed + streaming + replay)
```bash
python - <<'PY'
from caal.kernel.async_executor import ImmediateExecutor
from caal.kernel.event_store import SQLiteEventStore
from caal.kernel.kernel import Kernel
from caal.kernel.retry_policy import RetryPolicy
from caal.kernel.streaming import EventBus
from caal.tools.python_tools import PythonToolRunner
from caal.tools.tool_catalog import InMemoryToolCatalog, ToolMetadata
from caal.tools.tool_gate import AllowlistToolGate
from caal.adapters.chat.adapter import handle_chat_message

attempts = {"count": 0}
def flaky_tool(payload):
    attempts["count"] += 1
    if attempts["count"] == 1:
        raise RuntimeError("fail once")
    return {"text": "ok"}

store = SQLiteEventStore("/tmp/caal-events.db")
catalog = InMemoryToolCatalog({"flaky": ToolMetadata(name="flaky", description="Flaky tool", version="1.0")})
gate = AllowlistToolGate({"tool_use": ["flaky"]})
runner = PythonToolRunner({"flaky": flaky_tool}, db_path="/tmp/caal-tools.db")
bus = EventBus()

kernel = Kernel(
    event_store=store,
    tool_catalog=catalog,
    tool_gate=gate,
    tool_runner=runner,
    async_executor=ImmediateExecutor(),
    retry_policy=RetryPolicy(max_attempts=2, base_backoff_ms=10),
    event_bus=bus,
)

with kernel.handle_stream("session-1") as stream:
    response = handle_chat_message(
        kernel,
        user_id="user-1",
        session_id="session-1",
        text="run flaky",
        metadata={"tool_name": "flaky", "tool_input": {}},
    )
    stream.close()
    print("Streamed events:", [event.type for event in stream])
    print("Response messages:", response["messages"])
PY

python -m caal.cli.replay --db-path /tmp/caal-events.db --session-id session-1
```
