from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol
from uuid import UUID


@dataclass(frozen=True)
class TraceContext:
    parent_span_id: Optional[str] = None
    span_id: Optional[str] = None


@dataclass(frozen=True)
class NormalizedInputEvent:
    event_id: UUID
    timestamp: datetime
    user_id: str
    session_id: str
    channel: str
    type: str
    payload: Dict[str, Any]
    trace: TraceContext = field(default_factory=TraceContext)


@dataclass(frozen=True)
class Event:
    event_id: UUID
    session_id: str
    timestamp: datetime
    type: str
    payload: Dict[str, Any]
    trace: TraceContext = field(default_factory=TraceContext)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "type": self.type,
            "payload": self.payload,
            "trace": {
                "parent_span_id": self.trace.parent_span_id,
                "span_id": self.trace.span_id,
            },
        }


@dataclass
class KernelMessage:
    type: str
    text: str
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "text": self.text,
            "metadata": self.metadata,
        }


@dataclass
class KernelResponse:
    messages: List[KernelMessage]
    emitted_events: List[Event]
    state: Dict[str, Any]
    tool_requests: Optional[List[Dict[str, Any]]] = None
    telemetry: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "messages": [message.to_dict() for message in self.messages],
            "emitted_events": [event.to_dict() for event in self.emitted_events],
            "state": self.state,
            "tool_requests": self.tool_requests,
            "telemetry": self.telemetry,
        }


@dataclass
class ToolResult:
    status: str
    output: Optional[Dict[str, Any]]
    error: Optional[str]
    started_at: datetime
    finished_at: datetime
    idempotency_key: str
    tool_call_id: str
    deduped: bool = False
    original_tool_call_id: Optional[str] = None


class Capability(Protocol):
    def execute(self, state: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        ...
