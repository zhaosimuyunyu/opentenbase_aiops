"""Create an isolated long-running query and verify health-audit diagnosis."""
import argparse
import json
import math
import threading
import time
from urllib.request import Request, urlopen

from psycopg2 import connect

from ..utils.config import Config


APP_NAME = "aiops-course-slow-query-demo"


def _run_audit(api_url, timeout, busy_retries=6):
    last_events = []
    for attempt in range(busy_retries + 1):
        audit, events = _run_audit_once(api_url, timeout)
        last_events = events
        if audit is not None:
            return audit, events
        if attempt < busy_retries:
            time.sleep(5)
    return None, last_events


def _run_audit_once(api_url, timeout):
    request = Request(
        f"{api_url.rstrip('/')}/api/audits/health/stream",
        data=b"",
        headers={"Accept": "text/event-stream"},
        method="POST",
    )
    events = []
    with urlopen(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            events.append(event)
            if event["type"] == "result":
                return event["audit"], events
            if event["type"] == "busy":
                return None, events
            if event["type"] == "error":
                raise RuntimeError(f"Health audit SSE ended with {event['type']}")
    raise RuntimeError("Health audit SSE ended before returning a result")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=210)
    parser.add_argument("--hold-seconds", type=int, default=15)
    args = parser.parse_args()

    config = Config()
    node_name = f"CN entry {config.DB_HOST}:{config.DB_PORT}"
    connection = connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        dbname=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        application_name=APP_NAME,
        connect_timeout=8,
    )
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT setting::int FROM pg_catalog.pg_settings "
            "WHERE name='log_min_duration_statement'"
        )
        log_threshold_ms = cursor.fetchone()[0]
    if log_threshold_ms < 0:
        connection.close()
        raise RuntimeError("OpenTenBase slow-statement logging is disabled")
    hold_seconds = max(args.hold_seconds, math.ceil(log_threshold_ms / 1000) + 2)
    query_started = threading.Event()
    query_error = []
    session = {}

    def run_query():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout TO 0")
                cursor.execute("SELECT pg_backend_pid()")
                session["pid"] = cursor.fetchone()[0]
                query_started.set()
                cursor.execute("SELECT pg_sleep(%s)", (hold_seconds,))
        except Exception as error:
            query_error.append(f"{type(error).__name__}: {error}")
            query_started.set()

    worker = threading.Thread(target=run_query, name="aiops-course-slow-query", daemon=True)
    worker.start()
    direct_observation = None
    try:
        if not query_started.wait(10) or query_error:
            raise RuntimeError("Could not start the simulated slow query: " + "; ".join(query_error))
        time.sleep(6)
        observer = connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            dbname=config.DB_NAME,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            application_name="aiops-course-slow-query-observer",
            connect_timeout=8,
        )
        try:
            with observer.cursor() as cursor:
                cursor.execute(
                    "SELECT pid,state,query_start,application_name,query "
                    "FROM pg_catalog.pg_stat_activity WHERE pid=%s",
                    (session["pid"],),
                )
                row = cursor.fetchone()
                if row:
                    direct_observation = {
                        "pid": row[0], "state": row[1], "query_start": row[2],
                        "application_name": row[3], "query": row[4],
                    }
        finally:
            observer.close()
        worker.join(hold_seconds + 10)
        if worker.is_alive():
            connection.cancel()
            worker.join(10)
            raise RuntimeError("The simulated slow query did not finish within the expected time")
        if query_error:
            raise RuntimeError("The simulated slow query failed: " + "; ".join(query_error))
        audit, events = _run_audit(args.api_url, args.timeout)
        if audit is None:
            print(json.dumps({
                "status": "not_captured",
                "reason": "Health audit remained busy after retrying",
                "node": node_name,
                "pid": session.get("pid"),
                "application_name": APP_NAME,
                "sse_event_types": [event["type"] for event in events],
            }, ensure_ascii=False, indent=2))
            return
        captured = [
            row for row in ((audit.get("evidence") or {}).get("performance") or {}).get("slow_query_logs") or []
            if row.get("pid") == session.get("pid")
            and row.get("application_name") == APP_NAME
        ]
        finding = next(
            (item for item in audit.get("findings", []) if item.get("check") == "long_running_queries"),
            None,
        )
        finding_captured = bool(finding and any(
            row.get("pid") == session.get("pid") for row in finding.get("evidence", [])
        ))
        if not captured or not finding_captured:
            print(json.dumps({
                "status": "not_captured",
                "node": node_name,
                "database": config.DB_NAME,
                "pid": session["pid"],
                "application_name": APP_NAME,
                "live_pg_stat_activity": direct_observation,
                "audit_id": audit.get("audit_id"),
                "collection_status": (audit.get("evidence") or {}).get("collection_status"),
                "collection_errors": (audit.get("evidence") or {}).get("collection_errors"),
                "sse_event_types": [event["type"] for event in events],
                "reason": "The completed audit did not include the simulated PID in both performance evidence and findings",
            }, ensure_ascii=False, indent=2, default=str))
            return
        result = {
            "status": "passed",
            "node": node_name,
            "database": config.DB_NAME,
            "pid": session["pid"],
            "application_name": APP_NAME,
            "hold_seconds": hold_seconds,
            "live_pg_stat_activity": direct_observation,
            "query": captured[0].get("query"),
            "duration_ms": captured[0].get("duration_ms"),
            "audit_id": audit.get("audit_id"),
            "risk_level": audit.get("risk_level"),
            "finding": finding.get("observed"),
            "analysis_source": (audit.get("structured") or {}).get("analysis_source"),
            "knowledge_reference_count": len(audit.get("knowledge_refs") or []),
            "sse_event_types": [event["type"] for event in events],
            "cleanup": "the pg_sleep demo session completed naturally",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        if worker.is_alive():
            connection.cancel()
        worker.join(timeout=10)
        connection.close()
        if worker.is_alive():
            print("Warning: simulated long-query thread did not exit promptly")


if __name__ == "__main__":
    main()
