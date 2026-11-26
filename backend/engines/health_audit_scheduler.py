import asyncio
from datetime import datetime, timedelta, timezone
from psycopg2.extras import Json
from starlette.concurrency import run_in_threadpool

from ..utils.operations_store import OperationsStore
from ..utils.config import Config
from ..utils.logger import setup_logger
from .readonly_audit_engine import ReadonlyAuditEngine
from .repair_workflow import RepairWorkflow


logger = setup_logger(__name__)
ADVISORY_LOCK_ID = 742031905


class HealthAuditScheduler:
    def __init__(self, config=None):
        self.config = config or Config()
        self._run_lock = asyncio.Lock()
        self._runtime_status = {
            "state": "idle",
            "target": None,
            "started_at": None,
            "finished_at": None,
            "next_retry_at": None,
            "last_error_type": None,
            "consecutive_failures": 0,
            "completed_targets": [],
            "skipped_targets": [],
            "failed_targets": [],
            "restored_from_store": False,
        }

    def runtime_status(self):
        return dict(self._runtime_status)

    def _set_runtime_status(self, **updates):
        self._runtime_status.update(updates)

    def _restore_runtime_status_sync(self):
        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS aiops_scheduler_runtime (
                        state_id text PRIMARY KEY,
                        status jsonb NOT NULL,
                        updated_at timestamptz NOT NULL DEFAULT now()
                    )
                """)
                cursor.execute(
                    "SELECT status FROM aiops_scheduler_runtime WHERE state_id='health_audit'"
                )
                row = cursor.fetchone()
            if row and isinstance(row[0], dict):
                restored = {**self._runtime_status, **row[0]}
                restored["restored_from_store"] = True
                self._runtime_status = restored
        finally:
            store.close()

    def _persist_runtime_status_sync(self):
        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS aiops_scheduler_runtime (
                        state_id text PRIMARY KEY,
                        status jsonb NOT NULL,
                        updated_at timestamptz NOT NULL DEFAULT now()
                    )
                """)
                cursor.execute("""
                    INSERT INTO aiops_scheduler_runtime(state_id,status,updated_at)
                    VALUES('health_audit',%s,now())
                    ON CONFLICT(state_id) DO UPDATE
                    SET status=EXCLUDED.status,updated_at=now()
                """, (Json(self.runtime_status()),))
        finally:
            store.close()

    async def _restore_runtime_status(self):
        await run_in_threadpool(self._restore_runtime_status_sync)

    async def _persist_runtime_status(self):
        try:
            await run_in_threadpool(self._persist_runtime_status_sync)
        except Exception:
            logger.exception("Could not persist health audit scheduler state")

    async def run_once(self, *, scheduled=False, table=None, progress=None,
                       trigger=None, trigger_context=None):
        if self._run_lock.locked():
            return None
        async with self._run_lock:
            if progress is not None:
                return await run_in_threadpool(
                    self._run_with_database_lock, scheduled, table, progress, trigger, trigger_context
                )
            return await run_in_threadpool(
                self._run_with_database_lock, scheduled, table, None, trigger, trigger_context
            )

    def _run_with_database_lock(self, scheduled, table, progress=None,
                                trigger=None, trigger_context=None):
        target = Json(self.config.audit_target)
        kb = OperationsStore()
        acquired = False
        try:
            with kb.conn.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_try_advisory_lock(%s, hashtext((%s::jsonb)::text))",
                    (ADVISORY_LOCK_ID, target),
                )
                acquired = cursor.fetchone()[0]
            kb.conn.commit()
            if not acquired:
                return None
            if scheduled:
                with kb.conn.cursor() as cursor:
                    cursor.execute("SELECT to_regclass('audit_records')")
                    if cursor.fetchone()[0] is not None:
                        cursor.execute(
                            """SELECT EXISTS (
                                SELECT 1 FROM audit_records
                                WHERE audit_type = 'readonly_health_audit'
                                  AND evidence->>'trigger' = 'scheduled'
                                  AND evidence->'audit_target' = %s::jsonb
                                  AND COALESCE(evidence->>'statistics_target', '') = COALESCE(%s::text, '')
                                  AND created_at > now() - make_interval(secs => %s)
                            )""",
                            (target, table, self.config.AIOPS_AUTO_AUDIT_INTERVAL_SECONDS),
                        )
                        if cursor.fetchone()[0]:
                            return None
                kb.conn.commit()
            audit_trigger = "scheduled" if scheduled else (trigger or "manual")
            options = {"table": table} if table else {}
            if progress is not None:
                options["progress"] = progress
            if trigger_context:
                options["trigger_context"] = trigger_context
            return asyncio.run(
                ReadonlyAuditEngine(self.config).run_health_audit(trigger=audit_trigger, **options)
            )
        finally:
            if acquired and not kb.conn.closed:
                try:
                    with kb.conn.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_advisory_unlock(%s, hashtext((%s::jsonb)::text))",
                            (ADVISORY_LOCK_ID, target),
                        )
                    kb.conn.commit()
                except Exception:
                    logger.exception("Failed to release health audit advisory lock")
            kb.close()

    async def run_forever(self):
        try:
            await self._restore_runtime_status()
            retry_at = self._runtime_status.get("next_retry_at")
            if retry_at:
                delay = max(
                    0,
                    (datetime.fromisoformat(retry_at) - datetime.now(timezone.utc)).total_seconds(),
                )
                if delay:
                    await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Could not restore health audit scheduler state")
        while True:
            delay = self.config.AIOPS_AUTO_AUDIT_INTERVAL_SECONDS
            completed_targets = []
            skipped_targets = []
            failed_targets = []
            cycle_error_type = None
            for table in self.config.AIOPS_AUTO_AUDIT_TARGETS:
                self._set_runtime_status(
                    state="running",
                    target=table or "full",
                    started_at=datetime.now(timezone.utc).isoformat(),
                    finished_at=None,
                    next_retry_at=None,
                    completed_targets=list(completed_targets),
                    skipped_targets=list(skipped_targets),
                    failed_targets=list(failed_targets),
                )
                try:
                    result = await self.run_once(scheduled=True, table=table)
                    if result:
                        logger.info("Scheduled health audit persisted as %s", result["audit_id"])
                        if self.config.AIOPS_AUTO_REPAIR_ENABLED:
                            try:
                                repair = await run_in_threadpool(
                                    RepairWorkflow(self.config).auto_repair_from_audit,
                                    result["audit_id"],
                                )
                            except Exception as error:
                                repair = {
                                    "status": "error",
                                    "error_type": type(error).__name__,
                                }
                                logger.exception(
                                    "Scheduled automatic repair failed for audit %s",
                                    result["audit_id"],
                                )
                            try:
                                self._persist_auto_repair_result(result["audit_id"], repair)
                                logger.info(
                                    "Scheduled automatic repair finished for %s: %s",
                                    result["audit_id"], repair.get("status"),
                                )
                            except Exception:
                                logger.exception(
                                    "Could not persist automatic repair result for audit %s",
                                    result["audit_id"],
                                )
                        completed_targets.append(table or "full")
                        self._set_runtime_status(completed_targets=list(completed_targets))
                    else:
                        skipped_targets.append(table or "full")
                        self._set_runtime_status(skipped_targets=list(skipped_targets))
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    failed_targets.append(table or "full")
                    cycle_error_type = type(error).__name__
                    self._set_runtime_status(failed_targets=list(failed_targets))
                    logger.exception("Scheduled health audit failed for %s", table)
            if failed_targets:
                failure_count = self._runtime_status["consecutive_failures"] + 1
                retry_cap = min(
                    self.config.AIOPS_AUTO_AUDIT_INTERVAL_SECONDS,
                    max(60, getattr(self.config, "AIOPS_AUTO_AUDIT_RETRY_MAX_SECONDS", 3600)),
                )
                retry_delay = 60 * 2 ** min(failure_count - 1, 16)
                delay = min(retry_cap, retry_delay)
                self._set_runtime_status(
                    state="failed",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    last_error_type=cycle_error_type,
                    consecutive_failures=failure_count,
                )
            elif skipped_targets:
                delay = min(self.config.AIOPS_AUTO_AUDIT_INTERVAL_SECONDS, 30)
                self._set_runtime_status(
                    state="skipped",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
            else:
                self._set_runtime_status(
                    state="completed",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    last_error_type=None,
                    consecutive_failures=0,
                )
            self._set_runtime_status(
                next_retry_at=(datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            )
            if self._runtime_status["state"] in {"completed", "failed"}:
                await self._persist_runtime_status()
            await asyncio.sleep(delay)

    @staticmethod
    def _persist_auto_repair_result(audit_id, result):
        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                cursor.execute(
                    """UPDATE audit_records
                       SET evidence=jsonb_set(
                           COALESCE(evidence, '{}'::jsonb),
                           '{automatic_repair}', %s::jsonb, true)
                       WHERE audit_id=%s""",
                    (Json(result), audit_id),
                )
        finally:
            store.close()
