# Kernel Integration (Runtime Entry Points)

## Feature Flags
- `CAAL_KERNEL_CHAT=1` enables the Kernel chat endpoint.
- `CAAL_EVENT_DB_PATH` sets the event store SQLite path (default `/tmp/caal-events.db`).
- `CAAL_TOOL_DB_PATH` sets the tool idempotency SQLite path (default `/tmp/caal-tools.db`).

## Runtime Entry Point (HTTP)
The kernel is wired into the existing FastAPI webhook server with a new endpoint:
`POST /kernel/chat` (feature-flagged).

When enabled, the endpoint:
- Creates a `NormalizedInputEvent`
- Streams session-ordered events from `Kernel.handle_stream(session_id)`
- Returns `events` + final `KernelResponse` JSON

## Smoke Test (Manual)
```bash
CAAL_KERNEL_CHAT=1 CAAL_EVENT_DB_PATH=/tmp/caal-events.db CAAL_TOOL_DB_PATH=/tmp/caal-tools.db \\
  python - <<'PY'
import uvicorn
from caal.webhooks import app
uvicorn.run(app, host="0.0.0.0", port=8889, log_level="info")
PY

curl -s http://localhost:8889/kernel/chat \\
  -H 'Content-Type: application/json' \\
  -d '{"user_id":"user-1","session_id":"session-1","text":"run flaky","metadata":{"tool_name":"flaky","tool_input":{"key":"demo"}}}'

python -m caal.cli.replay --db-path /tmp/caal-events.db --session-id session-1
```

## Voice Integration (Later)
Do not wire voice yet. The minimal seam is `voice_agent.py` at the text boundary:
transcription → `NormalizedInputEvent` → `Kernel`.
