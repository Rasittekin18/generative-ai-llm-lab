"""Yazma & Prompt Koçu penceresi (Alt+W): Türkçe düşünceyi veya kaba İngilizceyi doğal İngilizceye çevirir."""

from typing import Dict, List

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop.ui_styles import DARK_STYLESHEET


class WriterWindow(QWidget):
    """Türkçe -> Akıllı İngilizce ve İngilizce İyileştirme penceresi."""

    submit_write = Signal(str, str, str)  # text, tone, mode
    save_vocab_requested = Signal(dict, str)

    TONES = ["Casual", "Professional", "Technical Prompt", "Academic"]
    TONE_LABELS = {
        "Casual": "Günlük",
        "Professional": "Profesyonel",
        "Technical Prompt": "Teknik / AI Prompt",
        "Academic": "Akademik",
    }

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("✍️ Akıllı İngilizce Yazma & Prompt Koçu (Alt+W)")
        self.setMinimumSize(620, 560)
        self.setStyleSheet(DARK_STYLESHEET)

        self._selected_tone = "Professional"
        self._current_result = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Üst satır: Mod seçimi
        top_bar = QHBoxLayout()
        title = QLabel("Türkçe yaz ya da İngilizceni test et — bağlama uygun doğal İngilizce al")
        title.setStyleSheet("font-weight: 700; font-size: 14px;")
        top_bar.addWidget(title)
        top_bar.addStretch()

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Otomatik Algıla", "auto")
        self.mode_combo.addItem("Türkçe → İngilizce", "tr_to_en")
        self.mode_combo.addItem("İngilizcemi Düzelt", "improve_en")
        top_bar.addWidget(self.mode_combo)
        root.addLayout(top_bar)

        # Ton butonları
        tone_row = QHBoxLayout()
        tone_lbl = QLabel("Ton:")
        tone_lbl.setObjectName("Muted")
        tone_row.addWidget(tone_lbl)

        self.tone_group = QButtonGroup(self)
        self.tone_group.setExclusive(True)
        for idx, tone in enumerate(self.TONES):
            btn = QPushButton(self.TONE_LABELS[tone])
            btn.setObjectName("ToneBtn")
            btn.setCheckable(True)
            if tone == self._selected_tone:
                btn.setChecked(True)
            btn.clicked.connect(lambda _chk, t=tone: self._set_tone(t))
            self.tone_group.addButton(btn, idx)
            tone_row.addWidget(btn)
        tone_row.addStretch()
        root.addLayout(tone_row)

        # Girdi alanı
        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText(
            "Örnek 1: Yarınki toplantıyı öğleden sonraya çekebilir miyiz, API entegrasyonunda küçük bir hata çıktı.\n"
            "Örnek 2: Bu kodu benim için optimize et ama mantığını bozma."
        )
        self.input_edit.setMaximumHeight(120)
        root.addWidget(self.input_edit)

        action_row = QHBoxLayout()
        self.run_btn = QPushButton("✨ Doğal İngilizceye Dönüştür")
        self.run_btn.setObjectName("PrimaryBtn")
        self.run_btn.clicked.connect(self._on_submit)
        action_row.addWidget(self.run_btn)
        action_row.addStretch()
        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("Muted")
        action_row.addWidget(self.status_lbl)
        root.addLayout(action_row)

        # Çıktı Kartı
        out_card = QFrame()
        out_card.setObjectName("Card")
        out_lay = QVBoxLayout(out_card)
        out_lay.setContentsMargins(14, 12, 14, 12)
        out_lay.setSpacing(10)

        out_head = QHBoxLayout()
        lbl = QLabel("Önerilen Doğal İngilizce")
        lbl.setStyleSheet("font-weight: 700; color: #58A6FF;")
        out_head.addWidget(lbl)
        out_head.addStretch()

        self.copy_main_btn = QPushButton("📋 Kopyala")
        self.copy_main_btn.clicked.connect(self._copy_main)
        out_head.addWidget(self.copy_main_btn)
        out_lay.addLayout(out_head)

        self.result_lbl = QLabel("Sonuç burada görünecek...")
        self.result_lbl.setWordWrap(True)
        self.result_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.result_lbl.setStyleSheet("font-size: 15px; color: #FFFFFF; background: #121722; padding: 10px; border-radius: 8px;")
        out_lay.addWidget(self.result_lbl)

        self.alts_lbl = QLabel("")
        self.alts_lbl.setWordWrap(True)
        self.alts_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.alts_lbl.setStyleSheet("color: #C9D1D9;")
        out_lay.addWidget(self.alts_lbl)

        self.explain_lbl = QLabel("")
        self.explain_lbl.setWordWrap(True)
        self.explain_lbl.setStyleSheet("color: #9ECBFF; background: #141C2B; padding: 8px; border-radius: 8px;")
        out_lay.addWidget(self.explain_lbl)

        self.phrases_container = QVBoxLayout()
        out_lay.addLayout(self.phrases_container)

        root.addWidget(out_card, stretch=1)

    def _set_tone(self, tone: str) -> None:
        self._selected_tone = tone

    def prefill_and_show(self, text: str = "") -> None:
        if text:
            self.input_edit.setPlainText(text)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input_edit.setFocus()

    def _on_submit(self) -> None:
        txt = self.input_edit.toPlainText().strip()
        if not txt:
            return
        self.run_btn.setEnabled(False)
        self.status_lbl.setText("Düşünülüyor...")
        mode = self.mode_combo.currentData()
        self.submit_write.emit(txt, self._selected_tone, mode)

    def show_result(self, data: Dict) -> None:
        self.run_btn.setEnabled(True)
        self.status_lbl.setText(f"Dil: {data.get('detected_language', '').upper()} • {data.get('provider_used', '')}")
        self._current_result = data.get("english_result", "")
        self.result_lbl.setText(self._current_result)

        alts: List[str] = data.get("alternatives", [])
        if alts:
            alt_text = "\n".join(f"• {a}" for a in alts)
            self.alts_lbl.setText(f"Alternatif İfadeler:\n{alt_text}")
            self.alts_lbl.show()
        else:
            self.alts_lbl.hide()

        exp = data.get("explanation_tr", "")
        self.explain_lbl.setText(f"💡 Neden Böyle Kuruldu?\n{exp}" if exp else "")
        self.explain_lbl.setVisible(bool(exp))

        while self.phrases_container.count():
            child = self.phrases_container.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for p in data.get("key_phrases", []):
            row = QHBoxLayout()
            wrap = QWidget()
            wrap.setLayout(row)
            lbl = QLabel(f"<b>{p.get('word', '')}</b> [{p.get('cefr_level', 'B1')}] — {p.get('meaning_tr', '')}")
            lbl.setWordWrap(True)
            row.addWidget(lbl, stretch=1)
            btn = QPushButton("+ Deftere Ekle")
            btn.setStyleSheet("padding: 3px 8px; font-size: 11px;")

            def on_save(checked=False, item=p, b=btn) -> None:
                b.setText("✓ Eklendi")
                b.setEnabled(False)
                self.save_vocab_requested.emit(item, self._current_result)

            btn.clicked.connect(on_save)
            row.addWidget(btn)
            self.phrases_container.addWidget(wrap)

    def show_error(self, msg: str) -> None:
        self.run_btn.setEnabled(True)
        self.status_lbl.setText("Hata")
        self.result_lbl.setText(f"Hata: {msg}")

    def _copy_main(self) -> None:
        if self._current_result:
            QGuiApplication.clipboard().setText(self._current_result)
            self.copy_main_btn.setText("✓ Kopyalandı")
            QTimer.singleShot(1400, lambda: self.copy_main_btn.setText("📋 Kopyala"))
