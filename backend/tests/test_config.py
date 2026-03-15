from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import _env_files_for_repo


def test_env_files_for_repo_loads_openfda_key_from_root_env_local(tmp_path: Path) -> None:
    root_dir = tmp_path / "repo"
    backend_dir = root_dir / "backend"
    backend_dir.mkdir(parents=True)

    (root_dir / ".env.local").write_text("OPENFDA_API_KEY=test-key-from-root-env-local\n", encoding="utf-8")

    class LocalSettings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=_env_files_for_repo(backend_dir),
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

        openfda_api_key: str | None = None

    settings = LocalSettings()

    assert settings.openfda_api_key == "test-key-from-root-env-local"
