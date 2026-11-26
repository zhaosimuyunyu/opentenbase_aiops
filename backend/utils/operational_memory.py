"""Persistent, outcome-aware operational memory.

Memory lives in the metadata database so it does not depend on the target
OpenTenBase schema. A case may be stored before verification, but its
effectiveness is only updated from an observed postcondition.
"""
import json
import uuid

from .operations_store import OperationsStore
from psycopg2.extras import RealDictCursor


class OperationalMemory:
    def __init__(self):
        self.store = OperationsStore()
        with self.store.conn, self.store.conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS operational_memory_cases(
                    case_id text PRIMARY KEY,
                    category text NOT NULL,
                    symptoms text NOT NULL,
                    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
                    root_cause text,
                    solution text,
                    execution_result jsonb,
                    verification_result jsonb,
                    effectiveness numeric CHECK(effectiveness IS NULL OR (effectiveness >= 0 AND effectiveness <= 1)),
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_operational_memory_category_time
                ON operational_memory_cases(category, updated_at DESC)
            """)

    def close(self):
        self.store.close()

    def save_case(self, *, category, symptoms, evidence=None, root_cause=None,
                  solution=None, execution_result=None, verification_result=None,
                  effectiveness=None, case_id=None):
        case_id = case_id or str(uuid.uuid4())
        with self.store.conn, self.store.conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO operational_memory_cases(
                    case_id,category,symptoms,evidence,root_cause,solution,
                    execution_result,verification_result,effectiveness,updated_at
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT(case_id) DO UPDATE SET
                    evidence=EXCLUDED.evidence, root_cause=EXCLUDED.root_cause,
                    solution=EXCLUDED.solution, execution_result=EXCLUDED.execution_result,
                    verification_result=EXCLUDED.verification_result,
                    effectiveness=EXCLUDED.effectiveness, updated_at=now()
            """, (
                case_id, category, symptoms, json.dumps(evidence or {}, default=str),
                root_cause, solution, json.dumps(execution_result, default=str) if execution_result is not None else None,
                json.dumps(verification_result, default=str) if verification_result is not None else None,
                effectiveness,
            ))
        return case_id

    def recall(self, *, category=None, query=None, limit=10):
        clauses = []
        params = []
        if category:
            clauses.append("category=%s")
            params.append(category)
        if query:
            clauses.append("(symptoms ILIKE %s OR root_cause ILIKE %s OR solution ILIKE %s)")
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 50)))
        with self.store.conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                f"SELECT case_id,category,symptoms,evidence,root_cause,solution,"
                f"execution_result,verification_result,effectiveness,created_at,updated_at "
                f"FROM operational_memory_cases{where} ORDER BY updated_at DESC LIMIT %s",
                tuple(params),
            )
            return [dict(row) for row in cursor.fetchall()]
