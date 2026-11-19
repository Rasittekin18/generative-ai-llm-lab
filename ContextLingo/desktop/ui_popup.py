"""İmleç yanında açılan mini 'Çevir' butonu ve bağlamsal çeviri kartı."""

import ctypes
from typing import Dict, List

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop.ui_styles import DARK_STYLESHEET, place_near_cursor


class MiniTriggerPill(QWidget):
    """Fareyle metin seçilince imlecin yanında beliren mini tetikleme butonu."""

    clicked_at = Signal(int, int)

    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(DARK_STYLESHEET)
        self._anchor = (0, 0)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.btn = QPushButton("✨ Çevir")
        self.btn.setObjectName("PillBtn")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(self._on_click)
        layout.addWidget(self.btn)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        try:
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def show_at(self, x: int, y: int) -> None:
        self._anchor = (x, y)
        self.adjustSize()
        place_near_cursor(self, x, y, offset_x=10, offset_y=12)
        self.show()
        self._hide_timer.start(4000)

    def _on_click(self) -> None:
        self._hide_timer.stop()
        self.hide()
        self.clicked_at.emit(self._anchor[0], self._anchor[1])


class TranslationPopup(QWidget):
    """Seçili İngilizce metin için bağlam, NER, çeviri ve kelime kartı gösteren yüzen pencere."""

    save_vocab_requested = Signal(dict, str)
    open_in_writer_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(DARK_STYLESHEET)
        self.setMinimumWidth(450)
        self.setMaximumWidth(520)

        self._current_original = ""
        self._current_translation = ""
        self._drag_pos = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        self.card = QFrame()
        self.card.setObjectName("Card")
        outer.addWidget(self.card)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(10)

        # Üst başlık çubuğu
        header = QHBoxLayout()
        self.title_lbl = QLabel("✨ Bağlamsal Çeviri & Öğretmen")
        self.title_lbl.setStyleSheet("font-weight: 700; font-size: 14px; color: #FFFFFF;")
        header.addWidget(self.title_lbl)
        header.addStretch()

        self.context_badge = QLabel("Bağlam")
        self.context_badge.setObjectName("Badge")
        header.addWidget(self.context_badge)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setStyleSheet("padding: 0; border-radius: 13px;")
        close_btn.clicked.connect(self.hide)
        header.addWidget(close_btn)
        root.addLayout(header)

        # Kaynak pencere & orijinal metin
        self.source_lbl = QLabel("")
        self.source_lbl.setObjectName("Muted")
        root.addWidget(self.source_lbl)

        self.orig_lbl = QLabel("")
        self.orig_lbl.setWordWrap(True)
        self.orig_lbl.setStyleSheet("color: #A5B4CC; font-style: italic; background: #131824; padding: 8px; border-radius: 8px;")
        root.addWidget(self.orig_lbl)

        # Çeviri alanı
        trans_box = QFrame()
        trans_box.setObjectName("SubCard")
        trans_layout = QVBoxLayout(trans_box)
        trans_layout.setContentsMargins(10, 10, 10, 10)
        trans_layout.setSpacing(6)

        trans_head = QHBoxLayout()
        self.trans_title_lbl = QLabel("Doğal Çeviri")
        self.trans_title_lbl.setStyleSheet("font-weight: 700; color: #58A6FF; font-size: 12px;")
        trans_head.addWidget(self.trans_title_lbl)
        trans_head.addStretch()

        self.copy_btn = QPushButton("Kopyala")
        self.copy_btn.setStyleSheet("padding: 3px 10px; font-size: 11px;")
        self.copy_btn.clicked.connect(self._copy_translation)
        trans_head.addWidget(self.copy_btn)
        trans_layout.addLayout(trans_head)

        self.translation_lbl = QLabel("Yükleniyor...")
        self.translation_lbl.setWordWrap(True)
        self.translation_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.translation_lbl.setStyleSheet("font-size: 14px; color: #FFFFFF;")
        trans_layout.addWidget(self.translation_lbl)
        root.addWidget(trans_box)

        # Nüans / Öğretmen açıklaması
        self.nuance_lbl = QLabel("")
        self.nuance_lbl.setWordWrap(True)
        self.nuance_lbl.setStyleSheet("color: #C9D1D9; font-size: 12.5px;")
        root.addWidget(self.nuance_lbl)

        # NER etiketleri
        self.entities_lbl = QLabel("")
        self.entities_lbl.setWordWrap(True)
        self.entities_lbl.setObjectName("Muted")
        root.addWidget(self.entities_lbl)

        # Kelimeler kaydırma alanı
        self.vocab_scroll = QScrollArea()
        self.vocab_scroll.setWidgetResizable(True)
        self.vocab_scroll.setMaximumHeight(190)
        self.vocab_container = QWidget()
        self.vocab_layout = QVBoxLayout(self.vocab_container)
        self.vocab_layout.setContentsMargins(0, 0, 0, 0)
        self.vocab_layout.setSpacing(6)
        self.vocab_scroll.setWidget(self.vocab_container)
        root.addWidget(self.vocab_scroll)

        # Alt aksiyonlar
        footer = QHBoxLayout()
        self.to_writer_btn = QPushButton("✍️ Yazma Koçuna Gönder")
        self.to_writer_btn.clicked.connect(self._open_in_writer)
        footer.addWidget(self.to_writer_btn)
        footer.addStretch()
        self.provider_lbl = QLabel("")
        self.provider_lbl.setObjectName("Muted")
        footer.addWidget(self.provider_lbl)
        root.addLayout(footer)

    def show_loading(self, text: str, window_title: str, x: int, y: int) -> None:
        self._current_original = text
        self._current_translation = ""
        self.context_badge.setText("Analiz ediliyor...")
        self.source_lbl.setText(f"Kaynak: {window_title}" if window_title else "Kaynak: Aktif Pencere")
        preview = text if len(text) <= 220 else text[:220] + "..."
        self.orig_lbl.setText(preview)
        self.translation_lbl.setText("Bağlam analiz ediliyor ve çevriliyor...")
        self.nuance_lbl.setText("")
        self.entities_lbl.setText("")
        self.provider_lbl.setText("")
        self._clear_vocab_list()
        self.vocab_scroll.hide()

        self.adjustSize()
        place_near_cursor(self, x, y)
        self.show()
        self.raise_()

    def show_result(self, data: Dict) -> None:
        self._current_original = data.get("original_text", "")
        self._current_translation = data.get("natural_translation", "")
        target_lang = data.get("target_language", "tr")
        if target_lang == "en":
            self.trans_title_lbl.setText("Doğal İngilizce Çeviri (TR → EN)")
        else:
            self.trans_title_lbl.setText("Doğal Türkçe Çeviri (EN → TR)")
        ctx = data.get("detected_context", "Genel")
        self.context_badge.setText(ctx)
        self.translation_lbl.setText(self._current_translation)

        nuance = data.get("nuance_explanation", "")
        self.nuance_lbl.setText(f"💡 {nuance}" if nuance else "")
        self.nuance_lbl.setVisible(bool(nuance))

        entities: List[Dict] = data.get("entities", [])
        if entities:
            chips = "  •  ".join(f"{e['word']} [{e['entity_group']}]" for e in entities)
            self.entities_lbl.setText(f"🏷️ Varlıklar (NER): {chips}")
            self.entities_lbl.show()
        else:
            self.entities_lbl.hide()

        self._clear_vocab_list()
        vocab_items: List[Dict] = data.get("vocabulary", [])
        if vocab_items:
            for item in vocab_items:
                self.vocab_layout.addWidget(self._build_vocab_row(item))
            self.vocab_scroll.show()
        else:
            self.vocab_scroll.hide()

        self.provider_lbl.setText(data.get("provider_used", ""))
        self.adjustSize()

    def show_error(self, msg: str) -> None:
        self.context_badge.setText("Hata")
        self.translation_lbl.setText(f"Bağlantı/işlem hatası: {msg}")
        self.adjustSize()

    def _build_vocab_row(self, item: Dict) -> QFrame:
        row_frame = QFrame()
        row_frame.setObjectName("SubCard")
        lay = QHBoxLayout(row_frame)
        lay.setContentsMargins(8, 6, 8, 6)

        text_col = QVBoxLayout()
        word_line = QLabel(f"<b>{item.get('word', '')}</b>  <span style='color:#79C0FF;'>[{item.get('cefr_level', 'B1')}]</span> — {item.get('meaning_tr', '')}")
        word_line.setWordWrap(True)
        text_col.addWidget(word_line)

        ex = item.get("example_en", "")
        if ex:
            ex_lbl = QLabel(ex)
            ex_lbl.setWordWrap(True)
            ex_lbl.setObjectName("Muted")
            text_col.addWidget(ex_lbl)
        lay.addLayout(text_col, stretch=1)

        save_btn = QPushButton("+ Kaydet")
        save_btn.setStyleSheet("padding: 4px 10px; font-size: 11px;")

        def on_save() -> None:
            save_btn.setText("✓ Kaydedildi")
            save_btn.setObjectName("SuccessBtn")
            save_btn.setStyle(save_btn.style())
            save_btn.setEnabled(False)
            self.save_vocab_requested.emit(item, self._current_original)

        save_btn.clicked.connect(on_save)
        lay.addWidget(save_btn)
        return row_frame

    def _clear_vocab_list(self) -> None:
        while self.vocab_layout.count():
            child = self.vocab_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _copy_translation(self) -> None:
        if self._current_translation:
            QGuiApplication.clipboard().setText(self._current_translation)
            self.copy_btn.setText("✓ Kopyalandı")
            QTimer.singleShot(1400, lambda: self.copy_btn.setText("Kopyala"))

    def _open_in_writer(self) -> None:
        self.hide()
        self.open_in_writer_requested.emit(self._current_original)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None
