import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.engines.readonly_audit_engine import ReadonlyAuditEngine


class HealthAuditScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_complete_fallback_statistics_generate_repair_findings(self):
        module = "backend.engines.readonly_audit_engine"
        stats = {"schemaname": "public", "live_tuples": 1500, "modifications_since_analyze": 1500}
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
