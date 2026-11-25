from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Uygulama ortam değişkenlerini ve yollarını yönetir."""

    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-3-flash-preview")
    telegram_bot_token: str = Field(default="")
    telegram_allowed_user_ids: str = Field(default="")
    notes_dir: str = Field(default="./notes")
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8090)

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def resolved_notes_dir(self) -> Path:
        p = Path(self.notes_dir)
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def data_dir(self) -> Path:
        p = BASE_DIR / "data"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.data_dir / "second_brain.db"

    @property
    def gemini_configured(self) -> bool:
        key = self.gemini_api_key.strip()
        return bool(key) and not key.startswith("buraya")

    @property
    def telegram_configured(self) -> bool:
        tok = self.telegram_bot_token.strip()
        return bool(tok) and ":" in tok

    @property
    def allowed_telegram_ids(self) -> set[int]:
        ids: set[int] = set()
        for part in self.telegram_allowed_user_ids.split(","):
            cleaned = part.strip()
            if cleaned.isdigit():
                ids.add(int(cleaned))
        return ids


def get_settings() -> Settings:
    return Settings()
