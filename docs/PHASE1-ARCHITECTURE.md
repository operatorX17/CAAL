# Phase 1 Kernel + Event Sourcing Foundation

## Overview
Phase 1 establishes a deterministic Kernel that orchestrates routing and tool/capability execution. The Kernel does **not** embed LLM prompts or tool logic. It relies on adapters to normalize inputs into events and uses event sourcing for the canonical record of conversation history.

## Contracts (Canonical Types)
Defined in `src/caal/kernel/contracts.py`.

- **NormalizedInputEvent**: normalized user/system input with `event_id`, `timestamp`, `user_id`, `session_id`, `channel`, `type`, `payload`, `trace`.
- **Event**: append-only event record, includes `event_id`, `session_id`, `timestamp`, `type`, `payload`, `trace`.
- **KernelResponse**: returned by Kernel with `messages`, `emitted_events`, `state`, optional `tool_requests`, and `telemetry`.
- **ToolResult**: deterministic tool execution result with idempotency support.

## Event Sourcing + Projection
- **EventStore** (`src/caal/kernel/event_store.py`) is append-only and queryable by `session_id`.
- **StateProjector** (`src/caal/kernel/projector.py`) derives **CanonicalConversationState** by reducing the event stream. Recovery is done by replaying events.
  - Projection currently reacts to: `ROUTE_DECIDED`, `TOOL_PLANNED`, `TOOL_SUCCEEDED`, `STATE_SNAPSHOT`, `TOOL_CATALOG_UPDATED`, `TOOL_GATE_EVALUATED`.

## Event Taxonomy (Emitted in Phase 1)
`USER_MESSAGE_RECEIVED`, `ROUTE_DECIDED`, `TOOL_CATALOG_UPDATED`, `TOOL_GATE_EVALUATED`, `TOOL_PLANNED`, `TOOL_STARTED`, `TOOL_SUCCEEDED`, `TOOL_FAILED`, `TOOL_DEDUPED`, `CAPABILITY_STARTED`, `CAPABILITY_FINISHED`, `ASSISTANT_MESSAGE_EMITTED`.

## Kernel Responsibilities vs Capabilities/Tools
- **Kernel** (`src/caal/kernel/kernel.py`) is pure orchestration:
  1. Append `USER_MESSAGE_RECEIVED`
  2. Load history and project state
  3. Route (FAST / TOOL / CAPABILITY)
  4. Run capability or tool via interfaces
  5. Append resulting events
  6. Emit `ASSISTANT_MESSAGE_EMITTED`
  7. Return `KernelResponse`
- **Capabilities** implement business logic or LLM-backed behavior but are **pluggable**. Example: `FastLLMResponse` capability.
- **Tools** are managed through:
  - `ToolCatalog` (installed tools)
  - `ToolGate` (enabled tools for this session)
  - `ToolRunner` (execution + idempotency)

## Idempotency (Phase 1)
Tool execution idempotency is enforced durably in SQLite by `(session_id, tool_name, idempotency_key)`. A deduped call emits `TOOL_DEDUPED` with the original tool call id and still returns the recorded result.

## Extending to PersonaPlex + Registry Later
- **PersonaPlex** becomes another adapter that emits `NormalizedInputEvent` into the Kernel (no business logic in the adapter).
- **Tool registry** can populate `ToolCatalog` and configure `ToolGate` without changing Kernel logic.
- **Additional LLM providers** can be registered as new Capabilities behind the `CapabilityRunner`.

## How to Run Locally (Phase 1)
### 1) Start a minimal chat flow
```bash
python - <<'PY'
from uuid import uuid4
from caal.adapters.chat.adapter import handle_chat_message
from caal.kernel.event_store import SQLiteEventStore
from caal.kernel.kernel import Kernel
from caal.tools.python_tools import PythonToolRunner, uppercase_tool
from caal.tools.tool_catalog import InMemoryToolCatalog, ToolMetadata
from caal.tools.tool_gate import AllowlistToolGate

store = SQLiteEventStore("/tmp/caal-events.db")

catalog = InMemoryToolCatalog({
    "uppercase": ToolMetadata(name="uppercase", description="Uppercase tool", version="1.0"),
})

gate = AllowlistToolGate({"tool_use": ["uppercase"]})
runner = PythonToolRunner({"uppercase": uppercase_tool})

kernel = Kernel(event_store=store, tool_catalog=catalog, tool_gate=gate, tool_runner=runner)

response = handle_chat_message(
    kernel,
    user_id="user-1",
    session_id="session-1",
    text="hello tools",
    metadata={"tool_name": "uppercase", "tool_input": {"text": "hello"}},
)
print(response["messages"])
PY
```

### 2) See events appended
```bash
python - <<'PY'
from caal.kernel.event_store import SQLiteEventStore

store = SQLiteEventStore("/tmp/caal-events.db")
for event in store.list_by_session("session-1"):
    print(event.type, event.payload)
PY
```

### 3) See projected state
```bash
python - <<'PY'
from caal.kernel.event_store import SQLiteEventStore
from caal.kernel.projector import project_state

store = SQLiteEventStore("/tmp/caal-events.db")
state = project_state(store.list_by_session("session-1"))
print(state)
PY
```

### 4) Replay state for a session
```bash
python -m caal.cli.replay --db-path /tmp/caal-events.db --session-id session-1
```
