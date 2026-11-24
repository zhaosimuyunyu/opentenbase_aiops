"""Read-only OpenTenBase health checks with isolated query failures."""
from datetime import datetime
import socket

from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from ..utils.config import Config
from ..utils.db_connector import OpenTenBaseConnector


CHECKS = {
    "nodes": """
        SELECT node_name, node_type, node_host, node_port,
               nodeis_primary, nodeis_preferred
        FROM pgxc_node ORDER BY node_type, node_name
    """,
    "connections": """
        SELECT datname, state, count(*) AS connection_count
        FROM pg_stat_activity GROUP BY datname, state
        ORDER BY datname, state
    """,
    "max_connections": "SELECT current_setting('max_connections')::int AS max_connections",
    "replication": """
        SELECT pid, usename, application_name, client_addr, state,
               sync_state, replay_lag
        FROM pg_stat_replication
    """,
    "prepared_transactions": """
        SELECT transaction::text AS transaction_id, gid, prepared, owner, database
        FROM pg_prepared_xacts ORDER BY prepared
    """,
    "database_info": """
        SELECT version() AS version, current_database() AS database,
               current_user AS user, pg_is_in_recovery() AS is_replica
    """,
    "locks": """
        SELECT l.locktype, l.relation::text AS relation, l.mode, l.granted,
               l.pid, l.transactionid::text AS transactionid,
               COALESCE(a.usename, '') AS usename,
               a.state, a.wait_event_type, a.wait_event,
               a.xact_start, a.query_start, COALESCE(a.query, '') AS query,
               CASE WHEN NOT l.granted THEN pg_blocking_pids(l.pid)
                    ELSE ARRAY[]::int[] END AS blocker_pids
        FROM pg_locks l
        LEFT JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE l.pid IS NOT NULL
    """,
    "long_running_queries": """
        SELECT pid, usename, datname, state, query, query_start,
               now() - query_start AS duration
        FROM pg_stat_activity
        WHERE state != 'idle'
          AND query NOT ILIKE '%pg_stat_activity%'
          AND now() - query_start > interval '5 seconds'
        ORDER BY duration DESC LIMIT 20
    """,
    "idle_transactions": """
        SELECT pid, usename, datname, application_name, state, xact_start,
               now() - xact_start AS transaction_age, query
        FROM pg_stat_activity
        WHERE state = 'idle in transaction' AND xact_start IS NOT NULL
        ORDER BY xact_start LIMIT 50
    """,
    "table_stats": """
        SELECT schemaname, relname AS tablename, n_live_tup AS live_tuples,
               n_dead_tup AS dead_tuples, n_tup_ins AS inserts,
               n_mod_since_analyze AS modifications_since_analyze,
               n_tup_upd AS updates, n_tup_del AS deletes,
               last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
        FROM pg_stat_user_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY n_live_tup DESC LIMIT 50
    """,
    "index_usage": """
        SELECT schemaname, relname AS tablename, indexrelname AS indexname,
               idx_scan AS scans, idx_tup_read AS tuples_read,
               idx_tup_fetch AS tuples_fetched
        FROM pg_stat_user_indexes
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY idx_scan DESC LIMIT 50
    """,
}


class ReadonlyHealthCollector:
    def __init__(self, config=None, statement_timeout_ms=2500, lock_timeout_ms=750):
        self.config = config or Config()
        self.statement_timeout_ms = statement_timeout_ms
        self.lock_timeout_ms = lock_timeout_ms

    def collect(self):
        connector = OpenTenBaseConnector(self.config)
        results = {}
        errors = {}
        try:
            connection = connector.connect()
            connection.set_session(readonly=True, autocommit=False)
            for name, sql in CHECKS.items():
                try:
                    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                        cursor.execute(
                            "SELECT set_config('statement_timeout', %s, true)",
                            (f"{self.statement_timeout_ms}ms",),
                        )
                        cursor.execute(
                            "SELECT set_config('lock_timeout', %s, true)",
                            (f"{self.lock_timeout_ms}ms",),
                        )
                        cursor.execute(sql)
                        results[name] = [dict(row) for row in cursor.fetchall()]
                    connection.rollback()
                except Exception as error:
                    connection.rollback()
                    errors[name] = {
                        "type": type(error).__name__,
                        "message": str(error).strip(),
                    }
            nodes = results.get("nodes", [])
            if nodes:
                results["node_connectivity"] = self._probe_node_connectivity(nodes)
                node_stats, node_stats_errors = self._collect_data_node_stats(
                    connection, nodes
                )
                results["data_node_table_stats"] = node_stats
                errors.update(node_stats_errors)
                prepared, prepared_errors = self._collect_data_node_prepared_xacts(
                    connection, nodes
                )
                results["data_node_prepared_transactions"] = prepared
                errors.update(prepared_errors)
        except Exception as error:
            errors["connection"] = {
                "type": type(error).__name__,
                "message": str(error).strip(),
            }
        finally:
            connector.close()
        return {
            "timestamp": datetime.now().astimezone().isoformat(),
            "status": "success" if not errors else ("partial" if results else "error"),
            "checks": results,
            "errors": errors,
        }

    @staticmethod
    def _probe_node_connectivity(nodes):
        checks = []
        for node in nodes:
            host, port = node.get("node_host"), node.get("node_port")
            status = "unknown"
            error = None
            if host and port:
                try:
                    with socket.create_connection((host, int(port)), timeout=0.75):
                        status = "reachable"
                except OSError as exception:
                    status = "unreachable"
                    error = str(exception)
            checks.append({
                "node_name": node.get("node_name"),
                "node_type": node.get("node_type"),
                "host": host,
                "port": port,
                "status": status,
                "error": error,
            })
        return checks

    def _collect_data_node_stats(self, connection, nodes):
        node_stats = []
        errors = {}
        data_nodes = [node for node in nodes if node.get("node_type") == "D"]
        for node in data_nodes:
            name = node.get("node_name")
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '2500ms'")
                    cursor.execute("SET LOCAL lock_timeout = '750ms'")
                    remote_query = (
                        "SELECT schemaname,relname,n_live_tup,n_mod_since_analyze,last_analyze "
                        "FROM pg_stat_user_tables "
                        "WHERE schemaname NOT IN ('pg_catalog','information_schema') LIMIT 200"
                    )
                    cursor.execute(
                        sql.SQL("EXECUTE DIRECT ON ({}) %s").format(sql.Identifier(name)),
                        (remote_query,),
                    )
                    columns = [item[0] for item in cursor.description]
                    node_stats.extend(
                        {"node_name": name, **dict(zip(columns, row))}
                        for row in cursor.fetchall()
                    )
                connection.rollback()
            except Exception as error:
                connection.rollback()
                errors[f"data_node_stats:{name}"] = {
                    "type": type(error).__name__,
                    "message": str(error).strip(),
                }

        by_table = {}
        for row in node_stats:
            key = (row["schemaname"], row["relname"])
            table = by_table.setdefault(key, {
                "schemaname": key[0],
                "tablename": key[1],
                "live_tuples": 0,
                "modifications_since_analyze": 0,
                "nodes": [],
            })
            table["live_tuples"] += row.get("n_live_tup") or 0
            table["modifications_since_analyze"] += row.get("n_mod_since_analyze") or 0
            table["nodes"].append({
                "node_name": row["node_name"],
                "live_tuples": row.get("n_live_tup") or 0,
                "modifications_since_analyze": row.get("n_mod_since_analyze") or 0,
                "last_analyze": row.get("last_analyze"),
            })
        return list(by_table.values()), errors

    def _collect_data_node_prepared_xacts(self, connection, nodes):
        transactions = []
        errors = {}
        for node in nodes:
            if node.get("node_type") != "D":
                continue
            name = node.get("node_name")
            try:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '2500ms'")
                    cursor.execute("SET LOCAL lock_timeout = '750ms'")
                    remote_query = (
                        "SELECT transaction::text AS transaction_id,gid,owner,database,prepared "
                        "FROM pg_prepared_xacts ORDER BY prepared"
                    )
                    cursor.execute(
                        sql.SQL("EXECUTE DIRECT ON ({}) %s").format(sql.Identifier(name)),
                        (remote_query,),
                    )
                    transactions.extend(
                        {"node_name": name, **dict(row)} for row in cursor.fetchall()
                    )
                connection.rollback()
            except Exception as error:
                connection.rollback()
                errors[f"data_node_prepared_transactions:{name}"] = {
                    "type": type(error).__name__,
                    "message": str(error).strip(),
                }
        return transactions, errors
