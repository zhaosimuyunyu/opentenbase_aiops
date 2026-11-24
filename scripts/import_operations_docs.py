"""Import versioned OpenTenBase operations references into pgvector."""
import hashlib
import json
import sys
import time
from pathlib import Path

import requests
from psycopg2.errors import DeadlockDetected

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ai.embedding_client import EmbeddingClient
from backend.ai.knowledge_base_pgvector import PgVectorKnowledgeBase

COMMIT = "b2b129b35b58855ea0017650ab2abce192a4d93c"
DOCS_COMMIT = "4eaeba90188926ddf4da23b74775cdf150ffdfe8"
SOURCES = {
    "doc/src/sgml/runtime.sgml": "Server setup and operation",
    "doc/src/sgml/config.sgml": "Server configuration",
    "doc/src/sgml/maintenance.sgml": "Routine database maintenance",
    "doc/src/sgml/backup.sgml": "Backup and restore",
    "doc/src/sgml/high-availability.sgml": "High availability and replication",
    "doc/src/sgml/perform.sgml": "Query performance and EXPLAIN",
    "doc/src/sgml/indices.sgml": "Indexes",
    "doc/src/sgml/client-auth.sgml": "Client authentication",
    "doc/src/sgml/user-manag.sgml": "Database roles",
    "doc/src/sgml/diskusage.sgml": "Disk usage",
    "doc/src/sgml/pgstatstatements.sgml": "Query statistics",
    "doc/src/sgml/catalogs.sgml": "System catalogs and views",
    "doc/src/sgml/monitoring.sgml": "Monitoring database activity and statistics",
    "doc/src/sgml/pgxcmonitor.sgml": "OpenTenBase node availability monitor utility",
    "doc/src/sgml/auto-explain.sgml": "Automatic query plan logging",
    "doc/src/sgml/generic-wal.sgml": "Write ahead logging",
    "doc/src/sgml/pgrowlocks.sgml": "Row lock inspection",
    "contrib/pg_unlock/pg_unlock--1.0.sql": "pg_unlock extension function definitions and default privileges",
}
TOPICS = {
    "doc/src/sgml/catalogs.sgml": ["pg_locks", "pg_stat_activity", "pg_blocking_pids", "pg_prepared_xacts", "lock wait", "锁等待"],
    "doc/src/sgml/monitoring.sgml": ["pg_stat_activity", "pg_locks", "pg_stat_replication", "wait_event", "monitoring", "监控"],
    "doc/src/sgml/pgxcmonitor.sgml": ["pgxc_monitor", "node availability", "GTM", "CN", "DN"],
    "contrib/pg_unlock/pg_unlock--1.0.sql": ["pg_unlock", "distributed deadlock", "privilege", "permission", "死锁", "权限"],
    "doc/src/sgml/mvcc.sgml": ["transactionid", "row lock", "deadlock", "concurrency", "事务锁", "行锁", "死锁"],
    "doc/src/sgml/pgstatstatements.sgml": ["pg_stat_statements", "slow query", "query statistics", "慢查询"],
    "doc/src/sgml/generic-wal.sgml": ["wal", "write ahead log", "checkpoint", "预写日志"],
    "doc/src/sgml/pgrowlocks.sgml": ["pgrowlocks", "row lock", "行锁"],
    "doc/src/sgml/auto-explain.sgml": ["auto_explain", "query plan", "explain", "执行计划"],
}
GUIDES = (
    "01-quickstart", "02-access", "03-basic-use", "04-advanced-use",
    "05-component", "06-switching", "07-user-rights", "08-data-dump-restore",
    "09-problem-performance", "10-pg_clean", "11-pg_unlock",
    "12-opentenbase_subscription", "13-opentenbase_monitoring",
    "14-kubeblocks-support", "15-docker-deploy", "23-opentenbase_ai",
)
ENGLISH_GUIDES = (
    "01-quickstart", "02-access", "03-basic-use", "07-user-rights",
    "11-pg_unlock", "13-opentenbase_monitoring", "14-kubeblocks-support",
    "15-docker-deploy", "23-opentenbase_ai",
)
SITE_REFERENCES = (
    "faq.md", "faq.en.md",
    "guide/usecase/FAST_DDL.md", "guide/usecase/Flashback.md",
    "guide/usecase/Parallel_Copy_DDL.md", "guide/usecase/RETURNING.md",
    "guide/usecase/Thread_poll.md", "guide/usecase/column_compression.md",
    "release/v2-2-0.md", "release/v2-2-0.en.md", "release/v2-3-0.md",
    "release/v2-4-0.md", "release/v2-4-0.en.md",
    "release/v2-5-0.md", "release/v2-5-0.en.md",
    "release/v2-6-0.md", "release/v2-6-0.en.md",
)


def import_source(kb, embedding, repository, commit, path, title, category="official_doc"):
    url = f"https://raw.githubusercontent.com/OpenTenBase/{repository}/{commit}/{path}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    content = response.content.decode("utf-8")
    chunks = kb._chunks(content)
    if not chunks:
        raise ValueError("Empty source")
    digest = hashlib.sha256(response.content).hexdigest()
    topics = TOPICS.get(path, [])
    query = """SELECT c.content, vector_dims(c.embedding), c.metadata
               FROM knowledge_documents d JOIN knowledge_chunks c USING(document_id)
               WHERE d.digest=%s AND d.source_url=%s AND d.version=%s
               ORDER BY c.chunk_index"""
    expected_metadata = {"source_url": url, "version": commit}
    if topics:
        expected_metadata["topics"] = topics
    expected = [
        (chunk, embedding.dimension, expected_metadata)
        for chunk in chunks
    ]
    with kb.conn, kb.conn.cursor() as cursor:
        cursor.execute(query, (digest, url, commit))
        if cursor.fetchall() == expected:
            return "verified existing", len(chunks)

    vectors = []
    for start in range(0, len(chunks), 24):
        batch = chunks[start:start + 24]
        embedded = embedding.embed_batch(batch)
        if len(embedded) != len(batch) or not all(embedded):
            raise RuntimeError(f"Embedding batch failed at chunk {start}")
        vectors.extend(embedded)
    kb.add_document(title, content, vectors, category, url, commit)
    if topics:
        for attempt in range(3):
            try:
                with kb.conn, kb.conn.cursor() as cursor:
                    cursor.execute(
                        """UPDATE knowledge_chunks
                           SET metadata = metadata || %s::jsonb
                           WHERE document_id = (
                               SELECT document_id FROM knowledge_documents WHERE digest=%s
                           ) AND metadata->'topics' IS DISTINCT FROM %s::jsonb""",
                        (json.dumps({"topics": topics}), digest, json.dumps(topics)),
                    )
                break
            except DeadlockDetected:
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))
    with kb.conn, kb.conn.cursor() as cursor:
        cursor.execute(query, (digest, url, commit))
        if cursor.fetchall() != expected:
            raise RuntimeError("Stored chunks or source metadata do not match")
    return "imported and verified", len(chunks)


def main():
    embedding = EmbeddingClient()
    kb = PgVectorKnowledgeBase()
    failures = 0
    sources = [
        ("OpenTenBase", COMMIT, path, f"OpenTenBase official reference - {title}",
         "official_source" if path.startswith("contrib/") else "official_doc")
        for path, title in SOURCES.items()
    ]
    for guide, suffix in [(name, ".md") for name in GUIDES] + [
        (name, ".en.md") for name in ENGLISH_GUIDES
    ]:
        sources.append(("docs", DOCS_COMMIT, f"docs/guide/{guide}{suffix}",
                        f"OpenTenBase official guide - {guide}{suffix}", "official_doc"))
    sources.extend(
        ("docs", DOCS_COMMIT, f"docs/{path}", f"OpenTenBase official reference - {path}", "official_doc")
        for path in SITE_REFERENCES
    )
    try:
        for repository, commit, path, title, category in sources:
            try:
                status, count = import_source(kb, embedding, repository, commit, path, title, category)
                print(f"{status}: {path} ({count} chunks)", flush=True)
            except (requests.RequestException, ValueError, RuntimeError) as error:
                failures += 1
                print(f"failed: {path}: {error}", file=sys.stderr, flush=True)
    finally:
        kb.close()
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
