"""Read-only OpenTenBase health checks with isolated query failures."""
from datetime import datetime
import socket
import time

from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from ..utils.config import Config
from ..utils.db_connector import OpenTenBaseConnector
from .slow_query_logs import SlowQueryLogCollector


def _collection_error(error):
    return {
        "type": type(error).__name__,
        "message": str(error).strip(),
        "sqlstate": getattr(error, "pgcode", None),
    }


def stale_statistics_nodes(nodes):
    return [
        node["node_name"] for node in nodes
        if (node.get("modifications_since_analyze") or 0)
        >= max(1000, (node.get("live_tuples") or 0) * 0.2)
    ]


CHECKS = {
    "pg_unlock_diagnostics": """
        SELECT dependency_oid IS NOT NULL AS dependency_registered,
               pg_catalog.has_function_privilege(dependency_oid, 'EXECUTE') AS dependency_executable,
               deadlock_oid IS NOT NULL AS deadlock_registered,
               pg_catalog.has_function_privilege(deadlock_oid, 'EXECUTE') AS deadlock_executable,
               EXISTS (SELECT 1 FROM pg_catalog.pg_available_extensions
                       WHERE name = 'pg_unlock') AS package_available
        FROM (SELECT pg_catalog.to_regprocedure('pg_unlock_check_dependency()')::oid
                     AS dependency_oid,
                     pg_catalog.to_regprocedure('pg_unlock_check_deadlock()')::oid
                     AS deadlock_oid) AS diagnostic
    """,
    "pg_clean_diagnostics": """
        SELECT function_oid IS NOT NULL AS registered,
               pg_catalog.has_function_privilege(function_oid, 'EXECUTE') AS executable,
               record_list_oid IS NOT NULL AS record_list_registered,
               pg_catalog.has_function_privilege(record_list_oid, 'EXECUTE') AS record_list_executable,
               EXISTS (SELECT 1 FROM pg_catalog.pg_available_extensions
                       WHERE name = 'pg_clean') AS package_available,
               (SELECT extversion FROM pg_catalog.pg_extension
                WHERE extname = 'pg_clean') AS installed_version,
               pg_catalog.current_setting('enable_clean_2pc_launcher', true) AS launcher_setting
        FROM (SELECT pg_catalog.to_regprocedure('pg_clean_check_txn(integer)')::oid
                     AS function_oid,
                     pg_catalog.to_regprocedure('pgxc_get_record_list()')::oid
                     AS record_list_oid) AS diagnostic
    """,
    "database_identity": """
        SELECT system_identifier::text AS system_identifier,
               current_database() AS database
        FROM pg_catalog.pg_control_system()
    """,
    "nodes": """
        SELECT node_name, node_type, node_host, node_port,
               nodeis_primary, nodeis_preferred
        FROM pgxc_node ORDER BY node_type, node_name
    """,
    "connections": """
        SELECT datname, state, count(*) AS connection_count
        FROM pg_catalog.pg_stat_activity
        WHERE backend_type = 'client backend'
        GROUP BY datname, state
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
               COALESCE(a.datname, '') AS database,
               COALESCE(a.application_name, '') AS application_name,
               a.state, a.wait_event_type, a.wait_event,
               a.xact_start, a.query_start, COALESCE(a.query, '') AS query,
               CASE WHEN NOT l.granted THEN array_remove(pg_blocking_pids(l.pid), 0)
                    ELSE ARRAY[]::int[] END AS blocker_pids
        FROM pg_locks l
        LEFT JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE l.pid IS NOT NULL OR l.granted
    """,
    "data_node_lock_blockers": """
        WITH waiting AS (
            SELECT DISTINCT l.pid AS waiting_pid, l.locktype,
                   l.relation::text AS relation, l.transactionid::text AS transactionid,
                   l.mode AS waiting_mode,
                   unnest(pg_catalog.pg_blocking_pids(l.pid)) AS blocker_pid
            FROM pg_catalog.pg_locks l
            WHERE NOT l.granted AND l.pid IS NOT NULL
        )
        SELECT w.waiting_pid, w.locktype, w.relation, w.transactionid, w.waiting_mode,
               a.pid, COALESCE(a.usename, '') AS usename,
               COALESCE(a.datname, '') AS database,
               COALESCE(a.application_name, '') AS application_name,
               a.state, a.xact_start, a.query_start, COALESCE(a.query, '') AS query,
               a.backend_type
        FROM waiting w
        JOIN pg_catalog.pg_stat_activity a ON a.pid = w.blocker_pid
        WHERE a.backend_type = 'client backend'
    """,
    "long_running_queries": """
        SELECT pid, usename, datname, application_name, state, query, query_start,
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
    "key_guc": """
        SELECT name, setting, unit, source, short_desc
        FROM pg_catalog.pg_settings
        WHERE name IN (
            'max_connections', 'shared_buffers', 'work_mem',
            'maintenance_work_mem', 'statement_timeout', 'lock_timeout',
            'idle_in_transaction_session_timeout', 'max_prepared_transactions',
            'wal_level', 'synchronous_commit'
        )
        ORDER BY name
    """,
    "storage": """
        SELECT n.nspname AS schema_name,
               c.relname AS relation_name,
               c.relkind,
               pg_catalog.pg_total_relation_size(c.oid) AS total_bytes,
               pg_catalog.pg_relation_size(c.oid) AS table_bytes,
               COALESCE(s.n_live_tup, 0) AS live_tuples,
               COALESCE(s.n_dead_tup, 0) AS dead_tuples
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_catalog.pg_stat_user_tables s ON s.relid = c.oid
        WHERE c.relkind IN ('r', 'm')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY pg_catalog.pg_total_relation_size(c.oid) DESC
        LIMIT 50
    """,
}


class ReadonlyHealthCollector:
    def __init__(self, config=None, statement_timeout_ms=None, lock_timeout_ms=None):
        self.config = config or Config()
        self.statement_timeout_ms = max(
            250,
            int(statement_timeout_ms if statement_timeout_ms is not None else
                getattr(self.config, "AIOPS_COLLECTION_STATEMENT_TIMEOUT_MS", 2500)),
        )
        self.lock_timeout_ms = max(
            100,
            int(lock_timeout_ms if lock_timeout_ms is not None else
                getattr(self.config, "AIOPS_COLLECTION_LOCK_TIMEOUT_MS", 750)),
        )

    def _set_query_timeouts(self, cursor):
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true), set_config('lock_timeout', %s, true)",
            (f"{self.statement_timeout_ms}ms", f"{self.lock_timeout_ms}ms"),
        )

    def collect(self, *, table=None):
        collection_started = time.perf_counter()
        connector = OpenTenBaseConnector(self.config)
        results = {}
        errors = {}
        try:
            connection = connector.connect()
            connection.set_session(readonly=True, autocommit=False)
            for name, sql in CHECKS.items():
                distributed_nodes = results.get("nodes", [])
                if name in {"table_stats", "index_usage", "storage"} and any(
                    node.get("node_type") == "D" for node in distributed_nodes
                ):
                    continue
                try:
                    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                        self._set_query_timeouts(cursor)
                        cursor.execute(sql)
                        results[name] = [dict(row) for row in cursor.fetchall()]
                    connection.rollback()
                except Exception as error:
                    connection.rollback()
                    errors[name] = _collection_error(error)
            nodes = results.get("nodes", [])
            pg_clean_rows, pg_clean_errors = self._collect_pg_clean_transactions(
                connection,
                results.get("pg_clean_diagnostics", []),
                results.get("prepared_transactions", []),
            )
            if pg_clean_rows or pg_clean_errors:
                results["pg_clean_transaction_diagnostics"] = pg_clean_rows
            errors.update(pg_clean_errors)
            if "nodes" in results:
                connectivity = self._probe_node_connectivity(nodes)
                results["node_connectivity"] = connectivity
                for node in connectivity:
                    if node["status"] != "reachable":
                        errors[f"node_connectivity:{node['node_name']}"] = {
                            "type": "NodeConnectivity",
                            "message": node["error"] or "Node endpoint is unavailable",
                        }
                slow_query_logs, slow_query_log_errors = SlowQueryLogCollector(
                    self.config
                ).collect(nodes)
                results["slow_query_logs"] = slow_query_logs
                errors.update(slow_query_log_errors)
            if any(node.get("node_type") == "D" for node in nodes):
                blocker_rows, blocker_errors = self._collect_data_node_lock_blockers(connection, nodes)
                results["data_node_lock_blockers"] = blocker_rows
                errors.update(blocker_errors)
                long_query_rows, long_query_errors = self._collect_data_node_long_queries(connection, nodes)
                results["data_node_long_running_queries"] = long_query_rows
                errors.update(long_query_errors)
                node_stats, node_stats_errors = self._collect_data_node_stats(
                    connection, nodes, table=table
                )
                results["data_node_table_stats"] = node_stats
                errors.update(node_stats_errors)
                node_index_usage, index_usage_errors = self._collect_data_node_rows(
                    connection, nodes, "index_usage", CHECKS["index_usage"]
                )
                results["data_node_index_usage"] = node_index_usage
                errors.update(index_usage_errors)
                node_storage, storage_errors = self._collect_data_node_rows(
                    connection, nodes, "storage", CHECKS["storage"]
                )
                results["data_node_storage"] = node_storage
                errors.update(storage_errors)
                if table is None and any(
                    error.get("sqlstate") == "55P03" or error.get("type") == "CollectionLimit"
                    for error in node_stats_errors.values()
                ):
                    fallback_stats = {}
                    for target in self.config.AIOPS_AUTO_AUDIT_TARGETS:
                        if target is None:
                            continue
                        tables, target_errors = self._collect_data_node_stats(
                            connection, nodes, table=target
                        )
                        fallback_stats[target] = {"tables": tables, "errors": target_errors}
                    if fallback_stats:
                        results["data_node_stats_fallback"] = fallback_stats
                prepared, prepared_errors = self._collect_data_node_prepared_xacts(
                    connection, nodes
                )
                results["data_node_prepared_transactions"] = prepared
                errors.update(prepared_errors)
            elif "nodes" in results:
                errors["data_node_stats:topology"] = {
                    "type": "MissingDataNodes",
                    "message": "No data nodes are registered",
                }
        except Exception as error:
            errors["connection"] = _collection_error(error)
        finally:
            connector.close()
        return {
            "timestamp": datetime.now().astimezone().isoformat(),
            "collection_duration_ms": round((time.perf_counter() - collection_started) * 1000, 2),
            "status": "success" if not errors else ("partial" if results else "error"),
            "checks": results,
            "errors": errors,
        }

    def _collect_data_node_rows(self, connection, nodes, check_name, statement):
        rows = []
        errors = {}
        for node in nodes:
            if node.get("node_type") != "D":
                continue
            name = node.get("node_name")
            try:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    self._set_query_timeouts(cursor)
                    cursor.execute(
                        sql.SQL("EXECUTE DIRECT ON ({}) %s").format(sql.Identifier(name)),
                        (statement,),
                    )
                    rows.extend(
                        {"node_name": name, **dict(row)} for row in cursor.fetchall()
                    )
                connection.rollback()
            except Exception as error:
                connection.rollback()
                errors[f"data_node_{check_name}:{name}"] = _collection_error(error)
        return rows, errors

    def _collect_pg_clean_transactions(self, connection, diagnostics, prepared_transactions):
        diagnostic = next(iter(diagnostics or []), {})
        if not prepared_transactions or not all(
            diagnostic.get(key) is True
            for key in ("registered", "executable")
        ):
            return [], {}

        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self._set_query_timeouts(cursor)
                cursor.execute(
                    "SELECT * FROM pg_clean_check_txn(%s)",
                    (self.config.AIOPS_PG_CLEAN_MIN_AGE_SECONDS,),
                )
                rows = [dict(row) for row in cursor.fetchall()]
            connection.rollback()
            return rows, {}
        except Exception as error:
            connection.rollback()
            return [], {"pg_clean_transaction_diagnostics": _collection_error(error)}

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

    def _collect_data_node_stats(self, connection, nodes, *, table=None):
        node_stats = []
        errors = {}
        data_nodes = [node for node in nodes if node.get("node_type") == "D"]
        limit = self.config.AIOPS_DATA_NODE_TABLE_LIMIT
        for node in data_nodes:
            name = node.get("node_name")
            try:
                with connection.cursor() as cursor:
                    self._set_query_timeouts(cursor)
                    remote_query = (
                        "SELECT schemaname,relname,relid,n_live_tup,n_dead_tup,n_mod_since_analyze,"
                        "last_analyze,last_autoanalyze "
                        "FROM pg_stat_user_tables "
                        "WHERE schemaname NOT IN ('pg_catalog','information_schema') "
                        f"ORDER BY schemaname, relname LIMIT {limit + 1}"
                    )
                    if table:
                        schema, relation = table.split(".", 1)
                        qualified = sql.Identifier(schema, relation).as_string(connection)
                        remote_query = sql.SQL(
                            "SELECT {}::text AS schemaname, relname, oid AS relid, "
                            "pg_stat_get_live_tuples(oid) AS n_live_tup, "
                            "pg_stat_get_dead_tuples(oid) AS n_dead_tup, "
                            "pg_stat_get_mod_since_analyze(oid) AS n_mod_since_analyze, "
                            "pg_stat_get_last_analyze_time(oid) AS last_analyze, "
                            "pg_stat_get_last_autoanalyze_time(oid) AS last_autoanalyze "
                            "FROM pg_catalog.pg_class WHERE oid=pg_catalog.to_regclass({}) "
                            "AND relkind IN ('r', 'p')"
                        ).format(sql.Literal(schema), sql.Literal(qualified)).as_string(connection)
                    cursor.execute(
                        sql.SQL("EXECUTE DIRECT ON ({}) %s").format(sql.Identifier(name)),
                        (remote_query,),
                    )
                    columns = [item[0] for item in cursor.description]
                    rows = cursor.fetchall()
                    if len(rows) > limit:
                        errors[f"data_node_stats:{name}"] = {
                            "type": "CollectionLimit",
                            "message": f"Only the first {limit} tables were collected",
                        }
                        rows = rows[:limit]
                    if table and not rows:
                        raise ValueError("Target table statistics are unavailable on this node")
                    node_stats.extend(
                        {"node_name": name, **dict(zip(columns, row))}
                        for row in rows
                    )
                connection.rollback()
            except Exception as error:
                connection.rollback()
                errors[f"data_node_stats:{name}"] = _collection_error(error)

        by_table = {}
        for row in node_stats:
            key = (row["schemaname"], row["relname"])
            table = by_table.setdefault(key, {
                "schemaname": key[0],
                "tablename": key[1],
                "live_tuples": 0,
                "dead_tuples": 0,
                "modifications_since_analyze": 0,
                "nodes": [],
            })
            table["live_tuples"] += row.get("n_live_tup") or 0
            table["dead_tuples"] += row.get("n_dead_tup") or 0
            table["modifications_since_analyze"] += row.get("n_mod_since_analyze") or 0
            table["nodes"].append({
                "node_name": row["node_name"],
                "relation_oid": row.get("relid"),
                "live_tuples": row.get("n_live_tup") or 0,
                "dead_tuples": row.get("n_dead_tup") or 0,
                "modifications_since_analyze": row.get("n_mod_since_analyze") or 0,
                "last_analyze": row.get("last_analyze"),
                "last_autoanalyze": row.get("last_autoanalyze"),
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
                    self._set_query_timeouts(cursor)
                    remote_query = (
                        "SELECT p.transaction::text AS transaction_id,p.gid,p.owner,p.database,p.prepared, "
                        "ARRAY(SELECT DISTINCT l.pid FROM pg_locks l "
                        "WHERE l.locktype='transactionid' AND l.transactionid=p.transaction "
                        "AND NOT l.granted AND l.pid IS NOT NULL ORDER BY l.pid) AS waiting_pids "
                        "FROM pg_prepared_xacts p ORDER BY p.prepared"
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
                errors[f"data_node_prepared_transactions:{name}"] = _collection_error(error)
        return transactions, errors

    def _collect_data_node_lock_blockers(self, connection, nodes):
        blockers = []
        errors = {}
        for node in nodes:
            if node.get("node_type") != "D":
                continue
            name = node.get("node_name")
            try:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    self._set_query_timeouts(cursor)
                    cursor.execute(
                        sql.SQL("EXECUTE DIRECT ON ({}) %s").format(sql.Identifier(name)),
                        (CHECKS["data_node_lock_blockers"],),
                    )
                    blockers.extend(
                        {"node_name": name, **dict(row)} for row in cursor.fetchall()
                    )
                connection.rollback()
            except Exception as error:
                connection.rollback()
                errors[f"data_node_lock_blockers:{name}"] = _collection_error(error)
        return blockers, errors

    def _collect_data_node_long_queries(self, connection, nodes):
        queries = []
        errors = {}
        for node in nodes:
            if node.get("node_type") != "D":
                continue
            name = node.get("node_name")
            try:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    self._set_query_timeouts(cursor)
                    cursor.execute(
                        sql.SQL("EXECUTE DIRECT ON ({}) %s").format(sql.Identifier(name)),
                        (CHECKS["long_running_queries"],),
                    )
                    queries.extend({"node_name": name, **dict(row)} for row in cursor.fetchall())
                connection.rollback()
            except Exception as error:
                connection.rollback()
                errors[f"data_node_long_running_queries:{name}"] = _collection_error(error)
        return queries, errors
