#!/usr/bin/env python3
"""Run a disposable, end-to-end ANALYZE approval test against OpenTenBase."""
import argparse
import json
import os
import secrets
import string
import sys
import traceback
from pathlib import Path

import psycopg2
from psycopg2 import sql

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))


def _test_identity():
    suffix = secrets.token_hex(8)
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(32))
    role = f"aiops_repair_test_{suffix}"
    table = f"aiops_repair_test_{suffix}"
    return suffix, role, table, password


def _create_test_objects(database, distribution_group, repair_user, repair_password, table):
    connection = psycopg2.connect(
        host=os.getenv("DB_HOST", "otb-node1"),
        port=int(os.getenv("DB_PORT", "11003")),
        user=os.getenv("DB_USER", "opentenbase"),
        password=os.getenv("DB_PASSWORD", ""),
        dbname=database,
        connect_timeout=10,
    )
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT"
                ).format(sql.Identifier(repair_user), sql.Literal(repair_password))
            )
            cursor.execute(
                sql.SQL(
                    "CREATE TABLE public.{} (id bigint NOT NULL, payload text) "
                    "DISTRIBUTE BY REPLICATION TO GROUP {}"
                ).format(sql.Identifier(table), sql.Identifier(distribution_group))
            )
            cursor.execute(
                sql.SQL("ALTER TABLE public.{} OWNER TO {}").format(
                    sql.Identifier(table), sql.Identifier(repair_user)
                )
            )
            cursor.execute(
                sql.SQL("ALTER TABLE public.{} SET (autovacuum_enabled = false)").format(
                    sql.Identifier(table)
                )
            )
            cursor.execute(
                sql.SQL(
                    "INSERT INTO public.{} "
                    "SELECT value, repeat('x', 64) FROM generate_series(1, 3000) AS value"
                ).format(sql.Identifier(table))
            )
    finally:
        connection.close()


def _cleanup_test_objects(database, repair_user, table, audit_id):
    cleanup_errors = []
    try:
        from backend.utils.operations_store import OperationsStore

        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                if audit_id:
                    cursor.execute(
                        "DELETE FROM repair_request_events WHERE request_id IN "
                        "(SELECT request_id FROM repair_requests WHERE audit_id=%s)",
                        (audit_id,),
                    )
                    cursor.execute("DELETE FROM repair_requests WHERE audit_id=%s", (audit_id,))
                    cursor.execute(
                        "DELETE FROM operational_memory_cases WHERE evidence->>'audit_id'=%s",
                        (audit_id,),
                    )
                    cursor.execute("DELETE FROM audit_records WHERE audit_id=%s", (audit_id,))
        finally:
            store.close()
    except Exception as error:
        cleanup_errors.append(f"metadata: {type(error).__name__}: {error}")

    try:
        connection = psycopg2.connect(
            host=os.getenv("DB_HOST", "otb-node1"),
            port=int(os.getenv("DB_PORT", "11003")),
            user=os.getenv("DB_USER", "opentenbase"),
            password=os.getenv("DB_PASSWORD", ""),
            dbname=database,
            connect_timeout=10,
        )
        try:
            with connection, connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP TABLE IF EXISTS public.{} CASCADE").format(
                        sql.Identifier(table)
                    )
                )
                cursor.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(repair_user))
                )
        finally:
            connection.close()
    except Exception as error:
        cleanup_errors.append(f"opentenbase: {type(error).__name__}: {error}")
    return cleanup_errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.getenv("DB_NAME", "postgres"))
    parser.add_argument("--distribution-group", default="default_group")
    args = parser.parse_args()

    suffix, repair_user, table, repair_password = _test_identity()
    approval_token = secrets.token_urlsafe(32)
    os.environ.update({
        "DB_NAME": args.database,
        "AIOPS_REPAIR_DB_USER": repair_user,
        "AIOPS_REPAIR_DB_PASSWORD": repair_password,
        "AIOPS_REPAIR_FUNCTION_ENABLED": "false",
        "AIOPS_AUTO_REPAIR_ENABLED": "false",
        "AIOPS_AUTO_AUDIT_ENABLED": "false",
        "AIOPS_APPROVER_TOKENS": "",
        "AIOPS_APPROVAL_TOKEN": approval_token,
        "AIOPS_APPROVER_ID": "isolated-verification",
        "AIOPS_INSTANCE_ID": f"analyze-repair-test-{suffix}",
    })

    report = {
        "database": args.database,
        "table": f"public.{table}",
        "repair_account": repair_user,
    }
    audit_id = None
    try:
        _create_test_objects(
            args.database, args.distribution_group, repair_user,
            repair_password, table,
        )
        from fastapi.testclient import TestClient
        from backend.app import app

        with TestClient(app) as client:
            response = client.post(
                "/api/audits/health",
                params={"table": f"public.{table}"},
            )
            report["audit_http_status"] = response.status_code
            response.raise_for_status()
            audit = response.json()
            audit_id = audit["audit_id"]
            report.update({
                "audit_id": audit_id,
                "analysis_fallback": audit.get("analysis_fallback"),
                "knowledge_reference_count": len(audit.get("knowledge_refs") or []),
                "collection_status": audit["evidence"]["collection_status"],
            })

            candidates = [
                (index, finding)
                for index, finding in enumerate(audit.get("findings") or [])
                if finding.get("check") == "stale_table_statistics"
                and finding.get("evidence", {}).get("table") == table
            ]
            if len(candidates) != 1:
                raise RuntimeError(
                    f"Expected one stale-statistics finding for the test table, got {len(candidates)}"
                )

            response = client.post(
                f"/api/audits/{audit_id}/repair-requests",
                json={
                    "finding_index": candidates[0][0],
                    "operation": "analyze_table",
                    "reason": "Disposable ANALYZE workflow verification",
                },
            )
            report["proposal_http_status"] = response.status_code
            response.raise_for_status()
            request_id = response.json()["request_id"]
            report["request_id"] = request_id

            response = client.post(
                f"/api/repairs/{request_id}/human-approval",
                json={"token": approval_token},
            )
            report["human_approval_http_status"] = response.status_code
            response.raise_for_status()

            response = client.post(
                f"/api/repairs/{request_id}/approve",
                json={"approver": "isolated-verification", "token": approval_token},
            )
            report["execution_http_status"] = response.status_code
            response.raise_for_status()
            execution = response.json()
            result = execution.get("result") or {}
            postcondition = result.get("postcondition") or {}
            report.update({
                "request_status": execution.get("status"),
                "execution_succeeded": result.get("success"),
                "database_session_user": result.get("database_session_user"),
                "stale_nodes_before_execution": (
                    result.get("precondition") or {}
                ).get("stale_nodes"),
                "postcondition": postcondition,
            })
            if execution.get("status") != "executed" or not result.get("success"):
                raise RuntimeError("ANALYZE execution did not pass its postcondition")
            if postcondition.get("verified") is not True:
                raise RuntimeError("ANALYZE postcondition was not verified on every data node")
            expected_nodes = {
                item["node_name"] for item in result["precondition"]["data_nodes"]
            }
            if set(postcondition.get("advanced_nodes") or []) != expected_nodes:
                raise RuntimeError("ANALYZE did not advance statistics on every participating data node")
    except Exception as error:
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
        report["traceback"] = traceback.format_exc(limit=6)
    finally:
        report["cleanup_errors"] = _cleanup_test_objects(
            args.database, repair_user, table, audit_id,
        )

    report["status"] = (
        "passed"
        if not report.get("error") and not report.get("cleanup_errors")
        else "failed"
    )
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
