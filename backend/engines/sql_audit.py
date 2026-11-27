"""Deterministic SQL safety audit with an optional read-only EXPLAIN."""
import json
import re

from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from ..utils.config import Config
from ..utils.db_connector import OpenTenBaseConnector


def _sequential_scan_nodes(plan):
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError:
            return []
    if isinstance(plan, list):
        return [node for item in plan for node in _sequential_scan_nodes(item)]
    if not isinstance(plan, dict):
        return []

    nodes = [plan] if plan.get("Node Type") == "Seq Scan" else []
    for value in plan.values():
        if isinstance(value, (dict, list)):
            nodes.extend(_sequential_scan_nodes(value))
    return nodes


def _risk_level(findings):
    if any(item["severity"] == "critical" for item in findings):
        return "critical"
    if any(item["severity"] == "high" for item in findings):
        return "high"
    if any(item["severity"] == "medium" for item in findings):
        return "medium"
    return "low"


_RULES = (
    ("critical", "delete_without_where", re.compile(r"\bdelete\s+from\b(?![\s\S]*\bwhere\b)", re.I),
     "DELETE without WHERE can remove every row"),
    ("critical", "update_without_where", re.compile(r"\bupdate\b[\s\S]*\bset\b(?![\s\S]*\bwhere\b)", re.I),
     "UPDATE without WHERE can modify every row"),
    ("critical", "drop_table", re.compile(r"\bdrop\s+table\b", re.I), "DROP TABLE is destructive"),
    ("critical", "truncate", re.compile(r"\btruncate\b", re.I), "TRUNCATE removes table data"),
    ("high", "alter_system", re.compile(r"\balter\s+system\b", re.I), "ALTER SYSTEM changes server configuration"),
    ("critical", "backend_termination", re.compile(r"\bpg_(cancel|terminate)_backend\s*\(", re.I),
     "Backend cancellation or termination affects active database work"),
    ("critical", "transaction_recovery", re.compile(r"\bpg_clean_(execute|commit|rollback)\s*\(", re.I),
     "Prepared transaction recovery changes cluster transaction state"),
    ("high", "role_privilege_change", re.compile(r"\b(grant|revoke|create\s+(role|user))\b", re.I),
     "Role and privilege changes require explicit review"),
    ("medium", "select_star", re.compile(r"\bselect\s+\*\b", re.I), "SELECT * may increase data and network cost"),
    ("medium", "alter_table", re.compile(r"\balter\s+table\b", re.I), "ALTER TABLE may lock or rewrite a relation"),
)


def _single_statement(statement):
    value = (statement or "").strip()
    if not value:
        raise ValueError("SQL must not be empty")
    quote = None
    index = 0
    terminator = None
    while index < len(value):
        char = value[index]
        if quote:
            if char == quote:
                if index + 1 < len(value) and value[index + 1] == quote:
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"'}:
            quote = char
        elif char == ";":
            if terminator is not None or value[index + 1:].strip():
                raise ValueError("Only one SQL statement can be audited")
            terminator = index
        index += 1
    if quote:
        raise ValueError("SQL contains an unterminated quoted value")
    if terminator is not None:
        value = value[:terminator].rstrip()
    if len(value) > 20000:
        raise ValueError("SQL is too long")
    return value


def audit_sql(statement, *, explain=True, config=None):
    query = _single_statement(statement)
    findings = [
        {"severity": severity, "rule": rule, "message": message}
        for severity, rule, pattern, message in _RULES if pattern.search(query)
    ]
    settings = config or Config()
    sequential_scan_rows = max(
        1, int(getattr(settings, "AIOPS_SQL_AUDIT_SEQ_SCAN_ROWS", 10000))
    )
    result = {
        "sql": query,
        "risk_level": _risk_level(findings),
        "findings": findings,
        "explain": None,
        "explain_error": None,
    }
    high_risk = result["risk_level"] in {"high", "critical"}
    if explain and not high_risk and query.lower().startswith(("select", "with", "values")):
        connector = OpenTenBaseConnector(settings)
        try:
            connection = connector.connect()
            connection.set_session(readonly=True, autocommit=False)
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SET LOCAL statement_timeout = '2500ms'")
                cursor.execute("SET LOCAL lock_timeout = '750ms'")
                cursor.execute(sql.SQL("EXPLAIN (FORMAT JSON) {} ").format(sql.SQL(query)))
                row = cursor.fetchone()
                result["explain"] = row.get("QUERY PLAN") if row else None
                for node in _sequential_scan_nodes(result["explain"]):
                    estimated_rows = float(node.get("Plan Rows") or 0)
                    large_scan = estimated_rows >= sequential_scan_rows
                    table = node.get("Relation Name") or "unknown relation"
                    result["findings"].append({
                        "severity": "high" if large_scan else "medium",
                        "rule": "large_sequential_scan" if large_scan else "sequential_scan_review",
                        "message": (
                            f"Execution plan contains a sequential scan of {table} "
                            f"(estimated {estimated_rows:g} rows); review filtering and indexing"
                        ),
                    })
                result["risk_level"] = _risk_level(result["findings"])
            connection.rollback()
        except Exception as error:
            result["explain_error"] = {
                "type": type(error).__name__, "message": str(error),
                "sqlstate": getattr(error, "pgcode", None),
            }
        finally:
            connector.close()
    return result
