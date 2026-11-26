"""Durable state and transcript persistence for interactive Agent turns."""
import uuid

from psycopg2.extras import Json, RealDictCursor

from ..utils.operations_store import OperationsStore


def ensure_agent_sessions(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_sessions(
            session_id text PRIMARY KEY,
            title text NOT NULL,
            messages jsonb NOT NULL DEFAULT '[]'::jsonb,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def _ensure_agent_turns(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_turns(
            turn_id text PRIMARY KEY,
            session_id text,
            question text NOT NULL,
            status text NOT NULL,
            answer text,
            tool_trace jsonb,
            rounds integer,
            error_type text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)


class AgentTurnStore:
    def start(self, session_id, turn_id, question):
        turn_id = turn_id or str(uuid.uuid4())
        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                ensure_agent_sessions(cursor)
                _ensure_agent_turns(cursor)
                cursor.execute(
                    "SELECT status FROM agent_turns WHERE turn_id=%s FOR UPDATE",
                    (turn_id,),
                )
                existing = cursor.fetchone()
                if existing:
                    return {"turn_id": turn_id, "status": existing[0], "created": False}

                if session_id:
                    cursor.execute(
                        "SELECT title,messages FROM agent_sessions WHERE session_id=%s FOR UPDATE",
                        (session_id,),
                    )
                    session = cursor.fetchone()
                    title = question[:24] or "新会话"
                    messages = []
                    if session:
                        title, messages = session
                    messages = messages or []
                    if not any(
                        message.get("turn_id") == turn_id
                        for message in messages if isinstance(message, dict)
                    ):
                        messages = [
                            *messages,
                            {"role": "user", "content": question, "turn_id": turn_id},
                        ]
                    if session:
                        cursor.execute(
                            """UPDATE agent_sessions SET title=%s,messages=%s,updated_at=now()
                               WHERE session_id=%s""",
                            (title, Json(messages), session_id),
                        )
                    else:
                        cursor.execute(
                            """INSERT INTO agent_sessions(session_id,title,messages)
                               VALUES(%s,%s,%s)""",
                            (session_id, title, Json(messages)),
                        )

                cursor.execute("""
                    INSERT INTO agent_turns(turn_id,session_id,question,status)
                    VALUES(%s,%s,%s,'running')
                """, (turn_id, session_id, question))
            return {"turn_id": turn_id, "status": "running", "created": True}
        finally:
            store.close()

    def complete(self, turn_id, result):
        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                _ensure_agent_turns(cursor)
                cursor.execute(
                    "SELECT session_id,status FROM agent_turns WHERE turn_id=%s FOR UPDATE",
                    (turn_id,),
                )
                row = cursor.fetchone()
                if not row or row[1] != "running":
                    return False
                session_id = row[0]
                trace = result.get("tool_trace") or []
                if session_id:
                    ensure_agent_sessions(cursor)
                    message = {
                        "role": "assistant",
                        "content": result.get("answer", ""),
                        "tool_calls": trace,
                        "turn_id": turn_id,
                    }
                    cursor.execute("""
                        UPDATE agent_sessions
                        SET messages=messages || %s, updated_at=now()
                        WHERE session_id=%s
                    """, (Json([message]), session_id))
                cursor.execute("""
                    UPDATE agent_turns
                    SET status='completed',answer=%s,tool_trace=%s,rounds=%s,updated_at=now()
                    WHERE turn_id=%s AND status='running'
                """, (result.get("answer", ""), Json(trace), result.get("rounds", 0), turn_id))
            return True
        finally:
            store.close()

    def fail(self, turn_id, error_type):
        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                _ensure_agent_turns(cursor)
                cursor.execute("""
                    UPDATE agent_turns SET status='failed',error_type=%s,updated_at=now()
                    WHERE turn_id=%s AND status='running'
                """, (error_type, turn_id))
        finally:
            store.close()

    def get(self, turn_id):
        store = OperationsStore()
        try:
            with store.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT to_regclass('public.agent_turns') AS turn_table")
                if cursor.fetchone()["turn_table"] is None:
                    return None
                cursor.execute("""
                    SELECT turn_id,session_id,question,status,answer,tool_trace,rounds,
                           error_type,created_at,updated_at
                    FROM agent_turns WHERE turn_id=%s
                """, (turn_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        finally:
            store.close()

    def list_for_session(self, session_id, limit=20):
        store = OperationsStore()
        try:
            with store.conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT to_regclass('public.agent_turns') AS turn_table")
                if cursor.fetchone()["turn_table"] is None:
                    return []
                cursor.execute("""
                    SELECT turn_id,question,status,error_type,created_at,updated_at
                    FROM agent_turns WHERE session_id=%s
                    ORDER BY created_at DESC LIMIT %s
                """, (session_id, limit))
                return [dict(row) for row in cursor.fetchall()]
        finally:
            store.close()

    def delete_session(self, session_id):
        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                ensure_agent_sessions(cursor)
                cursor.execute("SELECT to_regclass('public.agent_turns')")
                if cursor.fetchone()[0] is not None:
                    cursor.execute("DELETE FROM agent_turns WHERE session_id=%s", (session_id,))
                cursor.execute("DELETE FROM agent_sessions WHERE session_id=%s", (session_id,))
        finally:
            store.close()

    def mark_interrupted(self):
        store = OperationsStore()
        try:
            with store.conn, store.conn.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.agent_turns')")
                if cursor.fetchone()[0] is None:
                    return 0
                cursor.execute("""
                    UPDATE agent_turns
                    SET status='interrupted',error_type='ServiceRestart',updated_at=now()
                    WHERE status='running'
                """)
                return cursor.rowcount
        finally:
            store.close()
