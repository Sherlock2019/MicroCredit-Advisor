"""ModelGateway: one provider-independent interface for generation and embeddings.

    gateway.generate(messages, config) -> GenerationResult
    gateway.embed(texts, config)       -> list[list[float]]
    gateway.health()                   -> dict

Services call it from sync route handlers through run_sync(), which uses the AnyIO worker-thread bridge.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any, TypeVar

import anyio
import anyio.from_thread
from ifad_common.config import Settings, get_settings

from ifad_models.providers import (
    AzureMLOnlineEndpointProvider,
    AzureOpenAIProvider,
    ChatProvider,
    EmbeddingProvider,
    HashEmbeddingProvider,
    MockChatProvider,
    OllamaProvider,
)
from ifad_models.types import ChatMessage, EmbeddingConfig, GenerationConfig, GenerationResult

T = TypeVar("T")


def run_sync[T](fn: Callable[..., Awaitable[T]], *args: Any) -> T:
    try:
        return anyio.from_thread.run(fn, *args)
    except RuntimeError:  # not inside an AnyIO worker thread (scripts, tests)
        return anyio.run(fn, *args)


def _chat_provider(s: Settings) -> ChatProvider:
    if s.model_provider == "ollama":
        return OllamaProvider(s.ollama_base_url, s.ollama_chat_model, s.ollama_embed_model, s.model_timeout_seconds, s.embedding_dim)
    if s.model_provider == "azure_openai":
        return AzureOpenAIProvider(s)
    if s.model_provider == "azure_ml_managed":
        return AzureMLOnlineEndpointProvider(s, "managed")
    if s.model_provider == "azure_ml_kubernetes":
        return AzureMLOnlineEndpointProvider(s, "kubernetes")
    return MockChatProvider()


def _embedding_provider(s: Settings) -> EmbeddingProvider:
    if s.embedding_provider == "ollama":
        return OllamaProvider(s.ollama_base_url, s.ollama_chat_model, s.ollama_embed_model, s.model_timeout_seconds, s.embedding_dim)
    if s.embedding_provider == "azure_openai":
        return AzureOpenAIProvider(s)
    return HashEmbeddingProvider(s.embedding_dim)


class ModelGateway:
    def __init__(self, chat: ChatProvider, embeddings: EmbeddingProvider):
        self.chat, self.embeddings = chat, embeddings

    @property
    def embedding_model(self) -> str:
        return getattr(self.embeddings, "embed_model", None) or self.embeddings.name

    async def generate(self, messages: list[ChatMessage], config: GenerationConfig | None = None) -> GenerationResult:
        return await self.chat.generate(messages, config or GenerationConfig())

    async def embed(self, texts: list[str], config: EmbeddingConfig | None = None) -> list[list[float]]:
        if not texts:
            return []
        return await self.embeddings.embed(texts)

    async def health(self) -> dict:
        ok, detail = await self.chat.health()
        return {"ok": ok, "detail": detail, "provider": self.chat.name, "model": self.chat.model,
                "embedding_provider": self.embeddings.name, "embedding_model": self.embedding_model,
                "embedding_dim": self.embeddings.dim}


@lru_cache
def get_gateway() -> ModelGateway:
    s = get_settings()
    return ModelGateway(_chat_provider(s), _embedding_provider(s))
