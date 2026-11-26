import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.engines.health_audit_scheduler import HealthAuditScheduler


class HealthAuditSchedulerTests(unittest.IsolatedAsyncioTestCase):
    def make_scheduler(self):
        scheduler = HealthAuditScheduler(SimpleNamespace(
            AIOPS_AUTO_AUDIT_INTERVAL_SECONDS=120,
            AIOPS_AUTO_AUDIT_RETRY_MAX_SECONDS=3600,
            AIOPS_AUTO_AUDIT_TARGETS=(None,),
            AIOPS_AUTO_REPAIR_ENABLED=False,
        ))
        scheduler._restore_runtime_status = AsyncMock()
        scheduler._persist_runtime_status = AsyncMock()
        return scheduler

    def test_restores_persisted_scheduler_state(self):
        store = MagicMock()
        store.conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ({
            "state": "failed",
            "last_error_type": "OperationalError",
            "consecutive_failures": 2,
            "failed_targets": ["full"],
        },)
        scheduler = self.make_scheduler()
        with patch(
            "backend.engines.health_audit_scheduler.OperationsStore", return_value=store
        ):
            scheduler._restore_runtime_status_sync()

        status = scheduler.runtime_status()
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["last_error_type"], "OperationalError")
        self.assertEqual(status["consecutive_failures"], 2)
        self.assertEqual(status["failed_targets"], ["full"])
        self.assertTrue(status["restored_from_store"])
        store.close.assert_called_once()

    def test_persists_scheduler_state_as_json(self):
        scheduler = self.make_scheduler()
        scheduler._set_runtime_status(
            state="failed", last_error_type="OperationalError", consecutive_failures=1,
        )
        store = MagicMock()
        with patch(
            "backend.engines.health_audit_scheduler.OperationsStore", return_value=store
        ):
            scheduler._persist_runtime_status_sync()

        statement, parameters = store.conn.cursor.return_value.__enter__.return_value.execute.call_args_list[-1].args
        self.assertIn("ON CONFLICT(state_id) DO UPDATE", statement)
        self.assertEqual(parameters[0].adapted["state"], "failed")
        self.assertEqual(parameters[0].adapted["consecutive_failures"], 1)
        store.close.assert_called_once()

    async def test_restored_retry_deadline_is_honored_after_restart(self):
        scheduler = self.make_scheduler()
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=45)

        async def restore_state():
            scheduler._set_runtime_status(
                state="failed",
                consecutive_failures=2,
                next_retry_at=retry_at.isoformat(),
                restored_from_store=True,
            )

        scheduler._restore_runtime_status = AsyncMock(side_effect=restore_state)
        scheduler.run_once = AsyncMock(return_value={"audit_id": "unexpected"})

        with patch("backend.engines.health_audit_scheduler.asyncio.sleep", new=AsyncMock(
            side_effect=asyncio.CancelledError
        )) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await scheduler.run_forever()

        scheduler.run_once.assert_not_awaited()
        self.assertGreater(sleep.await_args.args[0], 40)
        self.assertEqual(scheduler.runtime_status()["consecutive_failures"], 2)

    async def test_runtime_status_tracks_successful_scheduled_audit(self):
        scheduler = self.make_scheduler()
        scheduler.run_once = AsyncMock(return_value={"audit_id": "audit-1"})

        with patch("backend.engines.health_audit_scheduler.asyncio.sleep", new=AsyncMock(
            side_effect=asyncio.CancelledError
        )):
            with self.assertRaises(asyncio.CancelledError):
                await scheduler.run_forever()

        status = scheduler.runtime_status()
        self.assertEqual(status["state"], "completed")
        self.assertEqual(status["target"], "full")
        self.assertIsNotNone(datetime.fromisoformat(status["started_at"]))
        self.assertIsNotNone(datetime.fromisoformat(status["finished_at"]))
        self.assertIsNotNone(datetime.fromisoformat(status["next_retry_at"]))
        self.assertEqual(status["consecutive_failures"], 0)
        scheduler.run_once.assert_awaited_once_with(scheduled=True, table=None)
        scheduler._persist_runtime_status.assert_awaited_once()

    async def test_runtime_status_records_failure_and_retry_time(self):
        scheduler = self.make_scheduler()
        scheduler.run_once = AsyncMock(side_effect=RuntimeError("database unavailable"))

        with patch("backend.engines.health_audit_scheduler.asyncio.sleep", new=AsyncMock(
            side_effect=asyncio.CancelledError
        )):
            with self.assertRaises(asyncio.CancelledError):
                await scheduler.run_forever()

        status = scheduler.runtime_status()
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["last_error_type"], "RuntimeError")
        self.assertEqual(status["consecutive_failures"], 1)
        self.assertIsNotNone(datetime.fromisoformat(status["next_retry_at"]))

    async def test_later_target_success_does_not_hide_failure_in_same_cycle(self):
        scheduler = HealthAuditScheduler(SimpleNamespace(
            AIOPS_AUTO_AUDIT_INTERVAL_SECONDS=120,
            AIOPS_AUTO_AUDIT_RETRY_MAX_SECONDS=3600,
            AIOPS_AUTO_AUDIT_TARGETS=("public.failed", "public.healthy"),
            AIOPS_AUTO_REPAIR_ENABLED=False,
        ))
        scheduler._restore_runtime_status = AsyncMock()
        scheduler._persist_runtime_status = AsyncMock()
        scheduler.run_once = AsyncMock(side_effect=[
            RuntimeError("target unavailable"),
            {"audit_id": "audit-healthy"},
        ])

        with patch("backend.engines.health_audit_scheduler.asyncio.sleep", new=AsyncMock(
            side_effect=asyncio.CancelledError
        )) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await scheduler.run_forever()

        status = scheduler.runtime_status()
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["failed_targets"], ["public.failed"])
        self.assertEqual(status["completed_targets"], ["public.healthy"])
        self.assertEqual(status["consecutive_failures"], 1)
        self.assertEqual(status["last_error_type"], "RuntimeError")
        sleep.assert_awaited_once_with(60)

    async def test_retry_backoff_is_exponential_and_capped(self):
        scheduler = HealthAuditScheduler(SimpleNamespace(
            AIOPS_AUTO_AUDIT_INTERVAL_SECONDS=900,
            AIOPS_AUTO_AUDIT_RETRY_MAX_SECONDS=180,
            AIOPS_AUTO_AUDIT_TARGETS=(None,),
            AIOPS_AUTO_REPAIR_ENABLED=False,
        ))
        scheduler._restore_runtime_status = AsyncMock()
        scheduler._persist_runtime_status = AsyncMock()
        scheduler._runtime_status["consecutive_failures"] = 2
        scheduler.run_once = AsyncMock(side_effect=RuntimeError("database unavailable"))

        with patch("backend.engines.health_audit_scheduler.asyncio.sleep", new=AsyncMock(
            side_effect=asyncio.CancelledError
        )) as sleep:
            with self.assertRaises(asyncio.CancelledError):
                await scheduler.run_forever()

        status = scheduler.runtime_status()
        self.assertEqual(status["consecutive_failures"], 3)
        self.assertEqual(status["state"], "failed")
        sleep.assert_awaited_once_with(180)

    async def test_successful_cycle_resets_consecutive_failures(self):
        scheduler = self.make_scheduler()
        scheduler._runtime_status["consecutive_failures"] = 3
        scheduler.run_once = AsyncMock(return_value={"audit_id": "audit-1"})

        with patch("backend.engines.health_audit_scheduler.asyncio.sleep", new=AsyncMock(
            side_effect=asyncio.CancelledError
        )):
            with self.assertRaises(asyncio.CancelledError):
                await scheduler.run_forever()

        self.assertEqual(scheduler.runtime_status()["consecutive_failures"], 0)

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

    def test_persists_automatic_repair_outcome_with_the_audit(self):
        store = MagicMock()
        outcome = {"status": "skipped", "reason": "health_collection_incomplete"}
        with patch(
            "backend.engines.health_audit_scheduler.OperationsStore", return_value=store
        ):
            HealthAuditScheduler._persist_auto_repair_result("audit-1", outcome)
        statement, parameters = store.conn.cursor.return_value.__enter__.return_value.execute.call_args.args
        self.assertIn("'{automatic_repair}'", statement)
        self.assertEqual(parameters[0].adapted, outcome)
        self.assertEqual(parameters[1], "audit-1")
        store.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
