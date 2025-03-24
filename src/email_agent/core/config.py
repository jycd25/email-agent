"""Static configuration (environment / .env) and mutable runtime settings.

Static config is read once at startup. Runtime settings live in the SQLite
store so they can be edited from the UI without restarting.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Provider(str, Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"


class Profile(str, Enum):
    """Who the agent is working for. Drives prompt context and defaults."""

    GENERAL = "general"


class AppConfig(BaseSettings):
    """Values that need to be known before the store exists."""

    model_config = SettingsConfigDict(env_prefix="EMAIL_AGENT_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default_factory=lambda: Path.home() / ".email-agent")
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    @property
    def db_path(self) -> Path:
        return self.data_dir / "email_agent.db"

    @property
    def credentials_path(self) -> Path:
        return self.data_dir / "credentials.json"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "token.json"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


class RuntimeSettings(BaseModel):
    """Everything the user can change from the UI. Persisted in the store."""

    profile: Profile = Profile.GENERAL
    provider: Provider = Provider.OLLAMA
    model: str = "llama3.1:8b"
    base_url: str = "http://localhost:11434/v1"

    poll_interval_seconds: int = Field(default=60, ge=5, le=3600)
    batch_size: int = Field(default=10, ge=1, le=100)
    max_attempts: int = Field(default=3, ge=1, le=10)
    fetch_since: str | None = None  # ISO date; None = no lower bound

    analyze_urgency: bool = True

    urgency_threshold: str = "high"
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
