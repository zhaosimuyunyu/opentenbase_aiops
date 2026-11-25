import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.engines.readonly_audit_engine import ReadonlyAuditEngine
from backend.collectors.readonly_health import stale_statistics_nodes


class HealthAuditScopeTests(unittest.IsolatedAsyncioTestCase):
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
