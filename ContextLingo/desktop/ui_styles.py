"""Ortak koyu tema stilleri ve çoklu monitör uyumlu pencere konumlandırma."""

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

DARK_STYLESHEET = """
QWidget {
    background-color: #131722;
    color: #E6EDF3;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}
QFrame#Card {
    background-color: #1B2130;
    border: 1px solid #2D364D;
    border-radius: 12px;
}
QFrame#SubCard {
    background-color: #151A26;
    border: 1px solid #262E42;
    border-radius: 8px;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
    background-color: #0F131C;
    color: #F0F6FC;
    border: 1px solid #2E3850;
    border-radius: 8px;
    padding: 7px 10px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #58A6FF;
}
QPushButton {
    background-color: #252E42;
    color: #E6EDF3;
    border: 1px solid #35415C;
    border-radius: 8px;
    padding: 7px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #303B54;
}
QPushButton#PrimaryBtn {
    background-color: #2F6FEB;
    border: 1px solid #4C87F5;
    color: #FFFFFF;
}
QPushButton#PrimaryBtn:hover {
    background-color: #3B7AF5;
}
QPushButton#SuccessBtn {
    background-color: #1F6F43;
    border: 1px solid #2E9B5E;
    color: #FFFFFF;
}
QPushButton#PillBtn {
    background-color: #2F6FEB;
    border: 1px solid #6BA0FF;
    color: #FFFFFF;
    border-radius: 14px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 700;
}
QPushButton#PillBtn:hover {
    background-color: #3E7EF7;
}
QPushButton#ToneBtn {
    background-color: #1D2433;
    border: 1px solid #2E3850;
    border-radius: 14px;
    padding: 5px 12px;
}
QPushButton#ToneBtn:checked {
    background-color: #2F6FEB;
    border: 1px solid #6BA0FF;
    color: #FFFFFF;
}
QLabel#Badge {
    background-color: #222B3F;
    color: #79C0FF;
    border: 1px solid #304163;
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#Muted {
    color: #8B949E;
    font-size: 12px;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
"""


def place_near_cursor(widget: QWidget, x: int, y: int, offset_x: int = 12, offset_y: int = 14) -> None:
    """Pencereyi ekran dışına taşmayacak şekilde imlecin yakınına yerleştirir."""
    screen = QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()
    geo = screen.availableGeometry()
    widget.adjustSize()
    w = max(widget.width(), widget.minimumWidth())
    h = max(widget.height(), widget.minimumHeight())

    target_x = x + offset_x
    target_y = y + offset_y

    if target_x + w > geo.right():
        target_x = max(geo.left() + 8, x - w - offset_x)
    if target_y + h > geo.bottom():
        target_y = max(geo.top() + 8, y - h - offset_y)

    target_x = max(geo.left() + 8, min(target_x, geo.right() - w - 8))
    target_y = max(geo.top() + 8, min(target_y, geo.bottom() - h - 8))
    widget.move(target_x, target_y)
