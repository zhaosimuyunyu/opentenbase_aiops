"""Verify independent pgvector store with one fixed official-source document."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from backend.ai.embedding_client import EmbeddingClient
from backend.ai.knowledge_base_pgvector import PgVectorKnowledgeBase

content = "OpenTenBase is a distributed database with GTM, CN and DN components. Diagnose lock waits with pg_locks and pg_stat_activity. A read-only audit must capture the waiting session, blocking session, node and query start time."
embedding = EmbeddingClient()
vectors = embedding.embed_batch([content])
kb = PgVectorKnowledgeBase()
doc = kb.add_document("OpenTenBase lock-wait audit", content, vectors, "official_doc", "https://github.com/OpenTenBase/OpenTenBase", "repository-head-verified-2026-11-22")
query = "How do I audit a blocked session and find the blocking query?"
hits = kb.search(embedding.embed_text(query), 3)
assert hits and hits[0]["source_url"].startswith("https://github.com/OpenTenBase")
print({"document_id": doc, "hits": len(hits), "top_similarity": round(float(hits[0]["similarity"]), 3), "source": hits[0]["source_url"]})
kb.close()
