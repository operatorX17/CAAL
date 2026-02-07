from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from typing import Iterable, List, Optional
from uuid import UUID

from caal.kernel.contracts import Event, TraceContext


class EventStore:
    def append(self, event: Event) -> int:
        raise NotImplementedError

    def append_many(self, events: Iterable[Event]) -> None:
        for event in events:
            self.append(event)

    def list_by_session(self, session_id: str) -> List[Event]:
        raise NotImplementedError


class SQLiteEventStore(EventStore):
    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL,
                trace TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def append(self, event: Event) -> int:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            INSERT INTO events (event_id, session_id, timestamp, type, payload, trace)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(event.event_id),
                event.session_id,
                event.timestamp.isoformat(),
                event.type,
                json.dumps(event.payload),
                json.dumps(asdict(event.trace)),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def list_by_session(self, session_id: str) -> List[Event]:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT event_id, session_id, timestamp, type, payload, trace
            FROM events
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        )
        rows = cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Event:
        trace_payload = json.loads(row["trace"])
        return Event(
            event_id=UUID(row["event_id"]),
            session_id=row["session_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            type=row["type"],
            payload=json.loads(row["payload"]),
            trace=TraceContext(
                parent_span_id=trace_payload.get("parent_span_id"),
                span_id=trace_payload.get("span_id"),
            ),
        )
