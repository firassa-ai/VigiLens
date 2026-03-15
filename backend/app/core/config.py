from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_files_for_repo(backend_dir: Path | None = None) -> tuple[Path, ...]:
    resolved_backend_dir = (backend_dir or Path(__file__).resolve().parents[2]).resolve()
    root_dir = resolved_backend_dir.parent
    return (
        resolved_backend_dir / ".env",
        resolved_backend_dir / ".env.local",
        root_dir / ".env",
        root_dir / ".env.local",
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files_for_repo(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "VigiLens API"
    database_url: str = "postgresql+psycopg://vigilens:vigilens@localhost:5432/vigilens"
    demo_mode: bool = True
    demo_data_dir: Path | None = Field(default=Path("/data/real"))
    gemini_api_key: str | None = None
    gemini_model_default: str = "gemini-3-flash-preview"
    gemini_model_reasoning: str = "gemini-3.1-pro-preview"
    # Grounding uses Google Search tool; keep separately configurable because preview models may not support tools.
    gemini_model_grounding: str = "gemini-2.5-flash"
    gemini_grounding_scorecard_verify: bool = True
    gemini_grounding_refresh_days: int = 14
    gemini_prediction_proof_verify: bool = True
    gemini_prediction_proof_refresh_days: int = 7
    openfda_live_background: bool = False
    openfda_api_base_url: str = "https://api.fda.gov/drug/event.json"
    openfda_api_key: str | None = None
    openfda_timeout_seconds: float = 20.0
    openfda_retry_attempts: int = 2
    openfda_retry_backoff_seconds: float = 0.75
    dailymed_api_base_url: str = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
    dailymed_timeout_seconds: float = 4.0
    evermemos_url: str = "http://localhost:1995"
    evermemos_timeout_seconds: float = 5.0
    evermemos_foresight_timeout_seconds: float = 15.0
    evermemos_write_retry_attempts: int = 2
    evermemos_retry_backoff_seconds: float = 0.75
    evermemos_event_log_page_limit: int = 200
    evermemos_event_log_max_pages: int = 15
    evermemos_coverage_mode: str = "aggressive"
    cors_allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000"


DEFAULT_SETTINGS = Settings()
