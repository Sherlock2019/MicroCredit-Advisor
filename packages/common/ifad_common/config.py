"""One settings object for every service. Values come from the environment (.env locally, Key Vault in Azure)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "ifad-platform"
    deployment_env: Literal["local", "test", "dev", "demo"] = "local"
    deployment_target: Literal["local-docker", "azure-aks"] = "local-docker"
    build_version: str = "0.1.0-local"
    commit_sha: str = "uncommitted"

    database_url: str = "postgresql+psycopg://ifad_owner:ifad_owner_dev_only@localhost:55433/ifad_platform"
    db_pool_size: int = 5

    # --- identity -------------------------------------------------------------------------------------------------
    # Dev mode accepts HS256 tokens minted by /api/v1/dev/token. Never enable outside a trusted local machine.
    auth_dev_mode: bool = False
    auth_dev_jwt_secret: str = ""
    auth_dev_issuer: str = "ifad-poc-dev-issuer"
    # When set (public demos, e.g. on EC2), demo sign-in requires this key in the X-Demo-Key header.
    demo_access_key: str = Field(default="", repr=False)
    # Entra ID v2: issuer https://login.microsoftonline.com/<tenant-guid>/v2.0, audience api://<app-id> or the app id.
    oidc_issuer: str = ""
    oidc_jwks_url: str = ""
    oidc_audience: str = "api://ifad-rural-ai-platform"
    # Business tenant (partner organisation) claim. Entra: a directory extension or optional claim mapped here.
    oidc_tenant_claim: str = "tenant_id"
    agent_token_secret: str = ""
    agent_token_ttl_seconds: int = 900

    # --- model gateway ----------------------------------------------------------------------------------------------
    model_provider: Literal["mock", "ollama", "azure_openai", "azure_ml_managed", "azure_ml_kubernetes"] = "mock"
    embedding_provider: Literal["hash", "ollama", "azure_openai"] = "hash"
    embedding_dim: int = 384
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen2.5:7b"
    ollama_embed_model: str = "all-minilm"
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""
    azure_openai_embedding_deployment: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_auth: Literal["entra", "api_key"] = "entra"
    azure_openai_api_key: str = Field(default="", repr=False)
    azure_ml_scoring_uri: str = ""
    azure_ml_auth_mode: Literal["key", "aml_token", "aad_token"] = "key"
    azure_ml_key: str = Field(default="", repr=False)
    azure_ml_deployment: str = ""
    model_timeout_seconds: float = 60.0

    # --- RAG --------------------------------------------------------------------------------------------------------
    rag_min_score: float = 0.12
    rag_min_query_coverage: float = 0.3  # share of the question's content words that must appear in the evidence
    rag_top_k: int = 6

    # --- storage ----------------------------------------------------------------------------------------------------
    storage_backend: Literal["local", "azure_blob"] = "local"
    storage_local_root: str = "./data/object-store"
    azure_storage_account_url: str = ""
    azure_storage_container: str = "documents"
    max_upload_bytes: int = 10 * 1024 * 1024

    # --- service topology -------------------------------------------------------------------------------------------
    finance_service_url: str = "http://localhost:8401"
    projects_service_url: str = "http://localhost:8402"
    downstream_timeout_seconds: float = 30.0
    cors_origins: str = "http://localhost:8480,http://127.0.0.1:8480"

    @model_validator(mode="after")
    def _dev_mode_needs_secret(self) -> Settings:
        if self.auth_dev_mode and len(self.auth_dev_jwt_secret) < 32:
            raise ValueError("AUTH_DEV_MODE=true requires AUTH_DEV_JWT_SECRET of at least 32 characters")
        if self.auth_dev_mode and self.deployment_target == "azure-aks":
            raise ValueError("AUTH_DEV_MODE must not be enabled on Azure deployments")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
