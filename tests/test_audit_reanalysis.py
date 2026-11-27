import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.engines.audit_reanalysis import reanalyze_persisted_audit


class AuditReanalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_reanalysis_uses_persisted_evidence_and_preserves_risk_floor(self):
        store = MagicMock()
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {
            "evidence": {
                "findings": [{"severity": "critical", "check": "node_unreachable"}],
                "cluster": {"nodes": [{"node_name": "dn1"}]},
            }
        }
        analysis = {
            "structured": {
                "risk_level": "low",
                "root_cause": "The audit captured an unavailable node.",
            },
            "knowledge_refs": [{"source_url": "https://example.invalid/doc"}],
            "analysis_fallback": False,
        }
        with patch(
            "backend.engines.audit_reanalysis.ReadonlyAuditEngine._diagnose",
            new=AsyncMock(return_value=analysis),
        ) as diagnose:
            result = await reanalyze_persisted_audit(
                "audit-1", store_factory=lambda: store
            )

        self.assertEqual(result["risk_level"], "critical")
        self.assertFalse(result["analysis_fallback"])
        self.assertEqual(diagnose.await_args.args[1]["cluster"]["nodes"][0]["node_name"], "dn1")
        update = next(
            call for call in cursor.execute.call_args_list
            if "UPDATE audit_records" in call.args[0]
        )
        self.assertEqual(update.args[1][2:], ("critical", "audit-1"))
        store.close.assert_called_once()

    async def test_reanalysis_redacts_literals_from_legacy_persisted_evidence(self):
        store = MagicMock()
        raw_query = "SELECT * FROM users WHERE email='private@example.com'"
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {
            "evidence": {
                "findings": [],
                "performance": {"long_running_queries": [{"query": raw_query}]},
            }
        }
        with patch(
            "backend.engines.audit_reanalysis.ReadonlyAuditEngine._diagnose",
            new=AsyncMock(return_value={"structured": {}, "knowledge_refs": []}),
        ) as diagnose:
            await reanalyze_persisted_audit("audit-legacy", store_factory=lambda: store)

        sent_evidence = diagnose.await_args.args[1]
        row = sent_evidence["performance"]["long_running_queries"][0]
        self.assertEqual(row["query"], "SELECT * FROM users WHERE email='?'")
        self.assertNotIn("private@example.com", str(sent_evidence))
        self.assertEqual(len(row["query_fingerprint"]), 64)
        store.close.assert_called_once()

    async def test_missing_audit_returns_not_found(self):
        store = MagicMock()
        store.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None
        with patch(
            "backend.engines.audit_reanalysis.ReadonlyAuditEngine._diagnose",
            new=AsyncMock(),
        ) as diagnose:
            with self.assertRaises(LookupError) as error:
                await reanalyze_persisted_audit("missing", store_factory=lambda: store)

        self.assertEqual(str(error.exception), "Audit not found")
        diagnose.assert_not_awaited()
        store.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
