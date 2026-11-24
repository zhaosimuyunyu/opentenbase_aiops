import asyncio
from starlette.concurrency import run_in_threadpool

from ..ai.knowledge_base_pgvector import PgVectorKnowledgeBase
from ..utils.config import Config
from ..utils.logger import setup_logger
from .readonly_audit_engine import ReadonlyAuditEngine


logger = setup_logger(__name__)
ADVISORY_LOCK_ID = 742031905


class HealthAuditScheduler:
    def __init__(self, config=None):
        self.config = config or Config()
        self._run_lock = asyncio.Lock()

    async def run_once(self, *, scheduled=False, table=None):
        if self._run_lock.locked():
            return None
        async with self._run_lock:
            return await run_in_threadpool(self._run_with_database_lock, scheduled, table)

    def _run_with_database_lock(self, scheduled, table):
        kb = PgVectorKnowledgeBase()
        acquired = False
        try:
            with kb.conn.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_ID,))
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
                                  AND (evidence->>'statistics_target') IS NOT DISTINCT FROM %s::text
                                  AND created_at > now() - make_interval(secs => %s)
                            )""",
                            (table, self.config.AIOPS_AUTO_AUDIT_INTERVAL_SECONDS),
                        )
                        if cursor.fetchone()[0]:
                            return None
                kb.conn.commit()
            trigger = "scheduled" if scheduled else "manual"
            options = {"table": table} if table else {}
            return asyncio.run(ReadonlyAuditEngine().run_health_audit(trigger=trigger, **options))
        finally:
            if acquired and not kb.conn.closed:
                try:
                    with kb.conn.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))
                    kb.conn.commit()
                except Exception:
                    logger.exception("Failed to release health audit advisory lock")
            kb.close()

    async def run_forever(self):
        while True:
            delay = self.config.AIOPS_AUTO_AUDIT_INTERVAL_SECONDS
            for table in self.config.AIOPS_AUTO_AUDIT_TARGETS:
                try:
                    result = await self.run_once(scheduled=True, table=table)
                    if result:
                        logger.info("Scheduled health audit persisted as %s", result["audit_id"])
                    else:
                        delay = min(delay, 30)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Scheduled health audit failed for %s", table)
                    delay = min(delay, 60)
            await asyncio.sleep(delay)
