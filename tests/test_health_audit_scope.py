import json
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.engines.readonly_audit_engine import ReadonlyAuditEngine
from backend.collectors.readonly_health import stale_statistics_nodes


class HealthAuditScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_audit_timeout_returns_rule_fallback(self):
        engine = ReadonlyAuditEngine()
        engine.config.AIOPS_AI_AUDIT_TIMEOUT_SECONDS = 0.01
        async def slow_diagnosis(*_args):
            await asyncio.sleep(1)

        with patch.object(
            engine, "_diagnose", new=AsyncMock(side_effect=slow_diagnosis)
        ):
            result = await engine._diagnose_with_budget("audit", {"findings": []})
        self.assertTrue(result["analysis_fallback"])
        self.assertEqual(result["ai_error"], "TimeoutError")

    async def test_health_audit_persists_evidence_when_ai_budget_expires(self):
        module = "backend.engines.readonly_audit_engine"
        engine = ReadonlyAuditEngine()
        engine.config.AIOPS_AI_AUDIT_TIMEOUT_SECONDS = 0.01
        snapshot = {
            "status": "success", "errors": {}, "collection_duration_ms": 12.5,
            "checks": {
                "locks": [], "connections": [], "max_connections": [{"max_connections": 100}],
                "long_running_queries": [], "idle_transactions": [], "nodes": [],
            },
        }
        async def slow_diagnosis(*_args):
            await asyncio.sleep(1)

        with patch(f"{module}.OperationsStore") as store, patch(
            f"{module}.ReadonlyHealthCollector"
        ) as collector, patch.object(engine, "_diagnose", new=slow_diagnosis):
            collector.return_value.collect.return_value = snapshot
            result = await engine.run_health_audit()
        self.assertTrue(result["analysis_fallback"])
        self.assertEqual(result["structured"]["analysis_source"], "deterministic_evidence_rules")
        persisted = store.return_value.conn.cursor.return_value.__enter__
        self.assertTrue(persisted.return_value.execute.called)
        insert = store.return_value.conn.cursor.return_value.__enter__.return_value.execute.call_args_list[-1]
        self.assertIn("risk_level,status)", insert.args[0])
        self.assertIn("'completed'", insert.args[0])
        persisted_evidence = json.loads(insert.args[1][2])
        self.assertEqual(persisted_evidence["collection_duration_ms"], 12.5)
        self.assertGreaterEqual(persisted_evidence["analysis_duration_ms"], 0)

    async def test_persists_data_node_lock_blockers_in_performance_evidence(self):
        module = "backend.engines.readonly_audit_engine"
        engine = ReadonlyAuditEngine()
        snapshot = {
            "status": "success", "errors": {},
            "checks": {
                "locks": [], "connections": [], "max_connections": [{"max_connections": 100}],
                "long_running_queries": [], "idle_transactions": [], "nodes": [],
                "data_node_lock_blockers": [{
                    "node_name": "dn1", "waiting_pid": 10, "pid": 20,
                    "locktype": "relation", "relation": "public.items",
                    "transactionid": None, "waiting_mode": "AccessShareLock",
                    "usename": "app", "database": "postgres", "application_name": "worker",
                    "query_start": "2026-01-01T00:00:00Z", "xact_start": "2026-01-01T00:00:00Z",
                    "query": "UPDATE public.items SET value=1", "backend_type": "client backend",
                }],
            },
        }
        with patch(f"{module}.OperationsStore"), patch(
            f"{module}.ReadonlyHealthCollector"
        ) as collector, patch.object(
            engine, "_diagnose", new=AsyncMock(return_value={"structured": {}, "knowledge_refs": []})
        ):
            collector.return_value.collect.return_value = snapshot
            result = await engine.run_health_audit()
        self.assertEqual(
            result["evidence"]["performance"]["data_node_lock_blockers"],
            snapshot["checks"]["data_node_lock_blockers"],
        )

    async def test_slow_query_log_records_create_a_finding_and_are_persisted(self):
        module = "backend.engines.readonly_audit_engine"
        slow_queries = [{
            "node_name": "cn0001", "pid": 42, "application_name": "course-demo",
            "duration_ms": 12015.69, "query": "SELECT pg_sleep(12)",
            "source": "server_csv_log",
        }]
        snapshot = {
            "status": "success", "errors": {},
            "checks": {
                "locks": [], "connections": [],
                "max_connections": [{"max_connections": 100}],
                "long_running_queries": [], "data_node_long_running_queries": [],
                "slow_query_logs": slow_queries, "idle_transactions": [], "nodes": [],
            },
        }
        with patch(f"{module}.OperationsStore"), patch(
            f"{module}.ReadonlyHealthCollector"
        ) as collector, patch.object(
            ReadonlyAuditEngine, "_diagnose",
            new=AsyncMock(return_value={"structured": {}, "knowledge_refs": []}),
        ):
            collector.return_value.collect.return_value = snapshot
            result = await ReadonlyAuditEngine().run_health_audit()

        finding = next(item for item in result["findings"] if item["check"] == "long_running_queries")
        self.assertEqual(finding["evidence"], slow_queries)
        self.assertEqual(result["evidence"]["performance"]["slow_query_logs"], slow_queries)

    async def test_prepared_transaction_reports_missing_official_record_diagnostic(self):
        module = "backend.engines.readonly_audit_engine"
        snapshot = {
            "status": "success", "errors": {},
            "checks": {
                "locks": [{"granted": False, "transactionid": "42"}],
                "nodes": [
                    {"node_name": "dn0001", "node_type": "D"},
                    {"node_name": "dn0002", "node_type": "D"},
                ],
                "prepared_transactions": [{"transaction_id": "42", "gid": "g", "database": "postgres"}],
                "data_node_prepared_transactions": [],
                "pg_clean_diagnostics": [{
                    "registered": False, "record_list_registered": False,
                    "package_available": False,
                }],
            },
        }
        with patch(f"{module}.OperationsStore") as store, patch(
            f"{module}.ReadonlyHealthCollector"
        ) as collector, patch.object(
            ReadonlyAuditEngine, "_diagnose",
            new=AsyncMock(return_value={"structured": {}, "knowledge_refs": []}),
        ):
            collector.return_value.collect.return_value = snapshot
            result = await ReadonlyAuditEngine().run_health_audit()
        checks = [item["check"] for item in result["findings"]]
        self.assertIn("official_2pc_record_diagnostics_unavailable", checks)
        blocker = next(
            item for item in result["findings"]
            if item["check"] == "prepared_transaction_blocker"
        )
        self.assertEqual(blocker["severity"], "high")
        self.assertEqual(blocker["evidence"][0]["data_node_participants"], [])
        self.assertEqual(blocker["evidence"][0]["data_node_participant_status"], "no_matching_records")
        self.assertEqual(blocker["evidence"][0]["data_node_participant_count"], 0)
        self.assertEqual(result["risk_level"], "high")
        inserts = " ".join(
            call.args[0] for call in store.return_value.conn.cursor.return_value
            .__enter__.return_value.execute.call_args_list
        )
        self.assertNotIn("repair_requests", inserts)

    async def test_correlates_prepared_transaction_by_gid_across_nodes(self):
        module = "backend.engines.readonly_audit_engine"
        gid = "_$XC$21973:cn0001:T:2:1"
        snapshot = {
            "status": "success", "errors": {},
            "checks": {
                "locks": [{
                    "granted": False, "locktype": "transactionid",
                    "transactionid": "21973", "pid": 3036,
                }],
                "nodes": [
                    {"node_name": "dn0001", "node_type": "D"},
                    {"node_name": "dn0002", "node_type": "D"},
                ],
                "prepared_transactions": [{
                    "transaction_id": "21973", "gid": gid,
                    "database": "postgres", "owner": "opentenbase",
                }],
                "data_node_prepared_transactions": [
                    {"node_name": "dn0001", "transaction_id": "11576", "gid": gid},
                    {"node_name": "dn0002", "transaction_id": "11457", "gid": gid},
                ],
                "pg_clean_diagnostics": [{"record_list_registered": True}],
                "pg_clean_transaction_diagnostics": [],
            },
        }
        with patch(f"{module}.OperationsStore") as store, patch(
            f"{module}.ReadonlyHealthCollector"
        ) as collector, patch.object(
            ReadonlyAuditEngine, "_diagnose",
            new=AsyncMock(return_value={
                "structured": {"risk_level": "low"}, "knowledge_refs": [],
            }),
        ):
            collector.return_value.collect.return_value = snapshot
            result = await ReadonlyAuditEngine().run_health_audit(trigger="scheduled")

        finding = next(
            item for item in result["findings"]
            if item["check"] == "prepared_transaction_blocker"
        )
        correlated = finding["evidence"][0]
        self.assertEqual(correlated["transaction_id"], "21973")
        self.assertEqual(correlated["gid"], gid)
        self.assertEqual(
            [(item["node_name"], item["transaction_id"])
             for item in correlated["data_node_participants"]],
            [("dn0001", "11576"), ("dn0002", "11457")],
        )
        self.assertEqual(correlated["data_node_participant_status"], "matched")
        self.assertEqual(correlated["data_node_participant_count"], 2)
        self.assertEqual(result["risk_level"], "high")
        inserted_sql = " ".join(
            call.args[0] for call in store.return_value.conn.cursor.return_value
            .__enter__.return_value.execute.call_args_list
        )
        self.assertIn("INSERT INTO audit_records", inserted_sql)
        self.assertNotIn("repair_requests", inserted_sql)

    async def test_lock_finding_notes_missing_official_unlock_diagnostics(self):
        module = "backend.engines.readonly_audit_engine"
        snapshot = {
            "status": "success",
            "errors": {},
            "checks": {
                "locks": [{"granted": False, "locktype": "transactionid"}],
                "pg_unlock_diagnostics": [{
                    "package_available": False,
                    "dependency_registered": False,
                    "dependency_executable": None,
                }],
            },
        }
        with patch(f"{module}.OperationsStore"), patch(
            f"{module}.ReadonlyHealthCollector"
        ) as collector, patch.object(
            ReadonlyAuditEngine, "_diagnose",
            new=AsyncMock(return_value={"structured": {}, "knowledge_refs": []}),
        ):
            collector.return_value.collect.return_value = snapshot
            result = await ReadonlyAuditEngine().run_health_audit()

        item = next(
            finding for finding in result["findings"]
            if finding["check"] == "official_lock_diagnostics_unavailable"
        )
        self.assertEqual(item["severity"], "low")
        self.assertIn("not available", item["observed"])

    def test_statistics_threshold_is_per_node(self):
        nodes = [
            {"node_name": "dn1", "live_tuples": 2000, "modifications_since_analyze": 600},
            {"node_name": "dn2", "live_tuples": 2000, "modifications_since_analyze": 600},
        ]
        self.assertEqual(stale_statistics_nodes(nodes), [])
        nodes[1]["modifications_since_analyze"] = 1000
        self.assertEqual(stale_statistics_nodes(nodes), ["dn2"])

    async def test_model_fallback_preserves_critical_node_risk(self):
        module = "backend.engines.readonly_audit_engine"
        with patch(f"{module}.OperationsStore") as store, patch(
            f"{module}.ReadonlyHealthCollector"
        ) as collector, patch.object(
            ReadonlyAuditEngine, "_diagnose",
            new=AsyncMock(return_value={
                "structured": {"risk_level": "unknown"},
                "analysis_fallback": True,
                "knowledge_refs": [],
            }),
        ):
            collector.return_value.collect.return_value = {
                "status": "partial",
                "errors": {"node_connectivity:dn1": {"type": "NodeConnectivity"}},
                "checks": {
                    "nodes": [],
                    "node_connectivity": [{
                        "status": "unreachable", "node_name": "dn1",
                        "node_type": "D", "host": "dn1", "port": 11006,
                    }],
                },
            }
            result = await ReadonlyAuditEngine().run_health_audit(trigger="scheduled")
            cursor = store.return_value.conn.cursor.return_value.__enter__.return_value
            self.assertEqual(cursor.execute.call_args.args[1][-1], "critical")
        self.assertEqual(result["risk_level"], "critical")

    async def test_connection_capacity_distinguishes_zero_from_collection_failure(self):
        module = "backend.engines.readonly_audit_engine"
        for count, limit, usage, severity in (
            (None, 100, None, None),
            (0, None, None, None),
            (0, 100, 0.0, None),
            (80, 100, 80.0, "medium"),
            (95, 100, 95.0, "high"),
        ):
            with self.subTest(count=count, limit=limit):
                checks = {}
                if count is not None:
                    checks["connections"] = [{"connection_count": count}] if count else []
                if limit is not None:
                    checks["max_connections"] = [{"max_connections": limit}]
                with patch(f"{module}.OperationsStore"), patch(
                    f"{module}.ReadonlyHealthCollector"
                ) as collector, patch.object(
                    ReadonlyAuditEngine, "_diagnose",
                    new=AsyncMock(return_value={"structured": {}, "knowledge_refs": []}),
                ):
                    collector.return_value.collect.return_value = {
                        "checks": checks, "errors": {}, "status": "success",
                    }
                    result = await ReadonlyAuditEngine().run_health_audit()

                capacity = result["evidence"]["cluster"]["connection_capacity"]
                self.assertEqual(capacity, {
                    "scope": "connected_cn", "total": count,
                    "max_connections": limit, "usage_percent": usage,
                })
                self.assertEqual(
                    [row["severity"] for row in result["findings"] if row["check"] == "connection_capacity"],
                    [severity] if severity else [],
                )

    async def test_only_complete_fallback_statistics_generate_repair_findings(self):
        module = "backend.engines.readonly_audit_engine"
        stats = {"schemaname": "public", "live_tuples": 1500, "modifications_since_analyze": 1500}
        stats["nodes"] = [{"node_name": "dn0001", **stats}]
        snapshot = {
            "status": "partial",
            "errors": {"data_node_stats:dn0002": {"sqlstate": "55P03"}},
            "checks": {
                "data_node_stats_fallback": {
                    "public.orders": {"tables": [dict(stats, tablename="orders")], "errors": {}},
                    "public.items": {
                        "tables": [dict(stats, tablename="items")],
                        "errors": {"data_node_stats:dn0002": {"type": "ValueError"}},
                    },
                },
            },
        }
        with patch(f"{module}.OperationsStore"), patch(f"{module}.ReadonlyHealthCollector") as collector, patch.object(
            ReadonlyAuditEngine, "_diagnose",
            new=AsyncMock(return_value={"structured": {}, "knowledge_refs": []}),
        ):
            collector.return_value.collect.return_value = snapshot
            result = await ReadonlyAuditEngine().run_health_audit()

        findings = [
            row["evidence"] for row in result["findings"] if row["check"] == "stale_table_statistics"
        ]
        self.assertEqual([(row["table"], row["statistics_source"]) for row in findings], [("orders", "fallback")])
        self.assertEqual(result["evidence"]["collection_status"], "partial")

    async def test_collected_table_does_not_replace_requested_target(self):
        module = "backend.engines.readonly_audit_engine"
        snapshot = {
            "status": "success",
            "errors": {},
            "checks": {
                "data_node_table_stats": [{
                    "schemaname": "public",
                    "tablename": "orders",
                    "live_tuples": 1500,
                    "modifications_since_analyze": 1500,
                    "nodes": [{"node_name": "dn0001", "live_tuples": 1500,
                               "modifications_since_analyze": 1500}],
                }],
            },
        }
        for target in (None, "public.orders"):
            with self.subTest(target=target):
                store = MagicMock()
                cursor = store.conn.cursor.return_value.__enter__.return_value
                with patch(f"{module}.OperationsStore", return_value=store), patch(
                    f"{module}.ReadonlyHealthCollector"
                ) as collector, patch.object(
                    ReadonlyAuditEngine, "_diagnose",
                    new=AsyncMock(return_value={"structured": {}, "knowledge_refs": []}),
                ):
                    collector.return_value.collect.return_value = snapshot
                    result = await ReadonlyAuditEngine().run_health_audit(
                        trigger="scheduled", table=target
                    )

                collector.return_value.collect.assert_called_once_with(table=target)
                persisted = json.loads(cursor.execute.call_args.args[1][2])
                self.assertEqual(result["evidence"]["statistics_target"], target)
                self.assertEqual(persisted["statistics_target"], target)
                self.assertEqual(persisted["trigger"], "scheduled")
                self.assertIn("stale_table_statistics", [row["check"] for row in persisted["findings"]])
