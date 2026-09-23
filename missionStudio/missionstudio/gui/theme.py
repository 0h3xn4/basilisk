#
#  ISC License
#
#  Copyright (c) 2026, Autonomous Vehicle Systems Lab, University of Colorado at Boulder
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
#  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
#  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
#  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
#  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
#  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
#  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
#  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#

"""Application-wide visual theme: one QSS stylesheet plus a QPalette,
applied once at startup (:func:`apply_theme`, called from ``gui/app.py``).

Before this, the app ran on whatever the platform's native Qt style
happened to render -- functional, but visually inconsistent across
platforms and, per user feedback, "looks very unfinished... not very
intuitive and comfortable to use". This is a pure presentation-layer
change: no widget's behavior, signal wiring, or layout STRUCTURE changes
because of it (see ``main_window.py``'s toolbar and ``results_widget.py``'s
empty-state message for the two places actual UX/behavior did change) --
every existing test that drives a widget by object identity/signals keeps
passing untouched.

Colors are a small, deliberately limited palette (see the ``_C`` dict
below) rather than picked ad hoc per rule, so the whole app reads as one
consistent system: a slate/graphite neutral scale for backgrounds/borders/
text, plus ONE accent color (a mid blue, evoking "engineering tool" rather
than a marketing brand) reused for focus rings, selection highlights, the
primary action button, and progress bars -- never a second accent color
introduced for a single widget.

Qt Style Sheets are a real but limited CSS dialect (see the Qt docs'
"Qt Style Sheets Reference") -- e.g. no ``box-shadow``, limited selector
combinators, per-widget-class property support varies. Everything here
was written against and cross-checked with that reference, not guessed.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Neutral (slate) scale, light -> dark, plus one accent color and the
# semantic status colors already implied by existing code (QMessageBox
# severities aren't styled here -- they use the platform's native icons/
# buttons on purpose, so errors still look unmistakably like errors).
_C = {
    "bg": "#F5F6F8",           # window/app background
    "surface": "#FFFFFF",       # cards, inputs, list/tree backgrounds
    "surface_alt": "#FAFBFC",   # subtly-recessed surfaces (tab pane, status bar)
    "border": "#D8DCE3",        # default borders
    "border_strong": "#C2C8D2",  # hovered/focused-adjacent borders
    "text": "#1F2530",          # primary text
    "text_muted": "#5B6472",    # secondary text, placeholders
    "text_disabled": "#A3AAB5",
    "accent": "#3457D5",        # primary accent (buttons, focus, selection)
    "accent_hover": "#2C49B8",
    "accent_pressed": "#243C99",
    "accent_soft": "#E8ECFC",   # accent tint for subtle highlights (selected tab, etc.)
    "on_accent": "#FFFFFF",     # text/icon color drawn ON the accent color
    "danger": "#C0392B",
}


def _qss() -> str:
    c = _C
    return f"""
    /* ---- base ---------------------------------------------------- */
    QWidget {{
        background-color: {c['bg']};
        color: {c['text']};
        font-size: 10.5pt;
        selection-background-color: {c['accent']};
        selection-color: {c['on_accent']};
    }}
    QMainWindow, QDialog {{
        background-color: {c['bg']};
    }}
    QToolTip {{
        background-color: {c['text']};
        color: {c['surface']};
        border: none;
        padding: 4px 8px;
        border-radius: 4px;
    }}
    QLabel {{
        background: transparent;
    }}

    /* ---- group boxes (the app's main structural unit) ------------- */
    QGroupBox {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        margin-top: 14px;
        padding-top: 6px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 12px;
        top: -2px;
        padding: 0 6px;
        background-color: {c['bg']};
        color: {c['accent']};
    }}
    QGroupBox::indicator {{
        width: 16px;
        height: 16px;
    }}

    /* ---- buttons ---------------------------------------------------- */
    QPushButton {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 5px 14px;
        color: {c['text']};
    }}
    QPushButton:hover {{
        border-color: {c['border_strong']};
        background-color: {c['surface_alt']};
    }}
    QPushButton:pressed {{
        background-color: {c['accent_soft']};
    }}
    QPushButton:disabled {{
        color: {c['text_disabled']};
        background-color: {c['surface_alt']};
    }}
    QPushButton:default, QPushButton[primary="true"] {{
        background-color: {c['accent']};
        border: 1px solid {c['accent']};
        color: {c['on_accent']};
        font-weight: 600;
    }}
    QPushButton:default:hover, QPushButton[primary="true"]:hover {{
        background-color: {c['accent_hover']};
    }}
    QPushButton:default:pressed, QPushButton[primary="true"]:pressed {{
        background-color: {c['accent_pressed']};
    }}

    /* ---- text/number inputs ------------------------------------------ */
    QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 5px;
        padding: 4px 6px;
        selection-background-color: {c['accent']};
        selection-color: {c['on_accent']};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border: 1px solid {c['accent']};
    }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        color: {c['text_disabled']};
        background-color: {c['surface_alt']};
    }}
    QLineEdit::placeholder {{
        color: {c['text_muted']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        selection-background-color: {c['accent']};
        selection-color: {c['on_accent']};
        outline: none;
    }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 16px;
        border: none;
    }}

    /* ---- lists -------------------------------------------------------- */
    QListWidget, QTreeWidget {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        outline: none;
    }}
    QListWidget::item, QTreeWidget::item {{
        padding: 4px 6px;
        border-radius: 4px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background-color: {c['accent']};
        color: {c['on_accent']};
    }}
    QListWidget::item:hover:!selected {{
        background-color: {c['accent_soft']};
    }}

    /* ---- tabs ------------------------------------------------------ */
    QTabWidget::pane {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        top: -1px;
    }}
    QTabBar::tab {{
        background-color: transparent;
        color: {c['text_muted']};
        padding: 7px 16px;
        margin-right: 2px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background-color: {c['surface']};
        color: {c['accent']};
        border: 1px solid {c['border']};
        border-bottom: 1px solid {c['surface']};
    }}
    QTabBar::tab:hover:!selected {{
        color: {c['text']};
    }}

    /* ---- scroll areas / scrollbars ------------------------------------ */
    QScrollArea {{
        border: none;
        background-color: transparent;
    }}
    QScrollArea > QWidget > QWidget {{
        background-color: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 12px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border_strong']};
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {c['text_muted']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 12px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {c['border_strong']};
        border-radius: 5px;
        min-width: 24px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    /* ---- menus / toolbar / status bar --------------------------------- */
    QMenuBar {{
        background-color: {c['surface']};
        border-bottom: 1px solid {c['border']};
        padding: 2px;
    }}
    QMenuBar::item {{
        padding: 5px 10px;
        border-radius: 4px;
        background: transparent;
    }}
    QMenuBar::item:selected {{
        background-color: {c['accent_soft']};
        color: {c['accent']};
    }}
    QMenu {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background-color: {c['accent']};
        color: {c['on_accent']};
    }}
    QMenu::separator {{
        height: 1px;
        background: {c['border']};
        margin: 4px 8px;
    }}
    QToolBar {{
        background-color: {c['surface']};
        border-bottom: 1px solid {c['border']};
        padding: 4px;
        spacing: 4px;
    }}
    QToolButton {{
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 4px 8px;
    }}
    QToolButton:hover {{
        background-color: {c['accent_soft']};
        border-color: {c['border']};
    }}
    QToolButton:pressed {{
        background-color: {c['accent']};
    }}
    QToolButton:disabled {{
        color: {c['text_disabled']};
    }}
    QToolButton#primaryToolButton {{
        background-color: {c['accent']};
        color: {c['on_accent']};
        font-weight: 600;
    }}
    QToolButton#primaryToolButton:hover {{
        background-color: {c['accent_hover']};
    }}
    QToolButton#primaryToolButton:pressed {{
        background-color: {c['accent_pressed']};
    }}
    QToolButton#primaryToolButton:disabled {{
        background-color: {c['surface_alt']};
        color: {c['text_disabled']};
    }}
    QStatusBar {{
        background-color: {c['surface_alt']};
        border-top: 1px solid {c['border']};
    }}
    QSplitter::handle {{
        background-color: {c['border']};
    }}
    QSplitter::handle:horizontal {{
        width: 2px;
    }}
    QSplitter::handle:vertical {{
        height: 2px;
    }}

    /* ---- progress bar (run-in-progress indicator) --------------------- */
    QProgressBar {{
        background-color: {c['surface_alt']};
        border: 1px solid {c['border']};
        border-radius: 5px;
        text-align: center;
        color: {c['text_muted']};
    }}
    QProgressBar::chunk {{
        background-color: {c['accent']};
        border-radius: 4px;
    }}

    /* ---- checkboxes / checkable group boxes --------------------------- */
    QCheckBox {{
        spacing: 8px;
    }}
    """


def apply_theme(app: QApplication) -> None:
    """Call once, right after constructing the ``QApplication`` (see
    ``gui/app.py``). "Fusion" is used as the base QStyle -- the one built
    -in Qt style that renders identically (and predictably styleable via
    QSS) across Linux/macOS/Windows, rather than each platform's native
    style, whose look/spacing QSS rules interact with inconsistently.
    """
    app.setStyle("Fusion")

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(_C["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(_C["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(_C["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(_C["surface_alt"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(_C["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(_C["surface"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(_C["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(_C["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(_C["on_accent"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(_C["text"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(_C["surface"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(_C["text_muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(_C["text_disabled"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(_C["text_disabled"]))
    app.setPalette(palette)

    app.setStyleSheet(_qss())
