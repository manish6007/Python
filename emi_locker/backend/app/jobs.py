"""Scheduled work, runnable by cron or a cloud scheduler.

    python -m backend.app.jobs nightly          # once a day, after midnight IST
    python -m backend.app.jobs deliver-notices  # every 15 minutes
    python -m backend.app.jobs unlock-monitor   # every 5 minutes

``unlock-monitor`` exits 1 when an unlock is past its deadline, so the
scheduler's own failure alert pages someone. ``deliver-notices`` retries
notices that failed earlier; a notice only counts towards a restriction once
it has been delivered.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from typing import Any, Dict, List, Optional

from emi_locker import devices, lifecycle, notices
from emi_locker.core import Actor
from emi_locker.db import file_db, tx
from emi_locker.settings_store import get_setting

from .auth import channel
from .config import settings


def deliver_notices(conn: sqlite3.Connection, actor: Optional[Actor] = None,
                    as_of=None) -> Dict[str, List[str]]:
    with tx(conn):
        return notices.deliver_pending_notices(
            conn, channel(), actor, as_of=as_of,
            business=get_setting(conn, "business.name"))


def nightly(conn: sqlite3.Connection, actor: Optional[Actor] = None) -> Dict[str, Any]:
    """The daily sweep, then send whatever notices it raised."""
    with tx(conn):
        moved = lifecycle.run_daily_status_sweep(conn, actor)
    sent = deliver_notices(conn, actor)
    out: Dict[str, Any] = {k: len(v) for k, v in moved.items()}
    out["NOTICES_DELIVERED"] = len(sent["delivered"])
    out["NOTICES_FAILED"] = len(sent["failed"])
    return out


def main(argv: List[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("nightly", "deliver-notices", "unlock-monitor"):
        print(__doc__)
        return 2
    conn = file_db(settings.db_path)
    try:
        if argv[0] == "nightly":
            print(json.dumps(nightly(conn)))
        elif argv[0] == "deliver-notices":
            print(json.dumps({k: len(v) for k, v in deliver_notices(conn).items()}))
        else:
            waiting = devices.unlock_monitor(conn)
            print(json.dumps({"waiting": waiting}))
            if any(w["overdue"] for w in waiting):
                return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
