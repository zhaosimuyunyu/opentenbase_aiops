#!/usr/bin/env python3
"""Probe the OpenTenBase SQL surface used by AIOps without changing data."""
import argparse
import json
import re
import socket
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql as pg_sql
from psycopg2.extras import RealDictCursor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.utils.config import Config
from backend.collectors.readonly_health import CHECKS, ReadonlyHealthCollector


PROBES = {
    "connection_identity": "SELECT version(), current_database(), current_user",
    "database_identity": CHECKS["database_identity"],
    "cluster_nodes": "SELECT node_name, node_type, node_host, node_port FROM pgxc_node ORDER BY node_type, node_name",
    "activity": CHECKS["connections"],
    "max_connections": CHECKS["max_connections"],
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", help="Also verify targeted data-node statistics for schema.table")
    parser.add_argument("--repair-account", action="store_true",
                        help="Probe with the configured repair login using read-only queries")
    parser.add_argument("--repair-lock", action="store_true",
                        help="Try the repair table lock and immediately roll back on a test table")
    args = parser.parse_args()
    if args.repair_lock and not (args.repair_account and args.table):
        parser.error("--repair-lock requires --repair-account and --table")
    if args.repair_account and args.table and not args.repair_lock:
        parser.error("--table with --repair-account requires --repair-lock")
    if args.table and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", args.table):
        parser.error("--table must use schema.table format")
    config = Config()
    if args.repair_account:
        if not config.AIOPS_REPAIR_DB_USER:
            parser.error("--repair-account requires AIOPS_REPAIR_DB_USER")
        config.DB_USER = config.AIOPS_REPAIR_DB_USER
        config.DB_PASSWORD = config.AIOPS_REPAIR_DB_PASSWORD
    report = {
        "target": {"host": config.DB_HOST, "port": config.DB_PORT, "database": config.DB_NAME, "user": config.DB_USER},
        "driver": "psycopg2",
        "probes": {},
        "node_connectivity": [],
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
            if args.repair_account and name not in {"connection_identity", "database_identity"}:
                continue
            try:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '1500ms'")
                    cursor.execute("SET LOCAL lock_timeout = '300ms'")
                    cursor.execute(sql)
                    rows = cursor.fetchall()
                if name == "database_identity" and (
                    len(rows) != 1
                    or not rows[0].get("system_identifier")
                    or rows[0].get("database") != config.DB_NAME
                ):
                    raise ValueError("Database identity is missing or does not match the configured database")
                connection.rollback()
                report["probes"][name] = {"status": "pass", "row_count": len(rows), "columns": list(rows[0]) if rows else []}
                if name == "cluster_nodes":
                    for node in rows:
                        host, port = node.get("node_host"), node.get("node_port")
                        result = {
                            "node_name": node.get("node_name"),
                            "node_type": node.get("node_type"),
                            "host": host,
                            "port": port,
                            "status": "unknown",
                        }
                        if host and port:
                            try:
                                with socket.create_connection((host, int(port)), timeout=0.75):
                                    result["status"] = "pass"
                            except OSError as error:
                                result["status"] = "fail"
                                result["error"] = str(error)
                        report["node_connectivity"].append(result)
            except Exception as error:
                connection.rollback()
                report["probes"][name] = {"status": "fail", "type": type(error).__name__, "message": str(error).strip(),
                                          "sqlstate": getattr(error, "pgcode", None)}

        nodes = report["node_connectivity"]
        data_nodes = [node for node in nodes if node["node_type"] == "D"]
        collector = ReadonlyHealthCollector(config)
        for label, table in (("data_node_statistics", None), ("targeted_data_node_statistics", args.table)):
            if args.repair_account:
                break
            if label == "targeted_data_node_statistics" and not table:
                continue
            tables, errors = collector._collect_data_node_stats(connection, data_nodes, table=table)
            report["probes"][label] = {
                "status": "pass" if data_nodes and not errors else "fail",
                "table": table,
                "data_node_count": len(data_nodes),
                "table_count": len(tables),
                "errors": errors,
            }
        if not args.repair_account:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '1500ms'")
                    cursor.execute("SET LOCAL lock_timeout = '300ms'")
                    cursor.execute(CHECKS["pg_clean_diagnostics"])
                    available = cursor.fetchone()[0]
                report["pg_clean_diagnostics"] = {
                    "status": "registered" if available else "missing",
                }
            except psycopg2.Error as error:
                report["pg_clean_diagnostics"] = {
                    "status": "unknown", "sqlstate": error.pgcode,
                }
            finally:
                connection.rollback()
        if args.repair_lock:
            connection.set_session(readonly=False)
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '1500ms'")
                    cursor.execute(
                        pg_sql.SQL("LOCK TABLE {} IN SHARE UPDATE EXCLUSIVE MODE NOWAIT").format(
                            pg_sql.Identifier(*args.table.split(".", 1))
                        )
                    )
                report["probes"]["repair_table_lock"] = {"status": "pass"}
            except psycopg2.Error as error:
                report["probes"]["repair_table_lock"] = {
                    "status": "fail", "type": type(error).__name__,
                    "message": str(error).strip(), "sqlstate": error.pgcode,
                }
            finally:
                connection.rollback()
    finally:
        connection.close()

    failed = [name for name, result in report["probes"].items() if result["status"] == "fail"]
    failed_nodes = [node["node_name"] for node in report["node_connectivity"] if node["status"] == "fail"]
    unverified_nodes = [node["node_name"] for node in report["node_connectivity"] if node["status"] == "unknown"]
    report["summary"] = {
        "sql_probes_passed": len(report["probes"]) - len(failed),
        "sql_probes_failed": len(failed),
        "failed_probes": failed,
        "unreachable_nodes": failed_nodes,
        "unverified_nodes": unverified_nodes,
        "status": "fail" if failed or failed_nodes or unverified_nodes else "pass",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if not failed and not failed_nodes and not unverified_nodes else 2


if __name__ == "__main__":
    raise SystemExit(main())
