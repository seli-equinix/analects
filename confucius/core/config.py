# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
"""CCA Configuration loader.

Reads ~/.confucius/config.toml (or CCA_CONFIG_PATH env var).
Raises CCAConfigError if config is missing or incomplete — never silently
falls back. All errors are structured for UI consumption.

Config format (TOML):
    [active]
    coder = "local"
    note_taker = "local"

    openai_model_prefixes = ["qwen", "/models/"]

    [providers.local.note_taker]
    model = "/models/Qwen3-8B-FP8"
    base_url = "http://localhost:8400/v1"
    initial_max_tokens = 4096
    temperature = 0.3

    [services]
    redis_url = "redis://localhost:6379/0"
    qdrant_url = "http://localhost:6333"
"""
from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# NOTE: LLMParams is NOT imported at module level to avoid circular imports.
# config.py -> llm_manager.llm_params -> __init__ -> auto -> azure -> constants -> config.py
# Instead, LLMParams is imported lazily inside functions that need it.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm_manager.llm_params import LLMParams

logger: logging.Logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path.home() / ".confucius" / "config.toml"


# ---------------------------------------------------------------------------
# Structured error — UI-consumable
# ---------------------------------------------------------------------------

class CCAConfigError(Exception):
    """Raised when CCA configuration is missing, invalid, or incomplete.

    Every field is designed for UI consumption:
        role        — which LLM role failed (e.g. "coder", "note_taker")
        detail      — human-readable explanation of what went wrong
        config_path — the config file path that was loaded (or expected)
        suggestion  — actionable fix the UI can display to the user

    Standard usage in CCA entry classes:
        try:
            params = get_llm_params("coder")
        except CCAConfigError as e:
            # e.role, e.detail, e.config_path, e.suggestion all available
            show_config_error(e)
    """

    def __init__(
        self,
        *,
        role: str,
        detail: str,
        config_path: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        self.role = role
        self.detail = detail
        self.config_path = config_path
        self.suggestion = suggestion
        super().__init__(f"[{role}] {detail}")

    def to_dict(self) -> dict[str, str | None]:
        """Serialize for JSON API / UI transport."""
        return {
            "error": "config_error",
            "role": self.role,
            "detail": self.detail,
            "config_path": self.config_path,
            "suggestion": self.suggestion,
        }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ProviderProfile(BaseModel):
    """A single LLM provider profile."""

    model: str
    provider: str = "openai"  # informational: "openai", "azure", "bedrock", "google"
    base_url: str | None = None
    api_key_env: str | None = None
    initial_max_tokens: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    thinking_budget: int | None = None
    use_responses_api: bool = False
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0

    class Config:
        extra = "ignore"

    def to_llm_params(self) -> LLMParams:
        """Convert to CCA's internal LLMParams format."""
        from .llm_manager.llm_params import LLMParams as _LLMParams

        additional_kwargs: dict[str, Any] = {}

        if self.base_url:
            additional_kwargs["base_url"] = self.base_url
        if self.use_responses_api:
            additional_kwargs["use_responses_api"] = True

        # Convert thinking_budget — format depends on provider
        if self.thinking_budget and self.thinking_budget > 0:
            if self.provider in ("azure", "bedrock", "anthropic"):
                # Anthropic-compatible providers use the Thinking object
                from .chat_models.bedrock.api.invoke_model import anthropic as ant
                additional_kwargs["thinking"] = ant.Thinking(
                    type=ant.ThinkingType.ENABLED,
                    budget_tokens=self.thinking_budget,
                ).dict()
            else:
                # OpenAI-compatible providers (vLLM, etc.)
                additional_kwargs["thinking_budget"] = self.thinking_budget

        return _LLMParams(
            model=self.model,
            initial_max_tokens=self.initial_max_tokens,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            additional_kwargs=additional_kwargs or None,
        )


class ServicesConfig(BaseModel):
    """Infrastructure service endpoints — single source of truth.

    All service URLs are configured here. Python code reads from this;
    env vars (QDRANT_URL, REDIS_URL, etc.) override these when set.
    """

    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    embedding_url: str = "http://localhost:8200"
    searxng_url: str = "http://localhost:8888"
    memgraph_host: str = "localhost"
    memgraph_port: int = 7687
    phoenix_endpoint: str = ""  # empty = disabled
    phoenix_project: str = "cca"
    cors_origins: str = "*"  # comma-separated

    class Config:
        extra = "ignore"


class RouterConfig(BaseModel):
    """Expert router configuration (Functionary-based classification)."""

    enabled: bool = False
    url: str = "http://localhost:8001"
    timeout_ms: int = 10000
    fallback_entry: str = "coder"
    temperature: float = 0.1
    escalation_enabled: bool = False  # Big LLM reroute for ambiguous classifications

    class Config:
        extra = "ignore"


class ToolRouterConfig(BaseModel):
    """In-loop tool selection configuration (Phase 2).

    When enabled, the Functionary model selects which additional tool
    groups to enable mid-loop when the agent gets stuck without the
    right tools.
    """

    enabled: bool = False
    url: str = "http://localhost:8001"
    timeout_ms: int = 10000
    temperature: float = 0.1

    class Config:
        extra = "ignore"


class CredentialConfig(BaseModel):
    """Named credential for accessing a git server.

    Token values can reference environment variables using ``${VAR}``
    syntax (e.g. ``"${GITLAB_PASS}"``).  The sync script resolves these
    at runtime so secrets never live in the TOML file.
    """

    id: str                                      # Lookup key (e.g. "gitlab-local")
    url: str = "http://localhost:8929"            # Git server base URL
    user: str = "root"
    token: str = ""                              # Plain text or "${ENV_VAR}"

    class Config:
        extra = "ignore"


class RepoConfig(BaseModel):
    """Single repository definition."""

    name: str                                    # Dir name under /workspace & Qdrant project name
    repo: str = ""                               # Repo path on server (e.g. "root/EVA")
    credential: str = ""                         # ID of [[workspace.credentials]] entry
    type: str = "source"                         # "source" (pull) or "migration" (CCA manages)
    branch: str = "main"                         # Git branch to clone/track

    class Config:
        extra = "ignore"


class WorkspaceConfig(BaseModel):
    """Workspace repository management — single source of truth.

    Defines which git repos are cloned into ``/workspace``, how they
    are authenticated, and how they are synced.  Both ``workspace-sync``
    (cloning/pulling) and the CCA indexer (Qdrant/Memgraph) derive their
    project lists from this section.
    """

    sync_interval: int = 60                      # Seconds between git pulls
    credentials: list[CredentialConfig] = Field(default_factory=list)
    repos: list[RepoConfig] = Field(default_factory=list)

    class Config:
        extra = "ignore"

    @property
    def source_repos(self) -> list[RepoConfig]:
        return [r for r in self.repos if r.type == "source"]

    @property
    def migration_repos(self) -> list[RepoConfig]:
        return [r for r in self.repos if r.type == "migration"]

    @property
    def all_project_names(self) -> list[str]:
        return [r.name for r in self.repos]

    def get_credential(self, cred_id: str) -> CredentialConfig | None:
        for c in self.credentials:
            if c.id == cred_id:
                return c
        return None


class IndexerConfig(BaseModel):
    """Workspace indexer configuration.

    Controls which projects are monitored and synced to Qdrant + Memgraph.
    If ``projects`` is empty, project names are derived from
    ``[workspace].repos`` automatically.
    """

    paths: list[str] = Field(default_factory=lambda: ["/workspace"])
    projects: list[str] = Field(default_factory=list)
    collection: str = "codebase_files"
    sync_interval: int = 300  # seconds between sync cycles
    skip_dirs: list[str] = Field(
        default_factory=lambda: [
            ".git", "node_modules", "__pycache__", ".venv", "venv",
            "build", "dist",
        ]
    )

    class Config:
        extra = "ignore"


class CCAConfig(BaseModel):
    """Top-level CCA configuration."""

    active: dict[str, str] = Field(default_factory=dict)
    openai_model_prefixes: list[str] = Field(
        default_factory=lambda: ["qwen"],
    )
    providers: dict[str, dict[str, ProviderProfile]] = Field(default_factory=dict)
    router: RouterConfig = Field(default_factory=RouterConfig)
    tool_router: ToolRouterConfig = Field(default_factory=ToolRouterConfig)
    services: ServicesConfig = Field(default_factory=ServicesConfig)
    indexer: IndexerConfig = Field(default_factory=IndexerConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)

    class Config:
        extra = "ignore"

    def get_profile(self, role: str) -> ProviderProfile | None:
        """Get the active profile for a role."""
        provider_set = self.active.get(role)
        if not provider_set:
            return None
        return self.providers.get(provider_set, {}).get(role)


# Module-level singleton
_config: CCAConfig | None = None
_config_path: str | None = None  # Track which path was loaded (for error messages)


def _resolve_config_path() -> Path:
    """Resolve the config file path from env or default."""
    return Path(os.environ.get("CCA_CONFIG_PATH", str(_DEFAULT_CONFIG_PATH)))


def _load_config() -> CCAConfig:
    """Load config from TOML file. Raises CCAConfigError on failure."""
    global _config, _config_path
    if _config is not None:
        return _config

    config_path = _resolve_config_path()
    _config_path = str(config_path)

    if not config_path.exists():
        raise CCAConfigError(
            role="*",
            detail=f"Config file not found: {config_path}",
            config_path=str(config_path),
            suggestion=(
                f"Create {config_path} with [active] and [providers] sections. "
                "Set CCA_CONFIG_PATH env var to use a different location."
            ),
        )

    try:
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
        _config = CCAConfig(**raw)
        logger.info(f"Loaded CCA config from {config_path}")
    except CCAConfigError:
        raise
    except Exception as e:
        raise CCAConfigError(
            role="*",
            detail=f"Failed to parse config: {e}",
            config_path=str(config_path),
            suggestion="Check TOML syntax. Validate with: python -c \"import tomllib; tomllib.load(open('config.toml','rb'))\"",
        ) from e

    return _config


def reload_config() -> CCAConfig:
    """Force reload config from disk (for hot-reload / UI updates)."""
    global _config, _config_path
    _config = None
    _config_path = None
    return _load_config()


def get_llm_params(role: str) -> LLMParams:
    """Get LLMParams for a named role from config.

    Raises CCAConfigError if the role is not configured. No silent fallbacks.

    Usage in entry classes:
        from ...core.config import get_llm_params, CCAConfigError

        params = get_llm_params("coder")
    """
    config = _load_config()
    config_path = _config_path or str(_resolve_config_path())

    # Check [active] section has this role
    provider_set = config.active.get(role)
    if not provider_set:
        available = list(config.active.keys()) or ["(none)"]
        raise CCAConfigError(
            role=role,
            detail=f"Role '{role}' not found in [active] section",
            config_path=config_path,
            suggestion=f"Add '{role} = \"local\"' to the [active] section. Configured roles: {', '.join(available)}",
        )

    # Check the provider set has a profile for this role
    profile = config.providers.get(provider_set, {}).get(role)
    if profile is None:
        available_sets = list(config.providers.keys()) or ["(none)"]
        raise CCAConfigError(
            role=role,
            detail=f"No profile for role '{role}' in provider set '{provider_set}'",
            config_path=config_path,
            suggestion=f"Add [providers.{provider_set}.{role}] section with at least 'model' key. Available provider sets: {', '.join(available_sets)}",
        )

    return profile.to_llm_params()


def get_openai_model_prefixes() -> list[str]:
    """Get OpenAI model prefixes from config.

    Raises CCAConfigError if config cannot be loaded.
    """
    config = _load_config()
    return config.openai_model_prefixes


def get_router_config() -> RouterConfig:
    """Get expert router configuration.

    Returns RouterConfig (enabled=False if section is missing).
    Never raises — router is optional.
    """
    config = _load_config()
    return config.router


def get_tool_router_config() -> ToolRouterConfig:
    """Get in-loop tool router configuration (Phase 2).

    Returns ToolRouterConfig (enabled=False if section is missing).
    Never raises — tool router is optional.
    """
    config = _load_config()
    return config.tool_router


def get_services_config() -> ServicesConfig:
    """Get infrastructure service endpoints from config.

    Returns ServicesConfig with defaults if [services] section is missing.
    Individual values can be overridden by env vars in calling code.
    """
    config = _load_config()
    return config.services


def get_indexer_config() -> IndexerConfig:
    """Get workspace indexer configuration.

    Returns IndexerConfig with defaults if [indexer] section is missing.
    If ``projects`` is empty, derives project names from ``[workspace].repos``.
    """
    config = _load_config()
    indexer = config.indexer
    if not indexer.projects and config.workspace.repos:
        indexer.projects = config.workspace.all_project_names
    return indexer


def get_workspace_config() -> WorkspaceConfig:
    """Get workspace repository management configuration.

    Returns WorkspaceConfig with defaults if [workspace] section is missing.
    """
    config = _load_config()
    return config.workspace
