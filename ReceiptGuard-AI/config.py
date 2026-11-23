"""Uygulama yapılandırma ayarları."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Ortam değişkenleri ve varsayılan uygulama ayarları."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # Sağlayıcı seçimi
    llm_provider: str = "ollama"  # ollama | gemini | openai
    vlm_provider: str = "auto"    # auto | ollama | gemini | openai

    # Ollama ayarları
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_llm_model: str = "qwen3:4b"
    ollama_vlm_model: str = "qwen2.5vl:3b"
    ollama_timeout_sec: int = 120

    # Yerel Embedding (Hugging Face önbelleğindeki Türkçe SBERT modeli)
    embedding_model: str = "emrecan/bert-base-turkish-cased-mean-nli-stsb-tr"

    # Opsiyonel bulut API'ler
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # Dizinler
    data_dir: Path = BASE_DIR / "data"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    db_path: Path = BASE_DIR / "data" / "app.db"
    vector_dir: Path = BASE_DIR / "data" / "vector_index"

    def ensure_dirs(self) -> None:
        """Gerekli veri klasörlerini oluşturur."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.vector_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
