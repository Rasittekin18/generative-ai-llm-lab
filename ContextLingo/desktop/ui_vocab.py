"""Kelime Defteri ve Geçmiş penceresi."""

from typing import Dict, List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from desktop.ui_styles import DARK_STYLESHEET


class VocabHistoryWindow(QWidget):
    """Kaydedilen kelimeleri tekrar etme ve geçmiş çevirileri görme penceresi."""

    refresh_requested = Signal(bool)
    toggle_mastered_requested = Signal(int)
    delete_vocab_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("📚 Kelime Defterim & Çeviri Geçmişi")
        self.setMinimumSize(720, 480)
        self.setStyleSheet(DARK_STYLESHEET)

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        # Sekme 1: Kelime Defteri
        vocab_tab = QWidget()
        v_lay = QVBoxLayout(vocab_tab)
        top = QHBoxLayout()
        self.only_unmastered_chk = QCheckBox("Sadece henüz öğrenmediklerimi göster")
        self.only_unmastered_chk.stateChanged.connect(lambda: self.refresh_requested.emit(self.only_unmastered_chk.isChecked()))
        top.addWidget(self.only_unmastered_chk)
        top.addStretch()
        refresh_btn = QPushButton("🔄 Yenile")
        refresh_btn.clicked.connect(lambda: self.refresh_requested.emit(self.only_unmastered_chk.isChecked()))
        top.addWidget(refresh_btn)
        v_lay.addLayout(top)

        self.vocab_table = QTableWidget(0, 6)
        self.vocab_table.setHorizontalHeaderLabels(["Kelime / Kalıp", "Türkçe Anlamı", "Seviye", "Durum", "İşlem", "Sil"])
        self.vocab_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.vocab_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        v_lay.addWidget(self.vocab_table)
        self.tabs.addTab(vocab_tab, "Kelime Defterim")

        # Sekme 2: Geçmiş
        hist_tab = QWidget()
        h_lay = QVBoxLayout(hist_tab)
        self.hist_table = QTableWidget(0, 3)
        self.hist_table.setHorizontalHeaderLabels(["Tarih", "Mod", "Kaynak Metin"])
        self.hist_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        h_lay.addWidget(self.hist_table)
        self.tabs.addTab(hist_tab, "Son İşlemler")

    def open_and_refresh(self) -> None:
        self.refresh_requested.emit(self.only_unmastered_chk.isChecked())
        self.show()
        self.raise_()
        self.activateWindow()

    def set_data(self, vocab_list: List[Dict], history_list: List[Dict]) -> None:
        self.vocab_table.setRowCount(len(vocab_list))
        for r, item in enumerate(vocab_list):
            vid = item["id"]
            mastered = bool(item.get("mastered", False))
            self.vocab_table.setItem(r, 0, QTableWidgetItem(item.get("word", "")))
            self.vocab_table.setItem(r, 1, QTableWidgetItem(item.get("meaning_tr", "")))
            self.vocab_table.setItem(r, 2, QTableWidgetItem(item.get("cefr_level", "B1")))
            self.vocab_table.setItem(r, 3, QTableWidgetItem("✓ Öğrenildi" if mastered else "Tekrar Edilecek"))

            toggle_btn = QPushButton("Tekrar Listesine Al" if mastered else "✓ Öğrendim")
            toggle_btn.clicked.connect(lambda _chk=False, x=vid: self.toggle_mastered_requested.emit(x))
            self.vocab_table.setCellWidget(r, 4, toggle_btn)

            del_btn = QPushButton("Sil")
            del_btn.clicked.connect(lambda _chk=False, x=vid: self.delete_vocab_requested.emit(x))
            self.vocab_table.setCellWidget(r, 5, del_btn)

        self.hist_table.setRowCount(len(history_list))
        for r, h in enumerate(history_list):
            self.hist_table.setItem(r, 0, QTableWidgetItem(h.get("created_at", "")))
            mode_str = "Okuma (EN→TR)" if h.get("mode") == "analyze" else "Yazma Koçu"
            self.hist_table.setItem(r, 1, QTableWidgetItem(mode_str))
            src = h.get("source_text", "")
            self.hist_table.setItem(r, 2, QTableWidgetItem(src[:140] + ("..." if len(src) > 140 else "")))
