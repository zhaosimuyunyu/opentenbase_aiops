import importlib.util
import unittest
from unittest.mock import MagicMock, patch


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "FastAPI is available in the API runtime")
class AutomationStatusTests(unittest.TestCase):
    @staticmethod
    def _get_status():
        from backend.app import get_automation_status
        return get_automation_status()

    def test_llm_client_is_initialized_on_first_ai_use_and_then_reused(self):
        from backend import app

        client = object()
        with patch.object(app, "llm_client", None), patch.object(
            app, "DeepSeekClient", return_value=client
        ) as client_factory:
            self.assertIs(app.get_llm_client(), client)
            self.assertIs(app.get_llm_client(), client)

        client_factory.assert_called_once_with(app.config)

    def test_audit_detail_redacts_legacy_query_literals_before_return(self):
        from backend.app import get_audit

        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            {"audit_table": "audit_records"},
            {
                "audit_id": "audit-legacy", "audit_type": "readonly_health_audit",
                "created_at": None, "risk_level": "medium", "status": "completed",
                "evidence": {
                    "performance": {
                        "slow_query_logs": [{
                            "query": "SELECT * FROM users WHERE email='private@example.com'",
                        }],
                    },
                },
                "ai_analysis": {}, "knowledge_refs": [],
            },
        ]
        with patch("backend.app.OperationsStore", return_value=store):
            result = get_audit("audit-legacy")

        query = result["evidence"]["performance"]["slow_query_logs"][0]
        self.assertEqual(query["query"], "SELECT * FROM users WHERE email='?'")
        self.assertNotIn("private@example.com", str(result))
        self.assertTrue(query["query_redacted"])
        store.close.assert_called_once()

    def test_reports_enabled_auto_repair_configuration_without_audit_tables(self):
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            {"audit_table": None},
            {"repair_table": None},
        ]
        with patch("backend.app.OperationsStore", return_value=store), patch(
            "backend.app.RepairWorkflow.readiness", return_value={
                "executor_ready": True, "ready": True, "targets": {"public.orders": True}
            }
        ), patch.multiple(
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
        self.assertTrue(status["repair_readiness"]["ready"])
        self.assertTrue(status["automatic_repair_ready"])
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
        with patch("backend.app.OperationsStore", return_value=store), patch(
            "backend.app.RepairWorkflow.readiness", return_value={
                "executor_ready": False, "ready": False,
                "reason": "separate_repair_account_not_configured",
            }
        ), patch.multiple(
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
        self.assertFalse(status["automatic_repair_ready"])
        self.assertEqual(status["repair_readiness"]["reason"], "separate_repair_account_not_configured")
        self.assertFalse(status["automatic_repair_enabled"])
        self.assertEqual(status["automatic_repair_targets"], [])
        self.assertFalse(status["repair_function_enabled"])


if __name__ == "__main__":
    unittest.main()
