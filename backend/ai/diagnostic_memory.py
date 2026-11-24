"""Diagnostic Memory System - Historical case management"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid
from ..utils.logger import setup_logger
from ..utils.db_connector import OpenTenBaseConnector
from .embedding_client import EmbeddingClient

logger = setup_logger(__name__)


class DiagnosticMemory:
    """
    Diagnostic Memory System

    Stores and retrieves historical diagnostic cases for:
    - Similar case recall
    - Solution effectiveness tracking
    - Continuous learning from experience
    """

    def __init__(self, db_connector: OpenTenBaseConnector, embedding_client: EmbeddingClient):
        self.db = db_connector
        self.embedding = embedding_client
        self._ensure_schema()

    def _ensure_schema(self):
        """Create memory tables"""
        schema_sql = """
        -- Diagnostic cases
        CREATE TABLE IF NOT EXISTS diagnostic_cases (
            case_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            symptoms TEXT NOT NULL,
            metrics_snapshot JSONB,  -- Cluster state at diagnosis time
            root_cause TEXT NOT NULL,
            solution TEXT NOT NULL,
            effectiveness FLOAT CHECK (effectiveness BETWEEN 0 AND 1),
            tags TEXT[],  -- ['replication', 'performance', 'lock', etc.]
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ,
            created_by TEXT  -- 'ai' | 'human' | user_id
        );

        -- Case embeddings (for similarity search)
        CREATE TABLE IF NOT EXISTS case_embeddings (
            embedding_id BIGSERIAL PRIMARY KEY,
            case_id UUID REFERENCES diagnostic_cases(case_id) ON DELETE CASCADE,
            embedding_vector FLOAT8[],
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(case_id)
        );

        -- Case applications (track when cases were used)
        CREATE TABLE IF NOT EXISTS case_applications (
            application_id BIGSERIAL PRIMARY KEY,
            case_id UUID REFERENCES diagnostic_cases(case_id),
            applied_at TIMESTAMPTZ DEFAULT NOW(),
            outcome TEXT CHECK (outcome IN ('solved', 'partially_solved', 'not_solved', 'made_worse')),
            user_feedback TEXT,
            user_id TEXT
        );

        -- Case relationships (similar cases, derived from)
        CREATE TABLE IF NOT EXISTS case_relationships (
            relationship_id BIGSERIAL PRIMARY KEY,
            source_case_id UUID REFERENCES diagnostic_cases(case_id),
            target_case_id UUID REFERENCES diagnostic_cases(case_id),
            relationship_type TEXT,  -- 'similar_to' | 'derived_from' | 'conflict_with'
            similarity_score FLOAT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        -- Indexes
        CREATE INDEX IF NOT EXISTS idx_cases_effectiveness ON diagnostic_cases(effectiveness DESC);
        CREATE INDEX IF NOT EXISTS idx_cases_created ON diagnostic_cases(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_cases_tags ON diagnostic_cases USING GIN(tags);
        CREATE INDEX IF NOT EXISTS idx_applications_case ON case_applications(case_id);
        """

        try:
            with self.db.get_cursor(dict_cursor=False) as cursor:
                cursor.execute(schema_sql)
            logger.info("Diagnostic memory schema ensured")
        except Exception as e:
            logger.error(f"Failed to create memory schema: {e}")

    def save_case(
        self,
        symptoms: str,
        root_cause: str,
        solution: str,
        metrics_snapshot: Optional[Dict] = None,
        effectiveness: float = 0.5,
        tags: Optional[List[str]] = None,
        created_by: str = 'ai'
    ) -> Optional[str]:
        """
        Save a diagnostic case

        Args:
            symptoms: Problem description
            root_cause: Identified root cause
            solution: Applied solution
            metrics_snapshot: Cluster metrics at the time
            effectiveness: Initial effectiveness score (0-1)
            tags: Category tags
            created_by: Creator identifier

        Returns:
            case_id if successful
        """
        try:
            # Insert case
            result = self.db.execute_query("""
                INSERT INTO diagnostic_cases
                (symptoms, root_cause, solution, metrics_snapshot, effectiveness, tags, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING case_id
            """, (
                symptoms,
                root_cause,
                solution,
                metrics_snapshot,
                effectiveness,
                tags or [],
                created_by
            ), fetch_one=True)

            case_id = str(result['case_id'])

            # Generate and store embedding
            case_text = f"{symptoms} {root_cause}"
            embedding = self.embedding.embed_text(case_text)

            if embedding:
                self.db.execute_query("""
                    INSERT INTO case_embeddings (case_id, embedding_vector)
                    VALUES (%s, %s)
                """, (case_id, embedding))
            else:
                logger.warning(f"Failed to generate embedding for case {case_id}")

            logger.info(f"Saved diagnostic case: {case_id}")
            return case_id

        except Exception as e:
            logger.error(f"Failed to save case: {e}")
            return None

    def recall_similar_cases(
        self,
        symptoms: str,
        top_k: int = 5,
        min_similarity: float = 0.5,
        tags: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Recall similar historical cases

        Args:
            symptoms: Current problem description
            top_k: Number of cases to return
            min_similarity: Minimum similarity threshold
            tags: Filter by tags

        Returns:
            List of similar cases with similarity scores
        """
        try:
            # Generate query embedding
            query_embedding = self.embedding.embed_text(symptoms)
            if not query_embedding:
                logger.error("Failed to generate query embedding")
                return []

            # Build query
            sql = """
                SELECT
                    c.*,
                    ce.embedding_vector,
                    (
                        SELECT COUNT(*)
                        FROM case_applications ca
                        WHERE ca.case_id = c.case_id
                          AND ca.outcome IN ('solved', 'partially_solved')
                    ) as success_count,
                    (
                        SELECT COUNT(*)
                        FROM case_applications ca
                        WHERE ca.case_id = c.case_id
                    ) as total_applications
                FROM diagnostic_cases c
                JOIN case_embeddings ce ON c.case_id = ce.case_id
            """

            params = []
            if tags:
                sql += " WHERE c.tags && %s"
                params.append(tags)

            results = self.db.execute_query(sql, tuple(params) if params else None)

            if not results:
                return []

            # Calculate similarities
            scored_cases = []
            for row in results:
                similarity = self.embedding.cosine_similarity(
                    query_embedding,
                    row['embedding_vector']
                )

                if similarity < min_similarity:
                    continue

                # Calculate adjusted effectiveness (combines initial + application history)
                success_rate = (
                    row['success_count'] / row['total_applications']
                    if row['total_applications'] > 0
                    else row['effectiveness']
                )

                scored_cases.append({
                    'case_id': row['case_id'],
                    'symptoms': row['symptoms'],
                    'root_cause': row['root_cause'],
                    'solution': row['solution'],
                    'effectiveness': row['effectiveness'],
                    'success_rate': success_rate,
                    'tags': row['tags'],
                    'similarity': similarity,
                    'created_at': row['created_at'],
                    'applications': row['total_applications']
                })

            # Sort by similarity * success_rate
            scored_cases.sort(
                key=lambda x: x['similarity'] * (x['success_rate'] + 0.1),  # +0.1 to avoid zero
                reverse=True
            )

            return scored_cases[:top_k]

        except Exception as e:
            logger.error(f"Failed to recall cases: {e}")
            return []

    def record_application(
        self,
        case_id: str,
        outcome: str,
        user_feedback: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> bool:
        """
        Record that a case was applied

        Args:
            case_id: Case ID
            outcome: Result ('solved' | 'partially_solved' | 'not_solved' | 'made_worse')
            user_feedback: Optional feedback text
            user_id: User who applied the solution

        Returns:
            Success status
        """
        try:
            self.db.execute_query("""
                INSERT INTO case_applications (case_id, outcome, user_feedback, user_id)
                VALUES (%s, %s, %s, %s)
            """, (case_id, outcome, user_feedback, user_id))

            # Update case effectiveness based on outcomes
            self._update_case_effectiveness(case_id)

            logger.info(f"Recorded application of case {case_id}: {outcome}")
            return True

        except Exception as e:
            logger.error(f"Failed to record application: {e}")
            return False

    def _update_case_effectiveness(self, case_id: str):
        """Recalculate case effectiveness based on application history"""
        try:
            # Calculate success rate from applications
            stats = self.db.execute_query("""
                SELECT
                    COUNT(*) FILTER (WHERE outcome IN ('solved', 'partially_solved')) as successes,
                    COUNT(*) as total
                FROM case_applications
                WHERE case_id = %s
            """, (case_id,), fetch_one=True)

            if stats and stats['total'] > 0:
                new_effectiveness = stats['successes'] / stats['total']

                self.db.execute_query("""
                    UPDATE diagnostic_cases
                    SET effectiveness = %s, updated_at = NOW()
                    WHERE case_id = %s
                """, (new_effectiveness, case_id))

        except Exception as e:
            logger.error(f"Failed to update effectiveness: {e}")

    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific case"""
        try:
            result = self.db.execute_query("""
                SELECT
                    c.*,
                    (
                        SELECT COUNT(*)
                        FROM case_applications ca
                        WHERE ca.case_id = c.case_id
                    ) as total_applications
                FROM diagnostic_cases c
                WHERE c.case_id = %s
            """, (case_id,), fetch_one=True)

            return dict(result) if result else None

        except Exception as e:
            logger.error(f"Failed to get case: {e}")
            return None

    def get_statistics(self) -> Dict[str, Any]:
        """Get memory system statistics"""
        try:
            stats = self.db.execute_query("""
                SELECT
                    COUNT(*) as total_cases,
                    AVG(effectiveness) as avg_effectiveness,
                    COUNT(DISTINCT unnest(tags)) as unique_tags
                FROM diagnostic_cases
            """, fetch_one=True)

            recent_cases = self.db.execute_query("""
                SELECT
                    case_id,
                    symptoms,
                    effectiveness,
                    created_at
                FROM diagnostic_cases
                ORDER BY created_at DESC
                LIMIT 10
            """)

            top_cases = self.db.execute_query("""
                SELECT
                    case_id,
                    symptoms,
                    effectiveness,
                    (
                        SELECT COUNT(*)
                        FROM case_applications ca
                        WHERE ca.case_id = dc.case_id
                    ) as applications
                FROM diagnostic_cases dc
                ORDER BY effectiveness DESC
                LIMIT 10
            """)

            return {
                'total_cases': stats['total_cases'],
                'avg_effectiveness': float(stats['avg_effectiveness']) if stats['avg_effectiveness'] else 0.0,
                'unique_tags': stats['unique_tags'],
                'recent_cases': recent_cases,
                'top_cases': top_cases
            }

        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}

    def find_conflicting_cases(self, case_id: str) -> List[Dict[str, Any]]:
        """Find cases with similar symptoms but different solutions"""
        try:
            case = self.get_case(case_id)
            if not case:
                return []

            similar = self.recall_similar_cases(case['symptoms'], top_k=10)

            # Filter for different solutions
            conflicts = [
                c for c in similar
                if c['case_id'] != case_id
                and c['solution'] != case['solution']
                and c['similarity'] > 0.7
            ]

            return conflicts

        except Exception as e:
            logger.error(f"Failed to find conflicts: {e}")
            return []
