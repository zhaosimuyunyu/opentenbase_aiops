"""Knowledge Base Management - Compatible with AgentX design"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import hashlib
from ..utils.logger import setup_logger
from ..utils.db_connector import OpenTenBaseConnector
from .embedding_client import EmbeddingClient

logger = setup_logger(__name__)


class KnowledgeBase:
    """
    Knowledge Base Manager

    Design inspired by OpenTenBase-AgentX:
    - Authorized retrieval
    - Version management
    - Evidence evaluation
    - Source citation
    """

    def __init__(self, db_connector: OpenTenBaseConnector, embedding_client: EmbeddingClient):
        self.db = db_connector
        self.embedding = embedding_client
        self._ensure_schema()

    def _ensure_schema(self):
        """Create knowledge base tables if not exist (OpenTenBase compatible)"""

        # For OpenTenBase: tables must be distributed
        # Use entity_id as distribution key for knowledge_entities
        # Use embedding_id for embeddings (since it's serial)

        schema_sql = """
        -- Knowledge entities (OpenTenBase distributed table)
        CREATE TABLE IF NOT EXISTS knowledge_entities (
            entity_id TEXT PRIMARY KEY,  -- Changed to TEXT for better distribution
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            content_digest TEXT NOT NULL,
            category TEXT,
            source_url TEXT,
            version TEXT,
            published_at TIMESTAMPTZ DEFAULT NOW(),
            created_at TIMESTAMPTZ DEFAULT NOW()
        ) DISTRIBUTE BY SHARD(entity_id) TO GROUP default_group;

        -- Vector embeddings (OpenTenBase distributed table)
        CREATE TABLE IF NOT EXISTS knowledge_embeddings (
            embedding_id TEXT NOT NULL,  -- Changed to TEXT UUID
            entity_id TEXT NOT NULL,
            chunk_index INT NOT NULL,
            chunk_text TEXT NOT NULL,
            embedding_vector FLOAT8[1024],  -- Fixed size array
            metadata JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (entity_id, chunk_index),
            UNIQUE(entity_id, embedding_id)
        ) DISTRIBUTE BY SHARD(entity_id) TO GROUP default_group;

        -- Retrieval audit log (replication table for small audit data)
        CREATE TABLE IF NOT EXISTS knowledge_retrieval_log (
            log_id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            results TEXT[],
            retrieval_time_ms INT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        ) DISTRIBUTE BY REPLICATION TO GROUP default_group;

        -- Create indexes
        CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge_entities(category);
        CREATE INDEX IF NOT EXISTS idx_knowledge_published ON knowledge_entities(published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_embeddings_entity ON knowledge_embeddings(entity_id);
        """

        try:
            with self.db.get_cursor(dict_cursor=False) as cursor:
                cursor.execute(schema_sql)
            logger.info("Knowledge base schema ensured")
        except Exception as e:
            logger.error(f"Failed to create schema: {e}")

    def add_document(
        self,
        title: str,
        content: str,
        category: str,
        source_url: Optional[str] = None,
        version: Optional[str] = None,
        chunk_size: int = 500
    ) -> Optional[str]:
        """
        Add document to knowledge base

        Args:
            title: Document title
            content: Full text content
            category: Document category
            source_url: Original URL
            version: Document version
            chunk_size: Characters per chunk

        Returns:
            entity_id if successful
        """
        try:
            # Generate content digest
            content_digest = hashlib.sha256(content.encode()).hexdigest()

            # Check if document already exists
            existing = self.db.execute_query(
                "SELECT entity_id FROM knowledge_entities WHERE content_digest = %s",
                (content_digest,),
                fetch_one=True
            )

            if existing:
                logger.info(f"Document already exists: {existing['entity_id']}")
                return str(existing['entity_id'])

            # Insert entity
            entity = self.db.execute_query("""
                INSERT INTO knowledge_entities
                (title, content, content_digest, category, source_url, version)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING entity_id
            """, (title, content, content_digest, category, source_url, version), fetch_one=True)

            entity_id = str(entity['entity_id'])

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
        # Simple chunking by characters with overlap
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

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            if embedding is None:
                logger.warning(f"Skipping chunk {i} (embedding failed)")
                continue

            try:
                self.db.execute_query("""
                    INSERT INTO knowledge_embeddings
                    (entity_id, chunk_index, chunk_text, embedding_vector, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (entity_id, chunk_index) DO UPDATE
                    SET embedding_vector = EXCLUDED.embedding_vector
                """, (
                    entity_id,
                    i,
                    chunk,
                    embedding,  # Store as array
                    {'length': len(chunk)}
                ))
            except Exception as e:
                logger.error(f"Failed to store embedding for chunk {i}: {e}")

    def search(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Semantic search in knowledge base

        Args:
            query: Search query
            top_k: Number of results
            category: Filter by category

        Returns:
            List of relevant chunks with metadata
        """
        start_time = datetime.now()

        try:
            # Generate query embedding
            query_embedding = self.embedding.embed_text(query)
            if not query_embedding:
                logger.error("Failed to generate query embedding")
                return []

            # Retrieve all embeddings (or use vector similarity if pgvector available)
            # For now, using Python-side similarity calculation
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

            # Sort by similarity and take top_k
            scored_results.sort(key=lambda x: x['similarity'], reverse=True)
            top_results = scored_results[:top_k]

            # Log retrieval
            retrieval_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            entity_ids = [r['entity_id'] for r in top_results]

            self.db.execute_query("""
                INSERT INTO knowledge_retrieval_log (query, results, retrieval_time_ms)
                VALUES (%s, %s, %s)
            """, (query, entity_ids, retrieval_time_ms))

            logger.info(f"Search completed: {len(top_results)} results in {retrieval_time_ms}ms")
            return top_results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def get_document(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full document by entity_id"""
        try:
            result = self.db.execute_query("""
                SELECT * FROM knowledge_entities WHERE entity_id = %s
            """, (entity_id,), fetch_one=True)

            return dict(result) if result else None
        except Exception as e:
            logger.error(f"Failed to get document: {e}")
            return None

    def delete_document(self, entity_id: str) -> bool:
        """Delete document (cascade to embeddings)"""
        try:
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
                    COUNT(DISTINCT entity_id) as total_documents,
                    COUNT(*) as total_chunks,
                    COUNT(DISTINCT category) as total_categories
                FROM knowledge_embeddings ke
                JOIN knowledge_entities e ON ke.entity_id = e.entity_id
            """, fetch_one=True)

            categories = self.db.execute_query("""
                SELECT category, COUNT(*) as count
                FROM knowledge_entities
                GROUP BY category
                ORDER BY count DESC
            """)

            return {
                'total_documents': stats['total_documents'],
                'total_chunks': stats['total_chunks'],
                'total_categories': stats['total_categories'],
                'categories': categories
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}
