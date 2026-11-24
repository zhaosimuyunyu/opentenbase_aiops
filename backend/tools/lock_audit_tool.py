LOCK_TOOL_SCHEMA = {'type': 'function', 'function': {'name': 'get_database_locks', 'description': 'Get current lock status from OpenTenBase cluster', 'parameters': {'type': 'object', 'properties': {'include_granted': {'type': 'boolean', 'default': True}}}}}
from ..utils.db_connector import OpenTenBaseConnector

async def execute_get_database_locks(include_granted: bool = True):
    db = OpenTenBaseConnector()
    try:
        sql = """
        SELECT l.locktype, l.relation::text AS relation, l.mode, l.granted, l.pid,
               l.transactionid::text AS transactionid, l.virtualxid::text AS virtualxid,
               COALESCE(a.usename, '') AS usename,
               COALESCE(a.application_name, '') AS application_name,
               a.state, a.wait_event_type, a.wait_event, a.xact_start, a.query_start,
               COALESCE(a.query, '') AS query,
               CASE WHEN NOT l.granted THEN pg_blocking_pids(l.pid) ELSE ARRAY[]::int[] END AS blocker_pids
        FROM pg_locks l
        LEFT JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE l.pid IS NOT NULL
        """
        rows = db.execute_query(sql) or []
        if not include_granted:
            rows = [row for row in rows if not row['granted']]
        return {
            'total_locks': len(rows),
            'blocked_locks': sum(1 for row in rows if not row['granted']),
            'locks': rows,
        }
    finally:
        db.close()

