from __future__ import annotations

from datetime import datetime
from typing import Any, Dict
from uuid import uuid4

from caal.kernel.contracts import NormalizedInputEvent, TraceContext
from caal.kernel.kernel import Kernel


def handle_chat_message(
    kernel: Kernel,
    user_id: str,
    session_id: str,
    text: str,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    event = NormalizedInputEvent(
        event_id=uuid4(),
        timestamp=datetime.utcnow(),
        user_id=user_id,
        session_id=session_id,
        channel="chat",
        type="user_message",
        payload={"text": text, "metadata": metadata or {}},
        trace=TraceContext(span_id=str(uuid4())),
    )
    response = kernel.handle(event, context={"latest_user_text": text})
    return response.to_dict()
