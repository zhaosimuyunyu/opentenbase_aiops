import time
from typing import Optional, Dict, Any
from ..ai.embedding_client import EmbeddingClient
from ..ai.knowledge_base_pgvector import PgVectorKnowledgeBase

TOOL_SCHEMA={"type":"function","function":{"name":"search_knowledge","description":"Search OpenTenBase official documentation, source-code references, and troubleshooting guides. Prefer category official_doc unless the user specifically requests implementation details or local troubleshooting material.","parameters":{"type":"object","properties":{"query":{"type":"string"},"category":{"type":"string","enum":["official_doc","official_source","troubleshooting","performance","distributed"],"default":"official_doc"},"top_k":{"type":"integer","default":5}},"required":["query"]}}}
async def execute_search_knowledge(query:str, category:Optional[str]="official_doc", top_k:int=5)->Dict[str,Any]:
    started = time.monotonic()
    emb = EmbeddingClient()
    kb = PgVectorKnowledgeBase(statement_timeout_ms=5000, initialize=False)
    try:
        vector = emb.embed_text(query)
        if vector is None:
            raise RuntimeError("Knowledge search embedding failed")
        hits = kb.search(vector, max(1, min(top_k, 20)), category=category, query=query)
        return {"hits":len(hits),"results":[{"content":h["content"],"source_url":h["source_url"],"version":h["version"],"category":h["category"],"similarity":float(h["similarity"]),"document_title":h["title"]} for h in hits],"search_time_ms":int((time.monotonic()-started)*1000)}
    finally: kb.close()
