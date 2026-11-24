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

    async def run_once(self):
        if self._run_lock.locked():
            return None
        async with self._run_lock:
            return await run_in_threadpool(self._run_with_database_lock)

    @staticmethod
    def _run_with_database_lock():
        kb = PgVectorKnowledgeBase()
        acquired = False
        try:
            with kb.conn.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_ID,))
                acquired = cursor.fetchone()[0]
            kb.conn.commit()
            if not acquired:
                return None
            return asyncio.run(ReadonlyAuditEngine().run_health_audit())
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
            try:
                result = await self.run_once()
                if result:
                    logger.info("Scheduled health audit persisted as %s", result["audit_id"])
                else:
                    delay = min(delay, 30)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled health audit failed")
                delay = min(delay, 60)
            await asyncio.sleep(delay)
