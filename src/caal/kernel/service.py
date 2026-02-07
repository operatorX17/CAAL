from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional

from caal.kernel.async_executor import ImmediateExecutor
from caal.kernel.event_store import SQLiteEventStore
from caal.kernel.kernel import Kernel
from caal.kernel.retry_policy import RetryPolicy
from caal.tools.python_tools import PythonToolRunner, uppercase_tool
from caal.tools.tool_catalog import InMemoryToolCatalog, ToolMetadata
from caal.tools.tool_gate import AllowlistToolGate


@dataclass
class KernelService:
    kernel: Kernel
    event_store: SQLiteEventStore


_KERNEL_SERVICE: Optional[KernelService] = None


def _build_tools() -> Dict[str, callable]:
    call_counts: Dict[str, int] = {}

    def flaky_tool(payload: Dict[str, object]) -> Dict[str, str]:
        key = str(payload.get("key", "default"))
        count = call_counts.get(key, 0)
        if count == 0:
            call_counts[key] = 1
            raise RuntimeError("fail once")
        return {"text": "ok"}

    return {"uppercase": uppercase_tool, "flaky": flaky_tool}


def get_kernel_service() -> KernelService:
    global _KERNEL_SERVICE
    if _KERNEL_SERVICE is None:
        event_db = os.getenv("CAAL_EVENT_DB_PATH", "/tmp/caal-events.db")
        tool_db = os.getenv("CAAL_TOOL_DB_PATH", "/tmp/caal-tools.db")

        event_store = SQLiteEventStore(event_db)
        tools = _build_tools()
        catalog = InMemoryToolCatalog(
            {
                name: ToolMetadata(
                    name=name,
                    description=f"{name} tool",
                    version="1.0",
                    side_effect=False,
                )
                for name in tools.keys()
            }
        )
        gate = AllowlistToolGate({"tool_use": list(tools.keys()), "default": list(tools.keys())})
        runner = PythonToolRunner(tools, db_path=tool_db)

        kernel = Kernel(
            event_store=event_store,
            tool_catalog=catalog,
            tool_gate=gate,
            tool_runner=runner,
            async_executor=ImmediateExecutor(),
            retry_policy=RetryPolicy(max_attempts=2, base_backoff_ms=10),
        )
        _KERNEL_SERVICE = KernelService(kernel=kernel, event_store=event_store)
    return _KERNEL_SERVICE


def reset_kernel_service() -> None:
    global _KERNEL_SERVICE
    _KERNEL_SERVICE = None
