"""Read recent slow-statement records from OpenTenBase CSV logs."""
import csv
from datetime import datetime, timedelta
import io
import re

import psycopg2
from psycopg2.extras import RealDictCursor
from ..utils.sql_redaction import query_fingerprint, redact_sql_literals


LOG_FILE_QUERY = """
    WITH settings AS (
        SELECT current_setting('data_directory') AS data_directory,
               current_setting('log_directory') AS log_directory
    ), log_path AS (
        SELECT CASE WHEN left(log_directory, 1) = '/' THEN log_directory
                    ELSE data_directory || '/' || log_directory END AS path
        FROM settings
    ), files AS (
        SELECT file, path, pg_catalog.pg_stat_file(path || '/' || file) AS stat
        FROM log_path, LATERAL pg_catalog.pg_ls_dir(path) AS file
        WHERE file LIKE 'postgresql-%%' AND file LIKE '%%.csv'
    ), recent_files AS (
        SELECT file, path, (stat).size AS file_size,
               (stat).modification AS modified_at
        FROM files
        ORDER BY (stat).modification DESC
        LIMIT %s
    )
    SELECT file,
           pg_catalog.pg_read_file(
               path || '/' || file,
               greatest(file_size - %s::bigint, 0),
               least(file_size, %s::bigint)
           ) AS contents,
           modified_at,
           file_size > %s::bigint AS partial_file
    FROM recent_files
    ORDER BY modified_at DESC
"""

SLOW_MESSAGE = re.compile(
    r"^duration:\s*([0-9]+(?:\.[0-9]+)?)\s*ms\s+statement:\s*(.*)$",
    re.DOTALL,
)
LOG_RECORD_START = re.compile(
    r"(?m)^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)? \w+,"
)
LOG_READ_BYTES = 8 * 1024 * 1024


def _parse_log_time(value, timezone):
    value = value.rsplit(" ", 1)[0]
    for pattern in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone)
        except ValueError:
            continue
    return None


def parse_slow_query_csv(
    contents, *, node_name, reference_time, lookback_seconds,
    source_file=None, partial_file=False, redact_literals=True,
):
    if partial_file:
        first_record = LOG_RECORD_START.search(contents)
        contents = contents[first_record.start():] if first_record else ""
    cutoff = reference_time - timedelta(seconds=lookback_seconds)
    slow_queries = []
    for record in csv.reader(io.StringIO(contents)):
        if len(record) < 27:
            continue
        match = SLOW_MESSAGE.match(record[17])
        if not match:
            continue
        logged_at = _parse_log_time(record[0], reference_time.tzinfo)
        if logged_at is None or logged_at < cutoff:
            continue
        raw_query = match.group(2).strip()
        if not raw_query:
            continue
        query = raw_query
        fingerprint = query_fingerprint(raw_query)
        if redact_literals:
            query, fingerprint = redact_sql_literals(raw_query)
        slow_queries.append({
            "node_name": node_name,
            "pid": int(record[4]) if record[4].isdigit() else None,
            "user": record[2] or None,
            "database": record[3] or None,
            "application_name": record[26] or None,
            "command_tag": record[11] or None,
            "duration_ms": float(match.group(1)),
            "logged_at": logged_at,
            "query": query,
            "query_fingerprint": fingerprint,
            "query_redacted": redact_literals,
            "source": "server_csv_log",
            "source_file": source_file,
        })
    return slow_queries


class SlowQueryLogCollector:
    def __init__(self, config, *, max_log_files=2):
        self.config = config
        self.max_log_files = max_log_files

    def collect(self, nodes):
        slow_queries = []
        errors = {}
        for node in nodes:
            if node.get("node_type") not in {"C", "D"}:
                continue
            name = node.get("node_name")
            connection = None
            try:
                connection = psycopg2.connect(
                    host=node["node_host"],
                    port=node["node_port"],
                    dbname=self.config.DB_NAME,
                    user=self.config.DB_USER,
                    password=self.config.DB_PASSWORD,
                    application_name="aiops-slow-query-log-collector",
                    connect_timeout=5,
                )
                connection.set_session(readonly=True, autocommit=False)
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '5000ms'")
                    cursor.execute("SET LOCAL lock_timeout = '1000ms'")
                    cursor.execute("SELECT now() AS reference_time")
                    reference_time = cursor.fetchone()["reference_time"]
                    lookback_seconds = self.config.AIOPS_SLOW_QUERY_LOG_LOOKBACK_SECONDS
                    since_time = reference_time - timedelta(seconds=lookback_seconds)
                    cursor.execute(
                        LOG_FILE_QUERY,
                        (self.max_log_files, LOG_READ_BYTES, LOG_READ_BYTES, LOG_READ_BYTES),
                    )
                    node_queries = []
                    for log_file in cursor.fetchall():
                        node_queries.extend(parse_slow_query_csv(
                            log_file["contents"],
                            node_name=name,
                            reference_time=reference_time,
                            lookback_seconds=lookback_seconds,
                            source_file=log_file["file"],
                            partial_file=log_file["partial_file"],
                            redact_literals=getattr(
                                self.config, "AIOPS_SLOW_QUERY_REDACT_LITERALS", True
                            ),
                        ))
                    slow_queries.extend(
                        query for query in node_queries
                        if query["logged_at"] >= since_time
                    )
                connection.rollback()
            except Exception as error:
                errors[f"slow_query_logs:{name}"] = {
                    "type": type(error).__name__,
                    "message": str(error).strip(),
                    "sqlstate": getattr(error, "pgcode", None),
                }
                if connection is not None and not connection.closed:
                    connection.rollback()
            finally:
                if connection is not None:
                    connection.close()

        unique = {}
        for query in slow_queries:
            key = (
                query["node_name"], query["pid"], query["logged_at"],
                query.get("query_fingerprint", query["query"]),
            )
            existing = unique.get(key)
            if existing is None or (
                existing.get("application_name") is None
                and query.get("application_name") is not None
            ):
                unique[key] = query
        ordered = sorted(
            unique.values(), key=lambda query: query["logged_at"], reverse=True
        )
        return ordered[:200], errors
