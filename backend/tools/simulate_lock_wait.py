"""Exercise a real OpenTenBase DN lock wait through the health-audit SSE API."""
import argparse
import json
import threading
import time
from .simulate_slow_query import _run_audit

import psycopg2

from ..utils.config import Config


LOCK_KEY = 867530900001


def _connect(config, host, port, application_name):
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        application_name=application_name,
        connect_timeout=8,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=220)
    parser.add_argument("--hold-seconds", type=int, default=270)
    args = parser.parse_args()

    config = Config()
    coordinator = _connect(config, config.DB_HOST, config.DB_PORT, "aiops-lock-simulator-discovery")
    try:
        with coordinator.cursor() as cursor:
            cursor.execute(
                "SELECT node_name,node_host,node_port FROM pgxc_node "
                "WHERE node_type='D' ORDER BY node_name LIMIT 1"
            )
            node = cursor.fetchone()
    finally:
        coordinator.close()
    if not node:
        raise RuntimeError("No OpenTenBase data node is registered")
    node_name, node_host, node_port = node
    release_blocker = threading.Event()
    blocker_ready = threading.Event()
    waiter_started = threading.Event()
    worker_errors = []
    session_ids = {}

    def hold_lock():
        connection = None
        try:
            connection = _connect(config, node_host, node_port, "aiops-lock-simulator-blocker")
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                session_ids["blocker_pid"] = cursor.fetchone()[0]
                cursor.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
            blocker_ready.set()
            if not release_blocker.wait(args.hold_seconds):
                worker_errors.append("blocker hold timed out")
        except Exception as error:
            worker_errors.append(f"blocker: {type(error).__name__}: {error}")
            blocker_ready.set()
        finally:
            if connection is not None:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
                except Exception:
                    pass
                connection.close()

    def wait_for_lock():
        connection = None
        try:
            connection = _connect(config, node_host, node_port, "aiops-lock-simulator-waiter")
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout TO 0")
                cursor.execute("SET statement_timeout TO 0")
                cursor.execute("SELECT pg_backend_pid()")
                session_ids["waiter_pid"] = cursor.fetchone()[0]
                waiter_started.set()
                cursor.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
                cursor.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
        except Exception as error:
            worker_errors.append(f"waiter: {type(error).__name__}: {error}")
            waiter_started.set()
        finally:
            if connection is not None:
                connection.close()

    blocker_thread = threading.Thread(target=hold_lock, name="aiops-lock-blocker", daemon=True)
    waiter_thread = threading.Thread(target=wait_for_lock, name="aiops-lock-waiter", daemon=True)
    blocker_thread.start()
    if not blocker_ready.wait(10) or worker_errors:
        release_blocker.set()
        raise RuntimeError("Could not establish the blocker session: " + "; ".join(worker_errors))
    waiter_thread.start()
    try:
        if not waiter_started.wait(10):
            raise RuntimeError("Waiter session did not start")
        time.sleep(1)
        observer = _connect(config, node_host, node_port, "aiops-lock-simulator-observer")
        try:
            with observer.cursor() as cursor:
                cursor.execute(
                    "SELECT pid,pg_catalog.pg_blocking_pids(pid) "
                    "FROM pg_catalog.pg_stat_activity WHERE pid=%s",
                    (session_ids["waiter_pid"],),
                )
                wait_row = cursor.fetchone()
        finally:
            observer.close()
        if not wait_row or session_ids["blocker_pid"] not in (wait_row[1] or []):
            raise RuntimeError(f"OpenTenBase did not report the expected blocker: {wait_row}")

        audit, events = _run_audit(args.api_url, args.timeout)
        if audit is None:
            raise RuntimeError("Health audit remained busy after retrying")
        finding = next(
            (item for item in audit.get("findings", []) if item.get("check") == "data_node_lock_waits"),
            None,
        )
        if finding is None:
            raise RuntimeError("Health audit completed but did not produce a data_node_lock_waits finding")
        captured = any(
            blocker.get("pid") == session_ids["blocker_pid"]
            and blocker.get("application_name") == "aiops-lock-simulator-blocker"
            for wait in (finding.get("evidence") or {}).get("waits", [])
            for blocker in wait.get("blockers", [])
        )
        if not captured:
            raise RuntimeError("Health audit finding did not include the simulated blocker identity")
        structured = audit.get("structured") or {}
        result = {
            "status": "passed",
            "node": node_name,
            "blocker_pid": session_ids["blocker_pid"],
            "waiter_pid": session_ids["waiter_pid"],
            "database_blocking_pids": wait_row[1],
            "audit_id": audit.get("audit_id"),
            "risk_level": audit.get("risk_level"),
            "collection_status": (audit.get("evidence") or {}).get("collection_status"),
            "data_node_lock_finding": finding.get("observed"),
            "blocker_identity_captured": captured,
            "analysis_source": structured.get("analysis_source"),
            "knowledge_reference_count": len(audit.get("knowledge_refs") or []),
            "sse_event_types": [event["type"] for event in events],
            "repair_executed": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        release_blocker.set()
        blocker_thread.join(timeout=10)
        waiter_thread.join(timeout=10)
        if blocker_thread.is_alive() or waiter_thread.is_alive():
            print("Warning: a simulation session did not exit promptly")
        if worker_errors:
            print(json.dumps({"worker_errors": worker_errors}, ensure_ascii=False))


if __name__ == "__main__":
    main()
