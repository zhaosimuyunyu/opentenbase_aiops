"""Durable lifecycle records for Alertmanager-triggered audits."""
import uuid

from psycopg2.extras import Json, RealDictCursor

from ..utils.operations_store import OperationsStore


class AlertTaskStore:
    def create(self, alert_status, alerts, target, worker_id=None):
        task_id = str(uuid.uuid4())
        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS alert_audit_tasks (
                        task_id text PRIMARY KEY,
                        alert_status text NOT NULL,
                        alert_count integer NOT NULL,
                        alert_summary jsonb NOT NULL,
                        target text,
                        worker_id text,
                        status text NOT NULL,
                        audit_id text,
                        analysis_fallback boolean,
                        error_type text,
                        created_at timestamptz NOT NULL DEFAULT now(),
                        updated_at timestamptz NOT NULL DEFAULT now()
                    )
                """)
                cursor.execute(
                    "ALTER TABLE alert_audit_tasks ADD COLUMN IF NOT EXISTS worker_id text"
                )
                cursor.execute("""
                    INSERT INTO alert_audit_tasks(
                        task_id, alert_status, alert_count, alert_summary, target, worker_id, status
                    ) VALUES (%s,%s,%s,%s,%s,%s,'running')
                """, (task_id, alert_status, len(alerts), Json(alerts), target, worker_id))
            return task_id
        finally:
            store.close()

    def finish(self, task_id, *, status, result=None, error_type=None):
        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE alert_audit_tasks
                    SET status=%s, audit_id=%s, analysis_fallback=%s,
                        error_type=%s, updated_at=now()
                    WHERE task_id=%s AND status='running'
                """, (
                    status,
                    result.get("audit_id") if result else None,
                    result.get("analysis_fallback") if result else None,
                    error_type,
                    task_id,
                ))
        finally:
            store.close()

    def get(self, task_id):
        store = OperationsStore()
        try:
            with store.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT to_regclass('public.alert_audit_tasks') AS task_table"
                )
                if cursor.fetchone()["task_table"] is None:
                    return None
                cursor.execute("""
                    SELECT task_id, alert_status, alert_count, alert_summary, target,
                           status, audit_id, analysis_fallback, error_type,
                           created_at, updated_at
                    FROM alert_audit_tasks WHERE task_id=%s
                """, (task_id,))
                task = cursor.fetchone()
                return dict(task) if task else None
        finally:
            store.close()

    def mark_interrupted(self, worker_id=None):
        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.alert_audit_tasks')")
                if cursor.fetchone()[0] is None:
                    return 0
                cursor.execute(
                    "ALTER TABLE alert_audit_tasks ADD COLUMN IF NOT EXISTS worker_id text"
                )
                if worker_id is None:
                    cursor.execute("""
                        UPDATE alert_audit_tasks
                        SET status='interrupted', error_type='ServiceRestart', updated_at=now()
                        WHERE status='running' AND worker_id IS NULL
                    """)
                else:
                    cursor.execute("""
                        UPDATE alert_audit_tasks
                        SET status='interrupted', error_type='ServiceRestart', updated_at=now()
                        WHERE status='running' AND (worker_id=%s OR worker_id IS NULL)
                    """, (worker_id,))
                return cursor.rowcount
        finally:
            store.close()
