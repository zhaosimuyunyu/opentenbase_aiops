"""BGE-M3 Embedding Client (SiliconFlow)"""
from typing import List, Optional
import requests
from ..utils.config import Config
from ..utils.logger import setup_logger

logger = setup_logger(__name__)


class EmbeddingClient:
    """BGE-M3 Embedding Client via SiliconFlow"""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.api_key = self.config.EMBEDDING_API_KEY
        self.api_base = self.config.EMBEDDING_API_BASE
        self.model = self.config.EMBEDDING_MODEL
        self.dimension = self.config.EMBEDDING_DIMENSION

        if not self.api_key:
            logger.warning("EMBEDDING_API_KEY not set, embedding features disabled")

    def embed_text(self, text: str) -> Optional[List[float]]:
        """Generate embedding for single text"""
        try:
            response = requests.post(
                f"{self.api_base}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "input": text,
                    "encoding_format": "float"
                },
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                embedding = data['data'][0]['embedding']

                # Validate dimension
                if len(embedding) != self.dimension:
                    logger.error(
                        f"Unexpected embedding dimension: {len(embedding)} "
                        f"(expected {self.dimension})"
                    )
                    return None

                return embedding
            else:
                logger.error(f"Embedding API error: {response.status_code} {response.text}")
                return None

        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for multiple texts"""
        try:
            response = requests.post(
                f"{self.api_base}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "input": texts,
                    "encoding_format": "float"
                },
                timeout=60
            )

            if response.status_code == 200:
                data = response.json()
                items = sorted(data['data'], key=lambda item: item['index'])
                if [item['index'] for item in items] != list(range(len(texts))):
                    logger.error("Embedding API returned inconsistent batch indices")
                    return [None] * len(texts)
                embeddings = [item['embedding'] for item in items]

                # Validate all dimensions
                for i, emb in enumerate(embeddings):
                    if len(emb) != self.dimension:
                        logger.error(
                            f"Text {i}: unexpected dimension {len(emb)} "
                            f"(expected {self.dimension})"
                        )
                        embeddings[i] = None

                return embeddings
            else:
                logger.error(f"Batch embedding API error: {response.status_code}")
                return [None] * len(texts)

        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            return [None] * len(texts)

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        if not vec1 or not vec2:
            return 0.0

        import math

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def test_connection(self) -> dict:
        """Test embedding service connection"""
        test_text = "数据库连接测试"

        try:
            embedding = self.embed_text(test_text)

            if embedding:
                return {
                    'status': 'success',
                    'model': self.model,
                    'dimension': len(embedding),
                    'api_base': self.api_base
                }
            else:
                return {
                    'status': 'failed',
                    'error': 'Failed to generate embedding'
                }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)
            }
