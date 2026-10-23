from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class GenerationConfig(BaseModel):
    temperature: float = Field(0.1, ge=0, le=2)
    max_tokens: int = Field(700, ge=1, le=4000)
    purpose: str = "general"  # recorded for evaluation and audit


class EmbeddingConfig(BaseModel):
    purpose: Literal["document", "query"] = "document"


class GenerationResult(BaseModel):
    text: str
    provider: str
    model: str
    latency_ms: float
    prompt_version: str | None = None


class ProviderError(RuntimeError):
    """A provider failed. The message never contains credentials."""
