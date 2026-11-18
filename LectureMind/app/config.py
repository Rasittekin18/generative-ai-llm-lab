"""Merkezi yapılandırma ayarları."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Uygulama yapılandırma sınıfı."""

    model_config = SettingsConfigDict(
        env_prefix="LECTUREMIND_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    MEDIA_DIR: Path = DATA_DIR / "media"
    DB_PATH: Path = DATA_DIR / "lecturemind.db"

    WHISPER_MODEL: str = "small"
    WHISPER_DEVICE: str = "auto"  # auto | cuda | cpu
    EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    LLM_PROVIDER: str = "local"  # local | ollama | openai | gemini
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    def ensure_dirs(self) -> None:
        """Gerekli veri klasörlerini oluşturur."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.MEDIA_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
