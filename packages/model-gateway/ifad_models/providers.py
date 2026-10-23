"""Provider adapters behind ModelGateway. Each adapter owns its own authentication and request contract.

Azure note: Azure ML managed online endpoints accept key, aml_token and aad_token (Entra) authentication; Kubernetes
online endpoints accept key and aml_token only. The Kubernetes adapter therefore rejects aad_token at construction
instead of failing at request time.
"""
from __future__ import annotations

import re
import time
from typing import Protocol

import httpx
from ifad_common.config import Settings
from ifad_common.correlation import outbound_headers

from ifad_models.embeddings import HashEmbedder
from ifad_models.types import ChatMessage, GenerationConfig, GenerationResult, ProviderError

_SECRETISH = re.compile(r"(api[-_]?key|authorization|bearer)\S*", re.IGNORECASE)


def _safe(exc: Exception) -> str:
    return _SECRETISH.sub("[redacted]", f"{type(exc).__name__}: {exc}")[:300]


class ChatProvider(Protocol):
    name: str
    model: str

    async def generate(self, messages: list[ChatMessage], config: GenerationConfig) -> GenerationResult: ...
    async def health(self) -> tuple[bool, str]: ...


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


# ------------------------------------------------------------------------------------------------------------ mock
class MockChatProvider:
    """Deterministic and offline. Returns the caller's grounded draft verbatim, so tests and demos never depend on a
    model and the output can always be traced to deterministic facts and cited evidence."""

    name = "mock"
    model = "mock-deterministic-v1"
    _DRAFT = re.compile(r"<deterministic_draft>\s*(.*?)\s*</deterministic_draft>", re.DOTALL)

    async def generate(self, messages: list[ChatMessage], config: GenerationConfig) -> GenerationResult:
        start = time.perf_counter()
        user = "\n".join(m.content for m in messages if m.role == "user")
        match = self._DRAFT.search(user)
        text = match.group(1) if match else "Insufficient evidence to answer from the provided sources."
        return GenerationResult(text=text, provider=self.name, model=self.model,
                                latency_ms=round((time.perf_counter() - start) * 1000, 3))

    async def health(self) -> tuple[bool, str]:
        return True, "mock provider (deterministic, offline)"


class HashEmbeddingProvider:
    def __init__(self, dim: int):
        self._embedder = HashEmbedder(dim)
        self.name, self.dim = self._embedder.name, dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.embed(texts)


# ---------------------------------------------------------------------------------------------------------- ollama
class OllamaProvider:
    """Ported from CreditpappraisalFlowise backend/app/llm_providers/ollama_provider.py @ d3ff23f (host fallbacks),
    rewritten for async httpx with explicit timeouts and the /api/embed endpoint."""

    name = "ollama"

    def __init__(self, base_url: str, chat_model: str, embed_model: str, timeout: float, dim: int):
        self.base_url, self.model, self.embed_model, self.dim = base_url.rstrip("/"), chat_model, embed_model, dim
        self.timeout = httpx.Timeout(timeout, connect=5.0)

    async def generate(self, messages: list[ChatMessage], config: GenerationConfig) -> GenerationResult:
        payload = {"model": self.model, "messages": [m.model_dump() for m in messages], "stream": False,
                   "options": {"temperature": config.temperature, "num_predict": config.max_tokens}}
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload, headers=outbound_headers())
                response.raise_for_status()
                text = response.json().get("message", {}).get("content", "")
        except Exception as exc:
            raise ProviderError(f"Ollama generate failed: {_safe(exc)}") from exc
        return GenerationResult(text=text, provider=self.name, model=self.model,
                                latency_ms=round((time.perf_counter() - start) * 1000, 1))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/embed", json={"model": self.embed_model, "input": texts})
                response.raise_for_status()
                vectors = response.json()["embeddings"]
        except Exception as exc:
            raise ProviderError(f"Ollama embed failed: {_safe(exc)}") from exc
        if vectors and len(vectors[0]) != self.dim:
            raise ProviderError(f"Embedding model returned {len(vectors[0])} dims; EMBEDDING_DIM is {self.dim}")
        return vectors

    async def health(self) -> tuple[bool, str]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
                tags = (await client.get(f"{self.base_url}/api/tags")).json()
            names = {m["name"] for m in tags.get("models", [])}
            ok = self.model in names
            return ok, f"ollama reachable; model {self.model} {'present' if ok else 'missing'}"
        except Exception as exc:  # noqa: BLE001
            return False, f"ollama unreachable ({type(exc).__name__})"


# ---------------------------------------------------------------------------------------------------- azure openai
class _EntraToken:
    def __init__(self, scope: str):
        self.scope, self._token, self._expires = scope, "", 0.0

    def get(self) -> str:
        if time.time() > self._expires - 120:
            from azure.identity import DefaultAzureCredential  # workload identity on AKS

            token = DefaultAzureCredential().get_token(self.scope)
            self._token, self._expires = token.token, float(token.expires_on)
        return self._token


class AzureOpenAIProvider:
    """Azure OpenAI chat completions + embeddings. Auth: Entra ID (default, workload identity) or api-key."""

    name = "azure_openai"

    def __init__(self, s: Settings):
        if not (s.azure_openai_endpoint and s.azure_openai_deployment):
            raise ProviderError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT are required")
        if s.azure_openai_auth == "api_key" and not s.azure_openai_api_key:
            raise ProviderError("AZURE_OPENAI_API_KEY is required for api_key auth")
        self.s, self.model, self.dim = s, s.azure_openai_deployment, s.embedding_dim
        self._entra = _EntraToken("https://cognitiveservices.azure.com/.default")
        self.timeout = httpx.Timeout(s.model_timeout_seconds, connect=5.0)

    def _headers(self) -> dict[str, str]:
        auth = {"api-key": self.s.azure_openai_api_key} if self.s.azure_openai_auth == "api_key" \
            else {"Authorization": f"Bearer {self._entra.get()}"}
        return {**auth, **outbound_headers()}

    def _url(self, deployment: str, op: str) -> str:
        return (f"{self.s.azure_openai_endpoint.rstrip('/')}/openai/deployments/{deployment}/{op}"
                f"?api-version={self.s.azure_openai_api_version}")

    async def generate(self, messages: list[ChatMessage], config: GenerationConfig) -> GenerationResult:
        start = time.perf_counter()
        body = {"messages": [m.model_dump() for m in messages], "temperature": config.temperature, "max_tokens": config.max_tokens}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(self._url(self.model, "chat/completions"), json=body, headers=self._headers())
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"] or ""
        except Exception as exc:
            raise ProviderError(f"Azure OpenAI generate failed: {_safe(exc)}") from exc
        return GenerationResult(text=text, provider=self.name, model=self.model,
                                latency_ms=round((time.perf_counter() - start) * 1000, 1))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        deployment = self.s.azure_openai_embedding_deployment
        if not deployment:
            raise ProviderError("AZURE_OPENAI_EMBEDDING_DEPLOYMENT is required for azure_openai embeddings")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(self._url(deployment, "embeddings"), json={"input": texts, "dimensions": self.dim},
                                      headers=self._headers())
                r.raise_for_status()
                return [row["embedding"] for row in r.json()["data"]]
        except Exception as exc:
            raise ProviderError(f"Azure OpenAI embed failed: {_safe(exc)}") from exc

    async def health(self) -> tuple[bool, str]:
        return True, f"azure_openai configured (deployment {self.model}); not probed to avoid token cost"


# -------------------------------------------------------------------------------------------------------- azure ml
class AzureMLOnlineEndpointProvider:
    """Azure ML online endpoint running this project's scoring contract (mlops/deployment/score.py):

        request  {"messages": [{"role", "content"}], "parameters": {"temperature", "max_new_tokens"}}
        response {"output": "<text>", "model": "<name>"}
    """

    MANAGED_MODES = {"key", "aml_token", "aad_token"}
    KUBERNETES_MODES = {"key", "aml_token"}

    def __init__(self, s: Settings, endpoint_type: str):
        self.name = f"azure_ml_{endpoint_type}"
        allowed = self.MANAGED_MODES if endpoint_type == "managed" else self.KUBERNETES_MODES
        if s.azure_ml_auth_mode not in allowed:
            raise ProviderError(f"{endpoint_type} online endpoints do not support auth mode {s.azure_ml_auth_mode}; "
                                f"use one of {sorted(allowed)}")
        if not s.azure_ml_scoring_uri:
            raise ProviderError("AZURE_ML_SCORING_URI is required")
        if s.azure_ml_auth_mode in {"key", "aml_token"} and not s.azure_ml_key:
            raise ProviderError("AZURE_ML_KEY must hold the endpoint key or the current aml_token")
        self.s, self.model = s, s.azure_ml_deployment or "default-deployment"
        self._entra = _EntraToken("https://ml.azure.com/.default")
        self.timeout = httpx.Timeout(s.model_timeout_seconds, connect=5.0)

    def _headers(self) -> dict[str, str]:
        token = self._entra.get() if self.s.azure_ml_auth_mode == "aad_token" else self.s.azure_ml_key
        headers = {"Authorization": f"Bearer {token}", **outbound_headers()}
        if self.s.azure_ml_deployment:
            headers["azureml-model-deployment"] = self.s.azure_ml_deployment
        return headers

    async def generate(self, messages: list[ChatMessage], config: GenerationConfig) -> GenerationResult:
        start = time.perf_counter()
        body = {"messages": [m.model_dump() for m in messages],
                "parameters": {"temperature": config.temperature, "max_new_tokens": config.max_tokens}}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(self.s.azure_ml_scoring_uri, json=body, headers=self._headers())
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            raise ProviderError(f"Azure ML endpoint failed: {_safe(exc)}") from exc
        return GenerationResult(text=str(data.get("output", "")), provider=self.name, model=str(data.get("model", self.model)),
                                latency_ms=round((time.perf_counter() - start) * 1000, 1))

    async def health(self) -> tuple[bool, str]:
        return True, f"{self.name} configured ({self.s.azure_ml_auth_mode}); not probed"
