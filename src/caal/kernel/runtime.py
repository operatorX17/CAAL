from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Tuple
from uuid import uuid4

from caal.kernel.contracts import NormalizedInputEvent, TraceContext
from caal.kernel.service import get_kernel_service


def handle_kernel_chat_request(
    *,
    user_id: str,
    text: str,
    session_id: str | None,
    metadata: Dict[str, Any] | None,
) -> Tuple[str, list[dict], dict]:
    service = get_kernel_service()
    resolved_session_id = session_id or os.urandom(6).hex()
    event = NormalizedInputEvent(
        event_id=uuid4(),
        timestamp=datetime.utcnow(),
        user_id=user_id,
        session_id=resolved_session_id,
        channel="chat",
        type="user_message",
        payload={"text": text, "metadata": metadata or {}},
        trace=TraceContext(span_id=str(uuid4())),
    )
    with service.kernel.handle_stream(resolved_session_id) as stream:
        response = service.kernel.handle(event, context={"latest_user_text": text})
        stream.close()
        events = [event.to_dict() for event in stream]
    return resolved_session_id, events, response.to_dict()
