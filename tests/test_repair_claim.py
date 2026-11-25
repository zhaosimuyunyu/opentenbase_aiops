import unittest
from unittest.mock import MagicMock, patch

from backend.engines.repair_workflow import RepairWorkflow
from backend.security.permissions import ApprovalWorkflow
from backend.capabilities import CAPABILITIES


class RepairClaimTests(unittest.TestCase):
    def test_capabilities_declare_only_verified_repair_executor(self):
        value = CAPABILITIES
        repairs = value["repairs"]
        self.assertEqual(repairs["verified_executors"], ["analyze_table"])
        self.assertFalse(repairs["automatic_prepared_transaction_resolution"])
        self.assertIn("kill_connection", repairs["suggestion_only"])

    def test_legacy_executor_never_reports_mock_success(self):
        workflow = ApprovalWorkflow.__new__(ApprovalWorkflow)
        result = workflow._execute_operation({
            "operation": "drop_database",
            "parameters": {"database": "production"},
        })
        self.assertFalse(result["success"])
        self.assertIn("No operation executor", result["error"])

    def test_analyze_requires_owner_privilege_on_every_data_node(self):
        nodes = [
            {"node_name": "dn1", "execution_user_is_owner": True},
            {"node_name": "dn2", "execution_user_is_owner": False},
        ]
        with self.assertRaisesRegex(ValueError, "dn2"):
            RepairWorkflow._require_analyze_ownership(nodes)
        nodes[1]["execution_user_is_owner"] = True
        RepairWorkflow._require_analyze_ownership(nodes)

    def test_destructive_proposals_are_blocked_before_model_or_database(self):
        workflow = RepairWorkflow()
        module = "backend.engines.repair_workflow"
        with patch.object(workflow, "_review_proposal") as review, patch(
            f"{module}.OperationsStore"
        ) as store:
            for operation in ("drop_database", "drop_table", "execute_sql"):
                with self.subTest(operation=operation):
                    with self.assertRaisesRegex(ValueError, "Operation is not enabled"):
                        workflow.create_request(operation, {"table": "public.orders"}, {}, "test")
            review.assert_not_called()
            store.assert_not_called()

    def test_resubmitting_reviewed_proposal_skips_model(self):
        workflow = RepairWorkflow()
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        parameters = {"table": "public.orders"}
        finding = {
            "check": "stale_table_statistics",
            "evidence": {
                "schema": "public", "table": "orders",
                "database_identity": {"system_identifier": "fixture", "database": "lab"},
                "nodes": [{"node_name": "dn1", "relation_oid": 123}],
            },
        }
        reviews = {"program_review": {"approved": True}, "model_review": {"approved": True}, "agent_review": {"approved": True}, "human_approval": {"approved": True}}
        cursor.fetchone.return_value = ("request-1", "pending", parameters, finding, reviews)
        with patch.object(workflow, "_ensure_schema"), patch.object(
            workflow, "_review_proposal"
        ) as review, patch("backend.engines.repair_workflow.OperationsStore", return_value=store):
            result = workflow.create_request("analyze_table", parameters, {}, "retry", "audit-1", finding)
        review.assert_not_called()
        self.assertEqual(result["request_id"], "request-1")
        self.assertTrue(result["reused"])

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
            with self.assertRaisesRegex(ValueError, "program, model, and agent review"):
                workflow.approve_and_execute("request-1", "operator", "test-token")
            connector.assert_not_called()
            store.conn.commit.assert_not_called()

    def test_execution_requires_human_approval_record(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_APPROVER_TOKENS="", AIOPS_APPROVAL_TOKEN="test-token",
            DB_USER="auditor", AIOPS_REPAIR_DB_USER="repair_operator",
        )
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "analyze_table", {"table": "public.orders"}, "pending", "audit-1", {},
            {"program_review": {"approved": True}, "model_review": {"approved": True},
             "agent_review": {"approved": True}},
        )
        with patch.object(workflow, "_ensure_schema"), patch(
            "backend.engines.repair_workflow.OperationsStore", return_value=store
        ), patch("backend.engines.repair_workflow.OpenTenBaseConnector") as connector:
            with self.assertRaisesRegex(ValueError, "Human approval"):
                workflow.approve_and_execute("request-1", "operator", "test-token")
            connector.assert_not_called()

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

    def test_independent_safety_agent_can_use_separate_model(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_SAFETY_REVIEW_MODEL="safety-model",
            DEEPSEEK_MODEL="diagnosis-model",
        )
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(
            content='{"approved":true,"reason":"Evidence supports the operation."}'
        ))]
        client = MagicMock()
        client.chat.completions.create.return_value = response
        client_context = MagicMock()
        client_context.__enter__.return_value = client
        with patch("backend.engines.repair_workflow.OpenAI", return_value=client_context):
            review = workflow._review_proposal(
                "analyze_table", "public.orders", {}, {"review_role": "independent_safety_agent"}
            )
        self.assertEqual(client.chat.completions.create.call_args.kwargs["model"], "safety-model")
        self.assertEqual(review["reviewer"], "independent_safety_agent")

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
        reviews = {"program_review": {"approved": True}, "model_review": {"approved": True}, "agent_review": {"approved": True}, "human_approval": {"approved": True}}
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
