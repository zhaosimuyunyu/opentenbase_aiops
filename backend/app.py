"""FastAPI application (optional REST API)"""
import asyncio
import json
import os
import socket
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, Literal, Optional

from .utils.config import Config
from .utils.db_connector import OpenTenBaseConnector
from .utils.logger import setup_logger
from .utils.distributed_collector import DistributedCollector
from .collectors.cluster import ClusterCollector
from .collectors.performance import PerformanceCollector
from .ai.llm_client import DeepSeekClient
from .ai.agent_client import AIOpsAgent
from .engines.readonly_audit_engine import ReadonlyAuditEngine
from .utils.operations_store import OperationsStore
from .utils.operational_memory import OperationalMemory
from .utils.audit_status import normalize_audit_record
from .utils.readiness import build_readiness
from .utils.latency_metrics import scheduled_analysis_latency_metrics
from psycopg2.extras import Json, RealDictCursor
from .engines.repair_workflow import RepairWorkflow, has_repair_identity
from .engines.health_audit_scheduler import HealthAuditScheduler
from .engines.sql_audit import audit_sql
from .engines.audit_reanalysis import reanalyze_persisted_audit
from .engines.alert_tasks import AlertTaskStore
from .engines.agent_turns import AgentTurnStore, ensure_agent_sessions as _ensure_agent_sessions
from .capabilities import CAPABILITIES

logger = setup_logger(__name__)
config = Config()
distributed_collector = DistributedCollector(config)
health_audit_scheduler = HealthAuditScheduler(config)
agent_turn_tasks = set()
agent_worker_id = os.getenv("AIOPS_INSTANCE_ID") or socket.gethostname()


@asynccontextmanager
async def lifespan(_app):
    scheduler_task = None
    try:
        interrupted = await asyncio.to_thread(
            AlertTaskStore().mark_interrupted, agent_worker_id
        )
        if interrupted:
            logger.warning("Marked %s interrupted alert audit task(s) after service startup", interrupted)
    except Exception:
        logger.exception("Failed to recover alert audit task state")
    try:
        interrupted = await asyncio.to_thread(
            AgentTurnStore().mark_interrupted, agent_worker_id
        )
        if interrupted:
            logger.warning("Marked %s interrupted Agent turn(s) after service startup", interrupted)
    except Exception:
        logger.exception("Failed to recover Agent turn state")
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
llm_client = None


def get_llm_client():
    global llm_client
    if llm_client is None:
        llm_client = DeepSeekClient(config)
    return llm_client


class QuestionRequest(BaseModel):
    question: str
    include_context: bool = True
    history: list[dict[str, str]] = Field(default_factory=list)
    session_id: Optional[str] = None
    turn_id: Optional[str] = None


class AgentSessionRequest(BaseModel):
    session_id: str
    title: str = "新会话"
    messages: list[dict[str, Any]] = Field(default_factory=list)


@app.get("/api/agent/sessions")
def list_agent_sessions():
    store = OperationsStore()
    try:
        with store.conn, store.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            _ensure_agent_sessions(cursor)
            cursor.execute("SELECT session_id,title,messages,updated_at FROM agent_sessions ORDER BY updated_at DESC")
            return {"items": [dict(row) for row in cursor.fetchall()]}
    finally:
        store.close()


@app.get("/api/agent/turns")
def list_agent_turns(session_id: str, limit: int = 20):
    return {"items": AgentTurnStore().list_for_session(session_id, max(1, min(limit, 100)))}


@app.get("/api/agent/turns/{turn_id}")
def get_agent_turn(turn_id: str):
    turn = AgentTurnStore().get(turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Agent turn not found")
    return turn


@app.get("/api/agent/turns/{turn_id}/stream")
async def stream_agent_turn(turn_id: str):
    async def stream():
        yield f'data: {json.dumps({"type": "progress", "stage": "starting", "turn_id": turn_id}, ensure_ascii=False)}\n\n'
        while True:
            turn = await asyncio.to_thread(AgentTurnStore().get, turn_id)
            if turn is None:
                yield f'data: {json.dumps({"type": "error", "message": "Agent turn not found"})}\n\n'
                return
            if turn["status"] == "completed":
                yield f'data: {json.dumps({"type": "result", "turn_id": turn_id, "answer": turn["answer"] or "", "tool_trace": turn["tool_trace"] or [], "rounds": turn["rounds"] or 0}, ensure_ascii=False, default=str)}\n\n'
                return
            if turn["status"] != "running":
                yield f'data: {json.dumps({"type": "error", "turn_id": turn_id, "status": turn["status"], "message": turn["error_type"] or turn["status"]}, ensure_ascii=False)}\n\n'
                return
            yield f'data: {json.dumps({"type": "progress", "stage": "running", "turn_id": turn_id, "message": "Agent 仍在后台处理"}, ensure_ascii=False)}\n\n'
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.put("/api/agent/sessions/{session_id}")
def save_agent_session(session_id: str, request: AgentSessionRequest):
    if session_id != request.session_id:
        raise HTTPException(status_code=400, detail="Session ID mismatch")
    store = OperationsStore()
    try:
        with store.conn, store.conn.cursor() as cursor:
            _ensure_agent_sessions(cursor)
            cursor.execute("""
                INSERT INTO agent_sessions(session_id,title,messages,updated_at)
                VALUES(%s,%s,%s,now())
                ON CONFLICT(session_id) DO UPDATE SET title=EXCLUDED.title,
                    messages=EXCLUDED.messages, updated_at=now()
            """, (session_id, request.title, Json(request.messages)))
        return {"session_id": session_id, "saved": True}
    finally:
        store.close()


@app.delete("/api/agent/sessions/{session_id}")
def delete_agent_session(session_id: str):
    try:
        AgentTurnStore().delete_session(session_id)
        return {"session_id": session_id, "deleted": True}
    except Exception as error:
        logger.exception("Failed to delete Agent session")
        raise HTTPException(status_code=503, detail="Could not delete Agent session") from error


class MemoryCaseRequest(BaseModel):
    category: str
    symptoms: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    root_cause: Optional[str] = None
    solution: Optional[str] = None
    execution_result: Optional[dict[str, Any]] = None
    verification_result: Optional[dict[str, Any]] = None
    effectiveness: Optional[float] = None


@app.get("/api/memory/cases")
def recall_memory_cases(category: Optional[str] = None, query: Optional[str] = None, limit: int = 10):
    memory = OperationalMemory()
    try:
        return {"items": memory.recall(category=category, query=query, limit=limit)}
    finally:
        memory.close()


@app.post("/api/memory/cases")
def save_memory_case(request: MemoryCaseRequest):
    memory = OperationalMemory()
    try:
        case_id = memory.save_case(**request.model_dump())
        return {"case_id": case_id, "saved": True}
    finally:
        memory.close()


class DiagnosisRequest(BaseModel):
    description: str


class SqlAuditRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)
    explain: bool = True


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
    operation: Literal["analyze_table", "cancel_query"] = "analyze_table"
    parameters: Dict[str, Any] = Field(default_factory=dict)


class AlertmanagerRequest(BaseModel):
    status: str = "firing"
    groupKey: str = ""
    alerts: list[dict] = Field(default_factory=list)


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
    """Report whether required database dependencies can serve requests."""
    database_status = db_connector.test_connection()
    metadata_status = {"connected": False}
    metadata_store = None
    try:
        metadata_store = OperationsStore(connect_timeout=2)
        with metadata_store.conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        metadata_status = {"connected": True}
    except Exception as error:
        metadata_status["error"] = type(error).__name__
        logger.warning("Metadata database readiness check failed: %s", type(error).__name__)
    finally:
        if metadata_store is not None:
            metadata_store.close()

    readiness = build_readiness(database_status, metadata_status)
    return JSONResponse(
        readiness,
        status_code=200 if readiness["status"] == "ready" else 503,
    )


@app.get("/api/capabilities")
async def capabilities():
    """Expose the verified operation boundary to agents and orchestrators."""
    return CAPABILITIES


@app.get("/api/cluster/status")
async def get_cluster_status(all_nodes: bool = Query(False, description="Collect from all nodes in cluster")):
    """Get cluster status with optional distributed collection"""
    try:
        result = cluster_collector.collect()

        if all_nodes and config.AIOPS_DISTRIBUTED_ENABLED:
            result['data']['distributed_collection'] = distributed_collector.collect_diagnostics(
                check_names=["database_info", "connections", "replication"]
            )

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
    """Run a multi-turn live AIOps agent with database, diagnostics and knowledge tools."""
    agent = AIOpsAgent(config)
    try:
        result = await asyncio.to_thread(
            lambda: asyncio.run(agent.chat(request.question, request.history))
        )
        return {"question": request.question, **result}
    except Exception as e:
        logger.error(f"Failed to answer question: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        agent.client.close()


@app.post("/api/qa/ask/stream")
async def stream_question(request: QuestionRequest):
    """Run a durable Agent turn and stream progress without tying it to the client."""
    events = asyncio.Queue()
    loop = asyncio.get_running_loop()
    turn_store = AgentTurnStore()
    try:
        turn = await asyncio.to_thread(
            turn_store.start, request.session_id, request.turn_id,
            request.question, agent_worker_id,
        )
    except Exception as error:
        logger.exception("Failed to create Agent turn")
        raise HTTPException(status_code=503, detail="Could not persist Agent turn") from error
    turn_id = turn["turn_id"]
    if not turn["created"]:
        raise HTTPException(status_code=409, detail="Agent turn ID already exists")

    async def run_agent():
        agent = AIOpsAgent(config)

        def publish(event):
            loop.call_soon_threadsafe(events.put_nowait, event)

        try:
            await events.put({"type": "progress", "stage": "thinking", "message": "Agent 正在理解问题"})
            result = await asyncio.to_thread(
                lambda: asyncio.run(
                    agent.chat(request.question, request.history, event_callback=publish)
                )
            )
            trace = result.get("tool_trace") or []
            await asyncio.to_thread(turn_store.complete, turn_id, result)
            await events.put({"type": "result", "answer": result.get("answer", ""),
                              "tool_trace": trace, "rounds": result.get("rounds", 0),
                              "runtime_context": result.get("runtime_context"),
                              "turn_id": turn_id})
        except Exception as error:
            logger.exception("Failed to stream Agent answer")
            try:
                await asyncio.to_thread(turn_store.fail, turn_id, type(error).__name__)
            except Exception:
                logger.exception("Failed to persist Agent turn failure")
            await events.put({
                "type": "error", "turn_id": turn_id,
                "message": f"{type(error).__name__}: {error}",
            })
        finally:
            agent.client.close()

    async def stream():
        task = asyncio.create_task(run_agent())
        agent_turn_tasks.add(task)
        task.add_done_callback(agent_turn_tasks.discard)
        yield f'data: {json.dumps({"type": "progress", "stage": "starting", "message": "已连接 Agent", "turn_id": turn_id}, ensure_ascii=False)}\n\n'
        while True:
            try:
                event = await asyncio.wait_for(events.get(), timeout=10)
            except asyncio.TimeoutError:
                yield ': keepalive\n\n'
                continue
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            if event["type"] in {"result", "error"}:
                await task
                return

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/diagnosis")
async def diagnose_issue(request: DiagnosisRequest):
    """Diagnose database issue"""
    try:
        # Collect cluster and performance data
        cluster_data = cluster_collector.collect().get('data', {})
        performance_data = performance_collector.collect().get('data', {})

        # Use AI to diagnose
        diagnosis = get_llm_client().diagnose_issue(
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


@app.post("/api/sql-audit")
def run_sql_audit(request: SqlAuditRequest):
    """Classify SQL risk and optionally run a read-only EXPLAIN."""
    try:
        return audit_sql(request.sql, explain=request.explain, config=config)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("SQL audit failed")
        raise HTTPException(status_code=503, detail="SQL audit is unavailable") from error


@app.get("/api/health-report")
async def get_health_report():
    """Generate AI-powered health report"""
    try:
        cluster_data = cluster_collector.collect().get('data', {})
        performance_data = performance_collector.collect().get('data', {})

        report = get_llm_client().generate_health_summary(
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


@app.get("/api/distributed/nodes")
async def get_distributed_nodes():
    """Collect fixed read-only diagnostics from registered CN/DN nodes."""
    try:
        if not config.AIOPS_DISTRIBUTED_ENABLED:
            raise HTTPException(status_code=403, detail="Distributed collection is disabled")
        return distributed_collector.collect_diagnostics()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cluster nodes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/distributed/collect")
async def distributed_collect(
    node_filter: Optional[Literal["C", "D"]] = Query(None),
    check: Optional[list[Literal[
        "database_info", "connections", "max_connections", "replication",
        "prepared_transactions", "locks", "long_running_queries", "idle_transactions",
        "table_stats", "index_usage", "key_guc", "storage",
    ]]] = Query(None),
):
    """Run selected built-in read-only checks on CN/DN nodes."""
    try:
        if not config.AIOPS_DISTRIBUTED_ENABLED:
            raise HTTPException(status_code=403, detail="Distributed collection is disabled")

        return distributed_collector.collect_diagnostics(node_filter, check)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Distributed collection failed: {e}")
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
        repair_readiness = RepairWorkflow(config).readiness()
        kb = OperationsStore()
        with kb.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT to_regclass('public.audit_records') AS audit_table")
            audit_table_exists = cursor.fetchone()["audit_table"] is not None
            latest = None
            latest_by_scope = {}
            latest_scheduled_at = None
            latest_scheduled_collection_status = None
            scheduled_targets = []
            scheduled_analysis_latency = {
                "sample_count": 0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
            }
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
                               evidence->>'collection_duration_ms' AS collection_duration_ms,
                               evidence->>'analysis_duration_ms' AS analysis_duration_ms,
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
                cursor.execute("""
                    SELECT count(*) AS sample_count,
                           percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
                           percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms
                    FROM (
                        SELECT (evidence->>'analysis_duration_ms')::double precision AS duration_ms
                        FROM audit_records
                        WHERE audit_type='readonly_health_audit'
                          AND evidence->>'trigger'='scheduled'
                          AND evidence->'audit_target'=%s::jsonb
                          AND evidence->>'analysis_duration_ms' ~ '^[0-9]+([.][0-9]+)?$'
                        ORDER BY created_at DESC, audit_id DESC
                        LIMIT 20
                    ) AS recent_scheduled_audits
                """, (Json(config.audit_target),))
                latency = cursor.fetchone()
                scheduled_analysis_latency = {
                    "sample_count": latency["sample_count"] or 0,
                    "p50_ms": float(latency["p50_ms"] or 0),
                    "p95_ms": float(latency["p95_ms"] or 0),
                }
                if scheduled_targets and all(row["created_at"] for row in scheduled_targets):
                    latest_scheduled_at = min(row["created_at"] for row in scheduled_targets)
                statuses = {row["collection_status"] for row in scheduled_targets}
                latest_scheduled_collection_status = next(
                    (value for value in ("error", "partial", "success") if value in statuses), None
                )
        return {
            "automatic_health_audit_enabled": config.AIOPS_AUTO_AUDIT_ENABLED,
            "repair_executor_ready": repair_readiness.get("executor_ready", False),
            "automatic_repair_ready": bool(
                config.AIOPS_AUTO_REPAIR_ENABLED and repair_readiness.get("ready")
            ),
            "repair_readiness": repair_readiness,
            "automatic_repair_enabled": config.AIOPS_AUTO_REPAIR_ENABLED,
            "automatic_repair_targets": list(config.AIOPS_AUTO_REPAIR_TARGETS),
            "repair_function_enabled": config.AIOPS_REPAIR_FUNCTION_ENABLED,
            "cancel_query_enabled": config.AIOPS_CANCEL_QUERY_ENABLED,
            "cancel_query_executor_ready": bool(
                config.AIOPS_CANCEL_QUERY_ENABLED
                and config.AIOPS_REPAIR_DB_USER
                and config.AIOPS_REPAIR_DB_PASSWORD
                and config.AIOPS_REPAIR_DB_USER != config.DB_USER
            ),
            "cancel_query_executor_status": (
                "ready_for_runtime_probe"
                if config.AIOPS_CANCEL_QUERY_ENABLED
                and config.AIOPS_REPAIR_DB_USER
                and config.AIOPS_REPAIR_DB_PASSWORD
                and config.AIOPS_REPAIR_DB_USER != config.DB_USER
                else "disabled_or_repair_account_missing"
            ),
            "repair_function": (
                f"{config.AIOPS_REPAIR_FUNCTION_SCHEMA}."
                f"{config.AIOPS_REPAIR_FUNCTION_NAME}"
            ),
            "interval_seconds": config.AIOPS_AUTO_AUDIT_INTERVAL_SECONDS,
            "statistics_target": config.AIOPS_AUTO_AUDIT_TABLE,
            "latest_audit": dict(latest) if latest else None,
            "latest_audits_by_scope": latest_by_scope,
            "latest_scheduled_at": latest_scheduled_at,
            "latest_scheduled_collection_status": latest_scheduled_collection_status,
            "scheduled_targets": scheduled_targets,
            "scheduled_analysis_latency": scheduled_analysis_latency,
            "scheduler_runtime": health_audit_scheduler.runtime_status(),
            "repair_review_count": repair_review_count,
        }
    except Exception as error:
        logger.exception("Failed to read automation status")
        raise HTTPException(status_code=503, detail="Automation status is unavailable") from error
    finally:
        if kb is not None:
            kb.close()


@app.post("/api/alerts", status_code=202)
async def receive_alertmanager_alert(request: AlertmanagerRequest):
    """Start a bounded read-only Agent audit from an Alertmanager webhook."""
    if request.status == "resolved" or not request.alerts:
        return {"accepted": False, "reason": "No active alerts to audit"}
    allowed_fields = {"alertname", "severity", "instance", "job", "summary", "description"}
    labels = []
    for alert in request.alerts:
        values = {**(alert.get("labels") or {}), **(alert.get("annotations") or {})}
        labels.append({
            key: str(value)[:500]
            for key, value in values.items()
            if key in allowed_fields and value is not None
        })
    target = next((item.get("table") for item in labels if item.get("table")), None)
    task_store = AlertTaskStore()
    task_id = task_store.create(request.status, labels, target, agent_worker_id)

    async def run_alert_audit():
        try:
            result = await health_audit_scheduler.run_once(
                table=target, trigger="alertmanager", trigger_context={
                    "group_key": request.groupKey[:200], "alerts": labels,
                },
            )
            task_store.finish(
                task_id, status="completed" if result else "busy", result=result
            )
        except Exception as error:
            logger.exception("Alert-triggered audit failed")
            task_store.finish(task_id, status="failed", error_type=type(error).__name__)

    asyncio.create_task(run_alert_audit())
    return {"accepted": True, "task_id": task_id, "target": target}


@app.get("/api/alerts/{task_id}")
def get_alert_task(task_id: str):
    task = AlertTaskStore().get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Alert task not found")
    return task


@app.get("/metrics", response_class=PlainTextResponse)
def audit_metrics():
    status = get_automation_status()
    latest = status["latest_audit"]
    scheduled = status["latest_scheduled_at"]
    scheduler_runtime = status["scheduler_runtime"]
    risk = latest["risk_level"] if latest else None
    levels = ("low", "medium", "high", "critical", "unknown")
    if latest and risk not in levels:
        risk = "unknown"
    metrics = [
        "# TYPE aiops_health_audit_schedule_enabled gauge",
        f"aiops_health_audit_schedule_enabled {int(status['automatic_health_audit_enabled'])}",
        "# TYPE aiops_health_audit_scheduler_running gauge",
        f"aiops_health_audit_scheduler_running {int(scheduler_runtime['state'] == 'running')}",
        "# TYPE aiops_health_audit_scheduler_consecutive_failures gauge",
        f"aiops_health_audit_scheduler_consecutive_failures {scheduler_runtime['consecutive_failures']}",
        "# TYPE aiops_health_audit_scheduler_started_timestamp_seconds gauge",
        f"aiops_health_audit_scheduler_started_timestamp_seconds {datetime.fromisoformat(scheduler_runtime['started_at']).timestamp() if scheduler_runtime['started_at'] else 0}",
        "# TYPE aiops_health_audit_scheduler_next_retry_timestamp_seconds gauge",
        f"aiops_health_audit_scheduler_next_retry_timestamp_seconds {datetime.fromisoformat(scheduler_runtime['next_retry_at']).timestamp() if scheduler_runtime['next_retry_at'] else 0}",
        "# TYPE aiops_health_audit_interval_seconds gauge",
        f"aiops_health_audit_interval_seconds {status['interval_seconds']}",
        "# TYPE aiops_health_audit_latest_timestamp_seconds gauge",
        f"aiops_health_audit_latest_timestamp_seconds {latest['created_at'].timestamp() if latest else 0}",
        "# TYPE aiops_health_audit_latest_scheduled_timestamp_seconds gauge",
        f"aiops_health_audit_latest_scheduled_timestamp_seconds {scheduled.timestamp() if scheduled else 0}",
        "# TYPE aiops_health_audit_latest_collection_duration_ms gauge",
        f"aiops_health_audit_latest_collection_duration_ms {float(latest['collection_duration_ms']) if latest and latest.get('collection_duration_ms') else 0}",
        "# TYPE aiops_health_audit_latest_analysis_duration_ms gauge",
        f"aiops_health_audit_latest_analysis_duration_ms {float(latest['analysis_duration_ms']) if latest and latest.get('analysis_duration_ms') else 0}",
        "# TYPE aiops_health_audit_latest_risk gauge",
    ]
    metrics.extend(scheduled_analysis_latency_metrics(status["scheduled_analysis_latency"]))
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
            records = [normalize_audit_record(row) for row in cursor.fetchall()]
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
        return normalize_audit_record(record)
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Failed to read audit")
        raise HTTPException(status_code=503, detail="Audit record is unavailable") from error
    finally:
        if kb is not None:
            kb.close()


@app.post("/api/audits/{audit_id}/reanalyze")
async def reanalyze_audit(audit_id: str):
    """Retry AI analysis from persisted read-only evidence without recollecting or executing SQL."""
    try:
        return await reanalyze_persisted_audit(audit_id)
    except HTTPException:
        raise
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        logger.exception("Failed to reanalyze audit")
        raise HTTPException(status_code=503, detail="Audit reanalysis is unavailable") from error


@app.post("/api/audits/{audit_id}/repair-requests")
def create_repair_from_audit(audit_id: str, request: RepairProposalRequest):
    """Create a supported repair proposal from a persisted audit finding."""
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
        evidence = finding.get("evidence") or {}
        if request.operation == "analyze_table":
            if finding.get("check") != "stale_table_statistics":
                raise HTTPException(status_code=400, detail="Selected audit finding is not eligible for ANALYZE")
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
            parameters = {"table": table}
        elif request.operation == "cancel_query":
            if finding.get("check") != "data_node_lock_waits":
                raise HTTPException(status_code=400, detail="Selected audit finding has no per-data-node blocker identity")
            parameters = request.parameters
        else:
            raise HTTPException(status_code=400, detail="Operation is not enabled for execution")
        return RepairWorkflow().create_request(
            request.operation, parameters,
            {
                "proposal_source": request.operation,
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


@app.get("/api/repairs/{request_id}/events")
def list_repair_events(request_id: str, limit: int = 200):
    try:
        return {"items": RepairWorkflow().list_events(request_id, limit)}
    except Exception as error:
        logger.exception("Failed to list repair request events")
        raise HTTPException(status_code=503, detail="Repair event storage is unavailable") from error


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
