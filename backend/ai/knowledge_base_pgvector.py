"""Independent PostgreSQL/pgvector knowledge store."""
import hashlib, uuid, re, math
from typing import Any
from psycopg2.extras import Json
from ..utils.operations_store import OperationsStore

class PgVectorKnowledgeBase(OperationsStore):
    def __init__(self, *, statement_timeout_ms: int | None = None):
        super().__init__()
        try:
            with self.conn, self.conn.cursor() as cur:
                if statement_timeout_ms is not None:
                    cur.execute(
                        "SELECT set_config('statement_timeout', %s, false), "
                        "set_config('lock_timeout', '1000ms', false)",
                        (str(statement_timeout_ms),),
                    )
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute("""CREATE TABLE IF NOT EXISTS knowledge_documents(
                    document_id text primary key, title text not null, content text not null,
                    digest text unique not null, category text, source_url text, version text,
                    created_at timestamptz default now())""")
                cur.execute("""CREATE TABLE IF NOT EXISTS knowledge_chunks(
                    chunk_id text primary key, document_id text references knowledge_documents on delete cascade,
                    chunk_index int not null, content text not null, embedding vector(1024) not null,
                    metadata jsonb, unique(document_id, chunk_index))""")
                cur.execute("CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_hnsw ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)")
                cur.execute("""CREATE TABLE IF NOT EXISTS knowledge_retrieval_log(
                    retrieval_id text primary key, query text not null, results jsonb, created_at timestamptz default now())""")
        except Exception:
            self.conn.close()
            raise

    def add_document(self, title: str, content: str, embeddings: list[list[float]], category: str, source_url: str, version: str) -> str:
        digest = hashlib.sha256(content.encode()).hexdigest()
        with self.conn, self.conn.cursor() as cur:
            cur.execute("SELECT document_id FROM knowledge_documents WHERE digest=%s", (digest,))
            row = cur.fetchone()
            doc_id = row[0] if row else str(uuid.uuid4())
            if not row:
                cur.execute("INSERT INTO knowledge_documents VALUES(%s,%s,%s,%s,%s,%s,%s)", (doc_id,title,content,digest,category,source_url,version))
            for i, (text, vector) in enumerate(zip(self._chunks(content), embeddings)):
                cur.execute("""INSERT INTO knowledge_chunks VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(document_id,chunk_index) DO UPDATE SET content=excluded.content,embedding=excluded.embedding""",
                    (str(uuid.uuid4()), doc_id, i, text, vector, Json({"source_url":source_url,"version":version})))
        return doc_id

    @staticmethod
    def _chunks(text: str, size: int = 700) -> list[str]:
        return [text[i:i+size].strip() for i in range(0, len(text), size-100) if text[i:i+size].strip()]

    def search(self, query_vector: list[float], top_k: int = 5, *,
               category: str | None = None, query: str = "") -> list[dict[str, Any]]:
        candidate_count = max(top_k, min(top_k * 100, 1000))
        with self.conn, self.conn.cursor() as cur:
            cur.execute("""SELECT d.document_id,d.title,c.content,d.category,d.source_url,d.version,c.metadata,
                1-(c.embedding <=> %s::vector) similarity FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.document_id=c.document_id
                WHERE (%s::text IS NULL OR d.category = %s)
                ORDER BY 1-(c.embedding <=> %s::vector) + CASE
                    WHEN d.source_url LIKE '%%/docs/guide/usecase/%%'
                    AND strpos(
                        ' ' || regexp_replace(lower(%s), '[^[:alnum:]]+', ' ', 'g') || ' ',
                        ' ' || regexp_replace(lower(split_part(
                            split_part(d.source_url, '/usecase/', 2), '.', 1
                        )), '[^[:alnum:]]+', ' ', 'g') || ' '
                    ) > 0 THEN 0.20 ELSE 0 END DESC
                LIMIT %s""",
                (query_vector, category, category, query_vector, query, candidate_count))
            cols=[x[0] for x in cur.description]; rows=[dict(zip(cols,r)) for r in cur.fetchall()]
            if query and rows:
                terms = [term for term in re.split(r"[^a-z0-9_]+", query.lower()) if len(term) > 2]
                texts = [(row["title"] + " " + row["content"]).lower() for row in rows]
                document_frequencies = {
                    term: sum(term in text for text in texts) for term in terms
                }
                for row, haystack in zip(rows, texts):
                    row["_lexical"] = sum(
                        math.log((len(rows) + 1) / (document_frequencies[term] + 1)) + 1
                        for term in terms if term in haystack
                    )
                    tags = [tag.lower() for tag in (row["metadata"] or {}).get("topics", [])]
                    normalized_query = query.lower()
                    row["_lexical"] += 2 * sum(tag in normalized_query for tag in tags)
                rows.sort(key=lambda row: (row["_lexical"], row["similarity"]), reverse=True)
                unique_rows = []
                seen_documents = set()
                for row in rows:
                    if row["document_id"] not in seen_documents:
                        seen_documents.add(row["document_id"])
                        unique_rows.append(row)
                    row.pop("_lexical", None)
                    row.pop("metadata", None)
                    row.pop("document_id", None)
                rows = unique_rows[:top_k]
            else:
                for row in rows:
                    row.pop("document_id", None)
                    row.pop("metadata", None)
            cur.execute("INSERT INTO knowledge_retrieval_log VALUES(%s,%s,%s)", (str(uuid.uuid4()),query,Json(rows)))
            return rows
