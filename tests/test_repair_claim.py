import unittest
from unittest.mock import MagicMock, patch

from backend.engines.repair_workflow import RepairWorkflow
from backend.security.permissions import ApprovalWorkflow, OperationRegistry
from backend.engines.repair_workflow import _proposal_fingerprint
from backend.capabilities import CAPABILITIES


class RepairClaimTests(unittest.TestCase):
    def test_repair_event_reader_filters_by_request_and_bounds_limit(self):
        workflow = RepairWorkflow()
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.description = [(name,) for name in (
            "event_id", "request_id", "event_type", "actor", "status", "event_data", "created_at"
        )]
        cursor.fetchall.return_value = [(
            1, "request-1", "proposal_created", None, "pending",
            {"finding": {"query": "SELECT * FROM users WHERE email='private@example.com'"}}, None,
        )]
        with patch.object(workflow, "_ensure_schema"), patch(
            "backend.engines.repair_workflow.OperationsStore", return_value=store
        ):
            events = workflow.list_events("request-1", limit=9999)
        self.assertEqual(events[0]["event_type"], "proposal_created")
        self.assertEqual(
            events[0]["event_data"]["finding"]["query"],
            "SELECT * FROM users WHERE email='?'",
        )
        self.assertNotIn("private@example.com", str(events))
        self.assertEqual(cursor.execute.call_args.args[1], ("request-1", 500))
        store.close.assert_called_once()

    def test_repair_request_reader_redacts_legacy_query_literals(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(AIOPS_SLOW_QUERY_REDACT_LITERALS=True)
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.description = [(name,) for name in (
            "request_id", "operation", "parameters", "evidence", "reason", "status",
            "created_at", "approved_at", "approved_by", "result", "audit_id", "finding",
            "manual_review",
        )]
        raw_query = "SELECT * FROM users WHERE email='private@example.com'"
        cursor.fetchall.return_value = [(
            "request-1", "cancel_query", {"query": raw_query},
            {"query": raw_query}, "review", "pending", None, None, None,
            {"observed": {"query": raw_query}}, "audit-1", {"query": raw_query}, None,
        )]
        with patch.object(workflow, "_ensure_schema"), patch(
            "backend.engines.repair_workflow.OperationsStore", return_value=store
        ):
            requests = workflow.list_requests()

        for key in ("parameters", "evidence", "finding"):
            self.assertEqual(requests[0][key]["query"], "SELECT * FROM users WHERE email='?'")
        self.assertEqual(
            requests[0]["result"]["observed"]["query"],
            "SELECT * FROM users WHERE email='?'",
        )
        self.assertNotIn("private@example.com", str(requests))
        store.close.assert_called_once()

    def test_capabilities_declare_only_verified_repair_executor(self):
        value = CAPABILITIES
        repairs = value["repairs"]
        self.assertEqual(repairs["verified_executors"], ["analyze_table"])
        self.assertTrue(CAPABILITIES["interactive_agent"]["unrestricted_sql_tool"])
        self.assertFalse(repairs["automatic_prepared_transaction_resolution"])
        self.assertIn("kill_connection", repairs["suggestion_only"])
        self.assertIn("cancel_query", repairs["suggestion_only"])

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

    def test_least_privilege_repair_function_must_be_security_definer_and_granted(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (True, True)
        self.assertTrue(RepairWorkflow._repair_function_available(
            connection, "aiops_admin", "analyze_table"
        ))
        self.assertIn("procedure.prosecdef", cursor.execute.call_args.args[0])
        connection.rollback.assert_called_once()

        cursor.fetchone.return_value = (False, True)
        self.assertFalse(RepairWorkflow._repair_function_available(
            connection, "aiops_admin", "analyze_table"
        ))
        cursor.fetchone.return_value = (True, False)
        self.assertFalse(RepairWorkflow._repair_function_available(
            connection, "aiops_admin", "analyze_table"
        ))

    def test_readiness_checks_database_functions_and_each_configured_target(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_REPAIR_DB_USER="repair_operator",
            AIOPS_REPAIR_DB_PASSWORD="secret",
            DB_USER="auditor",
            DB_NAME="postgres",
            AIOPS_REPAIR_FUNCTION_ENABLED=True,
            AIOPS_REPAIR_FUNCTION_SCHEMA="aiops_admin",
            AIOPS_REPAIR_FUNCTION_NAME="analyze_table",
            AIOPS_AUTO_REPAIR_TARGETS=("public.orders", "public.items"),
        )
        connector = MagicMock()
        connection = connector.connect.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("repair_operator", "postgres", False)
        cursor.fetchall.return_value = [
            ("dn0001", "dn1", 11006), ("dn0002", "dn2", 11006),
        ]
        node_connectors = [MagicMock(), MagicMock()]
        for node_connector in node_connectors:
            node_cursor = node_connector.connect.return_value.cursor.return_value.__enter__.return_value
            node_cursor.fetchone.return_value = ("repair_operator", "postgres", False)
        with patch(
            "backend.engines.repair_workflow.OpenTenBaseConnector",
            side_effect=[connector, *node_connectors],
        ), patch.object(
            workflow, "_repair_function_available", return_value=True
        ), patch.object(
            workflow, "_repair_target_allowed", side_effect=[True, True, True, True, True, False]
        ):
            readiness = workflow.readiness()

        self.assertTrue(readiness["executor_ready"])
        self.assertFalse(readiness["ready"])
        self.assertEqual(readiness["reason"], "targets_missing_from_database_allowlist")
        self.assertEqual(
            readiness["targets"],
            {"public.orders": {"coordinator": True, "data_nodes": {"dn0001": True, "dn0002": True}},
             "public.items": {"coordinator": True, "data_nodes": {"dn0001": True, "dn0002": False}}},
        )
        connector.close.assert_called_once()
        for node_connector in node_connectors:
            node_connector.close.assert_called_once()

    def test_readiness_stops_when_repair_account_is_not_configured(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(AIOPS_REPAIR_DB_USER="", DB_USER="auditor")
        with patch("backend.engines.repair_workflow.OpenTenBaseConnector") as connector:
            readiness = workflow.readiness()
        self.assertEqual(readiness["reason"], "separate_repair_account_not_configured")
        self.assertFalse(readiness["executor_ready"])
        connector.assert_not_called()

    def test_missing_repair_role_blocks_proposal_before_model_or_storage(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_REPAIR_DB_USER="", DB_USER="auditor",
        )
        with patch("backend.engines.repair_workflow.OperationsStore") as store:
            with self.assertRaisesRegex(ValueError, "AIOPS_REPAIR_DB_USER"):
                workflow.create_request(
                    "analyze_table", {"table": "public.orders"}, {}, "test",
                    "audit-1", {
                        "check": "stale_table_statistics",
                        "evidence": {
                            "schema": "public", "table": "orders",
                            "database_identity": {"system_identifier": "fixture", "database": "lab"},
                            "nodes": [{"node_name": "dn1", "relation_oid": 123}],
                        },
                    },
                )
            store.assert_not_called()

    def test_analyze_preflight_uses_audit_connection_for_data_node_fanout(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_REPAIR_DB_USER="repair_operator",
            AIOPS_REPAIR_DB_PASSWORD="repair-secret",
            DB_USER="auditor", DB_PASSWORD="audit-secret",
            DB_HOST="cn", DB_PORT=11003, DB_NAME="lab",
            audit_target={"host": "cn", "port": 11003, "database": "lab"},
            AIOPS_REPAIR_FUNCTION_ENABLED=False,
        )
        repair_connection = MagicMock()
        repair_connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            "fixture-system-id", "lab", "repair_operator", False,
        )
        audit_connection = MagicMock()
        stats = {
            "nodes": [{
                "node_name": "dn1", "relation_oid": 123,
                "live_tuples": 5000, "modifications_since_analyze": 1500,
                "execution_user_is_owner": True,
            }],
        }
        with patch(
            "backend.engines.repair_workflow.OpenTenBaseConnector"
        ) as connector, patch.object(
            workflow, "_read_data_node_stats", return_value=stats
        ) as read_stats, patch.object(
            workflow, "_repair_function_available", return_value=False
        ):
            connector.return_value.connect.side_effect = [repair_connection, audit_connection]
            workflow._preflight_analyze_target("public.orders", {
                "database_identity": {
                    "system_identifier": "fixture-system-id", "database": "lab",
                },
                "nodes": [{"node_name": "dn1", "relation_oid": 123}],
            })

        read_stats.assert_called_once_with(
            audit_connection, "public", "orders", execution_user="repair_operator",
        )
        self.assertEqual(connector.call_count, 2)
        self.assertIsNot(connector.call_args_list[0].args[0], connector.call_args_list[1].args[0])
        repair_connection.rollback.assert_called()
        self.assertEqual(connector.return_value.close.call_count, 2)

    def test_proposal_preflight_checks_database_identity_and_target_before_model(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_REPAIR_DB_USER="repair_operator", AIOPS_REPAIR_DB_PASSWORD="secret",
            DB_USER="auditor", DB_PASSWORD="audit-secret", DB_HOST="cn", DB_PORT=11003,
            DB_NAME="lab", audit_target={"host": "cn", "port": 11003, "database": "lab"},
        )
        finding = {
            "check": "stale_table_statistics",
            "evidence": {
                "schema": "public", "table": "orders",
                "database_identity": {"system_identifier": "fixture", "database": "lab"},
                "nodes": [{"node_name": "dn1", "relation_oid": 123}],
            },
        }
        with patch.object(workflow, "_preflight_analyze_target", side_effect=ValueError("preflight failed")) as preflight, patch("backend.engines.repair_workflow.OperationsStore") as store:
            with self.assertRaisesRegex(ValueError, "preflight failed"):
                workflow.create_request(
                    "analyze_table", {"table": "public.orders"}, {}, "test", "audit-1", finding
                )
        preflight.assert_called_once_with("public.orders", finding["evidence"])
        store.assert_not_called()

    def test_destructive_proposals_are_blocked_before_model_or_database(self):
        workflow = RepairWorkflow()
        module = "backend.engines.repair_workflow"
        with patch(f"{module}.OperationsStore") as store:
            for operation in ("drop_database", "drop_table", "execute_sql"):
                with self.subTest(operation=operation):
                    with self.assertRaisesRegex(ValueError, "Operation is not enabled"):
                        workflow.create_request(operation, {"table": "public.orders"}, {}, "test")
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
        fingerprint = _proposal_fingerprint("analyze_table", parameters, "audit-1", finding)
        reviews = {"risk_policy": {"proposal_fingerprint": fingerprint}, "human_approval": {"approved": True}}
        cursor.fetchone.return_value = ("request-1", "pending", parameters, finding, reviews)
        with patch.object(workflow, "_preflight_analyze_target"), patch.object(
            workflow, "_ensure_schema"), patch("backend.engines.repair_workflow.OperationsStore", return_value=store):
            result = workflow.create_request("analyze_table", parameters, {}, "retry", "audit-1", finding)
        self.assertEqual(result["request_id"], "request-1")
        self.assertTrue(result["reused"])

    def test_approval_rejects_stale_risk_policy(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_APPROVER_TOKENS="", AIOPS_APPROVAL_TOKEN="test-token",
            DB_USER="auditor", AIOPS_REPAIR_DB_USER="repair_operator",
        )
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (
            "analyze_table", {"table": "public.orders"}, "pending", "audit-1", {},
            {"risk_policy": {"proposal_fingerprint": "stale"}},
        )
        module = "backend.engines.repair_workflow"
        with patch.object(workflow, "_ensure_schema"), patch(
            f"{module}.OperationsStore", return_value=store
        ), patch(f"{module}.OpenTenBaseConnector") as connector:
            with self.assertRaisesRegex(ValueError, "Risk policy"):
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
            {"risk_policy": {"proposal_fingerprint": "stale"}},
        )
        with patch.object(workflow, "_ensure_schema"), patch(
            "backend.engines.repair_workflow.OperationsStore", return_value=store
        ), patch("backend.engines.repair_workflow.OpenTenBaseConnector") as connector:
            with self.assertRaisesRegex(ValueError, "Risk policy"):
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

    def test_automatic_execution_rejects_missing_policy_approval(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_AUTO_REPAIR_ENABLED=True,
            AIOPS_APPROVER_TOKENS="", AIOPS_APPROVAL_TOKEN="",
            DB_USER="auditor", AIOPS_REPAIR_DB_USER="repair_operator",
        )
        parameters = {"table": "public.orders"}
        finding = {"check": "stale_table_statistics", "evidence": {}}
        fingerprint = _proposal_fingerprint("analyze_table", parameters, "audit-1", finding)
        store = MagicMock()
        store.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            "analyze_table", parameters, "pending", "audit-1", finding,
            {"risk_policy": {"proposal_fingerprint": fingerprint}},
        )
        with patch.object(workflow, "_ensure_schema"), patch(
            "backend.engines.repair_workflow.OperationsStore", return_value=store
        ), patch("backend.engines.repair_workflow.OpenTenBaseConnector") as connector:
            with self.assertRaisesRegex(ValueError, "Human approval"):
                workflow.approve_and_execute(
                    "request-1", "aiops-auto-policy", automatic=True
                )
            connector.assert_not_called()

    def test_automatic_repair_is_off_by_default_and_does_not_read_storage(self):
        workflow = RepairWorkflow()
        workflow.config.AIOPS_AUTO_REPAIR_ENABLED = False
        with patch("backend.engines.repair_workflow.OperationsStore") as store:
            result = workflow.auto_repair_from_audit("audit-1")
        self.assertEqual(result, {"status": "skipped", "reason": "automatic_repair_disabled"})
        store.assert_not_called()

    def test_verified_analyze_outcome_is_saved_to_operational_memory(self):
        workflow = RepairWorkflow()
        result = {
            "success": True,
            "postcondition": {"verified": True, "advanced_nodes": ["dn1", "dn2"]},
            "precondition": {"stale_nodes": ["dn1", "dn2"]},
        }
        with patch("backend.engines.repair_workflow.OperationalMemory") as memory_type:
            workflow._save_analyze_memory(
                audit_id="audit-1", table="public.orders",
                evidence={"observation": {"stale_nodes": ["dn1"]}},
                result=result, status="executed", request_id="request-1",
            )

        memory_type.return_value.save_case.assert_called_once()
        saved = memory_type.return_value.save_case.call_args.kwargs
        self.assertEqual(saved["evidence"]["audit_id"], "audit-1")
        self.assertEqual(saved["verification_result"]["verified"], True)
        self.assertEqual(saved["effectiveness"], 1.0)
        memory_type.return_value.close.assert_called_once()

    def test_automatic_repair_skips_manual_or_incomplete_audits(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_AUTO_REPAIR_ENABLED=True,
            AIOPS_REPAIR_FUNCTION_ENABLED=True,
            AIOPS_REPAIR_DB_USER="repair_operator",
            DB_USER="auditor",
        )
        cases = [
            ({"trigger": "manual", "collection_status": "success",
              "performance_status": "success", "findings": []}, "audit_was_not_scheduled"),
            ({"trigger": "scheduled", "collection_status": "partial",
              "performance_status": "success", "findings": []}, "health_collection_incomplete"),
        ]
        for evidence, expected_reason in cases:
            with self.subTest(reason=expected_reason):
                store = MagicMock()
                store.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
                    evidence, {}, [],
                )
                with patch(
                    "backend.engines.repair_workflow.OperationsStore", return_value=store
                ), patch.object(workflow, "_ensure_schema"), patch.object(
                    workflow, "create_request"
                ) as create_request:
                    result = workflow.auto_repair_from_audit("audit-1")
                self.assertEqual(result["reason"], expected_reason)
                create_request.assert_not_called()
                store.close.assert_called_once()

    def test_automatic_repair_persists_policy_before_execution_handoff(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_AUTO_REPAIR_ENABLED=True,
            AIOPS_REPAIR_FUNCTION_ENABLED=True,
            AIOPS_REPAIR_DB_USER="repair_operator",
            DB_USER="auditor",
            AIOPS_AUTO_REPAIR_TARGETS=("public.orders",),
        )
        finding = {
            "check": "stale_table_statistics",
            "evidence": {"schema": "public", "table": "orders"},
        }
        audit_store = MagicMock()
        audit_store.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            {
                "trigger": "scheduled", "collection_status": "success",
                "performance_status": "success", "findings": [finding],
            },
            {"analysis_fallback": True}, [],
        )
        parameters = {"table": "public.orders"}
        repair_evidence = {"proposal_source": "scheduled_auto_repair", "trigger": "scheduled"}
        repair_store = MagicMock()
        repair_cursor = repair_store.conn.cursor.return_value.__enter__.return_value
        repair_cursor.fetchone.return_value = (
            "analyze_table", parameters, "pending", "audit-1", finding, repair_evidence,
        )
        repair_cursor.rowcount = 1
        with patch(
            "backend.engines.repair_workflow.OperationsStore",
            side_effect=[audit_store, repair_store],
        ), patch.object(workflow, "_ensure_schema"), patch.object(
            workflow, "create_request", return_value={"request_id": "request-1", "status": "pending"}
        ) as create_request, patch.object(
            workflow, "approve_and_execute", return_value={"request_id": "request-1", "status": "executed"}
        ) as execute:
            result = workflow.auto_repair_from_audit("audit-1")

        self.assertEqual(result["status"], "executed")
        create_request.assert_called_once()
        update_call = next(
            call for call in repair_cursor.execute.call_args_list
            if "UPDATE repair_requests SET evidence" in call.args[0]
        )
        policy = update_call.args[1][0].adapted["automatic_policy"]
        self.assertTrue(policy["approved"])
        self.assertEqual(policy["actor"], "aiops-auto-policy")
        self.assertEqual(policy["proposal_fingerprint"], _proposal_fingerprint(
            "analyze_table", parameters, "audit-1", finding
        ))
        self.assertEqual(repair_cursor.execute.call_args_list[0].args[1], ("request-1",))
        execute.assert_called_once_with("request-1", "aiops-auto-policy", automatic=True)
        audit_store.close.assert_called_once()
        repair_store.close.assert_called_once()

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

    def test_manual_review_requires_valid_disposition_before_storage(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_APPROVER_TOKENS="", AIOPS_APPROVAL_TOKEN="test-token"
        )
        with patch("backend.engines.repair_workflow.OperationsStore") as store:
            with self.assertRaisesRegex(ValueError, "disposition"):
                workflow.record_manual_review("request-1", "retry", "checked", "test-token")
            store.assert_not_called()

    def test_manual_review_only_claims_unverified_or_stale_execution(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_APPROVER_TOKENS="", AIOPS_APPROVAL_TOKEN="test-token"
        )
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        module = "backend.engines.repair_workflow"
        with patch.object(workflow, "_ensure_schema"), patch(
            f"{module}.OperationsStore", return_value=store
        ):
            with self.assertRaisesRegex(ValueError, "not awaiting manual review"):
                workflow.record_manual_review(
                    "request-1", "closed_no_retry", "Checked execution", "test-token"
                )
        statement = cursor.execute.call_args.args[0]
        self.assertIn("status='unverified'", statement)
        self.assertIn("interval '5 minutes'", statement)
        store.close.assert_called_once()

    def test_risk_classifier_requires_human_for_writes_and_unknown_actions(self):
        self.assertFalse(OperationRegistry.classify("get_database_locks")["requires_human_approval"])
        self.assertTrue(OperationRegistry.classify("analyze_table")["requires_human_approval"])
        self.assertTrue(OperationRegistry.classify("unknown_action")["requires_human_approval"])
        drop_database = OperationRegistry.classify("drop_database")
        self.assertEqual(drop_database["risk_level"], "high")
        self.assertEqual(drop_database["matched_keyword"].lower(), "drop")
        policy = OperationRegistry.classify("query_cluster_status", "DROP TABLE public.orders")
        self.assertEqual(policy["risk_level"], "high")
        self.assertEqual(policy["matched_keyword"].lower(), "drop")

    def test_cancel_query_proposal_binds_complete_blocker_identity(self):
        target = {
            "node_name": "dn0001", "pid": 123, "database": "appdb",
            "user": "app", "application_name": "worker", "query_start": "2026-01-01T00:00:00Z",
            "xact_start": "2026-01-01T00:00:00Z", "query": "UPDATE public.items SET value=1",
            "database_identity": {"system_identifier": "sys-1", "database": "postgres"},
        }
        blocker = {"node_name": target["node_name"], "pid": target["pid"],
                   "database": target["database"], "usename": target["user"],
                   "application_name": target["application_name"],
                   "query_start": target["query_start"], "xact_start": target["xact_start"],
                   "query": target["query"]}
        finding = {"check": "data_node_lock_waits", "evidence": {
            "waits": [{"node_name": "dn0001", "waiting_pid": 200, "blockers": [blocker]}],
            "database_identity": target["database_identity"],
        }}
        normalized = RepairWorkflow._lock_target(target, finding)
        self.assertEqual(normalized["query"], "UPDATE public.items SET value=?")
        self.assertEqual(len(normalized["query_fingerprint"]), 64)
        self.assertEqual(
            {key: value for key, value in normalized.items() if key not in {"query", "query_fingerprint"}},
            {key: value for key, value in target.items() if key != "query"},
        )
        with self.assertRaisesRegex(ValueError, "identity"):
            RepairWorkflow._lock_target({**target, "pid": 124}, finding)
        with self.assertRaisesRegex(ValueError, "complete blocker identity"):
            RepairWorkflow._lock_target(target, {"check": "lock_waits", "evidence": {"pid": 123}})
        self.assertTrue(OperationRegistry.classify("cancel_query")["requires_human_approval"])

    def test_cancel_query_execution_fails_closed_after_human_approval(self):
        workflow = RepairWorkflow()
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        target = {
            "node_name": "dn0001", "pid": 123, "database": "appdb", "user": "app",
            "application_name": "worker", "query_start": "2026-01-01T00:00:00Z",
            "xact_start": "2026-01-01T00:00:00Z", "query": "UPDATE public.items SET value=1",
            "database_identity": {"system_identifier": "sys-1", "database": "postgres"},
        }
        blocker = {"node_name": target["node_name"], "pid": target["pid"],
                   "database": target["database"], "usename": target["user"],
                   "application_name": target["application_name"],
                   "query_start": target["query_start"], "xact_start": target["xact_start"],
                   "query": target["query"]}
        finding = {"check": "data_node_lock_waits", "evidence": {
            "waits": [{"node_name": "dn0001", "waiting_pid": 200, "blockers": [blocker]}],
            "database_identity": target["database_identity"],
        }}
        cursor.fetchone.return_value = (
            "cancel_query", target, "pending", "audit-1", finding, {
                "risk_policy": {"proposal_fingerprint": _proposal_fingerprint(
                    "cancel_query", target, "audit-1", finding
                )},
                "human_approval": {"approved": True},
            },
        )
        workflow.config = MagicMock(
            AIOPS_APPROVER_TOKENS="", AIOPS_APPROVAL_TOKEN="test-token",
            AIOPS_APPROVER_ID="operator", AIOPS_REPAIR_DB_USER="repair",
            DB_USER="auditor",
        )
        with patch.object(workflow, "_ensure_schema"), patch(
            "backend.engines.repair_workflow.OperationsStore", return_value=store
        ):
            with self.assertRaisesRegex(ValueError, "executor"):
                workflow.approve_and_execute("request-1", "operator", "test-token")
        store.close.assert_called_once()

    def test_cancel_query_executor_requires_explicit_enablement(self):
        workflow = RepairWorkflow()
        workflow.config = MagicMock(
            AIOPS_CANCEL_QUERY_ENABLED=False,
            AIOPS_REPAIR_DB_USER="repair_operator",
            AIOPS_REPAIR_DB_PASSWORD="secret",
            DB_USER="auditor",
        )
        with self.assertRaisesRegex(ValueError, "disabled"):
            workflow._execute_cancel_query({}, {"check": "data_node_lock_waits", "evidence": {}})

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
        fingerprint = _proposal_fingerprint("analyze_table", parameters, "audit-1", finding)
        reviews = {"risk_policy": {"proposal_fingerprint": fingerprint}, "human_approval": {"approved": True}}
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
