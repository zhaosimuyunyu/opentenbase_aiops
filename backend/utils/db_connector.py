"""OpenTenBase database connector"""
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
from .config import Config
from .logger import setup_logger

logger = setup_logger(__name__)


class OpenTenBaseConnector:
    """OpenTenBase database connection manager"""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self._connection = None

    def connect(self) -> psycopg2.extensions.connection:
        """Establish database connection"""
        try:
            if self._connection is None or self._connection.closed:
                self._connection = psycopg2.connect(
                    host=self.config.DB_HOST,
                    port=self.config.DB_PORT,
                    user=self.config.DB_USER,
                    password=self.config.DB_PASSWORD,
                    database=self.config.DB_NAME,
                    connect_timeout=10
                )
                logger.info(
                    f"Connected to OpenTenBase at {self.config.DB_HOST}:"
                    f"{self.config.DB_PORT}"
                )
            return self._connection
        except Exception as e:
            logger.error(f"Failed to connect to OpenTenBase: {e}")
            raise

    def close(self):
        """Close database connection"""
        if self._connection and not self._connection.closed:
            self._connection.close()
            logger.info("Database connection closed")

    @contextmanager
    def get_cursor(self, dict_cursor: bool = True):
        """Get database cursor with context manager"""
        conn = self.connect()
        cursor_factory = RealDictCursor if dict_cursor else None
        cursor = conn.cursor(cursor_factory=cursor_factory)
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            cursor.close()

    def execute_query(
        self,
        sql: str,
        params: Optional[tuple] = None,
        fetch_one: bool = False
    ) -> Optional[List[Dict[str, Any]]]:
        """Execute SELECT query and return results"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(sql, params)
                if fetch_one:
                    return cursor.fetchone()
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            return None

    def execute_readonly(
        self,
        sql: str,
        timeout: int = 5
    ) -> Optional[List[Dict[str, Any]]]:
        """Execute read-only query with timeout"""
        readonly_sql = f"""
        BEGIN READ ONLY;
        SET LOCAL statement_timeout='{timeout}s';
        {sql}
        COMMIT;
        """
        return self.execute_query(readonly_sql)

    def test_connection(self) -> Dict[str, Any]:
        """Test database connection and return status"""
        try:
            result = self.execute_query(
                "SELECT version(), current_database(), current_user",
                fetch_one=True
            )
            return {
                'status': 'success',
                'connected': True,
                'version': result.get('version', 'unknown') if result else 'unknown',
                'database': result.get('current_database', 'unknown') if result else 'unknown',
                'user': result.get('current_user', 'unknown') if result else 'unknown'
            }
        except Exception as e:
            return {
                'status': 'error',
                'connected': False,
                'error': str(e)
            }
