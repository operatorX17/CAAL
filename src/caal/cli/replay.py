from __future__ import annotations

import argparse
import json

from caal.kernel.event_store import SQLiteEventStore
from caal.kernel.projector import project_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay conversation state from events.")
    parser.add_argument("--db-path", default=":memory:", help="SQLite DB path")
    parser.add_argument("--session-id", required=True, help="Session ID to replay")
    args = parser.parse_args()

    store = SQLiteEventStore(args.db_path)
    events = store.list_by_session(args.session_id)
    state = project_state(events)
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
