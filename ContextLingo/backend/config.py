"""Uygulama yapılandırması: .env ve data/settings.json birleşimi."""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

from backend.schemas import AppSettings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"
DB_FILE = DATA_DIR / "assistant.db"

load_dotenv(BASE_DIR / ".env")


def _env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> AppSettings:
    """Ayarları önce .env, ardından varsa data/settings.json üzerinden yükler."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    defaults = AppSettings(
        llm_provider=os.getenv("LLM_PROVIDER", "ollama"),
        llm_base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
        llm_model=os.getenv("LLM_MODEL", "qwen2.5:7b-instruct"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        local_hf_enabled=_env_bool("LOCAL_HF_ENABLED", True),
        hf_context_model=os.getenv("HF_CONTEXT_MODEL", "typeform/distilbert-base-uncased-mnli"),
        hf_ner_model=os.getenv("HF_NER_MODEL", "dslim/bert-base-NER"),
        enable_mouse_selection_popup=_env_bool("ENABLE_MOUSE_SELECTION_POPUP", True),
        hotkey_translate=os.getenv("HOTKEY_TRANSLATE", "<alt>+q"),
        hotkey_writer=os.getenv("HOTKEY_WRITER", "<alt>+w"),
        user_level=os.getenv("USER_LEVEL", "B1"),
    )

    if SETTINGS_FILE.exists():
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            merged = {**defaults.model_dump(), **raw}
            return AppSettings(**merged)
        except Exception:
            return defaults
    return defaults


def save_settings(settings: AppSettings) -> AppSettings:
    """Kullanıcı ayarlarını data/settings.json dosyasına kaydeder."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(settings.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return settings


def get_backend_url() -> str:
    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    port = os.getenv("BACKEND_PORT", "8765")
    return f"http://{host}:{port}"
