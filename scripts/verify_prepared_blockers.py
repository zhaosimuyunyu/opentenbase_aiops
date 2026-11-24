#!/usr/bin/env python3
"""Verify prepared-transaction blockers with read-only SQL."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.utils.db_connector import OpenTenBaseConnector

db = OpenTenBaseConnector()
try:
    waits = db.execute_query("""
        SELECT transactionid::text AS transaction_id, pid, mode, granted
        FROM pg_locks
        WHERE transactionid IS NOT NULL
          AND granted = false
    """) or []
    xids = sorted({row["transaction_id"] for row in waits})
    prepared = db.execute_query("""
        SELECT transaction::text AS transaction_id, gid, prepared, owner, database
        FROM pg_prepared_xacts
    """) or []
    matching = [row for row in prepared if row["transaction_id"] in xids]
    print(json.dumps({
        "waiting_transaction_ids": xids,
        "matching_prepared_transactions": matching,
        "verified": bool(matching),
    }, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if matching else 1)
finally:
    db.close()
