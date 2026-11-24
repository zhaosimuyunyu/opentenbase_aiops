import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.engines.readonly_audit_engine import ReadonlyAuditEngine


class HealthAuditScopeTests(unittest.IsolatedAsyncioTestCase):
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
