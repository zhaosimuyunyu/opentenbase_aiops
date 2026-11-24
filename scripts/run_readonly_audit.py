"""Real read-only audit: collect lock evidence from OpenTenBase and cite KB."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from backend.utils.db_connector import OpenTenBaseConnector
from backend.ai.embedding_client import EmbeddingClient
from backend.ai.knowledge_base_pgvector import PgVectorKnowledgeBase

db=OpenTenBaseConnector()
rows=db.execute_query("""SELECT l.pid, l.granted, l.mode, l.relation::text relation,
 a.query, a.query_start FROM pg_locks l LEFT JOIN pg_stat_activity a ON a.pid=l.pid
 WHERE l.pid IS NOT NULL ORDER BY l.granted LIMIT 100""") or []
blocked=[r for r in rows if not r.get('granted')]
query="How should an OpenTenBase audit investigate lock waits and identify the blocking query?"
emb=EmbeddingClient(); kb=PgVectorKnowledgeBase(); hits=kb.search(emb.embed_text(query),3)
result={"audit_type":"readonly_lock_audit","evidence":{"lock_rows":len(rows),"blocked_rows":len(blocked),"blocked":blocked},"knowledge":hits}
print(json.dumps(result, ensure_ascii=False, default=str))
assert hits and all("source_url" in h for h in hits)
kb.close(); db.close()
