#!/usr/bin/env python3
"""Probe the OpenTenBase SQL surface used by AIOps without changing data."""
import json
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.utils.config import Config


PROBES = {
    "connection_identity": "SELECT version(), current_database(), current_user",
    "cluster_nodes": "SELECT node_name, node_type, node_host, node_port FROM pgxc_node ORDER BY node_type, node_name",
    "activity": "SELECT datname, state, count(*) AS connection_count FROM pg_stat_activity GROUP BY datname, state",
    "locks": """SELECT l.locktype, l.mode, l.granted, l.pid,
               l.transactionid::text AS transactionid,
               CASE WHEN NOT l.granted THEN pg_blocking_pids(l.pid) ELSE ARRAY[]::int[] END AS blocker_pids
               FROM pg_locks l WHERE l.pid IS NOT NULL""",
    "prepared_transactions": "SELECT transaction::text AS transaction_id, gid, prepared, owner, database FROM pg_prepared_xacts",
    "replication": "SELECT pid, usename, application_name, state, sync_state, replay_lag FROM pg_stat_replication",
    "table_statistics": "SELECT schemaname, relname, n_live_tup, n_dead_tup FROM pg_stat_user_tables LIMIT 10",
    "index_statistics": "SELECT schemaname, relname, indexrelname, idx_scan FROM pg_stat_user_indexes LIMIT 10",
}


def main() -> int:
    config = Config()
    report = {
        "target": {"host": config.DB_HOST, "port": config.DB_PORT, "database": config.DB_NAME, "user": config.DB_USER},
        "driver": "psycopg2",
        "probes": {},
    }
    try:
        connection = psycopg2.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME,
            connect_timeout=5,
        )
    except Exception as error:
        report["connection_error"] = {"type": type(error).__name__, "message": str(error)}
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 1

    try:
        connection.set_session(readonly=True, autocommit=False)
        for name, sql in PROBES.items():
            try:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '1500ms'")
                    cursor.execute("SET LOCAL lock_timeout = '300ms'")
                    cursor.execute(sql)
                    rows = cursor.fetchall()
                connection.rollback()
                report["probes"][name] = {"status": "pass", "row_count": len(rows), "columns": list(rows[0]) if rows else []}
            except Exception as error:
                connection.rollback()
                report["probes"][name] = {"status": "fail", "type": type(error).__name__, "message": str(error).strip()}
    finally:
        connection.close()

    failed = [name for name, result in report["probes"].items() if result["status"] == "fail"]
    report["summary"] = {"passed": len(report["probes"]) - len(failed), "failed": len(failed), "failed_probes": failed}
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
