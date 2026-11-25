import unittest
from unittest.mock import MagicMock, patch

from backend.engines.repair_workflow import RepairWorkflow


class RepairClaimTests(unittest.TestCase):
    def test_approval_cannot_bypass_model_review(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_APPROVER_TOKENS="", AIOPS_APPROVAL_TOKEN="test-token",
            DB_USER="auditor", AIOPS_REPAIR_DB_USER="repair_operator",
        )
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "analyze_table", {"table": "public.orders"}, "pending", "audit-1", {},
            {"program_review": {"approved": True}},
        )
        module = "backend.engines.repair_workflow"
        with patch.object(workflow, "_ensure_schema"), patch(
            f"{module}.OperationsStore", return_value=store
        ), patch(f"{module}.OpenTenBaseConnector") as connector:
            with self.assertRaisesRegex(ValueError, "program and model review"):
                workflow.approve_and_execute("request-1", "operator", "test-token")
            connector.assert_not_called()
            store.conn.commit.assert_not_called()

    def test_execution_requires_separate_role_before_claiming_request(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_APPROVER_TOKENS="", AIOPS_APPROVAL_TOKEN="test-token",
            DB_USER="auditor",
        )
        with patch("backend.engines.repair_workflow.OperationsStore") as store:
            for repair_user in ("", "auditor"):
                workflow.config.AIOPS_REPAIR_DB_USER = repair_user
                with self.assertRaisesRegex(ValueError, "dedicated AIOPS_REPAIR_DB_USER"):
                    workflow.approve_and_execute("request-1", "operator", "test-token")
            store.assert_not_called()

    def test_individual_tokens_bind_identity_and_disable_shared_token(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_APPROVER_TOKENS='{"alice":"first","bob":"second"}',
            AIOPS_APPROVAL_TOKEN="shared",
        )
        self.assertEqual(workflow._authorize_decision("first"), "alice")
        self.assertEqual(workflow._authorize_decision("second"), "bob")
        with self.assertRaises(PermissionError):
            workflow._authorize_decision("shared")
        for invalid in ('{"alice":"first","bob":"first"}', '{"alice":"first","alice":"second"}'):
            workflow.config.AIOPS_APPROVER_TOKENS = invalid
            with self.assertRaises(PermissionError):
                workflow._authorize_decision("first")

    def test_reject_denies_invalid_token_before_accessing_storage(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(AIOPS_APPROVER_TOKENS="", AIOPS_APPROVAL_TOKEN="test-token")
        with patch("backend.engines.repair_workflow.OperationsStore") as store:
            with self.assertRaises(PermissionError):
                workflow.reject("request-1", "operator", "reason", "wrong-token")
            store.assert_not_called()

    def test_interrupted_execution_cannot_be_claimed_again(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(AIOPS_APPROVER_TOKENS="", AIOPS_APPROVAL_TOKEN="test-token", AIOPS_APPROVER_ID="configured-operator")
        workflow.config.DB_USER = "auditor"
        workflow.config.AIOPS_REPAIR_DB_USER = "repair_operator"
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        parameters = {"table": "public.orders"}
        finding = {
            "check": "stale_table_statistics",
            "evidence": {"schema": "public", "table": "orders"},
        }
        reviews = {"program_review": {"approved": True}, "model_review": {"approved": True}}
        cursor.fetchone.side_effect = [
            ("analyze_table", parameters, "pending", "audit-1", finding, reviews),
            ("analyze_table", parameters, "executing", "audit-1", finding, reviews),
        ]

        def interrupt():
            store.conn.commit.assert_called_once()
            self.assertIn("status='executing'", cursor.execute.call_args.args[0])
            self.assertEqual(cursor.execute.call_args.args[1][0], "configured-operator")
            raise KeyboardInterrupt

        module = "backend.engines.repair_workflow"
        with patch.object(workflow, "_ensure_schema"), patch(
            f"{module}.OperationsStore", return_value=store
        ), patch(f"{module}.OpenTenBaseConnector", side_effect=lambda _: interrupt()) as connector:
            with self.assertRaises(KeyboardInterrupt):
                workflow.approve_and_execute("request-1", "operator", "test-token")
            with self.assertRaisesRegex(ValueError, "not pending"):
                workflow.approve_and_execute("request-1", "operator", "test-token")
            connector.assert_called_once()
