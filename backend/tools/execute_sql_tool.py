"""Execute SQL on the configured OpenTenBase target for the interactive agent."""
import hashlib
import time
import uuid
from copy import copy

from psycopg2 import Error
from psycopg2.extras import Json

from ..utils.config import Config
from ..utils.db_connector import OpenTenBaseConnector
from ..utils.operations_store import OperationsStore


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "execute_sql",
        "description": (
            "Execute SQL directly on OpenTenBase. Without node_name, execute on the configured CN. "
            "With node_name, execute directly on that registered PostgreSQL-speaking CN or DN. "
            "GTM uses a native protocol and is not a PostgreSQL SQL target. Supports any SQL "
            "the connected database account is permitted to run, including DDL, DML, transaction "
            "control and administrative functions. Use this when the user asks you to inspect or "
            "operate the live database. The operation is committed on success."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL statement(s) to execute"},
                "node_name": {"type": "string", "description": "Optional registered OpenTenBase node name"},
            },
            "required": ["sql"],
        },
    },
}


def _record_execution(config, sql_text, status, command_tag, row_count, sqlstate, duration_ms, node_name=None):
    store = OperationsStore()
    try:
        with store.conn, store.conn.cursor() as cursor:
            cursor.execute("""CREATE TABLE IF NOT EXISTS agent_sql_execution_audit(
                execution_id text primary key,
                executed_at timestamptz not null default now(),
                actor text not null,
                target jsonb not null,
                sql_sha256 text not null,
                command_tag text,
                status text not null,
                row_count integer,
                sqlstate text,
                duration_ms integer not null
            )""")
            cursor.execute(
                """INSERT INTO agent_sql_execution_audit(
                    execution_id,actor,target,sql_sha256,command_tag,status,row_count,sqlstate,duration_ms
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    str(uuid.uuid4()), "ai_agent",
                    Json({
                        "host": config.DB_HOST, "port": config.DB_PORT,
                        "database": config.DB_NAME, "node_name": node_name or "configured_coordinator",
                    }),
                    hashlib.sha256(sql_text.encode("utf-8")).hexdigest(), command_tag,
                    status, row_count, sqlstate, duration_ms,
                ),
            )
        return True
    finally:
        store.close()


async def execute_sql(sql: str, node_name: str | None = None):
    if not isinstance(sql, str) or not sql.strip():
        return {"success": False, "error": "SQL text is empty"}

    config = Config()
    target_config = config
    if node_name:
        discovery = OpenTenBaseConnector(config)
        try:
            with discovery.connect().cursor() as cursor:
                cursor.execute(
                    "SELECT node_type,node_host,node_port FROM pgxc_node WHERE node_name=%s",
                    (node_name,),
                )
                endpoint = cursor.fetchone()
            discovery._connection.rollback()
        finally:
            discovery.close()
        if not endpoint:
            return {"success": False, "error": f"OpenTenBase node {node_name} was not found"}
        if endpoint[0] == "G":
            return {
                "success": False,
                "error": "GTM uses a native protocol and cannot execute PostgreSQL SQL. "
                         "Use get_cluster_diagnostics for TCP reachability.",
            }
        target_config = copy(config)
        target_config.DB_HOST, target_config.DB_PORT = endpoint[1:]
        target_config.DB_NAME = config.DB_NAME
        target_config.DB_USER = config.DB_USER
        target_config.DB_PASSWORD = config.DB_PASSWORD
    connector = OpenTenBaseConnector(target_config)
    started = time.monotonic()
    command_tag = None
    row_count = None
    result = {"success": False}
    sqlstate = None
    try:
        connection = connector.connect()
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(sql)
            command_tag = cursor.statusmessage
            row_count = cursor.rowcount if cursor.rowcount >= 0 else None
            if cursor.description:
                columns = [column[0] for column in cursor.description]
                rows = cursor.fetchall()
                result.update({
                    "columns": columns,
                    "rows": [dict(zip(columns, row)) for row in rows],
                    "rows_returned": len(rows),
                })
        result.update({"success": True, "command_tag": command_tag, "row_count": row_count})
    except Exception as error:
        sqlstate = getattr(error, "pgcode", None)
        if connector._connection and not connector._connection.closed:
            try:
                connector._connection.rollback()
            except Error:
                pass
        result.update({
            "success": False,
            "error": str(error),
            "error_type": type(error).__name__,
            "sqlstate": sqlstate,
        })
    finally:
        connector.close()

    duration_ms = int((time.monotonic() - started) * 1000)
    try:
        result["audit_recorded"] = _record_execution(
            target_config, sql, "success" if result["success"] else "failed",
            command_tag, row_count, sqlstate, duration_ms, node_name,
        )
    except Exception as error:
        result["audit_recorded"] = False
        result["audit_error"] = type(error).__name__
    result["execution_time_ms"] = duration_ms
    return result
