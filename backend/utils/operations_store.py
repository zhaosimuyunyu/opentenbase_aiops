"""PostgreSQL connection for operational records and knowledge storage."""
import os
import time

import psycopg2


class OperationsStore:
    def __init__(self, connect_timeout=5):
        settings = dict(
            host=os.getenv("KNOWLEDGE_DB_HOST", "knowledge-db"),
            port=int(os.getenv("KNOWLEDGE_DB_PORT", "5432")),
            dbname=os.getenv("KNOWLEDGE_DB_NAME", "aiops_knowledge"),
            user=os.getenv("KNOWLEDGE_DB_USER", "aiops_knowledge"),
            password=os.getenv("KNOWLEDGE_DB_PASSWORD", "aiops-local-dev-only"),
            connect_timeout=connect_timeout,
        )
        for attempt in range(3):
            try:
                self.conn = psycopg2.connect(**settings)
                break
            except psycopg2.OperationalError as error:
                if attempt == 2 or "Temporary failure in name resolution" not in str(error):
                    raise
                time.sleep(attempt + 1)

    def close(self):
        self.conn.close()
