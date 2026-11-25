import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.engines.health_audit_scheduler import HealthAuditScheduler


class HealthAuditSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_audit_when_another_instance_holds_database_lock(self):
        knowledge_base = MagicMock()
        knowledge_base.conn.closed = False
        cursor = knowledge_base.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (False,)

        with patch(
            "backend.engines.health_audit_scheduler.OperationsStore",
            return_value=knowledge_base,
        ), patch("backend.engines.health_audit_scheduler.ReadonlyAuditEngine") as engine:
            result = await HealthAuditScheduler().run_once()

        self.assertIsNone(result)
        engine.assert_not_called()
        knowledge_base.close.assert_called_once()
        cursor.execute.assert_called_once()

    async def test_runs_and_releases_database_lock(self):
        knowledge_base = MagicMock()
        knowledge_base.conn.closed = False
        cursor = knowledge_base.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [(True,)]
        audit_result = {"audit_id": "audit-1"}

        with patch(
            "backend.engines.health_audit_scheduler.OperationsStore",
            return_value=knowledge_base,
        ), patch("backend.engines.health_audit_scheduler.ReadonlyAuditEngine") as engine:
            engine.return_value.run_health_audit = AsyncMock(return_value=audit_result)
            result = await HealthAuditScheduler().run_once()

        self.assertEqual(result, audit_result)
        engine.return_value.run_health_audit.assert_awaited_once_with(trigger="manual")
        self.assertEqual(cursor.execute.call_count, 2)
        knowledge_base.conn.commit.assert_any_call()
        knowledge_base.close.assert_called_once()

    async def test_passes_alert_trigger_context_into_persisted_audit(self):
        store = MagicMock()
        store.conn.closed = False
        store.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (True,)
        context = {"group_key": "group-1", "alerts": [{"alertname": "high-risk"}]}
        with patch(
            "backend.engines.health_audit_scheduler.OperationsStore", return_value=store
        ), patch("backend.engines.health_audit_scheduler.ReadonlyAuditEngine") as engine:
            engine.return_value.run_health_audit = AsyncMock(return_value={"audit_id": "audit-1"})
            await HealthAuditScheduler().run_once(trigger="alertmanager", trigger_context=context)
        engine.return_value.run_health_audit.assert_awaited_once_with(
            trigger="alertmanager", trigger_context=context
        )

    async def test_skips_scheduled_audit_with_recent_persisted_record(self):
        store = MagicMock()
        store.conn.closed = False
        cursor = store.conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [(True,), ("audit_records",), (True,)]

        with patch(
            "backend.engines.health_audit_scheduler.OperationsStore", return_value=store
        ), patch("backend.engines.health_audit_scheduler.ReadonlyAuditEngine") as engine:
            result = await HealthAuditScheduler().run_once(scheduled=True)

        self.assertIsNone(result)
        engine.assert_not_called()
        store.close.assert_called_once()

    async def test_skips_audit_when_local_run_is_already_active(self):
        scheduler = HealthAuditScheduler()
        await scheduler._run_lock.acquire()
        try:
            with patch("backend.engines.health_audit_scheduler.OperationsStore") as knowledge_base:
                result = await scheduler.run_once()
            self.assertIsNone(result)
            knowledge_base.assert_not_called()
        finally:
            scheduler._run_lock.release()


if __name__ == "__main__":
    unittest.main()
