"""Ayarlar penceresi: LLM sağlayıcıları, Hugging Face yerel modelleri ve tetikleyici tercihleri."""

from typing import Dict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop.ui_styles import DARK_STYLESHEET

PROVIDER_PRESETS = {
    "groq": ("https://api.groq.com/openai/v1", "qwen/qwen3.8-27b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
    "huggingface": ("https://router.huggingface.co/v1", "Qwen/Qwen2.5-7B-Instruct"),
    "ollama": ("http://localhost:11434/v1", "qwen2.5:3b"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
}


class SettingsWindow(QWidget):
    """Kullanıcının uygulama ve model ayarlarını arayüzden güncellemesini sağlar."""

    save_requested = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("⚙️ Ayarlar — Akıllı İngilizce Asistanı")
        self.setMinimumWidth(520)
        self.setStyleSheet(DARK_STYLESHEET)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Groq API (Ücretsiz & Çok Hızlı)", "groq")
        self.provider_combo.addItem("Google Gemini API (Ücretsiz Katman)", "gemini")
        self.provider_combo.addItem("Hugging Face Inference Router (Ücretsiz)", "huggingface")
        self.provider_combo.addItem("Ollama (Tamamen Yerel & Ücretsiz)", "ollama")
        self.provider_combo.addItem("OpenAI", "openai")
        self.provider_combo.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow("LLM Sağlayıcı:", self.provider_combo)

        self.base_url_edit = QLineEdit()
        form.addRow("API Base URL:", self.base_url_edit)

        self.model_edit = QLineEdit()
        form.addRow("Model Adı:", self.model_edit)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Ollama için boş bırakabilirsiniz")
        form.addRow("API Key:", self.api_key_edit)

        self.level_combo = QComboBox()
        for lvl in ["A2", "B1", "B2", "C1"]:
            self.level_combo.addItem(lvl, lvl)
        form.addRow("İngilizce Seviyeniz:", self.level_combo)

        self.local_hf_chk = QCheckBox("Yerel Hugging Face Sınıflandırma & NER modellerini kullan (Bölüm 2 & 3)")
        form.addRow("", self.local_hf_chk)

        self.mouse_popup_chk = QCheckBox("Fareyle metin seçince mini '✨ Çevir' butonu göster")
        form.addRow("", self.mouse_popup_chk)

        root.addLayout(form)

        info = QLabel(
            "İpucu: Kısayollar her uygulamada çalışır → Seçili Metni Çevir: Alt+Q  |  Yazma Koçu: Alt+W"
        )
        info.setObjectName("Muted")
        info.setWordWrap(True)
        root.addWidget(info)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("💾 Ayarları Kaydet")
        save_btn.setObjectName("PrimaryBtn")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

        self._raw_settings: Dict = {}

    def load_and_show(self, settings: Dict) -> None:
        self._raw_settings = dict(settings)
        idx = self.provider_combo.findData(settings.get("llm_provider", "ollama"))
        if idx >= 0:
            self.provider_combo.blockSignals(True)
            self.provider_combo.setCurrentIndex(idx)
            self.provider_combo.blockSignals(False)

        self.base_url_edit.setText(settings.get("llm_base_url", ""))
        self.model_edit.setText(settings.get("llm_model", ""))
        self.api_key_edit.setText(settings.get("llm_api_key", ""))

        lvl_idx = self.level_combo.findData(settings.get("user_level", "B1"))
        if lvl_idx >= 0:
            self.level_combo.setCurrentIndex(lvl_idx)

        self.local_hf_chk.setChecked(bool(settings.get("local_hf_enabled", True)))
        self.mouse_popup_chk.setChecked(bool(settings.get("enable_mouse_selection_popup", True)))
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_preset_changed(self) -> None:
        prov = self.provider_combo.currentData()
        if prov in PROVIDER_PRESETS:
            url, model = PROVIDER_PRESETS[prov]
            self.base_url_edit.setText(url)
            self.model_edit.setText(model)

    def _on_save(self) -> None:
        updated = dict(self._raw_settings)
        updated["llm_provider"] = self.provider_combo.currentData()
        updated["llm_base_url"] = self.base_url_edit.text().strip()
        updated["llm_model"] = self.model_edit.text().strip()
        updated["llm_api_key"] = self.api_key_edit.text().strip()
        updated["user_level"] = self.level_combo.currentData()
        updated["local_hf_enabled"] = self.local_hf_chk.isChecked()
        updated["enable_mouse_selection_popup"] = self.mouse_popup_chk.isChecked()
        self.save_requested.emit(updated)
        self.hide()
