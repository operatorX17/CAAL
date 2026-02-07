from __future__ import annotations

from datetime import datetime
import json
import sqlite3
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from caal.kernel.contracts import ToolResult
from caal.tools.tool_runner import ToolRunner


def uppercase_tool(payload: Dict[str, Any]) -> Dict[str, Any]:
    text = payload.get("text", "")
    return {"text": text.upper()}


class PythonToolRunner(ToolRunner):
    def __init__(
        self,
        tools: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]],
        db_path: str = ":memory:",
    ) -> None:
        self._tools = tools
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tool_idempotency (
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                tool_call_id TEXT NOT NULL,
                status TEXT NOT NULL,
                output TEXT,
                error TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                PRIMARY KEY (session_id, tool_name, idempotency_key)
            )
            """
        )
        self._conn.commit()

    def _load_idempotent_result(
        self,
        session_id: str,
        tool_name: str,
        idempotency_key: str,
    ) -> Optional[ToolResult]:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT tool_call_id, status, output, error, started_at, finished_at
            FROM tool_idempotency
            WHERE session_id = ? AND tool_name = ? AND idempotency_key = ?
            """,
            (session_id, tool_name, idempotency_key),
        )
        row = cursor.fetchone()
        if not row:
            return None
        if row["status"] != "succeeded":
            return None
        output_payload = json.loads(row["output"]) if row["output"] else None
        return ToolResult(
            status=row["status"],
            output=output_payload,
            error=row["error"],
            started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=datetime.fromisoformat(row["finished_at"]),
            idempotency_key=idempotency_key,
            tool_call_id=row["tool_call_id"],
            deduped=True,
            original_tool_call_id=row["tool_call_id"],
        )

    def _record_idempotent_result(
        self,
        session_id: str,
        tool_name: str,
        result: ToolResult,
    ) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO tool_idempotency (
                session_id, tool_name, idempotency_key, tool_call_id,
                status, output, error, started_at, finished_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                tool_name,
                result.idempotency_key,
                result.tool_call_id,
                result.status,
                json.dumps(result.output) if result.output is not None else None,
                result.error,
                result.started_at.isoformat(),
                result.finished_at.isoformat(),
            ),
        )
        self._conn.commit()

    def run_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        context: Dict[str, Any],
        session_id: str,
        idempotency_key: str,
    ) -> ToolResult:
        existing = self._load_idempotent_result(session_id, tool_name, idempotency_key)
        if existing:
            return existing

        started_at = datetime.utcnow()
        tool_call_id = context.get("tool_call_id") or str(uuid4())
        tool = self._tools.get(tool_name)
        if not tool:
            result = ToolResult(
                status="failed",
                output=None,
                error=f"Unknown tool '{tool_name}'",
                started_at=started_at,
                finished_at=datetime.utcnow(),
                idempotency_key=idempotency_key,
                tool_call_id=tool_call_id,
            )
            self._record_idempotent_result(session_id, tool_name, result)
            return result

        try:
            output = tool(tool_input)
            result = ToolResult(
                status="succeeded",
                output=output,
                error=None,
                started_at=started_at,
                finished_at=datetime.utcnow(),
                idempotency_key=idempotency_key,
                tool_call_id=tool_call_id,
            )
        except Exception as exc:  # noqa: BLE001 - deterministic stub
            result = ToolResult(
                status="failed",
                output=None,
                error=str(exc),
                started_at=started_at,
                finished_at=datetime.utcnow(),
                idempotency_key=idempotency_key,
                tool_call_id=tool_call_id,
            )
        self._record_idempotent_result(session_id, tool_name, result)
        return result
