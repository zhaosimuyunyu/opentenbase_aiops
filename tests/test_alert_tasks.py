import unittest
from unittest.mock import MagicMock, patch

from backend.engines.alert_tasks import AlertTaskStore


class AlertTaskStoreTests(unittest.TestCase):
    def test_create_persists_alert_summary_and_target(self):
        store = MagicMock()
        with patch("backend.engines.alert_tasks.OperationsStore", return_value=store), patch(
            "backend.engines.alert_tasks.uuid.uuid4", return_value="task-1"
        ):
            task_id = AlertTaskStore().create(
                "firing", [{"alertname": "high-risk"}], "public.orders"
            )
        self.assertEqual(task_id, "task-1")
        statement, parameters = store.conn.cursor.return_value.__enter__.return_value.execute.call_args_list[-1].args
        self.assertIn("INSERT INTO alert_audit_tasks", statement)
        self.assertEqual(parameters[0:3], ("task-1", "firing", 1))
        self.assertEqual(parameters[4], "public.orders")
        store.close.assert_called_once()

    def test_finish_records_audit_and_fallback_outcome(self):
        store = MagicMock()
        with patch("backend.engines.alert_tasks.OperationsStore", return_value=store):
            AlertTaskStore().finish(
                "task-1", status="completed",
                result={"audit_id": "audit-1", "analysis_fallback": True},
            )
        statement, parameters = store.conn.cursor.return_value.__enter__.return_value.execute.call_args.args
        self.assertIn("WHERE task_id=%s AND status='running'", statement)
        self.assertEqual(parameters, ("completed", "audit-1", True, None, "task-1"))

    def test_restart_marks_inflight_tasks_interrupted(self):
        store = MagicMock()
        store.conn.cursor.return_value.__enter__.return_value.rowcount = 2
        with patch("backend.engines.alert_tasks.OperationsStore", return_value=store):
            count = AlertTaskStore().mark_interrupted()
        self.assertEqual(count, 2)
        statement = store.conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        self.assertIn("SET status='interrupted'", statement)
        self.assertIn("WHERE status='running'", statement)

    def test_restart_before_first_task_table_creation_is_a_noop(self):
        store = MagicMock()
        store.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (None,)
        with patch("backend.engines.alert_tasks.OperationsStore", return_value=store):
            count = AlertTaskStore().mark_interrupted()
        self.assertEqual(count, 0)
        self.assertEqual(store.conn.cursor.return_value.__enter__.return_value.execute.call_count, 1)

    def test_get_before_first_task_table_creation_returns_none(self):
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"task_table": None}
        with patch("backend.engines.alert_tasks.OperationsStore", return_value=store):
            task = AlertTaskStore().get("missing-task")
        self.assertIsNone(task)
        self.assertEqual(cursor.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
