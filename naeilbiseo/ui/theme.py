"""화면 색·글꼴·스타일."""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

# 색
INK = "#1f2a2e"
MUTED = "#5f6d73"
LINE = "#d9dfdb"
BG = "#f5f4ef"
PANEL = "#ffffff"
PRIMARY = "#1f6f5c"
PRIMARY_DARK = "#17574a"
PRIMARY_SOFT = "#e6f1ed"
AMBER = "#b4690e"
AMBER_SOFT = "#fdf1d8"
DANGER = "#b3261e"
DANGER_SOFT = "#fbe9e7"
USER_BUBBLE = "#e9f3ef"

FONT_STEPS = (11, 13, 15, 17)          # pt — '큰 글씨'가 기본
DEFAULT_FONT_STEP = 1
FONT_STEP_NAMES = ("작게", "보통(큰 글씨)", "크게", "아주 크게")
_PREFERRED_FONTS = ("Pretendard", "Malgun Gothic", "맑은 고딕", "Apple SD Gothic Neo", "NanumBarunGothic",
                    "NanumGothic", "Noto Sans CJK KR", "Noto Sans KR")


def pick_font_family() -> str:
    families = set(QFontDatabase.families())
    for name in _PREFERRED_FONTS:
        if name in families:
            return name
    return QApplication.font().family()


def font_pt(step: int) -> int:
    return FONT_STEPS[max(0, min(len(FONT_STEPS) - 1, int(step)))]


def _check_icon_path() -> str:
    """체크 표시 그림을 한 번 그려 두고 그 경로를 돌려준다(스타일시트에서 씀)."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    from .. import config

    folder = config.app_data_dir() / "ui"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "check.png"
    if not path.exists():
        pix = QPixmap(36, 36)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("white"), 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([QPointF(8, 19), QPointF(15, 26), QPointF(28, 10)])
        painter.end()
        pix.save(str(path))
    arrow = folder / "arrow.png"
    if not arrow.exists():
        pix = QPixmap(24, 24)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(MUTED), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([QPointF(6, 9), QPointF(12, 15), QPointF(18, 9)])
        painter.end()
        pix.save(str(arrow))
    return str(path).replace("\\", "/")


def apply_theme(app: QApplication, step: int = DEFAULT_FONT_STEP) -> None:
    pt = font_pt(step)
    font = QFont(pick_font_family(), pt)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(stylesheet(pt, _check_icon_path()))


def stylesheet(pt: int, check_icon: str = "") -> str:
    small = max(9, pt - 2)
    big = pt + 5
    box = max(16, pt + 5)
    return f"""
QCheckBox::indicator, QListWidget::indicator, QTableWidget::indicator {{
    width: {box}px; height: {box}px; border: 2px solid #94a39d; border-radius: 5px; background: {PANEL}; }}
QCheckBox::indicator:hover, QListWidget::indicator:hover, QTableWidget::indicator:hover {{ border-color: {PRIMARY}; }}
QCheckBox::indicator:checked, QListWidget::indicator:checked, QTableWidget::indicator:checked {{
    background: {PRIMARY}; border-color: {PRIMARY}; image: url("{check_icon}"); }}
QCheckBox::indicator:disabled {{ background: #eceeeb; border-color: #c9d0cc; }}
QWidget {{ color: {INK}; font-size: {pt}pt; }}
QMainWindow, QDialog {{ background: {BG}; }}
QLabel#appTitle {{ font-size: {big}pt; font-weight: 800; color: {PRIMARY_DARK}; }}
QLabel#appSub {{ color: {MUTED}; font-size: {small}pt; }}
QLabel#sectionTitle {{ font-weight: 800; color: {PRIMARY_DARK}; padding: 6px 2px 2px 2px; }}
QLabel#muted {{ color: {MUTED}; font-size: {small}pt; }}
QLabel#banner {{ background: {AMBER_SOFT}; color: #6b3f00; border: 1px solid #f0d28c; border-radius: 8px; padding: 8px 12px; }}
QLabel#sendLine {{ background: {PRIMARY_SOFT}; color: {PRIMARY_DARK}; border-radius: 8px; padding: 6px 10px; font-size: {small}pt; }}
QLabel#sendLineMock {{ background: {AMBER_SOFT}; color: #6b3f00; border-radius: 8px; padding: 6px 10px; font-size: {small}pt; }}
QFrame#header {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
QFrame#sidebar {{ background: {PANEL}; border-right: 1px solid {LINE}; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#pending {{ background: #fffaf0; border: 1px solid #f0d28c; border-radius: 10px; }}

QPushButton {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {PRIMARY}; }}
QPushButton:disabled {{ color: #a3adb1; background: #f0f1ee; }}
QPushButton#primary {{ background: {PRIMARY}; border-color: {PRIMARY}; color: white; font-weight: 700; }}
QPushButton#primary:hover {{ background: {PRIMARY_DARK}; }}
QPushButton#primary:disabled {{ background: #9dbdb3; border-color: #9dbdb3; color: white; }}
QPushButton#danger {{ background: {DANGER}; border-color: {DANGER}; color: white; font-weight: 700; }}
QPushButton#chip {{ border-radius: 14px; padding: 5px 12px; background: {PRIMARY_SOFT}; border-color: #c9e0d8; color: {PRIMARY_DARK}; }}
QPushButton#seg {{ border-radius: 0; padding: 7px 16px; }}
QPushButton#seg:checked {{ background: {PRIMARY}; color: white; border-color: {PRIMARY}; font-weight: 700; }}
QPushButton#status {{ border-radius: 16px; padding: 6px 14px; background: {PRIMARY_SOFT}; border-color: #c9e0d8; color: {PRIMARY_DARK}; font-weight: 700; }}
QPushButton#statusMock {{ border-radius: 16px; padding: 6px 14px; background: {AMBER_SOFT}; border-color: #f0d28c; color: #6b3f00; font-weight: 700; }}
QPushButton#statusBad {{ border-radius: 16px; padding: 6px 14px; background: {DANGER_SOFT}; border-color: #f2b8b5; color: {DANGER}; font-weight: 700; }}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QTimeEdit, QDateEdit, QSpinBox {{
    background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; padding: 6px 8px;
    selection-background-color: {PRIMARY}; selection-color: white; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: {PRIMARY}; }}
QTextBrowser {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; padding: 6px; }}

QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {PRIMARY}; color: white; }}
QListWidget::item:hover:!selected {{ background: {PRIMARY_SOFT}; }}
QListWidget#plain::item {{ padding: 4px 6px; }}
QListWidget#plain::item:selected {{ background: {PRIMARY_SOFT}; color: {INK}; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 10px 18px; margin-right: 2px; border-bottom: 3px solid transparent; color: {MUTED}; }}
QTabBar::tab:selected {{ color: {PRIMARY_DARK}; border-bottom: 3px solid {PRIMARY}; font-weight: 800; }}
QTabBar::tab:hover:!selected {{ color: {INK}; }}

QTableWidget, QTreeWidget {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px;
    gridline-color: #edf0ee; alternate-background-color: #fafbf9; }}
QTableWidget::item, QTreeWidget::item {{ padding: 5px; }}
QTableWidget::item:selected, QTreeWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {INK}; }}
QHeaderView::section {{ background: #eef1ee; border: none; border-bottom: 1px solid {LINE}; padding: 7px 8px; font-weight: 700; }}
QGroupBox {{ border: 1px solid {LINE}; border-radius: 10px; margin-top: 14px; background: {PANEL}; padding: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {PRIMARY_DARK}; font-weight: 800; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QScrollBar:vertical {{ width: 12px; background: transparent; }}
QScrollBar::handle:vertical {{ background: #c7cfcb; border-radius: 6px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{ background: {INK}; color: white; border: none; padding: 6px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{check_icon.replace("check.png", "arrow.png")}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {LINE}; selection-background-color: {PRIMARY_SOFT};
    selection-color: {INK}; outline: none; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; color: {MUTED}; font-size: {small}pt; }}
QStatusBar QLabel {{ color: {MUTED}; font-size: {small}pt; }}
QSplitter::handle {{ background: transparent; width: 8px; }}
"""
