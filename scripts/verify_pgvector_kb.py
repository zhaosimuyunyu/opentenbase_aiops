"""Verify semantic retrieval from the indexed OpenTenBase source corpus."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ai.embedding_client import EmbeddingClient
from backend.ai.knowledge_base_pgvector import PgVectorKnowledgeBase

PINNED_SOURCE = re.compile(
    r"https://raw\.githubusercontent\.com/OpenTenBase/(?:OpenTenBase|docs)/([0-9a-f]{40})/.+"
)


def main():
    query = "How do I use pg_locks and pg_stat_activity to diagnose blocking queries?"
    vector = EmbeddingClient().embed_text(query)
    if not vector:
        raise SystemExit("Embedding request failed")
    kb = PgVectorKnowledgeBase()
    try:
        kb.conn.set_session(readonly=True)
        hits = kb.search(vector, top_k=5, query=query, log_retrieval=False)
    finally:
        kb.close()
    for hit in hits:
        source = PINNED_SOURCE.fullmatch(hit.get("source_url") or "")
        if source and source[1] == hit.get("version"):
            print({"hits": len(hits), "similarity": round(float(hit["similarity"]), 3),
                   "source": hit["source_url"]})
            return
    raise SystemExit("No commit-pinned OpenTenBase source found in the top five results")


if __name__ == "__main__":
    main()
