import importlib.util
import unittest
from unittest.mock import MagicMock, patch


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "FastAPI is available in the API runtime")
class AutomationStatusTests(unittest.TestCase):
    @staticmethod
    def _get_status():
        from backend.app import get_automation_status
        return get_automation_status()

    def test_reports_enabled_auto_repair_configuration_without_audit_tables(self):
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            {"audit_table": None},
            {"repair_table": None},
        ]
        with patch("backend.app.OperationsStore", return_value=store), patch.multiple(
            "backend.app.config",
            AIOPS_AUTO_AUDIT_ENABLED=True,
            AIOPS_AUTO_AUDIT_INTERVAL_SECONDS=300,
            AIOPS_AUTO_AUDIT_TABLE="public.orders",
            AIOPS_AUTO_AUDIT_TARGETS=("public.orders",),
            AIOPS_REPAIR_DB_USER="repair_user",
            DB_USER="auditor",
            AIOPS_AUTO_REPAIR_ENABLED=True,
            AIOPS_AUTO_REPAIR_TARGETS=("public.orders",),
            AIOPS_REPAIR_FUNCTION_ENABLED=True,
            AIOPS_REPAIR_FUNCTION_SCHEMA="aiops_admin",
            AIOPS_REPAIR_FUNCTION_NAME="analyze_table",
        ):
            status = self._get_status()

        self.assertTrue(status["repair_executor_ready"])
        self.assertTrue(status["automatic_repair_enabled"])
        self.assertEqual(status["automatic_repair_targets"], ["public.orders"])
        self.assertTrue(status["repair_function_enabled"])
        self.assertEqual(status["repair_function"], "aiops_admin.analyze_table")
        self.assertIsNone(status["latest_audit"])
        store.close.assert_called_once()

    def test_reports_missing_repair_login_as_not_ready(self):
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            {"audit_table": None},
            {"repair_table": None},
        ]
        with patch("backend.app.OperationsStore", return_value=store), patch.multiple(
            "backend.app.config",
            AIOPS_AUTO_AUDIT_ENABLED=False,
            AIOPS_AUTO_AUDIT_INTERVAL_SECONDS=900,
            AIOPS_AUTO_AUDIT_TABLE=None,
            AIOPS_AUTO_AUDIT_TARGETS=(None,),
            AIOPS_REPAIR_DB_USER="",
            DB_USER="opentenbase",
            AIOPS_AUTO_REPAIR_ENABLED=False,
            AIOPS_AUTO_REPAIR_TARGETS=(),
            AIOPS_REPAIR_FUNCTION_ENABLED=False,
            AIOPS_REPAIR_FUNCTION_SCHEMA="aiops_admin",
            AIOPS_REPAIR_FUNCTION_NAME="analyze_table",
        ):
            status = self._get_status()

        self.assertFalse(status["repair_executor_ready"])
        self.assertFalse(status["automatic_repair_enabled"])
        self.assertEqual(status["automatic_repair_targets"], [])
        self.assertFalse(status["repair_function_enabled"])


if __name__ == "__main__":
    unittest.main()
