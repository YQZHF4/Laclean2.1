"""Dark industrial visual theme."""

DARK_STYLESHEET = r"""
QWidget {
    color: #d7dde7;
    background-color: #171a1f;
    font-family: "Microsoft YaHei UI";
}

QMainWindow, QDialog { background-color: #171a1f; }

QMenuBar {
    background-color: #1d2127;
    border-bottom: 1px solid #303640;
    padding: 2px;
}
QMenuBar::item { padding: 6px 12px; background: transparent; }
QMenuBar::item:selected { background-color: #2b323c; border-radius: 3px; }
QMenu {
    background-color: #22272e;
    border: 1px solid #3a424e;
    padding: 5px;
}
QMenu::item { padding: 7px 28px 7px 12px; border-radius: 3px; }
QMenu::item:selected { background-color: #185f88; color: white; }
QMenu::separator { height: 1px; background: #39414c; margin: 5px 8px; }

QToolBar {
    background-color: #20252c;
    border: 0;
    border-bottom: 1px solid #343b45;
    spacing: 4px;
    padding: 5px 8px;
}
QToolBar::separator { background: #3b434e; width: 1px; margin: 5px 7px; }
QToolButton {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 5px 8px;
}
QToolButton:hover { background-color: #2b333d; border-color: #3d4855; }
QToolButton:pressed, QToolButton:checked { background-color: #174f70; border-color: #2388bd; }

QDockWidget { color: #cfd6e1; font-weight: 600; }
QDockWidget::title {
    background-color: #20252c;
    border-bottom: 1px solid #343b45;
    padding: 8px 10px;
    text-align: left;
}

QTreeWidget, QTreeView, QTableWidget {
    background-color: #1c2026;
    alternate-background-color: #20252c;
    border: 0;
    outline: 0;
    padding: 4px;
}
QTreeWidget::item { min-height: 28px; border-radius: 3px; }
QTreeWidget::item:hover { background-color: #262d36; }
QTreeWidget::item:selected { background-color: #14557c; color: #ffffff; }

QHeaderView::section {
    background-color: #242a32;
    color: #aeb8c6;
    border: 0;
    border-right: 1px solid #343b45;
    border-bottom: 1px solid #343b45;
    padding: 6px;
}

QPushButton {
    background-color: #2a313a;
    border: 1px solid #3b4652;
    border-radius: 4px;
    padding: 6px 12px;
}
QPushButton:hover { background-color: #333c47; border-color: #4a5968; }
QPushButton:pressed { background-color: #164f72; }
QPushButton[accent="true"] { background-color: #0877ad; border-color: #1799d3; color: white; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #14171b;
    border: 1px solid #39424e;
    border-radius: 4px;
    padding: 5px 7px;
    selection-background-color: #1775a5;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #168bc2; }

QScrollArea { border: 0; }
QGroupBox {
    border: 1px solid #313944;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #aeb9c8; }

QStatusBar {
    background-color: #1d2228;
    border-top: 1px solid #343b45;
    color: #aeb8c6;
}
QStatusBar::item { border: 0; }

QLabel[muted="true"] { color: #7f8b99; }
QLabel[section="true"] { color: #f0f4f9; font-size: 14px; font-weight: 600; }
QLabel[badge="offline"] {
    color: #aab3bf;
    background-color: #2a3038;
    border: 1px solid #3b444f;
    border-radius: 8px;
    padding: 2px 8px;
}
QFrame[card="true"] {
    background-color: #20252c;
    border: 1px solid #303844;
    border-radius: 6px;
}
QFrame#viewerHeader {
    background-color: #1d2228;
    border-bottom: 1px solid #343b45;
}
QLabel#viewerTitle {
    background-color: transparent;
    font-weight: 600;
    color: #d9e1eb;
}
QLabel#cropModeBadge {
    color: #dff5ff;
    background-color: #105f84;
    border: 1px solid #269ed0;
    border-radius: 9px;
    padding: 3px 9px;
    font-weight: 600;
}
QLabel#occUnavailable {
    color: #8793a1;
    background-color: #111419;
    border: 1px dashed #3a424d;
    border-radius: 8px;
    padding: 20px;
}

QScrollBar:vertical { background: #191d22; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #3b444f; min-height: 28px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #4b5866; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
