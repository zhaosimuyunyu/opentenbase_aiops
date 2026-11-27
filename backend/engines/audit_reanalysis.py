import json

from ..utils.operations_store import OperationsStore
from ..utils.config import Config
from ..utils.sql_redaction import redact_query_data
from .readonly_audit_engine import ReadonlyAuditEngine


def _risk_floor(evidence):
    ranks = {"unknown": 0, "low": 0, "medium": 1, "high": 2, "critical": 3}
    return max(
        (ranks.get(str(item.get("severity", "unknown")).lower(), 0)
         for item in evidence.get("findings", [])),
        default=0,
    )


async def reanalyze_persisted_audit(audit_id, store_factory=OperationsStore, engine_factory=ReadonlyAuditEngine):
    store = store_factory()
    try:
        with store.conn.cursor() as cursor:
            cursor.execute("SELECT evidence FROM audit_records WHERE audit_id=%s", (audit_id,))
            record = cursor.fetchone()
        if record is None:
            raise LookupError("Audit not found")
        evidence = record["evidence"] if isinstance(record, dict) else record[0]
        evidence = redact_query_data(
            evidence or {},
            redact_literals=Config.AIOPS_SLOW_QUERY_REDACT_LITERALS,
        )
        issue = (
            "重新分析已持久化的 OpenTenBase 只读健康审计证据。"
            "只能基于证据给出根因和只读建议，不得执行写操作。"
        )
        analysis = await engine_factory._diagnose(issue, evidence)
        structured = analysis.get("structured") or {}
        risk_level = str(structured.get("risk_level") or "unknown").strip().lower()
        risk_level = {
            "低": "low", "中": "medium", "中等": "medium",
            "高": "high", "严重": "critical",
        }.get(risk_level, risk_level)
        if risk_level not in {"low", "medium", "high", "critical"}:
            risk_level = "unknown"
        risk_floor = _risk_floor(evidence)
        ranks = {"unknown": 0, "low": 0, "medium": 1, "high": 2, "critical": 3}
        if ranks[risk_level] < risk_floor:
            risk_level = next(level for level, rank in ranks.items() if rank == risk_floor)
        with store.conn, store.conn.cursor() as cursor:
            cursor.execute(
                "UPDATE audit_records SET ai_analysis=%s, knowledge_refs=%s, risk_level=%s "
                "WHERE audit_id=%s",
                (json.dumps(analysis, default=str),
                 json.dumps(analysis.get("knowledge_refs", []), default=str),
                 risk_level, audit_id),
            )
        return {"audit_id": audit_id, "risk_level": risk_level, **analysis}
    finally:
        store.close()
