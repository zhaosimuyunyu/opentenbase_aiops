import unittest
from unittest.mock import MagicMock, patch

from backend.engines.repair_workflow import RepairWorkflow


class RepairClaimTests(unittest.TestCase):
    def test_reject_denies_invalid_token_before_accessing_storage(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(AIOPS_APPROVAL_TOKEN="test-token")
        with patch("backend.engines.repair_workflow.PgVectorKnowledgeBase") as store:
            with self.assertRaises(PermissionError):
                workflow.reject("request-1", "operator", "reason", "wrong-token")
            store.assert_not_called()

    def test_interrupted_execution_cannot_be_claimed_again(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(AIOPS_APPROVAL_TOKEN="test-token", AIOPS_APPROVER_ID="configured-operator")
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        parameters = {"table": "public.orders"}
        finding = {
            "check": "stale_table_statistics",
            "evidence": {"schema": "public", "table": "orders"},
        }
        cursor.fetchone.side_effect = [
            ("analyze_table", parameters, "pending", "audit-1", finding),
            ("analyze_table", parameters, "executing", "audit-1", finding),
        ]

        def interrupt():
            store.conn.commit.assert_called_once()
            self.assertIn("status='executing'", cursor.execute.call_args.args[0])
            self.assertEqual(cursor.execute.call_args.args[1][0], "configured-operator")
            raise KeyboardInterrupt

        module = "backend.engines.repair_workflow"
        with patch.object(workflow, "_ensure_schema"), patch(
            f"{module}.PgVectorKnowledgeBase", return_value=store
        ), patch(f"{module}.OpenTenBaseConnector", side_effect=lambda _: interrupt()) as connector:
            with self.assertRaises(KeyboardInterrupt):
                workflow.approve_and_execute("request-1", "operator", "test-token")
            with self.assertRaisesRegex(ValueError, "not pending"):
                workflow.approve_and_execute("request-1", "operator", "test-token")
            connector.assert_called_once()
