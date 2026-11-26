"""PostgreSQL connection for operational records and knowledge storage."""
import os

import psycopg2


class OperationsStore:
    def __init__(self, connect_timeout=5):
        self.conn = psycopg2.connect(
            host=os.getenv("KNOWLEDGE_DB_HOST", "knowledge-db"),
            port=int(os.getenv("KNOWLEDGE_DB_PORT", "5432")),
            dbname=os.getenv("KNOWLEDGE_DB_NAME", "aiops_knowledge"),
            user=os.getenv("KNOWLEDGE_DB_USER", "aiops_knowledge"),
            password=os.getenv("KNOWLEDGE_DB_PASSWORD", "aiops-local-dev-only"),
            connect_timeout=connect_timeout,
        )

    def close(self):
        self.conn.close()
