import re
import hmac
import uuid
from datetime import datetime, timezone

from psycopg2 import sql
from psycopg2.extras import Json
from ..utils.config import Config
from ..utils.db_connector import OpenTenBaseConnector
from ..ai.knowledge_base_pgvector import PgVectorKnowledgeBase


ALLOWED_OPERATIONS = {"analyze_table"}


def _table_name(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?", value or ""):
        raise ValueError("Only a simple schema-qualified table name is allowed")
    return value


def _identifier(value):
    return sql.Identifier(*value.split("."))


class RepairWorkflow:
    def __init__(self):
        self.config = Config()

    def _ensure_schema(self, kb):
        with kb.conn, kb.conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS repair_requests(
                request_id text primary key, operation text not null, parameters jsonb not null,
                evidence jsonb not null, reason text not null, status text not null default 'pending',
                created_at timestamptz default now(), approved_at timestamptz, approved_by text,
                result jsonb)""")

    def create_request(self, operation, parameters, evidence, reason):
        if operation not in ALLOWED_OPERATIONS:
            raise ValueError("Operation is not enabled for execution")
        params = dict(parameters or {})
        params["table"] = _table_name(params.get("table"))
        request_id = str(uuid.uuid4())
        kb = PgVectorKnowledgeBase()
        try:
            self._ensure_schema(kb)
            with kb.conn, kb.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO repair_requests(request_id,operation,parameters,evidence,reason) VALUES(%s,%s,%s,%s,%s)",
                    (request_id, operation, Json(params), Json(evidence or {}), reason),
                )
        finally:
            kb.close()
        return {"request_id": request_id, "status": "pending", "operation": operation, "parameters": params}

    def approve_and_execute(self, request_id, approver, token):
        if not self.config.AIOPS_APPROVAL_TOKEN or not hmac.compare_digest(
            token or "", self.config.AIOPS_APPROVAL_TOKEN
        ):
            raise PermissionError("Approval token is not configured or is invalid")
        kb = PgVectorKnowledgeBase()
        try:
            self._ensure_schema(kb)
            with kb.conn, kb.conn.cursor() as cur:
                cur.execute(
                    "SELECT operation,parameters,status FROM repair_requests WHERE request_id=%s FOR UPDATE",
                    (request_id,),
                )
                request = cur.fetchone()
                if not request or request[2] != "pending":
                    raise ValueError("Repair request is missing or is not pending")
                operation, params, _ = request
                table = _table_name(params["table"])
                db = OpenTenBaseConnector(self.config)
                try:
                    conn = db.connect()
                    conn.set_session(readonly=False, autocommit=False)
                    with conn.cursor() as target:
                        target.execute("SET LOCAL statement_timeout = '10s'")
                        target.execute("SET LOCAL lock_timeout = '1s'")
                        schema_name, table_name = (
                            table.split(".", 1) if "." in table else ("public", table)
                        )
                        target.execute(
                            "SELECT n_live_tup,n_dead_tup FROM pg_stat_user_tables "
                            "WHERE schemaname=%s AND relname=%s",
                            (schema_name, table_name),
                        )
                        stats = target.fetchone()
                        if not stats:
                            raise ValueError("Table statistics are unavailable for the approved table")
                        live_tuples, dead_tuples = stats
                        total = (live_tuples or 0) + (dead_tuples or 0)
                        dead_ratio = (dead_tuples or 0) / total if total else 0
                        if (dead_tuples or 0) < 1000 or dead_ratio < 0.2:
                            raise ValueError("The original ANALYZE finding is no longer present")
                        target.execute(
                            sql.SQL("ANALYZE {}").format(_identifier(table))
                        )
                        target.execute(
                            "SELECT last_analyze FROM pg_stat_user_tables "
                            "WHERE schemaname=%s AND relname=%s",
                            (schema_name, table_name),
                        )
                        verified = target.fetchone()
                    conn.commit()
                    result = {
                        "success": True,
                        "operation": operation,
                        "table": table,
                        "precondition": {
                            "live_tuples_estimate": live_tuples,
                            "dead_tuples_estimate": dead_tuples,
                            "dead_ratio_estimate": dead_ratio,
                        },
                        "postcondition": {
                            "last_analyze": verified[0] if verified else None,
                            "verified": bool(verified and verified[0]),
                        },
                        "executed_at": datetime.now(timezone.utc).isoformat(),
                    }
                except Exception as error:
                    if db._connection and not db._connection.closed:
                        db._connection.rollback()
                    result = {"success": False, "operation": operation, "table": table, "error": str(error)}
                finally:
                    db.close()
                status = "executed" if result["success"] else "failed"
                cur.execute(
                    "UPDATE repair_requests SET status=%s,approved_at=now(),approved_by=%s,result=%s WHERE request_id=%s",
                    (status, approver, Json(result), request_id),
                )
                return {"request_id": request_id, "status": status, "result": result}
        finally:
            kb.close()

    def reject(self, request_id, approver, reason):
        kb = PgVectorKnowledgeBase()
        try:
            self._ensure_schema(kb)
            with kb.conn, kb.conn.cursor() as cur:
                cur.execute(
                    "UPDATE repair_requests SET status='rejected',approved_at=now(),approved_by=%s,"
                    "result=%s WHERE request_id=%s AND status='pending' RETURNING request_id",
                    (approver, Json({"reason": reason}), request_id),
                )
                if not cur.fetchone():
                    raise ValueError("Repair request is missing or is not pending")
                return {"request_id": request_id, "status": "rejected"}
        finally:
            kb.close()

    def list_requests(self, limit=50):
        kb = PgVectorKnowledgeBase()
        try:
            self._ensure_schema(kb)
            with kb.conn.cursor() as cur:
                cur.execute(
                    "SELECT request_id,operation,parameters,evidence,reason,status,created_at,approved_at,approved_by,result "
                    "FROM repair_requests ORDER BY created_at DESC LIMIT %s",
                    (max(1, min(limit, 100)),),
                )
                columns = [item[0] for item in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
        finally:
            kb.close()
