"""Performance metrics collector"""
from typing import Dict, Any, List
from psycopg2 import sql
from .base import BaseCollector
from ..utils.logger import setup_logger
from ..utils.config import Config
from ..utils.sql_redaction import redact_query_record

logger = setup_logger(__name__)


class PerformanceCollector(BaseCollector):
    """Collect performance metrics"""

    def __init__(self, db_connector, config: Config = None):
        super().__init__(db_connector)
        self.config = config or Config()

    def _query_rows(self, statement, params=None):
        with self.db.get_cursor() as cursor:
            cursor.execute(
                "SELECT set_config('statement_timeout', %s, true), "
                "set_config('lock_timeout', %s, true)",
                (
                    f"{self.config.AIOPS_COLLECTION_STATEMENT_TIMEOUT_MS}ms",
                    f"{self.config.AIOPS_COLLECTION_LOCK_TIMEOUT_MS}ms",
                ),
            )
            cursor.execute(statement, params)
            rows = cursor.fetchall()
            return [
                redact_query_record(
                    row,
                    redact_literals=getattr(
                        self.config, "AIOPS_SLOW_QUERY_REDACT_LITERALS", True
                    ),
                )
                for row in rows
            ]

    def _query_data_nodes(self, statement, check_name):
        nodes = self.db.execute_query(
            "SELECT node_name FROM pgxc_node WHERE node_type='D' ORDER BY node_name"
        )
        if nodes is None:
            self._record_error(
                "data_node_discovery", RuntimeError("Could not discover registered data nodes")
            )
            return None
        if not nodes:
            return None

        rows = []
        for node in nodes:
            node_name = node["node_name"]
            try:
                with self.db.get_cursor() as cursor:
                    cursor.execute(
                        "SELECT set_config('statement_timeout', %s, true), "
                        "set_config('lock_timeout', %s, true)",
                        (
                            f"{self.config.AIOPS_COLLECTION_STATEMENT_TIMEOUT_MS}ms",
                            f"{self.config.AIOPS_COLLECTION_LOCK_TIMEOUT_MS}ms",
                        ),
                    )
                    cursor.execute(
                        sql.SQL("EXECUTE DIRECT ON ({}) %s").format(sql.Identifier(node_name)),
                        (statement,),
                    )
                    rows.extend(
                        redact_query_record(
                            {"node_name": node_name, **dict(row)},
                            redact_literals=getattr(
                                self.config, "AIOPS_SLOW_QUERY_REDACT_LITERALS", True
                            ),
                        )
                        for row in cursor.fetchall()
                    )
            except Exception as error:
                self._record_error(f"data_node_{check_name}:{node_name}", error)
        return rows

    def _collect_single(self, name, reader, key):
        self.errors = []
        try:
            value = reader()
            if isinstance(value, dict) and value.get("error"):
                self._record_error(name, RuntimeError(value["error"]))
                value = [] if key != "locks" else {}
            return self._create_result(
                status="success", data={key: value}
            )
        except Exception as error:
            self._record_error(name, error)
            return self._create_result(status="error", error=str(error))

    def collect_locks(self):
        """Collect only lock state so unrelated catalog scans cannot block this view."""
        def read_locks():
            info = self.get_lock_info()
            return info.get("all_locks", info) if isinstance(info, dict) else info
        result = self._collect_single("locks", read_locks, "locks")
        lock_rows = result.get("data", {}).get("locks", [])
        result["data"]["summary"] = {
            "total_locks": len(lock_rows) if isinstance(lock_rows, list) else 0,
            "blocked_count": sum(1 for row in lock_rows if not row.get("granted"))
            if isinstance(lock_rows, list) else 0,
        }
        return result

    def collect_long_queries(self, threshold_seconds=5):
        threshold_seconds = max(1, min(int(threshold_seconds), 86400))
        statement = """
            SELECT pid, usename, datname, application_name, state, query,
                   query_start, now() - query_start AS duration
            FROM pg_catalog.pg_stat_activity
            WHERE state != 'idle'
              AND query NOT ILIKE '%%pg_stat_activity%%'
              AND now() - query_start > (%s * interval '1 second')
            ORDER BY duration DESC LIMIT 50
        """
        return self._collect_single(
            "long_running_queries",
            lambda: self._query_rows(statement, (threshold_seconds,)),
            "queries",
        )

    def collect_table_stats(self, limit=50):
        limit = max(1, min(int(limit), 500))
        statement = """
            SELECT schemaname, relname AS tablename, n_live_tup,
                   n_dead_tup, n_tup_ins, n_tup_upd, n_tup_del,
                   last_vacuum, last_autovacuum, last_analyze, last_autoanalyze,
                   pg_catalog.pg_relation_size(relid) AS table_size_bytes,
                   pg_catalog.pg_indexes_size(relid) AS indexes_size_bytes,
                   pg_catalog.pg_total_relation_size(relid) AS total_size_bytes
            FROM pg_catalog.pg_stat_user_tables
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY n_live_tup DESC LIMIT %s
        """

        def read_tables():
            remote_statement = statement.replace("LIMIT %s", f"LIMIT {limit}")
            rows = self._query_data_nodes(remote_statement, "table_stats")
            if rows is not None:
                return sorted(rows, key=lambda row: row.get("n_live_tup") or 0, reverse=True)[:limit]
            return self._query_rows(statement, (limit,))

        return self._collect_single(
            "table_stats", read_tables, "tables"
        )

    def collect(self) -> Dict[str, Any]:
        """Collect all performance metrics"""
        self.errors = []
        try:
            return self._create_result(
                status='success',
                data={
                    'locks': self.get_lock_info(),
                    'long_running_queries': self.get_long_running_queries(),
                    'table_stats': self.get_table_stats(),
                    'index_usage': self.get_index_usage()
                }
            )
        except Exception as e:
            self._record_error('performance', e)
            logger.error(f"Performance collection failed: {e}")
            return self._create_result(status='error', error=str(e))

    def get_lock_info(self) -> Dict[str, Any]:
        """Get lock information"""
        sql = """
        SELECT
            l.pid,
            l.locktype,
            l.relation::regclass::text as relation,
            l.mode,
            l.granted,
            a.query,
            a.state,
            a.query_start,
            NOW() - a.query_start as duration
        FROM pg_locks l
        LEFT JOIN pg_stat_activity a ON l.pid = a.pid
        WHERE l.pid IS NOT NULL
        ORDER BY l.granted, duration DESC
        LIMIT 100;
        """
        try:
            locks = self._query_rows(sql)
            node_locks = self._query_data_nodes(sql, "locks")
            if node_locks is not None:
                locks.extend(node_locks)

            blocking = [l for l in locks if not l['granted']] if locks else []
            active = [l for l in locks if l['granted']] if locks else []

            return {
                'all_locks': locks or [],
                'blocking_locks': blocking,
                'active_locks': active,
                'total_locks': len(locks) if locks else 0,
                'blocked_count': len(blocking)
            }
        except Exception as e:
            self._record_error('locks', e)
            logger.error(f"Failed to get lock info: {e}")
            return {'error': str(e)}

    def get_long_running_queries(self) -> List[Dict[str, Any]]:
        """Get long running queries"""
        sql = """
        SELECT
            pid,
            usename,
            datname,
            state,
            query,
            query_start,
            NOW() - query_start as duration
        FROM pg_stat_activity
        WHERE state != 'idle'
          AND query NOT ILIKE '%pg_stat_activity%'
          AND NOW() - query_start > interval '5 seconds'
        ORDER BY duration DESC
        LIMIT 20;
        """
        try:
            result = self._query_rows(sql)
            node_queries = self._query_data_nodes(sql, "long_running_queries")
            if node_queries is not None:
                result.extend(node_queries)
            return result if result else []
        except Exception as e:
            self._record_error('long_running_queries', e)
            logger.error(f"Failed to get long running queries: {e}")
            return []

    def get_table_stats(self) -> List[Dict[str, Any]]:
        """Get table statistics"""
        sql = """
        SELECT
            schemaname,
            relname AS tablename,
            n_live_tup as live_tuples,
            n_dead_tup as dead_tuples,
            n_tup_ins as inserts,
            n_tup_upd as updates,
            n_tup_del as deletes,
            last_vacuum,
            last_autovacuum,
            last_analyze,
            last_autoanalyze,
            pg_catalog.pg_relation_size(relid) as table_size_bytes,
            pg_catalog.pg_indexes_size(relid) as indexes_size_bytes,
            pg_catalog.pg_total_relation_size(relid) as total_size_bytes
        FROM pg_stat_user_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY n_live_tup DESC
        LIMIT 50;
        """
        try:
            result = self._query_data_nodes(sql, "table_stats")
            if result is None:
                result = self._query_rows(sql)
            return result if result else []
        except Exception as e:
            self._record_error('table_stats', e)
            logger.error(f"Failed to get table stats: {e}")
            return []

    def get_index_usage(self) -> List[Dict[str, Any]]:
        """Get index usage statistics"""
        sql = """
        SELECT
            schemaname,
            relname AS tablename,
            indexrelname AS indexname,
            idx_scan as scans,
            idx_tup_read as tuples_read,
            idx_tup_fetch as tuples_fetched
        FROM pg_stat_user_indexes
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY idx_scan DESC
        LIMIT 50;
        """
        try:
            result = self._query_data_nodes(sql, "index_usage")
            if result is None:
                result = self._query_rows(sql)

            # Find unused indexes
            unused = [idx for idx in result if idx['scans'] == 0] if result else []

            return result if result else []
        except Exception as e:
            self._record_error('index_usage', e)
            logger.error(f"Failed to get index usage: {e}")
            return []
