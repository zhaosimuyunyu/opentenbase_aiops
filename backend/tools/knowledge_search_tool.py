import time
from typing import Optional, Dict, Any
from ..ai.embedding_client import EmbeddingClient
from ..ai.knowledge_base_pgvector import PgVectorKnowledgeBase

TOOL_SCHEMA={"type":"function","function":{"name":"search_knowledge","description":"Search all imported OpenTenBase documentation, source-code references, troubleshooting guides, performance notes and local operations knowledge. Searches every category by default. An optional category is only a preference because the tool falls back to all categories when it returns no hits.","parameters":{"type":"object","properties":{"query":{"type":"string"},"category":{"type":"string","description":"Optional preferred category. Any category value is accepted. Omit to search all categories."},"top_k":{"type":"integer","default":8}},"required":["query"]}}}
async def execute_search_knowledge(query:str, category:Optional[str]=None, top_k:int=8)->Dict[str,Any]:
    started = time.monotonic()
    emb = EmbeddingClient()
    kb = PgVectorKnowledgeBase(statement_timeout_ms=5000, initialize=False)
    try:
        vector = emb.embed_text(query)
        if vector is None:
            raise RuntimeError("Knowledge search embedding failed")
        hits = kb.search(vector, max(1, min(top_k, 100)), category=category, query=query)
        fallback_used = bool(category and not hits)
        if fallback_used:
            hits = kb.search(vector, max(1, min(top_k, 100)), category=None, query=query)
        return {"hits":len(hits),"requested_category":category,"category_fallback_to_all":fallback_used,"results":[{"content":h["content"],"source_url":h["source_url"],"version":h["version"],"category":h["category"],"similarity":float(h["similarity"]),"document_title":h["title"]} for h in hits],"search_time_ms":int((time.monotonic()-started)*1000)}
    finally: kb.close()
