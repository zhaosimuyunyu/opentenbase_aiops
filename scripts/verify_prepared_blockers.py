#!/usr/bin/env python3
"""Verify prepared-transaction blockers with read-only SQL."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.collectors.readonly_health import ReadonlyHealthCollector

snapshot = ReadonlyHealthCollector().collect()
checks = snapshot["checks"]
xids = {
    str(row["transactionid"]) for row in checks.get("locks", [])
    if row.get("transactionid") and not row["granted"]
}
matching = [
    row for row in checks.get("prepared_transactions", [])
    if str(row["transaction_id"]) in xids
]
participants = checks.get("data_node_prepared_transactions", [])
blocked_gids = {row["gid"] for row in matching}
blocked_gids.update(row["gid"] for row in participants if row.get("waiting_pids"))
print(json.dumps({
    "waiting_transaction_ids": sorted(xids),
    "matching_prepared_transactions": matching,
    "data_node_participants": [row for row in participants if row["gid"] in blocked_gids],
    "collection_status": snapshot["status"],
    "collection_errors": snapshot["errors"],
    "verified": bool(blocked_gids),
}, ensure_ascii=False, indent=2, default=str))
raise SystemExit(0 if blocked_gids else 1)
