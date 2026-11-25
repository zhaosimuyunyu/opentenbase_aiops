"""FastAPI application (optional REST API)"""
import asyncio
import json
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal, Optional

from .utils.config import Config
from .utils.db_connector import OpenTenBaseConnector
from .utils.logger import setup_logger
from .collectors.cluster import ClusterCollector
from .collectors.performance import PerformanceCollector
from .ai.llm_client import DeepSeekClient
from .engines.readonly_audit_engine import ReadonlyAuditEngine
from .utils.operations_store import OperationsStore
from psycopg2.extras import Json, RealDictCursor
from .engines.repair_workflow import RepairWorkflow, has_repair_identity
from .engines.health_audit_scheduler import HealthAuditScheduler
from .capabilities import CAPABILITIES

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


class RepairHumanApprovalRequest(BaseModel):
    token: str


class RepairRejectionRequest(BaseModel):
    approver: str
    reason: str
    token: str = ""


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


@app.get("/api/capabilities")
async def capabilities():
    """Expose the verified operation boundary to agents and orchestrators."""
    return CAPABILITIES


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
async def run_readonly_health_audit(
    table: Optional[str] = Query(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"),
):
    """Run and persist the read-only health audit."""
    try:
        result = await health_audit_scheduler.run_once(table=table)
        if result is None:
            raise HTTPException(status_code=409, detail="Another health audit is already running")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Read-only health audit failed")
        raise HTTPException(status_code=503, detail="Read-only health audit failed") from e


@app.post("/api/audits/health/stream")
async def stream_readonly_health_audit(
    table: Optional[str] = Query(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"),
):
    """Stream progress and the persisted result of a manual audit."""
    loop = asyncio.get_running_loop()
    events = asyncio.Queue()

    def progress(stage):
        loop.call_soon_threadsafe(events.put_nowait, {"type": "progress", "stage": stage})

    async def run():
        try:
            result = await health_audit_scheduler.run_once(table=table, progress=progress)
            event = {"type": "busy"} if result is None else {"type": "result", "audit": result}
        except Exception:
            logger.exception("Streaming health audit failed")
            event = {"type": "error"}
        events.put_nowait(event)

    async def stream():
        # Keep the audit running so a disconnected client can find it in history.
        task = asyncio.create_task(run())
        yield 'data: {"type":"progress","stage":"starting"}\n\n'
        while True:
            try:
                event = await asyncio.wait_for(events.get(), timeout=10)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            if event["type"] != "progress":
                await task
                return

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/automation/status")
def get_automation_status():
    kb = None
    try:
        kb = OperationsStore()
        with kb.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT to_regclass('public.audit_records') AS audit_table")
            audit_table_exists = cursor.fetchone()["audit_table"] is not None
            latest = None
            latest_by_scope = {}
            latest_scheduled_at = None
            latest_scheduled_collection_status = None
            scheduled_targets = []
            repair_review_count = 0
            cursor.execute("SELECT to_regclass('repair_requests') AS repair_table")
            if cursor.fetchone()["repair_table"] is not None:
                cursor.execute("""
                    SELECT count(*) AS review_count
                    FROM repair_requests AS request
                    WHERE to_jsonb(request)->>'manual_review' IS NULL
                      AND (status = 'unverified' OR
                           (status = 'executing' AND
                            COALESCE(approved_at, created_at) < now() - interval '5 minutes'))
                """)
                repair_review_count = cursor.fetchone()["review_count"]
            if audit_table_exists:
                cursor.execute(
                    """SELECT * FROM (
                        SELECT DISTINCT ON (scope) audit_id, created_at, risk_level,
                               evidence->>'trigger' AS trigger,
                               evidence->>'statistics_target' AS statistics_target,
                               CASE WHEN evidence->>'statistics_target' IS NULL
                                    THEN 'full' ELSE 'targeted' END AS scope
                        FROM audit_records WHERE audit_type='readonly_health_audit'
                          AND evidence->'audit_target' = %s::jsonb
                        ORDER BY scope, created_at DESC, audit_id DESC
                    ) AS scoped ORDER BY created_at DESC, audit_id DESC""",
                    (Json(config.audit_target),),
                )
                records = cursor.fetchall()
                latest = records[0] if records else None
                latest_by_scope = {row["scope"]: dict(row) for row in records}
                cursor.execute(
                    """SELECT target.name AS "table", audit.created_at, audit.collection_status,
                              audit.analysis_fallback
                       FROM unnest(%s::text[]) WITH ORDINALITY AS target(name, position)
                       LEFT JOIN LATERAL (
                           SELECT created_at, evidence->>'collection_status' AS collection_status,
                                  ai_analysis->'analysis_fallback' = 'true'::jsonb AS analysis_fallback
                           FROM audit_records
                           WHERE audit_type='readonly_health_audit' AND evidence->>'trigger'='scheduled'
                             AND evidence->'audit_target' = %s::jsonb
                             AND COALESCE(evidence->>'statistics_target', '') = COALESCE(target.name, '')
                           ORDER BY created_at DESC, audit_id DESC LIMIT 1
                       ) AS audit ON true
                       ORDER BY target.position""",
                    (list(config.AIOPS_AUTO_AUDIT_TARGETS), Json(config.audit_target)),
                )
                scheduled_targets = [dict(row) for row in cursor.fetchall()]
                if scheduled_targets and all(row["created_at"] for row in scheduled_targets):
                    latest_scheduled_at = min(row["created_at"] for row in scheduled_targets)
                statuses = {row["collection_status"] for row in scheduled_targets}
                latest_scheduled_collection_status = next(
                    (value for value in ("error", "partial", "success") if value in statuses), None
                )
        return {
            "automatic_health_audit_enabled": config.AIOPS_AUTO_AUDIT_ENABLED,
            "repair_executor_ready": bool(
                config.AIOPS_REPAIR_DB_USER.strip()
                and config.AIOPS_REPAIR_DB_USER != config.DB_USER
            ),
            "interval_seconds": config.AIOPS_AUTO_AUDIT_INTERVAL_SECONDS,
            "statistics_target": config.AIOPS_AUTO_AUDIT_TABLE,
            "latest_audit": dict(latest) if latest else None,
            "latest_audits_by_scope": latest_by_scope,
            "latest_scheduled_at": latest_scheduled_at,
            "latest_scheduled_collection_status": latest_scheduled_collection_status,
            "scheduled_targets": scheduled_targets,
            "repair_review_count": repair_review_count,
        }
    except Exception as error:
        logger.exception("Failed to read automation status")
        raise HTTPException(status_code=503, detail="Automation status is unavailable") from error
    finally:
        if kb is not None:
            kb.close()


@app.get("/metrics", response_class=PlainTextResponse)
def audit_metrics():
    status = get_automation_status()
    latest = status["latest_audit"]
    scheduled = status["latest_scheduled_at"]
    risk = latest["risk_level"] if latest else None
    levels = ("low", "medium", "high", "critical", "unknown")
    if latest and risk not in levels:
        risk = "unknown"
    metrics = [
        "# TYPE aiops_health_audit_schedule_enabled gauge",
        f"aiops_health_audit_schedule_enabled {int(status['automatic_health_audit_enabled'])}",
        "# TYPE aiops_health_audit_interval_seconds gauge",
        f"aiops_health_audit_interval_seconds {status['interval_seconds']}",
        "# TYPE aiops_health_audit_latest_timestamp_seconds gauge",
        f"aiops_health_audit_latest_timestamp_seconds {latest['created_at'].timestamp() if latest else 0}",
        "# TYPE aiops_health_audit_latest_scheduled_timestamp_seconds gauge",
        f"aiops_health_audit_latest_scheduled_timestamp_seconds {scheduled.timestamp() if scheduled else 0}",
        "# TYPE aiops_health_audit_latest_risk gauge",
    ]
    metrics.extend(
        f'aiops_health_audit_latest_risk{{level="{level}"}} {int(risk == level)}'
        for level in levels
    )
    metrics.append("# TYPE aiops_health_audit_scope_risk gauge")
    for scope, record in status["latest_audits_by_scope"].items():
        scope_risk = record["risk_level"] if record["risk_level"] in levels else "unknown"
        metrics.extend(
            f'aiops_health_audit_scope_risk{{scope="{scope}",level="{level}"}} {int(scope_risk == level)}'
            for level in levels
        )
    metrics.append("# TYPE aiops_health_audit_scheduled_collection_degraded gauge")
    degraded = status["latest_scheduled_collection_status"] in {"partial", "error"}
    metrics.append(f"aiops_health_audit_scheduled_collection_degraded {int(degraded)}")
    metrics.append("# TYPE aiops_health_audit_scheduled_analysis_degraded gauge")
    analysis_degraded = any(row["analysis_fallback"] for row in status["scheduled_targets"])
    metrics.append(f"aiops_health_audit_scheduled_analysis_degraded {int(analysis_degraded)}")
    metrics.append("# TYPE aiops_repair_review_count gauge")
    metrics.append(f"aiops_repair_review_count {status['repair_review_count']}")
    metrics.append("# TYPE aiops_repair_executor_ready gauge")
    metrics.append(f"aiops_repair_executor_ready {int(status['repair_executor_ready'])}")
    return PlainTextResponse("\n".join(metrics) + "\n", media_type="text/plain; version=0.0.4")


@app.get("/api/audits")
def list_audits(
    limit: int = 20,
    offset: int = 0,
    audit_type: Optional[str] = None,
    risk: Optional[Literal["high_or_critical", "critical"]] = None,
    table: Optional[str] = Query(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"),
    database: Optional[str] = None,
):
    """Return paginated audit summaries without exposing full SQL evidence."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    kb = None
    try:
        kb = OperationsStore()
        with kb.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT to_regclass('audit_records') AS audit_table")
            if cursor.fetchone()["audit_table"] is None:
                return {"items": [], "limit": limit, "offset": offset}
            cursor.execute(
                """SELECT audit_id, audit_type, created_at, risk_level, status,
                          evidence->>'collection_status' AS collection_status,
                          evidence->>'trigger' AS trigger,
                          evidence->>'statistics_target' AS statistics_target,
                          target.database,
                          jsonb_array_length(COALESCE(evidence->'findings', '[]'::jsonb)) AS finding_count,
                          CASE WHEN jsonb_typeof(knowledge_refs) = 'array'
                               THEN jsonb_array_length(knowledge_refs)
                               ELSE 0 END AS reference_count
                   FROM audit_records
                   CROSS JOIN LATERAL (VALUES (COALESCE(
                       evidence #>> '{cluster,database_identity,0,database}',
                       evidence #>> '{cluster,database_info,0,database}'
                   ))) AS target(database)
                   WHERE (%s::text IS NULL OR audit_type=%s)
                     AND (%s::text IS NULL OR risk_level = ANY(%s))
                     AND (%s::text IS NULL OR evidence->>'statistics_target' = %s)
                     AND (%s::text IS NULL OR target.database = %s)
                   ORDER BY created_at DESC, audit_id DESC LIMIT %s OFFSET %s""",
                (audit_type, audit_type, risk,
                 ["critical"] if risk == "critical" else ["high", "critical"],
                 table, table, database, database, limit, offset),
            )
            records = [dict(row) for row in cursor.fetchall()]
        return {"items": records, "limit": limit, "offset": offset}
    except Exception as error:
        logger.exception("Failed to list audit history")
        raise HTTPException(status_code=503, detail="Audit history is unavailable") from error
    finally:
        if kb is not None:
            kb.close()


@app.get("/api/audits/{audit_id}")
def get_audit(audit_id: str):
    """Return the stored evidence and diagnosis for one audit."""
    kb = None
    try:
        kb = OperationsStore()
        with kb.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT to_regclass('audit_records') AS audit_table")
            if cursor.fetchone()["audit_table"] is None:
                raise HTTPException(status_code=404, detail="Audit not found")
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
        if kb is not None:
            kb.close()


@app.post("/api/audits/{audit_id}/repair-requests")
def create_repair_from_audit(audit_id: str, request: RepairProposalRequest):
    """Create an ANALYZE proposal from a persisted statistics finding."""
    kb = None
    try:
        kb = OperationsStore()
        with kb.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT to_regclass('audit_records') AS audit_table")
            if cursor.fetchone()["audit_table"] is None:
                raise HTTPException(status_code=404, detail="Audit not found")
            cursor.execute(
                "SELECT evidence, ai_analysis, knowledge_refs FROM audit_records WHERE audit_id=%s",
                (audit_id,),
            )
            record = cursor.fetchone()
        if not record:
            raise HTTPException(status_code=404, detail="Audit not found")
        audit_evidence = record["evidence"] or {}
        findings = audit_evidence.get("findings", [])
        finding = findings[request.finding_index] if request.finding_index < len(findings) else {}
        if finding.get("check") != "stale_table_statistics":
            raise HTTPException(status_code=400, detail="Selected audit finding is not eligible for ANALYZE")
        evidence = finding["evidence"]
        if not has_repair_identity(evidence):
            raise HTTPException(status_code=400, detail="Audited database or table identity is missing; rerun the health audit")
        table = f"{evidence['schema']}.{evidence['table']}"
        if any(name.startswith("data_node_stats:") for name in audit_evidence.get("collection_errors", {})):
            fallback = (audit_evidence.get("performance") or {}).get("data_node_stats_fallback") or {}
            entry = fallback.get(table) or {}
            if evidence.get("statistics_source") != "fallback" or entry.get("errors") != {} or not any(
                row.get("nodes") == evidence["nodes"] for row in entry.get("tables", [])
            ):
                raise HTTPException(status_code=400, detail="Data-node statistics are incomplete; rerun the health audit")
        return RepairWorkflow().create_request(
            "analyze_table", {"table": table},
            {
                "proposal_source": "stale_table_statistics",
                "observation": evidence,
                "review_context": {
                    "collection_status": audit_evidence.get("collection_status"),
                    "failed_checks": sorted(audit_evidence.get("collection_errors") or {}),
                    "cluster_lock_wait_observed": any(
                        item.get("check") == "lock_waits" for item in findings
                    ),
                    "prepared_blocker_in_target_database": any(
                        item.get("check") == "prepared_transaction_blocker"
                        and any(
                            transaction.get("database") == evidence["database_identity"]["database"]
                            for transaction in item.get("evidence", [])
                        )
                        for item in findings
                    ),
                },
                "ai_analysis": record["ai_analysis"],
                "knowledge_refs": record["knowledge_refs"] if isinstance(record["knowledge_refs"], list) else [],
            }, request.reason,
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
        if kb is not None:
            kb.close()


@app.get("/api/repairs")
def list_repair_requests(
    limit: int = 50,
    offset: int = 0,
    queue: Optional[Literal["pending", "review"]] = None,
):
    try:
        return {"items": RepairWorkflow().list_requests(limit, offset, queue)}
    except Exception as error:
        logger.exception("Failed to list repair requests")
        raise HTTPException(status_code=503, detail="Repair storage is unavailable") from error


@app.post("/api/repairs/{request_id}/approve")
def approve_repair_request(request_id: str, request: RepairApprovalRequest):
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


@app.post("/api/repairs/{request_id}/human-approval")
def record_human_repair_approval(request_id: str, request: RepairHumanApprovalRequest):
    try:
        return RepairWorkflow().record_human_approval(request_id, request.token)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Failed to record human repair approval")
        raise HTTPException(status_code=503, detail="Repair approval is unavailable") from error


@app.post("/api/repairs/{request_id}/reject")
def reject_repair_request(request_id: str, request: RepairRejectionRequest):
    try:
        return RepairWorkflow().reject(request_id, request.approver, request.reason, request.token)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Failed to reject repair request")
        raise HTTPException(status_code=503, detail="Repair storage is unavailable") from error


class RepairManualReviewRequest(BaseModel):
    disposition: Literal["confirmed", "closed_no_retry"]
    note: str
    token: str


@app.post("/api/repairs/{request_id}/manual-review")
def record_repair_manual_review(request_id: str, request: RepairManualReviewRequest):
    try:
        return RepairWorkflow().record_manual_review(
            request_id, request.disposition, request.note, request.token
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("Failed to record manual repair review")
        raise HTTPException(status_code=503, detail="Repair storage is unavailable") from error


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.APP_HOST, port=8000)
