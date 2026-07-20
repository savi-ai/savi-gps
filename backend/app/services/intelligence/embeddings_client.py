"""Embeddings provider abstraction (Phase 0 stub — full implementation in Phase 1)."""
from abc import ABC, abstractmethod
from typing import List, Optional
from app.core.config import settings
from app.core.logger import logger


class EmbeddingsClient(ABC):
    @abstractmethod
    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        pass

    @abstractmethod
    async def embed_query(self, text: str) -> List[float]:
        pass


class OpenAIEmbeddingsClient(EmbeddingsClient):
    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.EMBEDDINGS_MODEL

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        response = await self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]

    async def embed_query(self, text: str) -> List[float]:
        result = await self.embed_texts([text])
        return result[0]


class StubEmbeddingsClient(EmbeddingsClient):
    """Deterministic stub for development without API keys."""

    DIMENSION = 8

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [[float(len(t) % 10) / 10.0] * self.DIMENSION for t in texts]

    async def embed_query(self, text: str) -> List[float]:
        return (await self.embed_texts([text]))[0]


def get_embeddings_client() -> EmbeddingsClient:
    provider = settings.EMBEDDINGS_PROVIDER.lower()
    if provider == "openai" and settings.OPENAI_API_KEY:
        return OpenAIEmbeddingsClient()
    logger.warning(
        "Using stub embeddings client — set EMBEDDINGS_PROVIDER and API keys for production"
    )
    return StubEmbeddingsClient()
