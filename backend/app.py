"""FastAPI application (optional REST API)"""
import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

from .utils.config import Config
from .utils.db_connector import OpenTenBaseConnector
from .utils.logger import setup_logger
from .collectors.cluster import ClusterCollector
from .collectors.performance import PerformanceCollector
from .ai.llm_client import DeepSeekClient
from .engines.readonly_audit_engine import ReadonlyAuditEngine
from .ai.knowledge_base_pgvector import PgVectorKnowledgeBase
from psycopg2.extras import RealDictCursor
from .engines.repair_workflow import RepairWorkflow
from .engines.health_audit_scheduler import HealthAuditScheduler

logger = setup_logger(__name__)
config = Config()
health_audit_scheduler = HealthAuditScheduler(config)


@asynccontextmanager
async def lifespan(_app):
    scheduler_task = None
    if config.AIOPS_AUTO_AUDIT_ENABLED:
        scheduler_task = asyncio.create_task(health_audit_scheduler.run_forever())
    try:
        yield
    finally:
        if scheduler_task:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task

# Initialize FastAPI app
app = FastAPI(
    title="OpenTenBase AIOps API",
    description="AI-powered operations platform for OpenTenBase",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize components
db_connector = OpenTenBaseConnector(config)
cluster_collector = ClusterCollector(db_connector)
performance_collector = PerformanceCollector(db_connector, config)
llm_client = DeepSeekClient(config)


class QuestionRequest(BaseModel):
    question: str
    include_context: bool = True


class DiagnosisRequest(BaseModel):
    description: str


class RepairApprovalRequest(BaseModel):
    approver: str
    token: str


class RepairRejectionRequest(BaseModel):
    approver: str
    reason: str


class RepairProposalRequest(BaseModel):
    reason: str
    finding_index: int = Field(ge=0)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "OpenTenBase AIOps",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    db_status = db_connector.test_connection()
    return {
        "api": "healthy",
        "database": db_status
    }


@app.get("/api/cluster/status")
async def get_cluster_status():
    """Get cluster status"""
    try:
        result = cluster_collector.collect()
        return result
    except Exception as e:
        logger.error(f"Failed to get cluster status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/performance/metrics")
async def get_performance_metrics():
    """Get performance metrics"""
    try:
        result = performance_collector.collect()
        return result
    except Exception as e:
        logger.error(f"Failed to get performance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/qa/ask")
async def ask_question(request: QuestionRequest):
    """Ask a question to the AI assistant"""
    try:
        context = None
        if request.include_context:
            # Get current cluster status as context
            cluster_data = cluster_collector.collect()
            context = f"当前集群状态：{cluster_data.get('data', {})}"

        answer = llm_client.answer_question(
            question=request.question,
            context=context
        )

        return {
            "question": request.question,
            "answer": answer,
            "context_included": request.include_context
        }
    except Exception as e:
        logger.error(f"Failed to answer question: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/diagnosis")
async def diagnose_issue(request: DiagnosisRequest):
    """Diagnose database issue"""
    try:
        # Collect cluster and performance data
        cluster_data = cluster_collector.collect().get('data', {})
        performance_data = performance_collector.collect().get('data', {})

        # Use AI to diagnose
        diagnosis = llm_client.diagnose_issue(
            issue_description=request.description,
            cluster_data={**cluster_data, **performance_data}
        )

        return {
            "description": request.description,
            "diagnosis": diagnosis,
            "cluster_data": cluster_data,
            "performance_data": performance_data
        }
    except Exception as e:
        logger.error(f"Failed to diagnose issue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health-report")
async def get_health_report():
    """Generate AI-powered health report"""
    try:
        cluster_data = cluster_collector.collect().get('data', {})
        performance_data = performance_collector.collect().get('data', {})

        report = llm_client.generate_health_summary(
            cluster_data=cluster_data,
            performance_data=performance_data
        )

        return {
            "report": report,
            "cluster_data": cluster_data,
            "performance_data": performance_data
        }
    except Exception as e:
        logger.error(f"Failed to generate health report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/audits/locks")
async def run_readonly_lock_audit():
    """Collect current locks, retrieve references, diagnose, and persist the audit."""
    try:
        return await ReadonlyAuditEngine().run_lock_audit()
    except Exception as e:
        logger.exception("Read-only lock audit failed")
        raise HTTPException(status_code=503, detail="Read-only lock audit failed") from e


@app.post("/api/audits/health")
async def run_readonly_health_audit():
    """Run and persist the read-only health audit."""
    try:
        result = await health_audit_scheduler.run_once()
        if result is None:
            raise HTTPException(status_code=409, detail="Another health audit is already running")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Read-only health audit failed")
        raise HTTPException(status_code=503, detail="Read-only health audit failed") from e


@app.get("/api/automation/status")
async def get_automation_status():
    kb = PgVectorKnowledgeBase()
    try:
        with kb.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT to_regclass('public.audit_records') AS audit_table")
            audit_table_exists = cursor.fetchone()["audit_table"] is not None
            latest = None
            if audit_table_exists:
                cursor.execute(
                    "SELECT audit_id,created_at,risk_level FROM audit_records "
                    "WHERE audit_type='readonly_health_audit' ORDER BY created_at DESC LIMIT 1"
                )
                latest = cursor.fetchone()
        return {
            "automatic_health_audit_enabled": config.AIOPS_AUTO_AUDIT_ENABLED,
            "interval_seconds": config.AIOPS_AUTO_AUDIT_INTERVAL_SECONDS,
            "latest_audit": dict(latest) if latest else None,
        }
    except Exception as error:
        logger.exception("Failed to read automation status")
        raise HTTPException(status_code=503, detail="Automation status is unavailable") from error
    finally:
        kb.close()


@app.get("/api/audits")
async def list_audits(limit: int = 20, offset: int = 0, audit_type: Optional[str] = None):
    """Return paginated audit summaries without exposing full SQL evidence."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    kb = PgVectorKnowledgeBase()
    try:
        with kb.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """SELECT audit_id, audit_type, created_at, risk_level, status,
                          evidence->>'collection_status' AS collection_status,
                          jsonb_array_length(COALESCE(evidence->'findings', '[]'::jsonb)) AS finding_count,
                          jsonb_array_length(COALESCE(knowledge_refs, '[]'::jsonb)) AS reference_count
                   FROM audit_records
                   WHERE (%s IS NULL OR audit_type=%s)
                   ORDER BY created_at DESC LIMIT %s OFFSET %s""",
                (audit_type, audit_type, limit, offset),
            )
            records = [dict(row) for row in cursor.fetchall()]
        return {"items": records, "limit": limit, "offset": offset}
    except Exception as error:
        logger.exception("Failed to list audit history")
        raise HTTPException(status_code=503, detail="Audit history is unavailable") from error
    finally:
        kb.close()


@app.get("/api/audits/{audit_id}")
async def get_audit(audit_id: str):
    """Return the stored evidence and diagnosis for one audit."""
    kb = PgVectorKnowledgeBase()
    try:
        with kb.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """SELECT audit_id, audit_type, created_at, risk_level, status,
                          evidence, ai_analysis, knowledge_refs
                   FROM audit_records WHERE audit_id=%s""",
                (audit_id,),
            )
            record = cursor.fetchone()
        if record is None:
            raise HTTPException(status_code=404, detail="Audit not found")
        return dict(record)
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to read audit")
        raise HTTPException(status_code=503, detail="Audit record is unavailable") from error
    finally:
        kb.close()


@app.post("/api/audits/{audit_id}/repair-requests")
def create_repair_from_audit(audit_id: str, request: RepairProposalRequest):
    """Create an ANALYZE proposal from a persisted statistics finding."""
    kb = PgVectorKnowledgeBase()
    try:
        with kb.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT evidence, knowledge_refs FROM audit_records WHERE audit_id=%s", (audit_id,))
            record = cursor.fetchone()
        if not record:
            raise HTTPException(status_code=404, detail="Audit not found")
        findings = (record["evidence"] or {}).get("findings", [])
        finding = findings[request.finding_index] if request.finding_index < len(findings) else {}
        if finding.get("check") != "stale_table_statistics":
            raise HTTPException(status_code=400, detail="Selected audit finding is not eligible for ANALYZE")
        evidence = finding["evidence"]
        table = f"{evidence['schema']}.{evidence['table']}"
        return RepairWorkflow().create_request(
            "analyze_table", {"table": table},
            {"observation": evidence, "knowledge_refs": record["knowledge_refs"] or []}, request.reason,
            audit_id, finding
        )
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Failed to create audit repair request")
        raise HTTPException(status_code=503, detail="Repair storage is unavailable") from error
    finally:
        kb.close()


@app.get("/api/repairs")
async def list_repair_requests(limit: int = 50):
    try:
        return {"items": RepairWorkflow().list_requests(limit)}
    except Exception as error:
        logger.exception("Failed to list repair requests")
        raise HTTPException(status_code=503, detail="Repair storage is unavailable") from error


@app.post("/api/repairs/{request_id}/approve")
async def approve_repair_request(request_id: str, request: RepairApprovalRequest):
    try:
        return RepairWorkflow().approve_and_execute(
            request_id, request.approver, request.token
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Failed to execute repair request")
        raise HTTPException(status_code=503, detail="Repair execution is unavailable") from error


@app.post("/api/repairs/{request_id}/reject")
async def reject_repair_request(request_id: str, request: RepairRejectionRequest):
    try:
        return RepairWorkflow().reject(request_id, request.approver, request.reason)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Failed to reject repair request")
        raise HTTPException(status_code=503, detail="Repair storage is unavailable") from error


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.APP_HOST, port=8000)
