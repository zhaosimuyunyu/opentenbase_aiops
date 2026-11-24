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
        WHERE l.pid IS NOT NULL OR l.granted
        """
        db.connect().set_session(readonly=True)
        with db.get_cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '2500ms'")
            cursor.execute("SET LOCAL lock_timeout = '750ms'")
            cursor.execute(sql)
            rows = cursor.fetchall()
        if not include_granted:
            rows = [row for row in rows if not row['granted']]
        return {
            'collection_status': 'success',
            'total_locks': len(rows),
            'blocked_locks': sum(1 for row in rows if not row['granted']),
            'locks': rows,
        }
    except Exception as error:
        return {
            'collection_status': 'error',
            'collection_errors': {'locks': {'type': type(error).__name__}},
            'total_locks': None,
            'blocked_locks': None,
            'locks': [],
        }
    finally:
        db.close()

