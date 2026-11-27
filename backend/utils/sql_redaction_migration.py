"""Idempotently redact query fields in persisted operational JSON records."""
from psycopg2 import sql
from psycopg2.extras import Json

from .sql_redaction import redact_query_data


JSON_RECORD_TABLES = (
    ("audit_records", "audit_id", ("evidence", "ai_analysis", "knowledge_refs")),
    ("repair_requests", "request_id", ("parameters", "evidence", "result", "finding")),
    ("repair_request_events", "event_id", ("event_data",)),
    (
        "operational_memory_cases", "case_id",
        ("evidence", "execution_result", "verification_result"),
    ),
)


def sanitize_json_fields(field_names, values):
    sanitized = {
        name: redact_query_data(value, redact_literals=True)
        for name, value in zip(field_names, values)
    }
    changed = any(sanitized[name] != value for name, value in zip(field_names, values))
    return sanitized, changed


def redact_persisted_query_literals(store, *, apply=False, batch_size=500):
    """Scan supported metadata tables in bounded batches and optionally update rows."""
    batch_size = max(1, min(int(batch_size), 5000))
    totals = {
        "tables_scanned": 0,
        "rows_scanned": 0,
        "rows_would_change": 0,
        "rows_updated": 0,
        "concurrent_changes": 0,
        "missing_tables": [],
    }

    for table_name, primary_key, candidate_fields in JSON_RECORD_TABLES:
        with store.conn, store.conn.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s)", (table_name,))
            if cursor.fetchone()[0] is None:
                totals["missing_tables"].append(table_name)
                continue
            cursor.execute(
                "SELECT attname FROM pg_catalog.pg_attribute "
                "WHERE attrelid=to_regclass(%s) AND attnum > 0 AND NOT attisdropped",
                (table_name,),
            )
            existing_columns = {row[0] for row in cursor.fetchall()}
        fields = tuple(name for name in candidate_fields if name in existing_columns)
        if not fields:
            continue

        totals["tables_scanned"] += 1
        last_key = None
        while True:
            selected_columns = sql.SQL(", ").join(
                [sql.Identifier(primary_key), *(sql.Identifier(name) for name in fields)]
            )
            query = sql.SQL("SELECT {} FROM {} ").format(
                selected_columns, sql.Identifier(table_name)
            )
            parameters = []
            if last_key is not None:
                query += sql.SQL("WHERE {} > %s ").format(sql.Identifier(primary_key))
                parameters.append(last_key)
            query += sql.SQL("ORDER BY {} LIMIT %s").format(sql.Identifier(primary_key))
            parameters.append(batch_size)

            with store.conn, store.conn.cursor() as cursor:
                cursor.execute(query, tuple(parameters))
                rows = cursor.fetchall()
                if not rows:
                    break
                last_key = rows[-1][0]
                totals["rows_scanned"] += len(rows)
                for row in rows:
                    record_key, values = row[0], row[1:]
                    sanitized, changed = sanitize_json_fields(fields, values)
                    if not changed:
                        continue
                    totals["rows_would_change"] += 1
                    if not apply:
                        continue

                    assignments = sql.SQL(", ").join(
                        sql.SQL("{}=%s::jsonb").format(sql.Identifier(name))
                        for name in fields
                        if sanitized[name] != values[fields.index(name)]
                    )
                    changed_fields = tuple(
                        name for name in fields
                        if sanitized[name] != values[fields.index(name)]
                    )
                    conditions = [sql.SQL("{}=%s").format(sql.Identifier(primary_key))]
                    update_parameters = [
                        Json(sanitized[name]) for name in changed_fields
                    ]
                    update_parameters.append(record_key)
                    for name in changed_fields:
                        value = values[fields.index(name)]
                        if value is None:
                            conditions.append(sql.SQL("{} IS NULL").format(sql.Identifier(name)))
                        else:
                            conditions.append(
                                sql.SQL("{} IS NOT DISTINCT FROM %s::jsonb").format(
                                    sql.Identifier(name)
                                )
                            )
                            update_parameters.append(Json(value))
                    cursor.execute(
                        sql.SQL("UPDATE {} SET {} WHERE {}").format(
                            sql.Identifier(table_name), assignments,
                            sql.SQL(" AND ").join(conditions),
                        ),
                        tuple(update_parameters),
                    )
                    if cursor.rowcount:
                        totals["rows_updated"] += 1
                    else:
                        totals["concurrent_changes"] += 1

    return totals
