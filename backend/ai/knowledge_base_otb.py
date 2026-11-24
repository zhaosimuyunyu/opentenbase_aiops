"""Knowledge Base Management - OpenTenBase Compatible"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import hashlib
import uuid
from psycopg2.extras import Json
from ..utils.logger import setup_logger
from ..utils.db_connector import OpenTenBaseConnector
from .embedding_client import EmbeddingClient

logger = setup_logger(__name__)


class KnowledgeBase:
    """
    Knowledge Base Manager - OpenTenBase Compatible

    Key changes for OpenTenBase:
    - All tables use DISTRIBUTE BY SHARD or REPLICATION
    - Use TEXT UUID instead of SERIAL for primary keys
    - Fixed-size FLOAT8[1024] array for vectors
    """

    def __init__(self, db_connector: OpenTenBaseConnector, embedding_client: EmbeddingClient):
        self.db = db_connector
        self.embedding = embedding_client
        self._ensure_schema()

    def _ensure_schema(self):
        """Create knowledge base tables (OpenTenBase compatible)"""

        schema_sql = """
        -- Knowledge entities (distributed by entity_id)
        CREATE TABLE IF NOT EXISTS knowledge_entities (
            entity_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            content_digest TEXT NOT NULL,
            category TEXT,
            source_url TEXT,
            version TEXT,
            published_at TIMESTAMPTZ DEFAULT NOW(),
            created_at TIMESTAMPTZ DEFAULT NOW()
        ) DISTRIBUTE BY SHARD(entity_id) TO GROUP default_group;

        -- Vector embeddings (distributed by entity_id for co-location)
        CREATE TABLE IF NOT EXISTS knowledge_embeddings (
            embedding_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            chunk_index INT NOT NULL,
            chunk_text TEXT NOT NULL,
            embedding_vector FLOAT8[1024],
            metadata JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (entity_id, chunk_index),
            UNIQUE(entity_id, embedding_id)
        ) DISTRIBUTE BY SHARD(entity_id) TO GROUP default_group;

        -- Retrieval log (replicated for audit)
        CREATE TABLE IF NOT EXISTS knowledge_retrieval_log (
            log_id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            results TEXT[],
            retrieval_time_ms INT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        ) DISTRIBUTE BY REPLICATION TO GROUP default_group;

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge_entities(category);
        CREATE INDEX IF NOT EXISTS idx_knowledge_published ON knowledge_entities(published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_embeddings_entity ON knowledge_embeddings(entity_id);
        """

        try:
            with self.db.get_cursor(dict_cursor=False) as cursor:
                cursor.execute(schema_sql)
            logger.info("Knowledge base schema created successfully")
        except Exception as e:
            logger.error(f"Failed to create schema: {e}")
            raise

    def add_document(
        self,
        title: str,
        content: str,
        category: str,
        source_url: Optional[str] = None,
        version: Optional[str] = None,
        chunk_size: int = 500
    ) -> Optional[str]:
        """Add document to knowledge base"""
        try:
            # Generate IDs
            entity_id = str(uuid.uuid4())
            content_digest = hashlib.sha256(content.encode()).hexdigest()

            # Check duplicate
            existing = self.db.execute_query(
                "SELECT entity_id FROM knowledge_entities WHERE content_digest = %s",
                (content_digest,),
                fetch_one=True
            )

            if existing:
                entity_id = existing['entity_id']
            else:
                inserted = self.db.execute_query("""
                    INSERT INTO knowledge_entities
                    (entity_id, title, content, content_digest, category, source_url, version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING entity_id
                """, (entity_id, title, content, content_digest, category, source_url, version), fetch_one=True)
                if inserted is None:
                    return None

            # Chunk and embed
            chunks = self._chunk_text(content, chunk_size)
            self._embed_chunks(entity_id, chunks)

            logger.info(f"Added document: {entity_id} with {len(chunks)} chunks")
            return entity_id

        except Exception as e:
            logger.error(f"Failed to add document: {e}")
            return None

    def _chunk_text(self, text: str, chunk_size: int = 500) -> List[str]:
        """Split text into chunks"""
        chunks = []
        overlap = 100

        for i in range(0, len(text), chunk_size - overlap):
            chunk = text[i:i + chunk_size]
            if chunk.strip():
                chunks.append(chunk.strip())

        return chunks

    def _embed_chunks(self, entity_id: str, chunks: List[str]):
        """Generate embeddings for chunks and store"""
        embeddings = self.embedding.embed_batch(chunks)

        if not chunks or len(embeddings) != len(chunks) or any(v is None for v in embeddings):
            raise ValueError("Could not generate all document embeddings")
        with self.db.get_cursor() as cursor:
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                cursor.execute("""
                    INSERT INTO knowledge_embeddings
                    (embedding_id, entity_id, chunk_index, chunk_text, embedding_vector, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (entity_id, chunk_index) DO UPDATE
                    SET chunk_text = EXCLUDED.chunk_text,
                        embedding_vector = EXCLUDED.embedding_vector,
                        metadata = EXCLUDED.metadata
                """, (
                    str(uuid.uuid4()),
                    entity_id,
                    i,
                    chunk,
                    embedding,
                    Json({'length': len(chunk)})
                ))

    def search(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Semantic search in knowledge base"""
        start_time = datetime.now()

        try:
            # Generate query embedding
            query_embedding = self.embedding.embed_text(query)
            if not query_embedding:
                logger.error("Failed to generate query embedding")
                return []

            # Retrieve embeddings
            sql = """
                SELECT
                    ke.embedding_id,
                    ke.entity_id,
                    ke.chunk_text,
                    ke.embedding_vector,
                    e.title,
                    e.category,
                    e.source_url,
                    e.version
                FROM knowledge_embeddings ke
                JOIN knowledge_entities e ON ke.entity_id = e.entity_id
            """
            params = []

            if category:
                sql += " WHERE e.category = %s"
                params.append(category)

            results = self.db.execute_query(sql, tuple(params) if params else None)

            if not results:
                return []

            # Calculate similarities
            scored_results = []
            for row in results:
                similarity = self.embedding.cosine_similarity(
                    query_embedding,
                    row['embedding_vector']
                )
                scored_results.append({
                    'entity_id': row['entity_id'],
                    'title': row['title'],
                    'chunk_text': row['chunk_text'],
                    'category': row['category'],
                    'source_url': row['source_url'],
                    'version': row['version'],
                    'similarity': similarity
                })

            # Sort and take top_k
            scored_results.sort(key=lambda x: x['similarity'], reverse=True)
            top_results = scored_results[:top_k]

            # Log retrieval
            retrieval_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            entity_ids = [r['entity_id'] for r in top_results]
            log_id = str(uuid.uuid4())

            with self.db.get_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO knowledge_retrieval_log (log_id, query, results, retrieval_time_ms)
                    VALUES (%s, %s, %s, %s)
                """, (log_id, query, entity_ids, retrieval_time_ms))

            logger.info(f"Search completed: {len(top_results)} results in {retrieval_time_ms}ms")
            return top_results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def get_document(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full document"""
        try:
            result = self.db.execute_query("""
                SELECT * FROM knowledge_entities WHERE entity_id = %s
            """, (entity_id,), fetch_one=True)

            return dict(result) if result else None
        except Exception as e:
            logger.error(f"Failed to get document: {e}")
            return None

    def delete_document(self, entity_id: str) -> bool:
        """Delete document"""
        try:
            # Delete embeddings first
            self.db.execute_query("""
                DELETE FROM knowledge_embeddings WHERE entity_id = %s
            """, (entity_id,))

            # Delete entity
            self.db.execute_query("""
                DELETE FROM knowledge_entities WHERE entity_id = %s
            """, (entity_id,))

            logger.info(f"Deleted document: {entity_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete document: {e}")
            return False

    def get_statistics(self) -> Dict[str, Any]:
        """Get knowledge base statistics"""
        try:
            stats = self.db.execute_query("""
                SELECT
                    COUNT(DISTINCT e.entity_id) as total_documents,
                    COUNT(ke.*) as total_chunks,
                    COUNT(DISTINCT e.category) as total_categories
                FROM knowledge_entities e
                LEFT JOIN knowledge_embeddings ke ON e.entity_id = ke.entity_id
            """, fetch_one=True)

            categories = self.db.execute_query("""
                SELECT category, COUNT(*) as count
                FROM knowledge_entities
                GROUP BY category
                ORDER BY count DESC
            """)

            return {
                'total_documents': stats['total_documents'] if stats else 0,
                'total_chunks': stats['total_chunks'] if stats else 0,
                'total_categories': stats['total_categories'] if stats else 0,
                'categories': categories or []
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
