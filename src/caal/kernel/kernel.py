from __future__ import annotations

import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from caal.capabilities.fast_llm_response import FastLLMResponse
from caal.kernel.capability_runner import CapabilityRunner
from caal.kernel.contracts import (
    Event,
    KernelMessage,
    KernelResponse,
    NormalizedInputEvent,
    ToolResult,
    TraceContext,
)
from caal.kernel.async_executor import ImmediateExecutor, AsyncToolExecutor
from caal.kernel.event_store import EventStore
from caal.kernel.policy import AllowAllMemoryPolicy, ApprovalPolicy, MemoryPolicy, SideEffectApprovalPolicy
from caal.kernel.projector import project_state
from caal.kernel.router import Router
from caal.kernel.retry_policy import RetryPolicy
from caal.kernel.streaming import EventBus, EventEnvelope, SessionEventStream
from caal.memory.memory_store import MemoryStore
from caal.tools.tool_catalog import ToolCatalog, ToolMetadata
from caal.tools.tool_gate import ToolGate
from caal.tools.tool_runner import ToolRunner


class Kernel:
    def __init__(
        self,
        event_store: EventStore,
        router: Optional[Router] = None,
        capability_runner: Optional[CapabilityRunner] = None,
        tool_catalog: Optional[ToolCatalog] = None,
        tool_gate: Optional[ToolGate] = None,
        tool_runner: Optional[ToolRunner] = None,
        memory_store: Optional[MemoryStore] = None,
        approval_policy: Optional[ApprovalPolicy] = None,
        memory_policy: Optional[MemoryPolicy] = None,
        retry_policy: Optional[RetryPolicy] = None,
        async_executor: Optional[AsyncToolExecutor] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._event_store = event_store
        self._router = router or Router()
        self._capability_runner = capability_runner or CapabilityRunner(
            {"fast_llm_response": FastLLMResponse()}
        )
        self._tool_catalog = tool_catalog
        self._tool_gate = tool_gate
        self._tool_runner = tool_runner
        self._memory_store = memory_store or MemoryStore()
        self._approval_policy = approval_policy or SideEffectApprovalPolicy()
        self._memory_policy = memory_policy or AllowAllMemoryPolicy()
        self._retry_policy = retry_policy or RetryPolicy()
        self._async_executor = async_executor or ImmediateExecutor()
        self._event_bus = event_bus or EventBus()

    def handle_stream(self, session_id: str) -> SessionEventStream:
        return SessionEventStream(self._event_bus, session_id=session_id)

    def _append_event(self, event: Event, emitted_events: Optional[List[Event]] = None) -> None:
        seq = self._event_store.append(event)
        if emitted_events is not None:
            emitted_events.append(event)
        self._event_bus.publish(EventEnvelope(seq=seq, event=event))

    def handle(self, event: NormalizedInputEvent, context: Optional[Dict[str, Any]] = None) -> KernelResponse:
        start_time = time.time()
        context = context or {}
        emitted_events: List[Event] = []

        received_event = Event(
            event_id=event.event_id,
            session_id=event.session_id,
            timestamp=event.timestamp,
            type="USER_MESSAGE_RECEIVED",
            payload={
                "user_id": event.user_id,
                "channel": event.channel,
                "type": event.type,
                "payload": event.payload,
            },
            trace=event.trace,
        )
        self._append_event(received_event, emitted_events)

        history = self._event_store.list_by_session(event.session_id)
        state = project_state(history)

        if self._tool_catalog:
            installed_tools = self._tool_catalog.list_installed()
            catalog_event = Event(
                event_id=uuid4(),
                session_id=event.session_id,
                timestamp=datetime.utcnow(),
                type="TOOL_CATALOG_UPDATED",
                payload={"installed_tools": [tool.name for tool in installed_tools]},
                trace=event.trace,
            )
            self._append_event(catalog_event, emitted_events)

        if event.type == "human_input":
            return self._handle_human_input(event, state, emitted_events, context)

        route_decision = self._router.route(event, state)
        route_event = Event(
            event_id=uuid4(),
            session_id=event.session_id,
            timestamp=datetime.utcnow(),
            type="ROUTE_DECIDED",
            payload=route_decision,
            trace=event.trace,
        )
        self._append_event(route_event, emitted_events)

        messages: List[KernelMessage] = []
        tool_requests: Optional[List[Dict[str, Any]]] = None

        if route_decision["route"] == "TOOL":
            tool_name = event.payload.get("metadata", {}).get("tool_name")
            tool_input = event.payload.get("metadata", {}).get("tool_input", {})
            if not tool_name:
                messages.append(KernelMessage(type="text", text="No tool specified."))
            else:
                tool_requests = [{"tool_name": tool_name, "tool_input": tool_input}]
                allowed_tools = []
                installed_tools = []
                if self._tool_catalog and self._tool_gate:
                    installed_tools = self._tool_catalog.list_installed()
                    allowed_tools = self._tool_gate.enabled_tools(
                        context=context,
                        installed_tools=installed_tools,
                        state=state,
                    )
                    gate_event = Event(
                        event_id=uuid4(),
                        session_id=event.session_id,
                        timestamp=datetime.utcnow(),
                        type="TOOL_GATE_EVALUATED",
                        payload={"enabled_tools": allowed_tools},
                        trace=event.trace,
                    )
                    self._append_event(gate_event, emitted_events)

                if tool_name not in allowed_tools:
                    messages.append(
                        KernelMessage(
                            type="text",
                            text=f"Tool '{tool_name}' is not enabled for this session.",
                        )
                    )
                else:
                    tool_metadata = self._find_tool_metadata(tool_name, installed_tools)
                    approval_id = str(uuid4())
                    tool_call_id = str(uuid4())
                    planned_event = Event(
                        event_id=uuid4(),
                        session_id=event.session_id,
                        timestamp=datetime.utcnow(),
                        type="TOOL_PLANNED",
                        payload={
                            "tool_name": tool_name,
                            "tool_input": tool_input,
                            "approval_id": approval_id,
                            "attempt": 1,
                            "tool_call_id": tool_call_id,
                        },
                        trace=event.trace,
                    )
                    self._append_event(planned_event, emitted_events)

                    if tool_metadata and self._approval_policy.requires_approval(
                        tool_metadata, context=context, state=state
                    ):
                        approval_event = Event(
                            event_id=uuid4(),
                            session_id=event.session_id,
                            timestamp=datetime.utcnow(),
                            type="HUMAN_APPROVAL_REQUESTED",
                            payload={
                                "approval_id": approval_id,
                                "tool_name": tool_name,
                                "tool_call_id": tool_call_id,
                                "summary": f"Approve tool {tool_name} execution.",
                                "payload_preview": tool_input,
                                "risk_level": "high" if tool_metadata.side_effect else "low",
                            },
                            trace=event.trace,
                        )
                        paused_event = Event(
                            event_id=uuid4(),
                            session_id=event.session_id,
                            timestamp=datetime.utcnow(),
                            type="EXECUTION_PAUSED",
                            payload={"reason": "human_approval", "approval_id": approval_id},
                            trace=event.trace,
                        )
                        self._append_event(approval_event, emitted_events)
                        self._append_event(paused_event, emitted_events)
                        messages.append(
                            KernelMessage(
                                type="text",
                                text="Execution paused for human approval.",
                                metadata={"approval_id": approval_id},
                            )
                        )
                    else:
                        self._dispatch_tool_async(
                            session_id=event.session_id,
                            tool_name=tool_name,
                            tool_input=tool_input,
                            tool_call_id=tool_call_id,
                            attempt=1,
                            trace=event.trace,
                            context=context,
                            emitted_events=emitted_events,
                        )
                        messages.append(
                            KernelMessage(
                                type="text",
                                text="Tool execution started.",
                                metadata={"tool": tool_name},
                            )
                        )

        else:
            capability_name = "fast_llm_response"
            capability_start = Event(
                event_id=uuid4(),
                session_id=event.session_id,
                timestamp=datetime.utcnow(),
                type="CAPABILITY_STARTED",
                payload={"capability": capability_name},
                trace=event.trace,
            )
            self._append_event(capability_start, emitted_events)

            capability_result = self._capability_runner.run(
                capability_name, state=state, context=context
            )

            capability_finish = Event(
                event_id=uuid4(),
                session_id=event.session_id,
                timestamp=datetime.utcnow(),
                type="CAPABILITY_FINISHED",
                payload={"capability": capability_name},
                trace=event.trace,
            )
            self._append_event(capability_finish, emitted_events)

            for message in capability_result.get("messages", []):
                messages.append(KernelMessage(**message))
            self._handle_memory_updates(
                capability_result.get("proposed_memory_updates", []),
                event,
                state,
                emitted_events,
                context,
            )

        assistant_event = Event(
            event_id=uuid4(),
            session_id=event.session_id,
            timestamp=datetime.utcnow(),
            type="ASSISTANT_MESSAGE_EMITTED",
            payload={"messages": [asdict(message) for message in messages]},
            trace=event.trace,
        )
        self._append_event(assistant_event, emitted_events)

        projected_state = project_state(self._event_store.list_by_session(event.session_id))
        latency_ms = int((time.time() - start_time) * 1000)

        return KernelResponse(
            messages=messages,
            emitted_events=emitted_events,
            state=projected_state,
            tool_requests=tool_requests,
            telemetry={
                "latency_ms": latency_ms,
                "trace_ids": asdict(event.trace),
            },
        )

    def _run_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        context: Dict[str, Any],
        session_id: str,
    ) -> ToolResult:
        if not self._tool_runner:
            return ToolResult(
                status="failed",
                output=None,
                error="Tool runner is not configured",
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                idempotency_key="",
                tool_call_id="",
            )
        idempotency_key = context.get("idempotency_key") or str(UUID(int=0))
        return self._tool_runner.run_tool(
            tool_name=tool_name,
            tool_input=tool_input,
            context=context,
            session_id=session_id,
            idempotency_key=idempotency_key,
        )

    def _dispatch_tool_async(
        self,
        session_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_call_id: Optional[str],
        attempt: int,
        trace: TraceContext,
        context: Dict[str, Any],
        emitted_events: List[Event],
    ) -> None:
        tool_call_id = tool_call_id or str(uuid4())
        dispatch_event = Event(
            event_id=uuid4(),
            session_id=session_id,
            timestamp=datetime.utcnow(),
            type="TOOL_DISPATCHED",
            payload={
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "queue": "threadpool",
                "attempt": attempt,
            },
            trace=trace,
        )
        self._append_event(dispatch_event, emitted_events)

        execution_context = dict(context)
        execution_context["tool_call_id"] = tool_call_id

        def _execute() -> ToolResult:
            return self._run_tool(
                tool_name=tool_name,
                tool_input=tool_input,
                context=execution_context,
                session_id=session_id,
            )

        def _on_complete(result: ToolResult) -> None:
            self._handle_tool_result(
                result=result,
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_call_id=tool_call_id,
                attempt=attempt,
                trace=trace,
                context=execution_context,
            )

        self._async_executor.dispatch(_execute, on_complete=_on_complete)

    def _handle_tool_result(
        self,
        result: ToolResult,
        session_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_call_id: str,
        attempt: int,
        trace: TraceContext,
        context: Dict[str, Any],
    ) -> None:
        if result.deduped:
            deduped_event = Event(
                event_id=uuid4(),
                session_id=session_id,
                timestamp=datetime.utcnow(),
                type="TOOL_DEDUPED",
                payload={
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "attempt": attempt,
                    "idempotency_key": result.idempotency_key,
                    "original_tool_call_id": result.original_tool_call_id,
                },
                trace=trace,
            )
            self._append_event(deduped_event)
        else:
            started_event = Event(
                event_id=uuid4(),
                session_id=session_id,
                timestamp=datetime.utcnow(),
                type="TOOL_STARTED",
                payload={
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "attempt": attempt,
                },
                trace=trace,
            )
            self._append_event(started_event)

        tool_event_type = "TOOL_SUCCEEDED" if result.status == "succeeded" else "TOOL_FAILED"
        tool_event = Event(
            event_id=uuid4(),
            session_id=session_id,
            timestamp=datetime.utcnow(),
            type=tool_event_type,
            payload={
                "tool_name": tool_name,
                "status": result.status,
                "output": result.output,
                "error": result.error,
                "idempotency_key": result.idempotency_key,
                "tool_call_id": tool_call_id,
                "attempt": attempt,
            },
            trace=trace,
        )
        self._append_event(tool_event)

        if result.status != "succeeded":
            decision = self._retry_policy.evaluate(attempt)
            if decision.should_retry:
                next_tool_call_id = str(uuid4())
                retry_event = Event(
                    event_id=uuid4(),
                    session_id=session_id,
                    timestamp=datetime.utcnow(),
                    type="TOOL_RETRY_SCHEDULED",
                    payload={
                        "tool_call_id": next_tool_call_id,
                        "tool_name": tool_name,
                        "attempt": attempt + 1,
                        "backoff_ms": decision.backoff_ms,
                        "reason": result.error or "unknown",
                        "previous_tool_call_id": tool_call_id,
                        "run_at": (
                            datetime.utcnow()
                            + timedelta(milliseconds=decision.backoff_ms)
                        ).isoformat(),
                    },
                    trace=trace,
                )
                self._append_event(retry_event)
                self._schedule_retry(
                    session_id=session_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_call_id=next_tool_call_id,
                    attempt=attempt + 1,
                    trace=trace,
                    context=context,
                    backoff_ms=decision.backoff_ms,
                )
            else:
                exhausted_event = Event(
                    event_id=uuid4(),
                    session_id=session_id,
                    timestamp=datetime.utcnow(),
                    type="TOOL_RETRY_EXHAUSTED",
                    payload={
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "attempts": attempt,
                        "reason": result.error or "unknown",
                    },
                    trace=trace,
                )
                self._append_event(exhausted_event)

    def _handle_human_input(
        self,
        event: NormalizedInputEvent,
        state: Dict[str, Any],
        emitted_events: List[Event],
        context: Dict[str, Any],
    ) -> KernelResponse:
        approval_id = event.payload.get("metadata", {}).get("approval_id")
        decision = event.payload.get("metadata", {}).get("decision")
        decision_event = Event(
            event_id=uuid4(),
            session_id=event.session_id,
            timestamp=datetime.utcnow(),
            type="HUMAN_APPROVAL_DECISION",
            payload={
                "approval_id": approval_id,
                "decision": decision,
                "reviewer": event.user_id,
            },
            trace=event.trace,
        )
        resumed_event = Event(
            event_id=uuid4(),
            session_id=event.session_id,
            timestamp=datetime.utcnow(),
            type="EXECUTION_RESUMED",
            payload={"approval_id": approval_id},
            trace=event.trace,
        )
        self._append_event(decision_event, emitted_events)
        self._append_event(resumed_event, emitted_events)

        planned = self._find_planned_tool(event.session_id, approval_id)
        messages: List[KernelMessage] = []
        if decision != "approved" or not planned:
            messages.append(KernelMessage(type="text", text="Execution rejected."))
        else:
            self._dispatch_tool_async(
                session_id=event.session_id,
                tool_name=planned["tool_name"],
                tool_input=planned["tool_input"],
                tool_call_id=planned.get("tool_call_id"),
                attempt=planned.get("attempt", 1),
                trace=event.trace,
                context=context,
                emitted_events=emitted_events,
            )
            messages.append(
                KernelMessage(
                    type="text",
                    text="Execution resumed.",
                    metadata={"approval_id": approval_id},
                )
            )

        assistant_event = Event(
            event_id=uuid4(),
            session_id=event.session_id,
            timestamp=datetime.utcnow(),
            type="ASSISTANT_MESSAGE_EMITTED",
            payload={"messages": [asdict(message) for message in messages]},
            trace=event.trace,
        )
        self._append_event(assistant_event, emitted_events)
        projected_state = project_state(self._event_store.list_by_session(event.session_id))
        latency_ms = 0
        return KernelResponse(
            messages=messages,
            emitted_events=emitted_events,
            state=projected_state,
            telemetry={"latency_ms": latency_ms, "trace_ids": asdict(event.trace)},
        )

    def _find_planned_tool(self, session_id: str, approval_id: str) -> Optional[Dict[str, Any]]:
        for past in reversed(self._event_store.list_by_session(session_id)):
            if past.type == "TOOL_PLANNED" and past.payload.get("approval_id") == approval_id:
                return past.payload
        return None

    def _find_tool_metadata(
        self, tool_name: str, installed_tools: List[ToolMetadata]
    ) -> Optional[ToolMetadata]:
        for tool in installed_tools:
            if tool.name == tool_name:
                return tool
        return None

    def _handle_memory_updates(
        self,
        proposals: List[Dict[str, Any]],
        event: NormalizedInputEvent,
        state: Dict[str, Any],
        emitted_events: List[Event],
        context: Dict[str, Any],
    ) -> None:
        for proposal in proposals:
            proposal_id = str(uuid4())
            proposed_event = Event(
                event_id=uuid4(),
                session_id=event.session_id,
                timestamp=datetime.utcnow(),
                type="MEMORY_PROPOSED_UPDATE",
                payload={"proposal_id": proposal_id, "payload": proposal},
                trace=event.trace,
            )
            self._append_event(proposed_event, emitted_events)
            applied = self._memory_policy.should_commit(proposal, context=context, state=state)
            reason = None
            if applied:
                self._memory_store.propose_update(event.user_id, proposal)
                self._memory_store.commit_update(event.user_id)
            else:
                reason = "policy_rejected"
            committed_event = Event(
                event_id=uuid4(),
                session_id=event.session_id,
                timestamp=datetime.utcnow(),
                type="MEMORY_COMMITTED",
                payload={"proposal_id": proposal_id, "applied": applied, "reason": reason},
                trace=event.trace,
            )
            self._append_event(committed_event, emitted_events)

    def _schedule_retry(
        self,
        session_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_call_id: Optional[str],
        attempt: int,
        trace: TraceContext,
        context: Dict[str, Any],
        backoff_ms: int,
    ) -> None:
        def _delayed() -> None:
            self._dispatch_tool_async(
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_call_id=tool_call_id,
                attempt=attempt,
                trace=trace,
                context=context,
                emitted_events=[],
            )

        timer = threading.Timer(backoff_ms / 1000.0, _delayed)
        timer.daemon = True
        timer.start()
