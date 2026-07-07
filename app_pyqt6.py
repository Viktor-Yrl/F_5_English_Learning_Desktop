import json
import sys
import time
import urllib.error
from datetime import date
from pathlib import Path

import audio_service
import backup_service
import category_service
import db as database
import services
import settings_service
import translation_service
from PyQt6.QtCore import QUrl, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtSql import QSqlDatabase, QSqlTableModel
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
WORDS_JSON = DATA_DIR / "words.json"
PROGRESS_JSON = DATA_DIR / "progress.json"
APP_DB = DATA_DIR / "english_learning.sqlite"


COLORS = {
    "bg": "#f7f9fc",
    "sidebar": "#ffffff",
    "panel": "#ffffff",
    "panel_alt": "#f4f7fb",
    "line": "#e4e9f1",
    "text": "#10203f",
    "muted": "#66758f",
    "blue": "#2367f6",
    "blue_soft": "#eaf1ff",
    "pink": "#ef4d82",
    "pink_soft": "#ffe8f1",
    "yellow": "#f59e0b",
    "yellow_soft": "#fff5dc",
    "green": "#22a865",
    "green_soft": "#e5f7ed",
}

LIGHT_COLORS = COLORS.copy()
DARK_COLORS = {
    "bg": "#1b1c20",
    "sidebar": "#202228",
    "panel": "#2a2c33",
    "panel_alt": "#333642",
    "line": "#454955",
    "text": "#f2f4f8",
    "muted": "#b0b7c5",
    "blue": "#6d8cff",
    "blue_soft": "#273456",
    "pink": "#ef6bab",
    "pink_soft": "#49303f",
    "yellow": "#ffd166",
    "yellow_soft": "#4a412b",
    "green": "#55c583",
    "green_soft": "#2b4637",
}

TRANSLATIONS = {
    "English": {
        "window_title": "MemWord - English Learning Desktop",
        "sidebar": ["MemWord", "Vocabulary", "Study", "Statistics", "Categories", "Backup", "Settings", "Help"],
    },
    "Русский": {
        "window_title": "MemWord - изучение английского",
        "sidebar": ["MemWord", "Словарь", "Учёба", "Статистика", "Категории", "Бэкап", "Настройки", "Помощь"],
    },
}


connect_sqlite = database.connect_sqlite


def sql_quote(value: str) -> str:
    return value.replace("'", "''")


class BackupWorker(QThread):
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, action: str, path: Path):
        super().__init__()
        self.action = action
        self.path = path

    def run(self) -> None:
        try:
            if self.action == "import":
                backup_service.import_reword_backup(self.path)
                self.done.emit("Backup imported")
            else:
                backup_service.export_reword_backup(self.path)
                self.done.emit("Backup exported")
        except Exception as exc:
            self.failed.emit(str(exc))


class AudioWorker(QThread):
    ready = pyqtSignal(str)
    fallback = pyqtSignal(str, str, float)
    failed = pyqtSignal(str)

    def __init__(self, text: str, voice: str, rate: float):
        super().__init__()
        self.text = text
        self.voice = voice
        self.rate = rate

    def run(self) -> None:
        try:
            path = audio_service.synthesize_edge_tts(self.text, self.voice, self.rate)
            self.ready.emit(str(path))
        except ImportError:
            self.fallback.emit(self.text, self.voice, self.rate)
        except Exception as exc:
            self.failed.emit(str(exc))


class WordTableModel(QSqlTableModel):
    HEADERS = {
        1: "Word",
        2: "Translation",
        3: "Level",
        4: "Category",
        5: "Status",
        7: "Answers",
        8: "Series",
    }

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        value = super().data(index, role)
        if role == Qt.ItemDataRole.ForegroundRole:
            status = self.index(index.row(), 5).data()
            if status == "mastered":
                return QColor(COLORS["green"])
            if status == "review":
                return QColor(COLORS["yellow"])
            if status == "new":
                return QColor(COLORS["pink"])
        return value


class CategoryWordsDialog(QDialog):
    def __init__(self, category: str, db: QSqlDatabase, parent=None):
        super().__init__(parent)
        self.category = category
        self.db = db
        self.setWindowTitle(category)
        self.resize(1040, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel(category)
        title.setStyleSheet("font-size: 28px; font-weight: 800; color: #10203f;")
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet("color: #66758f; font-size: 15px;")
        title_box.addWidget(title)
        title_box.addWidget(self.stats_label)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        header.addLayout(title_box, 1)
        header.addWidget(close_btn)
        layout.addLayout(header)

        actions = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search words in this category...")
        self.search.textChanged.connect(self.apply_filter)
        open_main = QPushButton("Open in main list")
        open_main.setObjectName("primary")
        open_main.clicked.connect(self.open_in_main)
        start = QPushButton("Start category review")
        start.clicked.connect(self.start_review)
        actions.addWidget(self.search, 1)
        actions.addWidget(start)
        actions.addWidget(open_main)
        layout.addLayout(actions)

        self.model = WordTableModel(self, self.db)
        self.model.setTable("words")
        self.model.setEditStrategy(QSqlTableModel.EditStrategy.OnFieldChange)
        for column, title_text in WordTableModel.HEADERS.items():
            self.model.setHeaderData(column, Qt.Orientation.Horizontal, title_text)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column in [0, 6, 9, 10, 11, 12, 13]:
            self.table.hideColumn(column)
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(2, 360)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 190)
        self.table.setColumnWidth(5, 120)
        layout.addWidget(self.table, 1)

        self.setStyleSheet(
            f"""
            QDialog, QWidget {{
                background: {COLORS['bg']};
                color: {COLORS['text']};
                font-family: Segoe UI;
                font-size: 14px;
            }}
            QLineEdit {{
                background: {COLORS['panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['line']};
                border-radius: 10px;
                padding: 10px 14px;
                font-size: 15px;
            }}
            QPushButton {{
                background: {COLORS['panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['line']};
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: 600;
            }}
            QPushButton#primary {{
                background: {COLORS['blue']};
                color: #ffffff;
                border-color: {COLORS['blue']};
            }}
            QTableView {{
                background: {COLORS['panel']};
                alternate-background-color: #fbfcfe;
                color: {COLORS['text']};
                gridline-color: {COLORS['line']};
                border: 1px solid {COLORS['line']};
                border-radius: 10px;
                selection-background-color: {COLORS['blue_soft']};
                selection-color: {COLORS['text']};
            }}
            QHeaderView::section {{
                background: #fbfcfe;
                color: {COLORS['muted']};
                padding: 12px 10px;
                border: 0;
                border-bottom: 1px solid {COLORS['line']};
                font-weight: 700;
            }}
            """
        )
        self.apply_filter("")

    def category_where(self) -> str:
        return f"category = '{sql_quote(self.category)}'"

    def apply_filter(self, text: str) -> None:
        text = sql_quote(text.strip())
        filters = [self.category_where()]
        if text:
            filters.append(f"(word LIKE '%{text}%' OR translation LIKE '%{text}%' OR level LIKE '%{text}%')")
        self.model.setFilter(" AND ".join(filters))
        self.model.select()
        self.update_stats()

    def update_stats(self) -> None:
        con = connect_sqlite(APP_DB)
        total, mastered = con.execute(
            """
            SELECT
                COUNT(*),
                SUM(CASE WHEN status IN ('mastered', 'known') THEN 1 ELSE 0 END)
            FROM words
            WHERE category=?
            """,
            (self.category,),
        ).fetchone()
        con.close()
        total = int(total or 0)
        mastered = int(mastered or 0)
        percent = round(mastered * 100 / total) if total else 0
        self.stats_label.setText(f"{total} words    {percent}% mastered")

    def open_in_main(self) -> None:
        if self.parent() and hasattr(self.parent(), "open_category_in_main"):
            self.parent().open_category_in_main(self.category)
        self.accept()

    def start_review(self) -> None:
        if self.parent() and hasattr(self.parent(), "start_category_review"):
            self.parent().start_category_review(self.category)
        self.accept()


class WordEditDialog(QDialog):
    def __init__(self, word_id: int, parent=None):
        super().__init__(parent)
        self.word_id = word_id
        self.image_path = ""
        self.setWindowTitle("Edit word")
        self.resize(720, 680)

        con = connect_sqlite(APP_DB)
        self.row = con.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
        con.close()
        if not self.row:
            raise ValueError("Word not found")
        self.image_path = self.row["mnemonic_image"] or ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        title = QLabel("Edit word")
        title.setStyleSheet("font-size: 28px; font-weight: 800;")
        layout.addWidget(title)

        self.word_input = self.line("English word", self.row["word"] or "")
        self.transcription_input = self.line("Transcription (optional)", self.row["transcription"] or "")
        self.translation_input = self.line("Translation", self.row["translation"] or "")
        layout.addWidget(self.word_input)
        layout.addWidget(self.transcription_input)
        layout.addWidget(self.translation_input)

        translate_row = QHBoxLayout()
        auto_translate = QPushButton("Auto translate")
        auto_translate.setObjectName("primary")
        auto_translate.clicked.connect(self.auto_translate)
        reverso = QPushButton("Open in Reverso Context")
        reverso.clicked.connect(self.open_reverso_context)
        translate_row.addStretch(1)
        translate_row.addWidget(reverso)
        translate_row.addWidget(auto_translate)
        layout.addLayout(translate_row)

        image_row = QHBoxLayout()
        self.image_preview = QLabel("No mnemonic image")
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setFixedSize(220, 130)
        self.image_preview.setStyleSheet(f"border: 1px solid {COLORS['line']}; border-radius: 10px; color: {COLORS['muted']};")
        choose_image = QPushButton("Change mnemonic image")
        choose_image.clicked.connect(self.choose_image)
        clear_image = QPushButton("Remove image")
        clear_image.clicked.connect(self.clear_image)
        image_row.addWidget(self.image_preview)
        image_row.addWidget(choose_image)
        image_row.addWidget(clear_image)
        layout.addLayout(image_row)

        self.example_en_input = self.line("Example sentence in English", self.row["example_en"] or "")
        self.example_ru_input = self.line("Example translation", self.row["example_ru"] or "")
        layout.addWidget(self.example_en_input)
        layout.addWidget(self.example_ru_input)

        buttons = QHBoxLayout()
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self.setStyleSheet(
            f"""
            QDialog, QWidget {{ background: {COLORS['bg']}; color: {COLORS['text']}; font-family: Segoe UI; font-size: 14px; }}
            QLineEdit {{ background: {COLORS['panel']}; color: {COLORS['text']}; border: 1px solid {COLORS['line']}; border-radius: 10px; padding: 11px 14px; font-size: 16px; }}
            QPushButton {{ background: {COLORS['panel']}; color: {COLORS['text']}; border: 1px solid {COLORS['line']}; border-radius: 8px; padding: 10px 16px; font-weight: 600; }}
            QPushButton#primary {{ background: {COLORS['blue']}; color: #ffffff; border-color: {COLORS['blue']}; }}
            """
        )
        self.refresh_image_preview()

    def line(self, placeholder: str, value: str) -> QLineEdit:
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setText(value)
        return field

    def choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose mnemonic image",
            str(APP_DIR),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)",
        )
        if path:
            self.image_path = path
            self.refresh_image_preview()

    def clear_image(self) -> None:
        self.image_path = ""
        self.refresh_image_preview()

    def auto_translate(self) -> None:
        word = self.word_input.text().strip()
        if not word:
            QMessageBox.information(self, "Auto translate", "Enter an English word first.")
            return
        parent = self.parent()
        if not parent or not hasattr(parent, "setting_value"):
            QMessageBox.information(self, "Auto translate", "Settings are unavailable.")
            return
        provider = "MyMemory"
        try:
            translated = translation_service.translate_text(str(provider), word, parent.setting_value)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            QMessageBox.critical(self, f"{provider} error", f"HTTP {exc.code}\n{detail}")
            return
        except Exception as exc:
            QMessageBox.critical(self, f"{provider} error", str(exc))
            return
        self.translation_input.setText(translated)
        if not self.example_en_input.text().strip():
            self.example_en_input.setText(f"I want to remember the word {word}.")
        if not self.example_ru_input.text().strip():
            try:
                self.example_ru_input.setText(
                    translation_service.translate_text(str(provider), self.example_en_input.text().strip(), parent.setting_value)
                )
            except Exception:
                pass

    def open_reverso_context(self) -> None:
        word = self.word_input.text().strip()
        if not word:
            QMessageBox.information(self, "Reverso Context", "Enter an English word first.")
            return
        url = translation_service.reverso_context_url(word)
        QDesktopServices.openUrl(QUrl(url))

    def refresh_image_preview(self) -> None:
        if self.image_path and Path(self.image_path).exists():
            pixmap = QPixmap(self.image_path)
            self.image_preview.setPixmap(
                pixmap.scaled(220, 130, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
            return
        self.image_preview.setPixmap(QPixmap())
        self.image_preview.setText("No mnemonic image")

    def save(self) -> None:
        word = self.word_input.text().strip()
        if not word:
            QMessageBox.warning(self, "Edit word", "English word can not be empty.")
            return
        con = connect_sqlite(APP_DB)
        con.execute(
            """
            UPDATE words
            SET word=?, transcription=?, translation=?, mnemonic_image=?, example_en=?, example_ru=?
            WHERE id=?
            """,
            (
                word,
                self.transcription_input.text().strip(),
                self.translation_input.text().strip(),
                self.image_path,
                self.example_en_input.text().strip(),
                self.example_ru_input.text().strip(),
                self.word_id,
            ),
        )
        con.commit()
        con.close()
        self.accept()


class StatsChartWidget(QWidget):
    SERIES = [
        ("known", "Already known", "#cfd1d4"),
        ("new_learned", "New words learned", "#ef6bab"),
        ("reviewed", "Reviewed (unique)", "#ffd166"),
        ("mastered", "Mastered", "#55c583"),
    ]

    def __init__(self):
        super().__init__()
        self.days: list[str] = []
        self.data: dict[str, dict[str, int]] = {}
        self.setMinimumHeight(330)

    def set_stats(self, days: list[str], data: dict[str, dict[str, int]]) -> None:
        self.days = days
        self.data = data
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(COLORS["panel"]))

        left, top, right, bottom = 64, 28, 30, 46
        width = max(1, self.width() - left - right)
        height = max(1, self.height() - top - bottom)
        plot_left = left
        plot_top = top
        plot_bottom = top + height

        totals = [
            sum(self.data.get(day, {}).get(key, 0) for key, _, _ in self.SERIES)
            for day in self.days
        ]
        max_value = max(totals + [10])
        step = 30 if max_value <= 120 else max(50, ((max_value // 4 + 49) // 50) * 50)
        chart_max = max(step * 4, ((max_value + step - 1) // step) * step)

        grid_pen = QPen(QColor("#53565f"))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        label_color = QColor("#cfd3dc")
        for i in range(5):
            value = chart_max * i // 4
            y = plot_bottom - int(height * (value / chart_max))
            painter.drawLine(plot_left, y, plot_left + width, y)
            painter.setPen(label_color)
            painter.drawText(8, y - 9, 48, 18, Qt.AlignmentFlag.AlignRight, str(value))
            painter.setPen(grid_pen)

        if not self.days:
            painter.setPen(label_color)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No statistics yet")
            return

        slot = width / max(1, len(self.days))
        bar_width = max(12, min(46, int(slot * 0.48)))
        for index, day in enumerate(self.days):
            x = int(plot_left + slot * index + (slot - bar_width) / 2)
            y_cursor = plot_bottom
            for key, _, color in self.SERIES:
                value = self.data.get(day, {}).get(key, 0)
                if value <= 0:
                    continue
                bar_h = max(2, int(height * value / chart_max))
                y_cursor -= bar_h
                painter.fillRect(x, y_cursor, bar_width, bar_h, QColor(color))
                if bar_h > 18:
                    painter.setPen(QColor("#333333"))
                    painter.drawText(x, y_cursor + 2, bar_width, 18, Qt.AlignmentFlag.AlignCenter, str(value))

            painter.setPen(label_color)
            painter.drawText(
                int(plot_left + slot * index),
                plot_bottom + 8,
                int(slot),
                28,
                Qt.AlignmentFlag.AlignCenter,
                self.format_day_label(day),
            )

    def format_day_label(self, value: str) -> str:
        try:
            current = date.fromisoformat(value)
        except ValueError:
            return value
        if current == date.today():
            return "Today"
        return current.strftime("%d %b")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MemWord - English Learning Desktop")
        self.resize(1440, 900)
        self.worker = None
        self.active_category = ""
        self._updating_category_checks = False
        self.study_mode = "learn"
        self.audio_worker = None
        self.audio_output = QAudioOutput(self)
        self.audio_player = QMediaPlayer(self)
        self.audio_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.9)

        self.db = QSqlDatabase.addDatabase("QSQLITE")
        self.db.setDatabaseName(str(APP_DB))
        if not self.db.open():
            raise RuntimeError("Can not open SQLite database")
        self.apply_theme_colors(self.setting_value("theme", "Light"))

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(250)
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for title in self.sidebar_titles():
            item = QListWidgetItem(title)
            self.sidebar.addItem(item)
        layout.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        layout.addWidget(self.pages, 1)
        self.sidebar.currentRowChanged.connect(self.switch_page)

        self.pages.addWidget(self.build_dashboard_page())
        self.pages.addWidget(self.build_learn_page())
        self.pages.addWidget(self.build_menu_page())
        self.pages.addWidget(self.build_categories_page())
        self.pages.addWidget(self.build_dictionary_page())
        self.pages.addWidget(self.build_settings_page())
        self.pages.addWidget(self.build_statistics_page())
        self.sidebar.setCurrentRow(1)
        self.apply_style()
        self.apply_language(self.setting_value("ui_language", "Match system language"))

    def apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{
                background: {COLORS['bg']};
                color: {COLORS['text']};
                font-family: Segoe UI;
                font-size: 14px;
            }}
            QListWidget#sidebar {{
                background: {COLORS['sidebar']};
                border: 0;
                border-right: 1px solid {COLORS['line']};
                padding: 14px 12px;
                font-size: 15px;
            }}
            QListWidget#sidebar::item {{
                color: {COLORS['muted']};
                padding: 13px 16px;
                margin: 3px 0;
                border-radius: 8px;
            }}
            QListWidget#sidebar::item:first {{
                color: {COLORS['text']};
                font-size: 22px;
                font-weight: 800;
                padding: 18px 16px 22px 16px;
            }}
            QListWidget#sidebar::item:selected {{
                color: {COLORS['blue']};
                background: {COLORS['blue_soft']};
                font-weight: 700;
            }}
            QListWidget#sidebar::item:focus {{
                outline: none;
                border: 0;
            }}
            QFrame#card, QFrame#tableCard {{
                background: {COLORS['panel']};
                border: 1px solid {COLORS['line']};
                border-radius: 12px;
            }}
            QLabel#title {{
                color: {COLORS['text']};
                font-size: 22px;
                font-weight: 800;
            }}
            QLabel#muted {{
                color: {COLORS['muted']};
            }}
            QPushButton {{
                background: {COLORS['panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['line']};
                border-radius: 8px;
                padding: 10px 16px;
                font-size: 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {COLORS['panel_alt']};
                border-color: #cfd8e6;
            }}
            QPushButton#primary {{
                background: {COLORS['blue']};
                color: #ffffff;
                border-color: {COLORS['blue']};
            }}
            QPushButton#primary:hover {{
                background: #175ce5;
            }}
            QPushButton#ghost {{
                background: transparent;
            }}
            QLineEdit {{
                background: {COLORS['panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['line']};
                border-radius: 10px;
                padding: 10px 14px;
                font-size: 15px;
            }}
            QLineEdit:focus {{
                border-color: {COLORS['blue']};
            }}
            QScrollArea {{
                background: transparent;
                border: 0;
            }}
            QComboBox {{
                background: {COLORS['panel']};
                color: {COLORS['blue']};
                border: 1px solid {COLORS['line']};
                border-radius: 8px;
                padding: 8px 12px;
                font-weight: 600;
            }}
            QCheckBox {{
                color: {COLORS['text']};
                spacing: 10px;
                font-weight: 600;
            }}
            QCheckBox::indicator {{
                width: 44px;
                height: 24px;
                border-radius: 12px;
                background: #d5dbe6;
            }}
            QCheckBox::indicator:checked {{
                background: {COLORS['blue']};
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: #dfe5ee;
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {COLORS['blue']};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {COLORS['blue']};
                width: 20px;
                height: 20px;
                margin: -7px 0;
                border-radius: 10px;
            }}
            QTableView {{
                background: {COLORS['panel']};
                alternate-background-color: #fbfcfe;
                color: {COLORS['text']};
                gridline-color: {COLORS['line']};
                border: 0;
                font-size: 14px;
                selection-background-color: {COLORS['blue_soft']};
                selection-color: {COLORS['text']};
            }}
            QHeaderView::section {{
                background: #fbfcfe;
                color: {COLORS['muted']};
                padding: 12px 10px;
                border: 0;
                border-bottom: 1px solid {COLORS['line']};
                font-weight: 700;
            }}
            QListWidget#categoryList {{
                background: transparent;
                border: 0;
                font-size: 16px;
            }}
            QListWidget#categoryList::item {{
                background: {COLORS['panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['line']};
                border-radius: 10px;
                padding: 16px;
                margin: 5px 0;
            }}
            QListWidget#categoryList::item:hover {{
                background: {COLORS['panel_alt']};
            }}
            QListWidget#categoryList::item:selected {{
                background: {COLORS['blue_soft']};
                color: {COLORS['blue']};
                border-color: #c8d8ff;
            }}
            """
        )
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg"]))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
        self.setPalette(palette)

    def normalized_language(self, value: str | None = None) -> str:
        language = value or self.setting_value("ui_language", "Match system language")
        if language == "Русский":
            return "Русский"
        return "English"

    def sidebar_titles(self) -> list[str]:
        return TRANSLATIONS[self.normalized_language()]["sidebar"]

    def apply_language(self, value: str) -> None:
        language = self.normalized_language(value)
        self.setWindowTitle(TRANSLATIONS[language]["window_title"])
        titles = TRANSLATIONS[language]["sidebar"]
        for index, title in enumerate(titles):
            item = self.sidebar.item(index)
            if item:
                item.setText(title)
        category_choice = "Category choice" if language == "English" else "Выбор категорий"
        if self.sidebar.item(1):
            self.sidebar.item(1).setText(category_choice)
        dictionary_title = "Dictionary" if language == "English" else "Словарь"
        if self.sidebar.item(4):
            self.sidebar.item(4).setText(dictionary_title)

    def apply_theme_colors(self, value: str) -> None:
        theme = DARK_COLORS if value == "Dark" else LIGHT_COLORS
        COLORS.clear()
        COLORS.update(theme)

    def apply_theme(self, value: str) -> None:
        self.apply_theme_colors(value)
        self.apply_style()
        self.update_inline_styles()

    def update_inline_styles(self) -> None:
        if hasattr(self, "category_label"):
            self.category_label.setStyleSheet(f"color: {COLORS['blue']}; font-weight: 700;")

    def card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setFrameShape(QFrame.Shape.NoFrame)
        return frame

    def title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("title")
        return label

    def muted(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("muted")
        return label

    def switch_page(self, row: int) -> None:
        if row == 1:
            self.refresh_category_list()
            self.pages.setCurrentIndex(3)
            return
        if row == 4:
            self.refresh_dictionary_list()
            self.pages.setCurrentIndex(4)
            return
        if row == 2:
            self.pages.setCurrentIndex(1)
            self.study_mode = "learn"
            self.refresh_study_tabs()
            self.pick_random_word()
            return
        if row == 3:
            self.refresh_statistics()
            self.pages.setCurrentIndex(6)
            return
        if row == 6:
            self.pages.setCurrentIndex(5)
            return
        if row in (5, 7):
            self.pages.setCurrentIndex(2)
            return
        self.pages.setCurrentIndex(0)

    def setting_value(self, name: str, default):
        return settings_service.setting_value(name, default)

    def save_setting(self, name: str, value) -> None:
        settings_service.save_setting(name, value)

    def start_studying(self) -> None:
        self.pages.setCurrentIndex(1)
        self.pick_random_word()

    def study_tab_style(self, active: bool) -> str:
        if active:
            return "background: #343438; color: #f2f2f4; border: 0; border-radius: 22px; padding: 14px 42px; font-size: 24px; font-weight: 700;"
        return "background: transparent; color: #f2f2f4; border: 0; padding: 14px 30px; font-size: 24px; font-weight: 600;"

    def refresh_study_tabs(self) -> None:
        if hasattr(self, "learn_tab"):
            self.learn_tab.setStyleSheet(self.study_tab_style(self.study_mode == "learn"))
        if hasattr(self, "review_tab"):
            self.review_tab.setStyleSheet(self.study_tab_style(self.study_mode == "review"))

    def set_study_mode(self, mode: str) -> None:
        self.study_mode = "review" if mode == "review" else "learn"
        self.refresh_study_tabs()
        self.pick_random_word()

    def chosen_categories(self) -> list[str]:
        categories = self.setting_value("chosen_categories", [])
        if not isinstance(categories, list):
            return []
        return [str(category) for category in categories if str(category).strip()]

    def save_chosen_categories(self, categories: list[str]) -> None:
        unique_categories = sorted({category for category in categories if category})
        self.save_setting("chosen_categories", unique_categories)
        self.update_chosen_categories_label()

    def custom_categories(self) -> list[str]:
        categories = self.setting_value("custom_categories", [])
        if not isinstance(categories, list):
            return []
        return [str(category) for category in categories if str(category).strip()]

    def save_custom_categories(self, categories: list[str]) -> None:
        self.save_setting("custom_categories", sorted({category for category in categories if category}))

    def category_filter_sql(self, categories: list[str]) -> tuple[str, list[str]]:
        if not categories:
            return "", []
        return f"category IN ({','.join('?' for _ in categories)})", categories

    def update_chosen_categories_label(self) -> None:
        if not hasattr(self, "chosen_categories_label"):
            return
        categories = self.chosen_categories()
        if not categories:
            self.chosen_categories_label.setText("Выбрано для учёбы и повторения: ничего")
        elif len(categories) == 1:
            self.chosen_categories_label.setText(f"Выбрано для учёбы и повторения: {categories[0]}")
        else:
            preview = ", ".join(categories[:6])
            if len(categories) > 6:
                preview += f" и ещё {len(categories) - 6}"
            self.chosen_categories_label.setText(f"Выбрано для учёбы и повторения: {preview}")

    def stats(self) -> dict:
        return services.dashboard_stats()

    def stat_card(self, icon: str, title: str, value: str, subtitle: str, accent: str) -> QFrame:
        card = self.card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(18)

        icon_box = QLabel(icon)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box.setFixedSize(58, 58)
        icon_box.setStyleSheet(
            f"background: {accent}; border-radius: 12px; color: {COLORS['blue']}; font-size: 24px; font-weight: 800;"
        )

        text = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {COLORS['text']}; font-weight: 700;")
        value_label = QLabel(value)
        value_label.setStyleSheet("font-size: 28px; font-weight: 800;")
        subtitle_label = self.muted(subtitle)
        text.addWidget(title_label)
        text.addWidget(value_label)
        text.addWidget(subtitle_label)

        layout.addWidget(icon_box)
        layout.addLayout(text, 1)
        return card

    def build_statistics_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(
            """
            QWidget { background: #1b1c20; color: #f2f4f8; }
            QFrame#statsCard { background: #2a2c33; border: 0; border-radius: 24px; }
            QComboBox { background: #333642; color: #7f9bff; border: 1px solid #454955; border-radius: 8px; padding: 8px 12px; }
            QLabel { background: transparent; }
            QLabel#statsTitle { color: #f2f4f8; font-size: 36px; font-weight: 700; }
            QLabel#statsMuted { color: #b0b7c5; font-size: 18px; }
            QLabel#statsMain { color: #f2f4f8; font-size: 26px; font-weight: 700; }
            """
        )
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 26, 34, 34)
        layout.setSpacing(18)

        header = QHBoxLayout()
        logo = QLabel("<span style='color:#6d8cff;'>Mem</span>Word")
        logo.setObjectName("statsTitle")
        header.addStretch(1)
        header.addWidget(logo)
        header.addStretch(1)
        layout.addLayout(header)

        card = QFrame()
        card.setObjectName("statsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(34, 30, 34, 30)
        card_layout.setSpacing(18)

        period_row = QHBoxLayout()
        period_label = QLabel("Time period:")
        period_label.setStyleSheet("font-size: 26px; color: #f2f4f8;")
        self.stats_period_combo = QComboBox()
        self.stats_period_combo.addItems(["7 days", "30 days", "90 days", "Year", "All time"])
        self.stats_period_combo.currentTextChanged.connect(self.refresh_statistics)
        period_row.addWidget(period_label)
        period_row.addWidget(self.stats_period_combo)
        period_row.addStretch(1)
        card_layout.addLayout(period_row)

        self.stats_chart = StatsChartWidget()
        card_layout.addWidget(self.stats_chart)

        self.stats_learning_now = QLabel("Learning now: 0 new words")
        self.stats_learning_now.setObjectName("statsMain")
        card_layout.addWidget(self.stats_learning_now)

        summary = QGridLayout()
        summary.setHorizontalSpacing(28)
        summary.setVerticalSpacing(10)
        total_head = QLabel("Total")
        period_head = QLabel("Period")
        for label in (total_head, period_head):
            label.setObjectName("statsMuted")
        summary.addWidget(total_head, 0, 0)
        summary.addWidget(period_head, 0, 1)
        self.stats_summary_labels: dict[str, tuple[QLabel, QLabel]] = {}
        rows = [
            ("new_learned", "New words learned", "#ef6bab"),
            ("reviewed", "Reviewed (unique)", "#ffd166"),
            ("mastered", "Mastered", "#55c583"),
            ("known", "Already known", "#cfd1d4"),
        ]
        for row_index, (key, title, color) in enumerate(rows, start=1):
            total_value = QLabel("0")
            period_value = QLabel("0")
            legend = QLabel(f"<span style='color:{color}; font-size:24px;'>■</span>  {title}")
            for label in (total_value, period_value):
                label.setStyleSheet("font-size: 26px; color: #f2f4f8;")
            legend.setStyleSheet("font-size: 22px; color: #d8dbe2;")
            summary.addWidget(total_value, row_index, 0)
            summary.addWidget(period_value, row_index, 1)
            summary.addWidget(legend, row_index, 2)
            self.stats_summary_labels[key] = (total_value, period_value)
        card_layout.addLayout(summary)
        layout.addWidget(card, 1)
        self.refresh_statistics()
        return page

    def stats_period_days(self) -> list[str]:
        period = self.stats_period_combo.currentText() if hasattr(self, "stats_period_combo") else "7 days"
        return services.stats_period_days(period)

    def statistics_data(self, days: list[str]) -> tuple[dict[str, dict[str, int]], dict[str, int], dict[str, int], int]:
        return services.statistics_data(days, self.chosen_categories())

    def refresh_statistics(self) -> None:
        if not hasattr(self, "stats_chart"):
            return
        days = self.stats_period_days()
        data, period_totals, total_totals, learning_now = self.statistics_data(days)
        self.stats_chart.set_stats(days, data)
        self.stats_learning_now.setText(f"Learning now: {learning_now} new words")
        for key, labels in self.stats_summary_labels.items():
            total_label, period_label = labels
            total_label.setText(f"{total_totals.get(key, 0):,}")
            period_label.setText(f"{period_totals.get(key, 0):,}")

    def queue_row(self, count: int, title: str, subtitle: str, color: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 6, 0, 6)
        badge = QLabel(str(count))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(32, 32)
        badge.setStyleSheet(f"background: {color}; border-radius: 16px; font-weight: 800;")
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 700;")
        subtitle_label = self.muted(subtitle)
        arrow = QLabel(">")
        arrow.setStyleSheet(f"color: {COLORS['muted']}; font-size: 20px;")
        layout.addWidget(badge)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label, 1)
        layout.addWidget(arrow)
        return row

    def build_top_bar(self) -> QHBoxLayout:
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search words...")
        self.search.textChanged.connect(self.apply_filter)
        self.category_label = self.muted("All categories")
        self.category_label.setStyleSheet(f"color: {COLORS['blue']}; font-weight: 700;")
        clear_category = QPushButton("All categories")
        clear_category.clicked.connect(self.clear_category_filter)
        import_btn = QPushButton("Import backup")
        export_btn = QPushButton("Export backup")
        import_btn.clicked.connect(self.restore_backup)
        export_btn.clicked.connect(self.create_backup)
        top.addWidget(self.search, 1)
        top.addWidget(self.category_label)
        top.addWidget(clear_category)
        top.addWidget(import_btn)
        top.addWidget(export_btn)
        return top

    def build_dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 16, 18, 18)
        layout.setSpacing(16)
        layout.addLayout(self.build_top_bar())

        values = self.stats()
        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        cards.addWidget(self.stat_card("B", "Total words", f"{values['total']:,}", "All words in your library", COLORS["blue_soft"]), 0, 0)
        cards.addWidget(self.stat_card("C", "Due today", str(values["due"]), "Cards to review today", COLORS["yellow_soft"]), 0, 1)
        cards.addWidget(self.stat_card("T", "Mastered", f"{values['mastered']:,}", "Words you know well", COLORS["green_soft"]), 0, 2)
        cards.addWidget(self.stat_card("S", "Streak", "4 days", "Keep it going!", COLORS["pink_soft"]), 0, 3)
        layout.addLayout(cards)

        table_card = QFrame()
        table_card.setObjectName("tableCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(0, 0, 0, 12)
        table_layout.setSpacing(0)
        self.build_word_table()
        table_layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(18, 10, 18, 0)
        self.count_label = self.muted("")
        practice = QPushButton("Start studying")
        practice.setObjectName("primary")
        practice.clicked.connect(self.practice_selected)
        edit_selected = QPushButton("Edit selected")
        edit_selected.clicked.connect(self.edit_selected_word)
        footer.addWidget(self.count_label, 1)
        footer.addWidget(QLabel("Show"))
        footer.addWidget(QLabel("25"))
        footer.addWidget(edit_selected)
        footer.addWidget(practice)
        table_layout.addLayout(footer)
        layout.addWidget(table_card, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        bottom.addWidget(self.build_study_queue(values), 1)
        bottom.addWidget(self.build_timeline(values), 2)
        layout.addLayout(bottom)

        self.update_count()
        return page

    def build_word_table(self) -> None:
        self.model = WordTableModel(self, self.db)
        self.model.setTable("words")
        self.model.setEditStrategy(QSqlTableModel.EditStrategy.OnFieldChange)
        self.model.select()
        for column, title in WordTableModel.HEADERS.items():
            self.model.setHeaderData(column, Qt.Orientation.Horizontal, title)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column in [0, 6, 9, 10, 11, 12, 13]:
            self.table.hideColumn(column)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 300)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 190)
        self.table.setColumnWidth(5, 120)
        self.table.setColumnWidth(7, 90)
        self.table.setColumnWidth(8, 90)

    def build_study_queue(self, values: dict) -> QFrame:
        card = self.card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel(f"Study queue ({values['due']})")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        layout.addWidget(title)
        layout.addWidget(self.queue_row(values["review"], "Review", "Words to review", COLORS["yellow_soft"]))
        layout.addWidget(self.queue_row(values["new"], "New", "New words to learn", COLORS["blue_soft"]))
        layout.addWidget(self.queue_row(values["hard"], "Hard", "Struggling words", COLORS["pink_soft"]))
        layout.addStretch(1)
        buttons = QHBoxLayout()
        start = QPushButton("Start studying")
        start.setObjectName("primary")
        start.clicked.connect(self.start_studying)
        customize = QPushButton("Customize")
        customize.clicked.connect(lambda: QMessageBox.information(self, "Customize", "Training settings will be added here."))
        buttons.addWidget(start, 2)
        buttons.addWidget(customize, 1)
        layout.addLayout(buttons)
        return card

    def build_timeline(self, values: dict) -> QFrame:
        card = self.card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("Spaced repetition timeline")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        layout.addWidget(title)
        timeline = QLabel(f"Today {values['review']}  -  Tomorrow {max(values['new'], 1)}  -  Jun 7 24  -  Jun 8 16  -  Jun 9 12  -  Jun 10+ 42")
        timeline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timeline.setStyleSheet(
            f"background: {COLORS['panel_alt']}; border: 1px solid {COLORS['line']}; border-radius: 10px; padding: 26px; color: {COLORS['text']}; font-size: 15px;"
        )
        layout.addWidget(timeline, 1)
        row = QHBoxLayout()
        row.addWidget(self.muted(f"Total upcoming reviews: {values['due'] + 112}"), 1)
        row.addWidget(QPushButton("View calendar"))
        layout.addLayout(row)
        return card

    def settings_section(self, title: str, rows: list[QWidget]) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title_label = self.muted(title)
        title_label.setStyleSheet(f"color: {COLORS['muted']}; font-size: 16px; font-weight: 700; margin-left: 8px;")
        layout.addWidget(title_label)
        card = self.card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        for row in rows:
            card_layout.addWidget(row)
        layout.addWidget(card)
        return box

    def setting_row(self, title: str, subtitle: str = "", control: QWidget | None = None) -> QWidget:
        row = QWidget()
        row.setObjectName("settingRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(16)
        text = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet("background: transparent; border: 0; font-size: 17px; font-weight: 700;")
        text.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setStyleSheet(f"background: transparent; border: 0; color: {COLORS['blue']}; font-size: 14px;")
            text.addWidget(subtitle_label)
        layout.addLayout(text, 1)
        if control:
            layout.addWidget(control)
        row.setStyleSheet("QWidget#settingRow { border: 0; background: transparent; }")
        return row

    def choice_control(self, name: str, options: list[str], default: str) -> QComboBox:
        combo = QComboBox()
        combo.addItems(options)
        value = self.setting_value(name, default)
        if value in options:
            combo.setCurrentText(value)
        combo.currentTextChanged.connect(lambda value, key=name: self.setting_changed(key, value))
        return combo

    def text_control(self, name: str, default: str = "", password: bool = False) -> QLineEdit:
        field = QLineEdit()
        field.setText(str(self.setting_value(name, default) or ""))
        if password:
            field.setEchoMode(QLineEdit.EchoMode.Password)
        field.editingFinished.connect(lambda key=name, widget=field: self.setting_changed(key, widget.text().strip()))
        return field

    def setting_changed(self, name: str, value) -> None:
        self.save_setting(name, value)
        if name == "theme":
            self.apply_theme(value)
        elif name == "ui_language":
            self.apply_language(value)
        elif name == "daily_goal":
            services.set_daily_goal(int(value))
            self.update_daily_goal_progress()
        elif name in {"review_words_from", "new_word_mode", "review_mode", "display_new_first", "show_transcription"}:
            if hasattr(self, "model"):
                self.model.select()
            if getattr(self, "current_word_id", None):
                self.load_quiz_word(self.current_word_id)
        elif name == "auto_pronounce" and value and getattr(self, "current_english_word", ""):
            self.pronounce_english(self.current_english_word)

    def switch_control(self, name: str, default: bool) -> QCheckBox:
        checkbox = QCheckBox()
        checkbox.setChecked(bool(self.setting_value(name, default)))
        checkbox.stateChanged.connect(lambda _, key=name, widget=checkbox: self.setting_changed(key, widget.isChecked()))
        return checkbox

    def slider_control(self, name: str, default: float, value_label: QLabel) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(50, 200)
        slider.setValue(int(float(self.setting_value(name, default)) * 100))
        slider.valueChanged.connect(lambda value, key=name, label=value_label: self.update_speech_rate(key, value, label))
        return slider

    def update_speech_rate(self, name: str, value: int, value_label: QLabel) -> None:
        rate = round(value / 100, 2)
        value_label.setText(f"{rate:.2g}")
        self.setting_changed(name, rate)

    def build_settings_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(26, 18, 18, 18)
        outer.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.addWidget(self.title("Settings"))
        title_box.addWidget(self.muted("Configure learning, notifications, pronunciation and appearance."))
        header.addLayout(title_box, 1)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(18)

        layout.addWidget(
            self.settings_section(
                "Appearance",
                [
                    self.setting_row("Theme", "Light", self.choice_control("theme", ["Light", "Dark", "System"], "Light")),
                    self.setting_row("Turn on animation", "", self.switch_control("animation", True)),
                    self.setting_row("UI language", "Match system language", self.choice_control("ui_language", ["Match system language", "Русский", "English"], "Match system language")),
                ],
            )
        )
        layout.addWidget(
            self.settings_section(
                "General",
                [
                    self.setting_row("Native language", "Русский", self.choice_control("native_language", ["Русский", "English", "Українська"], "Русский")),
                    self.setting_row("Variety of English", "British", self.choice_control("english_variety", ["British", "American"], "British")),
                    self.setting_row("Enable the keyboard input exercise for words in", "English only", self.choice_control("keyboard_input", ["English only", "Russian only", "Both directions"], "English only")),
                    self.setting_row('Enable the "choose the correct word" exercise for words in', "English only", self.choice_control("choose_correct_word", ["English only", "Russian only", "Both directions"], "English only")),
                    self.setting_row("Display new words first in", "English", self.choice_control("display_new_first", ["English", "Russian", "Random"], "English")),
                    self.setting_row("New word learning mode", "Recall English word", self.choice_control("new_word_mode", ["Recall English word", "Recall translation", "Both directions"], "Recall English word")),
                    self.setting_row("Word review mode", "Recall English word", self.choice_control("review_mode", ["Recall English word", "Recall translation", "Both directions"], "Recall English word")),
                    self.setting_row('Review interval for words to become "Mastered"', "60 days", self.choice_control("mastered_interval", ["30 days", "60 days", "90 days"], "60 days")),
                    self.setting_row("Show transcription", "", self.switch_control("show_transcription", True)),
                    self.setting_row("Show pictures", "When translation is shown", self.choice_control("show_pictures", ["Never", "When translation is shown", "Always"], "When translation is shown")),
                    self.setting_row("Daily goal (new words learned)", "10", self.choice_control("daily_goal", ["5", "10", "15", "20", "30"], "10")),
                    self.setting_row("Review words from", "Chosen categories only", self.choice_control("review_words_from", ["Chosen categories only", "All categories", "Due words only"], "Chosen categories only")),
                    self.setting_row("Invert swipe direction", "", self.switch_control("invert_swipe", False)),
                ],
            )
        )
        layout.addWidget(
            self.settings_section(
                "Notifications",
                [
                    self.setting_row("Enable notifications", "", self.switch_control("notifications", False)),
                    self.setting_row("Silent mode", "22:00 - 08:00", self.choice_control("silent_mode", ["22:00 - 08:00", "23:00 - 07:00", "Off"], "22:00 - 08:00")),
                    self.setting_row("Notification frequency limit", "Once in 2 hours", self.choice_control("notification_frequency", ["Once in 1 hour", "Once in 2 hours", "Once in 4 hours"], "Once in 2 hours")),
                ],
            )
        )
        layout.addWidget(
            self.settings_section(
                "Integrations",
                [
                    self.setting_row("Auto translate provider", "MyMemory free API", QLabel("MyMemory")),
                    self.setting_row("MyMemory source language", "English", self.choice_control("mymemory_source_lang", ["en", "ru", "de", "fr", "es"], "en")),
                    self.setting_row("MyMemory target language", "Russian", self.choice_control("mymemory_target_lang", ["ru", "en", "de", "fr", "es"], "ru")),
                    self.setting_row("MyMemory email", "Optional. Increases free daily limit.", self.text_control("mymemory_email", "")),
                    self.setting_row("Context examples", "Opens the current word in browser", QLabel("Reverso Context")),
                ],
            )
        )

        rate_value = QLabel(f"{float(self.setting_value('speech_rate', 1.0)):.2g}")
        rate_value.setStyleSheet(f"color: {COLORS['blue']}; font-weight: 800; min-width: 42px;")
        rate_row_control = QWidget()
        rate_layout = QHBoxLayout(rate_row_control)
        rate_layout.setContentsMargins(0, 0, 0, 0)
        rate_layout.addWidget(rate_value)
        rate_layout.addWidget(self.slider_control("speech_rate", 1.0, rate_value), 1)
        layout.addWidget(
            self.settings_section(
                "Pronunciation",
                [
                    self.setting_row("Automatically pronounce English words", "", self.switch_control("auto_pronounce", True)),
                    self.setting_row(
                        "Robot voice",
                        "Microsoft Edge Natural Voice",
                        self.choice_control(
                            "robot_voice",
                            [
                                "Edge Jenny Natural",
                                "Edge Guy Natural",
                                "Edge Aria Natural",
                                "Edge Sonia Natural",
                                "Edge Ryan Natural",
                                "System text-to-speech engine",
                                "Microsoft David",
                                "Microsoft Zira",
                            ],
                            "Edge Jenny Natural",
                        ),
                    ),
                    self.setting_row("Robot speech rate", "1.0", rate_row_control),
                ],
            )
        )
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        return page

    def category_stats(self) -> list[dict]:
        categories = category_service.category_stats()
        existing = {category["name"] for category in categories}
        for name in self.custom_categories():
            if name not in existing:
                categories.append({"name": name, "total": 0, "mastered": 0, "percent": 0})
        return categories

    def build_categories_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 18, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.addWidget(self.title("Выбор категорий"))
        title_box.addWidget(self.muted("Отмеченные категории используются только для разделов Учёба и Повторение."))
        self.chosen_categories_label = self.muted("")
        title_box.addWidget(self.chosen_categories_label)
        start_btn = QPushButton("Начать учёбу")
        start_btn.setObjectName("primary")
        start_btn.clicked.connect(self.start_studying)
        clear_btn = QPushButton("Сбросить выбор")
        clear_btn.clicked.connect(self.clear_chosen_categories)
        import_btn = QPushButton("Import backup")
        import_btn.clicked.connect(self.restore_backup)
        add_btn = QPushButton("Добавить категорию")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self.add_category)
        header.addLayout(title_box, 1)
        header.addWidget(start_btn)
        header.addWidget(clear_btn)
        header.addWidget(import_btn)
        layout.addLayout(header)

        self.category_list = QListWidget()
        self.category_list.setObjectName("categoryList")
        self.category_list.itemActivated.connect(self.open_category_item)
        self.category_list.itemDoubleClicked.connect(self.open_category_item)
        self.category_list.itemChanged.connect(self.category_check_changed)
        layout.addWidget(self.category_list, 1)

        self.refresh_category_list()
        return page

    def build_dictionary_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 18, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        add_btn = QPushButton("Добавить категорию")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self.add_category)
        header.addStretch(1)
        header.addWidget(add_btn)
        layout.addLayout(header)

        self.dictionary_category_list = QListWidget()
        self.dictionary_category_list.setObjectName("categoryList")
        self.dictionary_category_list.itemActivated.connect(self.open_category_item)
        self.dictionary_category_list.itemDoubleClicked.connect(self.open_category_item)
        layout.addWidget(self.dictionary_category_list, 1)

        self.refresh_dictionary_list()
        return page

    def refresh_dictionary_list(self) -> None:
        if not hasattr(self, "dictionary_category_list"):
            return
        self.dictionary_category_list.clear()
        for category in self.category_stats():
            item = QListWidgetItem(
                f"{category['name']}\n{category['total']} words    {category['percent']}% mastered"
            )
            item.setData(Qt.ItemDataRole.UserRole, category["name"])
            self.dictionary_category_list.addItem(item)

    def add_category(self) -> None:
        name, accepted = QInputDialog.getText(self, "Добавить категорию", "Название категории:")
        if not accepted:
            return
        name = name.strip()
        if not name:
            return
        names = {category["name"] for category in self.category_stats()}
        if name in names:
            QMessageBox.information(self, "Категория", "Такая категория уже есть.")
            return
        self.save_custom_categories(self.custom_categories() + [name])
        self.refresh_category_list()
        self.refresh_dictionary_list()

    def clear_chosen_categories(self) -> None:
        self.save_chosen_categories([])
        self.refresh_category_list()

    def refresh_category_list(self) -> None:
        if not hasattr(self, "category_list"):
            return
        self._updating_category_checks = True
        self.category_list.clear()
        chosen = set(self.chosen_categories())
        for category in self.category_stats():
            item = QListWidgetItem(
                f"{category['name']}\n{category['total']} words    {category['percent']}% mastered"
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(Qt.ItemDataRole.UserRole, category["name"])
            item.setCheckState(Qt.CheckState.Checked if category["name"] in chosen else Qt.CheckState.Unchecked)
            self.category_list.addItem(item)
        self._updating_category_checks = False
        self.update_chosen_categories_label()

    def category_check_changed(self, item: QListWidgetItem) -> None:
        if self._updating_category_checks:
            return
        category = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if category:
            chosen = []
            for index in range(self.category_list.count()):
                category_item = self.category_list.item(index)
                if category_item.checkState() == Qt.CheckState.Checked:
                    chosen.append(str(category_item.data(Qt.ItemDataRole.UserRole) or ""))
            self.save_chosen_categories(chosen)

    def open_category_item(self, item: QListWidgetItem) -> None:
        category = item.data(Qt.ItemDataRole.UserRole) or ""
        self.open_category(str(category))

    def open_category(self, category: str) -> None:
        if not category:
            self.clear_category_filter()
            return
        dialog = CategoryWordsDialog(category, self.db, self)
        dialog.exec()

    def open_category_in_main(self, category: str) -> None:
        self.active_category = category
        if hasattr(self, "category_label"):
            self.category_label.setText(category if category else "All categories")
        self.apply_filter(self.search.text() if hasattr(self, "search") else "")
        self.pages.setCurrentIndex(0)
        self.sidebar.setCurrentRow(1)

    def clear_category_filter(self) -> None:
        self.active_category = ""
        if hasattr(self, "category_label"):
            self.category_label.setText("All categories")
        self.apply_filter(self.search.text() if hasattr(self, "search") else "")
        self.pages.setCurrentIndex(0)
        self.sidebar.setCurrentRow(1)

    def start_category_review(self, category: str) -> None:
        self.save_chosen_categories([category])
        if hasattr(self, "category_list"):
            self.refresh_category_list()
        con = connect_sqlite(APP_DB)
        row = con.execute(
            "SELECT id FROM words WHERE category=? AND status IN ('new','review') ORDER BY RANDOM() LIMIT 1",
            (category,),
        ).fetchone()
        if not row:
            row = con.execute("SELECT id FROM words WHERE category=? ORDER BY RANDOM() LIMIT 1", (category,)).fetchone()
        con.close()
        if row:
            self.load_quiz_word(int(row["id"]))
            self.pages.setCurrentIndex(1)
            self.sidebar.setCurrentRow(2)

    def chosen_review_categories(self) -> list[str]:
        return self.chosen_categories()

    def review_status_filter(self) -> str:
        if self.study_mode == "review":
            return "status='review'"
        return "status='new'"

    def prompt_mode_for_word(self, row) -> str:
        if row["status"] == "new":
            return self.setting_value("new_word_mode", "Recall English word")
        return self.setting_value("review_mode", "Recall English word")

    def prompt_for_word(self, row) -> tuple[str, str]:
        mode = self.prompt_mode_for_word(row)
        display_new = self.setting_value("display_new_first", "English")
        if row["status"] == "new" and display_new == "Russian":
            mode = "Recall English word"
        if mode == "Recall translation":
            return str(row["word"] or ""), str(row["translation"] or "")
        if mode == "Both directions" and int(row["id"] or 0) % 2 == 0:
            return str(row["translation"] or ""), str(row["word"] or "")
        return str(row["translation"] or ""), str(row["word"] or "")

    def pronounce_english(self, text: str) -> None:
        if not text or not self.setting_value("auto_pronounce", True):
            return
        voice = self.setting_value("robot_voice", "System text-to-speech engine")
        rate = float(self.setting_value("speech_rate", 1.0) or 1.0)
        if str(voice).startswith("Edge "):
            self.audio_worker = AudioWorker(text.strip(), voice, rate)
            self.audio_worker.ready.connect(self.play_audio_file)
            self.audio_worker.fallback.connect(self.play_windows_tts)
            self.audio_worker.failed.connect(lambda _message: self.play_windows_tts(text.strip(), "System text-to-speech engine", rate))
            self.audio_worker.start()
            return
        self.play_windows_tts(text.strip(), voice, rate)

    def play_audio_file(self, path: str) -> None:
        self.audio_player.stop()
        self.audio_player.setSource(QUrl.fromLocalFile(path))
        self.audio_player.play()

    def play_windows_tts(self, text: str, voice: str, rate: float) -> None:
        try:
            audio_service.speak_with_windows_sapi(text, voice, rate)
        except OSError:
            pass

    def build_learn_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("studyPage")
        page.setStyleSheet("QWidget#studyPage { background: #111112; color: #f2f2f4; }")
        outer_layout = QVBoxLayout(page)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        content = QWidget()
        content.setObjectName("studyContent")
        content.setMaximumWidth(1500)
        content.setStyleSheet("QWidget#studyContent { background: #111112; }")

        layout = QVBoxLayout(content)
        layout.setContentsMargins(34, 16, 34, 18)
        layout.setSpacing(12)

        top = QHBoxLayout()
        back_btn = QPushButton("<")
        back_btn.setFixedSize(58, 48)
        back_btn.setStyleSheet("font-size: 34px; border: 0; background: transparent; color: #f2f2f4;")
        back_btn.clicked.connect(lambda: self.sidebar.setCurrentRow(1))
        self.learn_tab = QPushButton("Learn new\nwords")
        self.learn_tab.clicked.connect(lambda: self.set_study_mode("learn"))
        self.review_tab = QPushButton("Review words")
        self.review_tab.clicked.connect(lambda: self.set_study_mode("review"))
        self.refresh_study_tabs()
        review_badge = QLabel("48")
        review_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        review_badge.setFixedSize(42, 42)
        review_badge.setStyleSheet("background: #6d8cff; color: #f2f2f4; border-radius: 21px; font-size: 20px;")
        top.addWidget(back_btn)
        top.addStretch(1)
        top.addWidget(self.learn_tab)
        top.addSpacing(24)
        top.addWidget(self.review_tab)
        top.addWidget(review_badge)
        top.addStretch(1)
        layout.addLayout(top)

        progress_row = QHBoxLayout()
        self.study_counter_label = QLabel("0 new words learned")
        self.study_counter_label.setStyleSheet("background: transparent; color: #9aa0a8; font-size: 22px;")
        undo_btn = QPushButton("↶")
        undo_btn.setFixedSize(56, 46)
        undo_btn.setStyleSheet("font-size: 34px; border: 0; background: transparent; color: #6d8cff;")
        undo_btn.clicked.connect(self.pick_random_word)
        progress_row.addWidget(self.study_counter_label)
        progress_row.addStretch(1)
        progress_row.addWidget(undo_btn)
        layout.addLayout(progress_row)

        self.daily_goal_marks = QLabel("")
        self.daily_goal_marks.setStyleSheet("background: transparent; color: #3b3b3d; font-size: 22px;")
        layout.addWidget(self.daily_goal_marks)

        card = QFrame()
        card.setObjectName("studyCard")
        card.setStyleSheet("QFrame#studyCard { background: #222224; border: 0; border-radius: 24px; }")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(34, 20, 34, 18)
        card_layout.setSpacing(10)

        meta_row = QHBoxLayout()
        marker = QLabel("")
        marker.setFixedSize(20, 20)
        marker.setStyleSheet("background: #686b70; border-radius: 4px;")
        self.study_category_label = QLabel("New word")
        self.study_category_label.setStyleSheet("background: transparent; font-size: 22px; color: #f0f0f2;")
        edit_btn = QPushButton("...")
        edit_btn.setFixedSize(54, 42)
        edit_btn.setStyleSheet("font-size: 28px; border: 0; background: transparent; color: #f0f0f2;")
        edit_btn.clicked.connect(self.edit_current_word)
        meta_row.addWidget(marker)
        meta_row.addWidget(self.study_category_label)
        meta_row.addStretch(1)
        meta_row.addWidget(edit_btn)
        card_layout.addLayout(meta_row)

        self.quiz_label = QLabel("Choose a word")
        self.quiz_label.setWordWrap(True)
        self.quiz_label.setMinimumHeight(44)
        self.quiz_label.setMaximumHeight(74)
        self.quiz_label.setStyleSheet("background: transparent; font-size: 32px; font-weight: 600; color: #f2f2f4;")
        self.transcription_label = QLabel("")
        self.transcription_label.setMaximumHeight(42)
        self.transcription_label.setStyleSheet("background: transparent; font-size: 22px; color: #cfd0d4;")
        self.mnemonic_preview = QLabel("")
        self.mnemonic_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mnemonic_preview.setFixedHeight(118)
        self.mnemonic_preview.setStyleSheet("background: #19191b; border: 0; border-radius: 18px; color: #8f949d; font-size: 16px;")
        play_word = QPushButton("▶")
        play_word.setFixedSize(58, 58)
        play_word.setStyleSheet("background: #6d8cff; color: #111112; border: 0; border-radius: 29px; font-size: 22px;")
        play_word.clicked.connect(lambda: self.pronounce_english(getattr(self, "current_english_word", "")))
        word_row = QHBoxLayout()
        word_text = QVBoxLayout()
        word_text.addWidget(self.quiz_label)
        word_text.addWidget(self.transcription_label)
        word_row.addLayout(word_text, 1)
        word_row.addWidget(play_word)

        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background: #151516;")

        self.translation_label = QLabel("")
        self.translation_label.setWordWrap(True)
        self.translation_label.setMinimumHeight(42)
        self.translation_label.setMaximumHeight(72)
        self.translation_label.setStyleSheet("background: transparent; font-size: 28px; color: #f2f2f4;")
        self.example_label = QLabel("")
        self.example_label.setWordWrap(True)
        self.example_label.setMaximumHeight(52)
        self.example_label.setStyleSheet("background: transparent; color: #d9dadd; font-size: 18px;")
        self.attempts_label = QLabel("Attempts left: 3")
        self.attempts_label.setStyleSheet("background: transparent; color: #6d8cff; font-size: 16px; font-weight: 800;")
        self.answer = QLineEdit()
        self.answer.setPlaceholderText("Type translation")
        self.answer.returnPressed.connect(self.check_answer)
        self.answer.setStyleSheet("background: #19191b; color: #f2f2f4; border: 1px solid #4d5f94; border-radius: 10px; padding: 10px 14px; font-size: 18px;")
        row = QHBoxLayout()
        known_btn = QPushButton("I already know\nthis word")
        known_btn.setStyleSheet("background: transparent; color: #e8e8ea; border: 0; font-size: 20px;")
        known_btn.clicked.connect(self.mark_current_known)
        prev_btn = QPushButton("‹")
        prev_btn.setStyleSheet("background: transparent; color: #cfd0d4; border: 0; font-size: 36px;")
        prev_btn.clicked.connect(self.pick_random_word)
        next_btn = QPushButton("›")
        next_btn.setStyleSheet("background: transparent; color: #cfd0d4; border: 0; font-size: 36px;")
        next_btn.clicked.connect(self.pick_random_word)
        check = QPushButton("Start learning\nthis word")
        check.setStyleSheet("background: transparent; color: #e8e8ea; border: 0; font-size: 20px;")
        check.clicked.connect(self.check_answer)
        row.addWidget(known_btn)
        row.addStretch(1)
        row.addWidget(prev_btn)
        row.addWidget(next_btn)
        row.addStretch(1)
        row.addWidget(check)
        self.result_label = QLabel("")
        self.result_label.setStyleSheet("background: transparent; color: #6d8cff; font-size: 18px;")
        self.current_word_id = None
        self.attempts_left = 3
        card_layout.addLayout(word_row)
        card_layout.addWidget(self.mnemonic_preview)
        card_layout.addWidget(separator)
        card_layout.addWidget(self.translation_label)
        card_layout.addWidget(self.example_label)
        card_layout.addWidget(self.attempts_label)
        card_layout.addWidget(self.answer)
        card_layout.addLayout(row)
        card_layout.addWidget(self.result_label)
        layout.addWidget(card)
        layout.addStretch(1)
        outer_layout.addWidget(content, 1, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.update_daily_goal_progress()
        return page

    def build_vocabulary_page(self) -> QWidget:
        return self.build_dashboard_page()

    def daily_goal_value(self) -> int:
        return services.daily_goal_value(int(self.setting_value("daily_goal", 10) or 10))

    def daily_learned_key(self) -> str:
        return f"daily_learned.{time.strftime('%Y-%m-%d')}"

    def learned_new_words_today(self) -> int:
        return services.learned_new_words_today()

    def increment_daily_learned(self) -> None:
        services.increment_daily_learned()

    def record_study_event(self, word_id: int | None, event_type: str) -> None:
        services.record_study_event(word_id, event_type)
        self.refresh_statistics()

    def update_daily_goal_progress(self) -> None:
        if not hasattr(self, "study_counter_label") or not hasattr(self, "daily_goal_marks"):
            return
        goal = self.daily_goal_value()
        learned = min(self.learned_new_words_today(), goal)
        self.study_counter_label.setText(f"{learned}/{goal} new words learned")
        marks = "".join(
            f"<span style='color:#6d8cff;'>━</span>" if index < learned else f"<span style='color:#3b3b3d;'>━</span>"
            for index in range(goal)
        )
        self.daily_goal_marks.setText(f"<span style='font-size:28px; letter-spacing:6px;'>{marks}</span>")

    def build_menu_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 26, 34, 34)
        layout.addWidget(self.title("Menu"))
        card = self.card()
        card_layout = QVBoxLayout(card)
        import_btn = QPushButton("Import backup")
        export_btn = QPushButton("Export backup")
        import_btn.setObjectName("primary")
        export_btn.setObjectName("primary")
        import_btn.clicked.connect(self.restore_backup)
        export_btn.clicked.connect(self.create_backup)
        self.status_label = QLabel("Ready")
        card_layout.addWidget(import_btn)
        card_layout.addWidget(export_btn)
        card_layout.addWidget(self.status_label)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def apply_filter(self, text: str) -> None:
        text = text.strip().replace("'", "''")
        filters = []
        if self.active_category:
            filters.append(f"category = '{sql_quote(self.active_category)}'")
        if text:
            filters.append(f"(word LIKE '%{text}%' OR translation LIKE '%{text}%' OR category LIKE '%{text}%')")
        self.model.setFilter(" AND ".join(filters))
        self.model.select()
        self.update_count()

    def update_count(self) -> None:
        con = connect_sqlite(APP_DB)
        total = con.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        if self.active_category:
            shown = con.execute("SELECT COUNT(*) FROM words WHERE category=?", (self.active_category,)).fetchone()[0]
            label = f"{shown} words in {self.active_category}. Total words: {total}"
        else:
            label = f"Rows loaded by Qt model. Total words: {total}"
        con.close()
        self.count_label.setText(label)

    def selected_word_id(self):
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return self.model.index(index.row(), 0).data()

    def edit_current_word(self) -> None:
        if not self.current_word_id:
            QMessageBox.information(self, "Edit word", "Choose a word first.")
            return
        dialog = WordEditDialog(int(self.current_word_id), self)
        if dialog.exec():
            self.model.select()
            self.load_quiz_word(int(self.current_word_id))

    def edit_selected_word(self) -> None:
        word_id = self.selected_word_id()
        if not word_id:
            QMessageBox.information(self, "Edit word", "Select a word first.")
            return
        dialog = WordEditDialog(int(word_id), self)
        if dialog.exec():
            self.model.select()
            self.update_count()

    def practice_selected(self) -> None:
        word_id = self.selected_word_id()
        if not word_id:
            QMessageBox.information(self, "Practice", "Select a word first.")
            return
        self.load_quiz_word(int(word_id))
        self.sidebar.setCurrentRow(2)

    def pick_random_word(self) -> None:
        categories = self.chosen_review_categories()
        if not categories:
            QMessageBox.information(self, "Study", "Choose at least one category in Categories first.")
            self.refresh_category_list()
            self.pages.setCurrentIndex(3)
            self.sidebar.setCurrentRow(1)
            return
        word_id = services.find_random_word_id(self.study_mode, categories)
        if word_id:
            self.load_quiz_word(word_id)
        else:
            message = "No review words found for the chosen categories." if self.study_mode == "review" else "No new words found for the chosen categories."
            QMessageBox.information(self, "Study", message)

    def load_quiz_word(self, word_id: int) -> None:
        row = services.get_word(word_id)
        if not row:
            return
        self.current_word_id = word_id
        self.attempts_left = 3
        prompt, correct = self.prompt_for_word(row)
        self.current_correct_answer = correct.strip().lower()
        self.current_english_word = str(row["word"] or "")
        transcription = f" · {row['transcription']}" if self.setting_value("show_transcription", True) and row["transcription"] else ""
        self.quiz_label.setText(f"{prompt}  ·  {row['category']}  ·  {row['level']}{transcription}")
        clean_transcription = str(row["transcription"] or "") if self.setting_value("show_transcription", True) else ""
        if hasattr(self, "study_category_label"):
            status_title = "New word" if row["status"] == "new" else "Review"
            self.study_category_label.setText(f"{status_title}  ·  {row['category']}")
        self.quiz_label.setText(str(row["word"] or prompt))
        if hasattr(self, "transcription_label"):
            self.transcription_label.setText(clean_transcription)
        if hasattr(self, "translation_label"):
            self.translation_label.setText(str(row["translation"] or correct))
        self.attempts_label.setText("Attempts left: 3")
        self.update_mnemonic_preview(row["mnemonic_image"] or "")
        self.update_examples(row["example_en"] or "", row["example_ru"] or "")
        self.answer.clear()
        self.result_label.setText("")
        self.answer.setFocus()
        self.pronounce_english(self.current_english_word)

    def update_mnemonic_preview(self, image_path: str) -> None:
        if image_path and Path(image_path).exists():
            pixmap = QPixmap(image_path)
            self.mnemonic_preview.setPixmap(
                pixmap.scaled(460, 108, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
            self.mnemonic_preview.setText("")
            return
        self.mnemonic_preview.setPixmap(QPixmap())
        self.mnemonic_preview.setText("No mnemonic image")

    def update_examples(self, example_en: str, example_ru: str) -> None:
        if example_en or example_ru:
            self.example_label.setText(f"{example_en}\n{example_ru}".strip())
        else:
            self.example_label.setText("No example sentence yet. Use Edit word to add one.")

    def mark_current_known(self) -> None:
        if not self.current_word_id:
            return
        services.mark_known(int(self.current_word_id))
        self.refresh_statistics()
        self.result_label.setText("Marked as known")
        self.model.select()
        self.update_daily_goal_progress()
        self.pick_random_word()

    def check_answer(self) -> None:
        if not self.current_word_id:
            return
        raw_answer = self.answer.text().strip()
        result = services.check_answer(
            int(self.current_word_id),
            raw_answer,
            getattr(self, "current_correct_answer", ""),
            int(getattr(self, "attempts_left", 3)),
        )
        self.attempts_left = result.attempts_left
        self.attempts_label.setText(f"Attempts left: {self.attempts_left}")
        if not raw_answer:
            self.result_label.setText(result.message)
            self.answer.setFocus()
            return
        message = result.message
        if not result.is_correct and self.attempts_left > 0:
            self.result_label.setText(message)
            self.answer.selectAll()
            self.answer.setFocus()
            return
        show_pictures = self.setting_value("show_pictures", "When translation is shown")
        if show_pictures == "Always" or (show_pictures == "When translation is shown" and not result.is_correct):
            message += "  Â·  Picture area enabled"
        self.result_label.setText(message)
        self.model.select()
        self.refresh_statistics()
        self.update_daily_goal_progress()
        return

    def restore_backup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose ReWord backup", str(APP_DIR), "Backup files (*.backup *.sqlite *.db);;All files (*.*)")
        if path:
            self.run_worker("import", Path(path))

    def create_backup(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save ReWord backup", str(APP_DIR / "reword_desktop.backup"), "ReWord backup (*.backup);;SQLite (*.sqlite);;All files (*.*)")
        if path:
            self.run_worker("export", Path(path))

    def run_worker(self, action: str, path: Path) -> None:
        self.status_label.setText("Working...")
        self.worker = BackupWorker(action, path)
        self.worker.done.connect(self.worker_done)
        self.worker.failed.connect(self.worker_failed)
        self.worker.start()

    def worker_done(self, message: str) -> None:
        self.status_label.setText(message)
        self.model.select()
        self.update_count()
        self.refresh_category_list()
        self.refresh_dictionary_list()
        QMessageBox.information(self, "Done", message)

    def worker_failed(self, message: str) -> None:
        self.status_label.setText("Error")
        QMessageBox.critical(self, "Error", message)


def main() -> int:
    database.ensure_database()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
