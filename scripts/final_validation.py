#!/usr/bin/env python3
import asyncio, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.engines.readonly_audit_engine import ReadonlyAuditEngine
from backend.ai.knowledge_base_pgvector import PgVectorKnowledgeBase
async def main():
    print('OpenTenBase AIOps final validation')
    result=await ReadonlyAuditEngine().run_lock_audit()
    audit_id=result.get('audit_id'); refs=result.get('knowledge_refs') or []
    checks={'audit_id':bool(audit_id),'lock_evidence':isinstance(result.get('locks'),list),'tool_called':bool(result.get('tool_called')),'ai_analysis':bool(result.get('analysis')),'knowledge_refs':bool(refs),'references_have_source':all(r.get('source_url') and r.get('version') for r in refs),'references_have_similarity':all(r.get('similarity') is not None for r in refs)}
    print(json.dumps({'audit_id':audit_id,'blocked_locks':result.get('blocked_locks'),'analysis':result.get('analysis'),'knowledge_refs':refs,'checks':checks},ensure_ascii=False,indent=2,default=str))
    kb=PgVectorKnowledgeBase()
    try:
        with kb.conn.cursor() as cur:
            cur.execute('SELECT audit_id,evidence,ai_analysis,knowledge_refs,risk_level,status FROM audit_records WHERE audit_id=%s',(audit_id,)); row=cur.fetchone()
    finally: kb.close()
    checks['audit_persisted']=row is not None
    if row:
        checks.update({'persisted_evidence':bool(row[1]),'persisted_ai_analysis':bool(row[2]),'persisted_knowledge_refs':bool(row[3])})
        print(json.dumps({'persisted':{'audit_id':row[0],'risk_level':row[4],'status':row[5],'knowledge_ref_count':len(row[3] or [])}},ensure_ascii=False,indent=2,default=str))
    ok=all(checks.values()); print('FINAL_VALIDATION='+('PASS' if ok else 'FAIL')); print(json.dumps(checks,ensure_ascii=False,indent=2)); return 0 if ok else 1
if __name__=='__main__': raise SystemExit(asyncio.run(main()))
