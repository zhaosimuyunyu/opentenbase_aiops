#!/usr/bin/env python3
"""Live retrieval regressions against the configured embedding API and pgvector store."""
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.tools.knowledge_search_tool import execute_search_knowledge
CASES = (
 ("pg_locks pg_stat_activity transactionid blocking", ("catalogs.sgml",)),
 ("OpenTenBase pg_stat_statements slow query", ("pgstatstatements.sgml",)),
 ("OpenTenBase WAL write ahead log checkpoint", ("generic-wal.sgml",)),
 ("OpenTenBase pgrowlocks row lock", ("pgrowlocks.sgml",)),
 ("OpenTenBase auto_explain query plan", ("auto-explain.sgml",)),
 ("OpenTenBase FAST_DDL fast add column", ("FAST_DDL.md",)),
 ("OpenTenBase Flashback restore", ("Flashback.md",)),
 ("OpenTenBase pg_dump backup restore", ("backup.sgml", "08-data-dump-restore.md")),
 ("OpenTenBase distributed deadlock pg_unlock dependency", ("11-pg_unlock.md", "11-pg_unlock.en.md")),
 ("OpenTenBase Prometheus postgres_exporter monitoring", ("13-opentenbase_monitoring.md", "13-opentenbase_monitoring.en.md")),
 ("OpenTenBase pgxc_monitor check GTM CN DN node availability", ("pgxcmonitor.sgml",)),
)
async def main():
 for query, expected_paths in CASES:
  result=await execute_search_knowledge(query,category="official_doc",top_k=3)
  assert result["hits"], query
  top=result["results"][0]
  assert any(path in top["source_url"] for path in expected_paths), (query,top["source_url"])
  assert top["version"]
  print(f"PASS {query}: {top['document_title']} ({top['similarity']:.3f})")
 source_query = "pg_unlock_execute pg_unlock_killbypid PUBLIC permissions terminate transaction"
 source_result = await execute_search_knowledge(
  source_query, category="official_source", top_k=3
 )
 assert source_result["hits"], source_query
 source_top = source_result["results"][0]
 assert "pg_unlock--1.0.sql" in source_top["source_url"], source_top["source_url"]
 print(f"PASS {source_query}: {source_top['document_title']} ({source_top['similarity']:.3f})")
if __name__=="__main__": asyncio.run(main())
