"""Read-only OpenTenBase health checks with isolated query failures."""
from datetime import datetime

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
