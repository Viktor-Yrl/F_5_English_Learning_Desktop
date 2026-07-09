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
from PyQt6.QtCore import QPointF, QRectF, QSize, QTimer, QUrl, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPainter, QPalette, QPen, QPixmap, QPolygonF
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
        "sidebar": ["MemWord", "Search", "Category choice", "Study", "English rules", "Statistics", "Dictionary", "Settings", "About"],
    },
    "Русский": {
        "window_title": "MemWord - изучение английского",
        "sidebar": ["MemWord", "Search", "Category choice", "Study", "English rules", "Statistics", "Dictionary", "Settings", "About"],
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


class PillSwitch(QCheckBox):
    def __init__(self):
        super().__init__()
        self.setFixedSize(56, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setText("")
        self.stateChanged.connect(lambda _: self.update())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        checked = self.isChecked()
        track_color = QColor(COLORS["blue"] if checked else COLORS["panel_alt"])
        border_color = QColor(COLORS["blue"] if checked else COLORS["line"])
        knob_color = QColor("#ffffff" if checked else COLORS["muted"])

        painter.setPen(QPen(border_color, 1))
        painter.setBrush(track_color)
        painter.drawRoundedRect(1, 1, 54, 28, 14, 14)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob_color)
        knob_x = 29 if checked else 4
        painter.drawEllipse(knob_x, 4, 22, 22)


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
        palette = self.table.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["panel"]))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["panel_alt"]))
        palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
        self.table.setPalette(palette)
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
                alternate-background-color: {COLORS['panel_alt']};
                color: {COLORS['text']};
                gridline-color: {COLORS['line']};
                border: 1px solid {COLORS['line']};
                border-radius: 10px;
                selection-background-color: {COLORS['blue_soft']};
                selection-color: {COLORS['text']};
            }}
            QHeaderView::section {{
                background: {COLORS['panel_alt']};
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
    def __init__(self, word_id: int | None = None, parent=None):
        super().__init__(parent)
        self.word_id = word_id
        self.is_new = word_id is None
        self.image_path = ""
        self.setWindowTitle("Add word" if self.is_new else "Edit word")
        self.resize(720, 680)

        if self.is_new:
            self.row = {
                "word": "",
                "translation": "",
                "level": "A1",
                "category": self.default_category(),
                "status": "new",
                "transcription": "",
                "mnemonic_image": "",
                "example_en": "",
                "example_ru": "",
            }
        else:
            con = connect_sqlite(APP_DB)
            self.row = con.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
            con.close()
            if not self.row:
                raise ValueError("Word not found")
        self.image_path = self.row["mnemonic_image"] or ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        title = QLabel("Add word" if self.is_new else "Edit word")
        title.setStyleSheet("font-size: 28px; font-weight: 800;")
        layout.addWidget(title)

        self.word_input = self.line("English word", self.row["word"] or "")
        self.transcription_input = self.line("Transcription (optional)", self.row["transcription"] or "")
        self.translation_input = self.line("Translation", self.row["translation"] or "")
        meta_row = QHBoxLayout()
        self.level_input = self.line("Level", self.row["level"] or "A1")
        self.category_input = self.line("Category", self.row["category"] or "Imported")
        meta_row.addWidget(self.level_input)
        meta_row.addWidget(self.category_input, 1)
        layout.addWidget(self.word_input)
        layout.addWidget(self.transcription_input)
        layout.addWidget(self.translation_input)
        layout.addLayout(meta_row)

        translate_row = QHBoxLayout()
        auto_translate = QPushButton("Auto translate")
        auto_translate.setObjectName("primary")
        auto_translate.clicked.connect(self.auto_translate)
        reverso = QPushButton("Open in Reverso Context")
        reverso.clicked.connect(self.open_reverso_context)
        deepl = QPushButton("Open in DeepL")
        deepl.clicked.connect(self.open_deepl)
        translate_row.addStretch(1)
        translate_row.addWidget(deepl)
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
            QPushButton:hover {{ background: {COLORS['blue_soft']}; border-color: {COLORS['blue']}; color: {COLORS['blue']}; }}
            QPushButton:pressed {{ background: {COLORS['blue']}; border-color: {COLORS['blue']}; color: #ffffff; }}
            QPushButton#primary {{ background: {COLORS['blue']}; color: #ffffff; border-color: {COLORS['blue']}; }}
            QPushButton#primary:hover {{ background: {COLORS['blue']}; color: #ffffff; border-color: {COLORS['blue']}; }}
            QPushButton#primary:pressed {{ background: #1d55d3; color: #ffffff; border-color: #1d55d3; }}
            """
        )
        self.refresh_image_preview()

    def default_category(self) -> str:
        parent = self.parent()
        if parent and hasattr(parent, "chosen_review_categories"):
            categories = parent.chosen_review_categories()
            if categories:
                return categories[0]
        return "Imported"

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

    def open_deepl(self) -> None:
        word = self.word_input.text().strip()
        if not word:
            QMessageBox.information(self, "DeepL", "Enter an English word first.")
            return
        url = translation_service.deepl_web_url(word)
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
            QMessageBox.warning(self, self.windowTitle(), "English word can not be empty.")
            return
        con = connect_sqlite(APP_DB)
        if self.is_new:
            cursor = con.execute(
                """
                INSERT INTO words(
                    word, transcription, translation, level, category, status,
                    mnemonic_image, example_en, example_ru
                ) VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?)
                """,
                (
                    word,
                    self.transcription_input.text().strip(),
                    self.translation_input.text().strip(),
                    self.level_input.text().strip() or "A1",
                    self.category_input.text().strip() or "Imported",
                    self.image_path,
                    self.example_en_input.text().strip(),
                    self.example_ru_input.text().strip(),
                ),
            )
            self.word_id = int(cursor.lastrowid)
        else:
            con.execute(
                """
                UPDATE words
                SET word=?, transcription=?, translation=?, level=?, category=?,
                    mnemonic_image=?, example_en=?, example_ru=?
                WHERE id=?
                """,
                (
                    word,
                    self.transcription_input.text().strip(),
                    self.translation_input.text().strip(),
                    self.level_input.text().strip() or "A1",
                    self.category_input.text().strip() or "Imported",
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
        ("new_learned", "New learned", "#ef6bab"),
        ("reviewed", "Reviewed", "#ffd166"),
        ("mastered", "Mastered", "#55c583"),
        ("known", "Already known", "#cfd1d4"),
    ]

    def __init__(self):
        super().__init__()
        self.days: list[str] = []
        self.data: dict[str, dict[str, int]] = {}
        self.setMinimumHeight(420)

    def set_stats(self, days: list[str], data: dict[str, dict[str, int]]) -> None:
        self.days = days
        self.data = data
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(COLORS["panel"]))

        painter.setPen(QColor(COLORS["text"]))
        painter.setFont(self.font())
        painter.drawText(18, 18, self.width() - 36, 24, Qt.AlignmentFlag.AlignLeft, "Activity over time")

        left, top, right, bottom = 64, 56, 30, 112
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
        step = 15 if max_value <= 120 else max(25, ((max_value // 8 + 24) // 25) * 25)
        chart_max = max(step * 8, ((max_value + step - 1) // step) * step)

        grid_pen = QPen(QColor("#464a54"))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        label_color = QColor("#cfd3dc")
        for i in range(9):
            value = chart_max * i // 8
            y = plot_bottom - int(height * (value / chart_max))
            painter.drawLine(plot_left, y, plot_left + width, y)
            painter.setPen(label_color if i % 2 == 0 else QColor("#8f96a5"))
            if i % 2 == 0 or i == 0:
                painter.drawText(8, y - 9, 48, 18, Qt.AlignmentFlag.AlignRight, str(value))
            painter.setPen(grid_pen)

        if not self.days:
            painter.setPen(label_color)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No statistics yet")
            return

        slot = width / max(1, len(self.days))
        bar_width = max(3, min(46, int(slot * 0.48)))
        label_step = self.day_label_step(slot)
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

            should_draw_label = index == 0 or index == len(self.days) - 1 or index % label_step == 0
            if should_draw_label:
                painter.setPen(label_color)
                painter.drawText(
                    int(plot_left + slot * index - 26),
                    plot_bottom + 12,
                    56,
                    28,
                    Qt.AlignmentFlag.AlignCenter,
                    self.format_day_label(day),
                )

        legend_y = self.height() - 42
        legend_width = 160
        start_x = max(left, int((self.width() - legend_width * len(self.SERIES)) / 2))
        for index, (_, title, color) in enumerate(self.SERIES):
            x = start_x + index * legend_width
            painter.fillRect(x, legend_y + 4, 12, 12, QColor(color))
            painter.setPen(QColor(COLORS["muted"]))
            painter.drawText(x + 20, legend_y, legend_width - 22, 22, Qt.AlignmentFlag.AlignLeft, title)

    def format_day_label(self, value: str) -> str:
        try:
            current = date.fromisoformat(value)
        except ValueError:
            return value
        if current == date.today():
            return "Today"
        return current.strftime("%d %b")

    def day_label_step(self, slot_width: float) -> int:
        min_label_width = 58
        if slot_width >= min_label_width:
            return 1
        return max(2, int(min_label_width / max(1, slot_width)) + 1)


class PlayButton(QPushButton):
    def __init__(self):
        super().__init__("")
        self.setFixedSize(42, 42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: 0;")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pressed = self.isDown()
        painter.setPen(QPen(QColor("#4d5f94"), 1.2))
        painter.setBrush(QColor("#6d8cff" if pressed else "#222631"))
        painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 10, 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffffff" if pressed else "#6d8cff"))
        triangle = QPolygonF([
            QPointF(17, 13),
            QPointF(17, 29),
            QPointF(29, 21),
        ])
        painter.drawPolygon(triangle)


class EyeRevealButton(QPushButton):
    def __init__(self):
        super().__init__("")
        self.setFixedSize(42, 42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Show mnemonic image, translation and examples")
        self.setStyleSheet("background: transparent; border: 0;")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pressed = self.isDown()
        hovered = self.underMouse()
        bg = "#6d8cff" if pressed else "#263251" if hovered else "#1b1e25"
        border = "#6d8cff" if hovered or pressed else "#343946"
        text_color = "#ffffff" if pressed else "#8fa6ff"
        painter.setPen(QPen(QColor(border), 1.2))
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 10, 10)

        painter.setPen(QPen(QColor(text_color), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(10, 14, 22, 14))
        painter.setBrush(QColor(text_color))
        painter.drawEllipse(QRectF(19, 19, 4, 4))


class SidebarIcon(QWidget):
    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.selected = False
        self.setFixedSize(38, 38)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.width() / 46, self.height() / 46)
        color = QColor(COLORS["blue"] if self.selected else COLORS["muted"])
        pen = QPen(color, 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self.kind == "logo":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["blue"]))
            painter.drawRoundedRect(QRectF(5, 5, 36, 36), 8, 8)
            painter.setPen(QPen(QColor("#ffffff"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(16, 16, 22, 20)
            painter.drawLine(16, 16, 16, 30)
            painter.drawLine(16, 30, 22, 33)
            painter.drawLine(30, 16, 24, 20)
            painter.drawLine(30, 16, 30, 30)
            painter.drawLine(30, 30, 24, 33)
            painter.drawLine(23, 20, 23, 33)
            return

        if self.kind == "folder":
            painter.drawLine(8, 17, 18, 17)
            painter.drawLine(18, 17, 22, 21)
            painter.drawLine(22, 21, 38, 21)
            painter.drawLine(38, 21, 38, 34)
            painter.drawLine(38, 34, 8, 34)
            painter.drawLine(8, 34, 8, 17)
        elif self.kind == "search":
            painter.drawEllipse(QRectF(11, 11, 18, 18))
            painter.drawLine(27, 27, 37, 37)
        elif self.kind == "study":
            painter.drawLine(8, 20, 23, 13)
            painter.drawLine(23, 13, 38, 20)
            painter.drawLine(38, 20, 23, 27)
            painter.drawLine(23, 27, 8, 20)
            painter.drawLine(15, 25, 15, 32)
            painter.drawLine(15, 32, 23, 36)
            painter.drawLine(23, 36, 31, 32)
            painter.drawLine(31, 32, 31, 25)
        elif self.kind == "stats":
            painter.drawRoundedRect(QRectF(10, 27, 5, 9), 2, 2)
            painter.drawRoundedRect(QRectF(20, 20, 5, 16), 2, 2)
            painter.drawRoundedRect(QRectF(30, 12, 5, 24), 2, 2)
        elif self.kind == "rules":
            painter.drawRoundedRect(QRectF(12, 9, 24, 30), 3, 3)
            painter.drawLine(17, 18, 31, 18)
            painter.drawLine(17, 25, 31, 25)
            painter.drawLine(17, 32, 27, 32)
        elif self.kind == "book":
            painter.drawLine(23, 16, 23, 35)
            painter.drawLine(23, 18, 14, 15)
            painter.drawLine(14, 15, 9, 17)
            painter.drawLine(9, 17, 9, 33)
            painter.drawLine(9, 33, 14, 31)
            painter.drawLine(14, 31, 23, 35)
            painter.drawLine(23, 18, 32, 15)
            painter.drawLine(32, 15, 37, 17)
            painter.drawLine(37, 17, 37, 33)
            painter.drawLine(37, 33, 32, 31)
            painter.drawLine(32, 31, 23, 35)
        elif self.kind == "info":
            painter.drawEllipse(QRectF(12, 10, 22, 22))
            painter.drawLine(23, 20, 23, 28)
            painter.drawPoint(23, 15)
        elif self.kind == "settings":
            painter.drawEllipse(QRectF(18, 18, 10, 10))
            painter.drawEllipse(QRectF(12, 12, 22, 22))
            for x1, y1, x2, y2 in [(23, 7, 23, 12), (23, 34, 23, 39), (7, 23, 12, 23), (34, 23, 39, 23), (12, 12, 15, 15), (31, 31, 34, 34), (34, 12, 31, 15), (15, 31, 12, 34)]:
                painter.drawLine(x1, y1, x2, y2)


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

        sidebar_panel = QWidget()
        sidebar_panel.setObjectName("sidebarPanel")
        sidebar_layout = QVBoxLayout(sidebar_panel)
        sidebar_layout.setContentsMargins(0, 0, 0, 16)
        sidebar_layout.setSpacing(0)
        sidebar_panel.setFixedWidth(292)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(292)
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_rows: list[dict[str, QLabel | QWidget | SidebarIcon]] = []
        for index, title in enumerate(self.sidebar_titles()):
            item = QListWidgetItem()
            item.setSizeHint(QSize(248, 72 if index == 0 else 62))
            self.sidebar.addItem(item)
            row = self.sidebar_item_widget(index, title)
            self.sidebar.setItemWidget(item, row)
        sidebar_layout.addWidget(self.sidebar, 1)

        self.sidebar_stats_label = QLabel("")
        self.sidebar_stats_label.setStyleSheet(f"background: transparent; border: 0; color: {COLORS['muted']}; padding: 0 22px;")
        sidebar_layout.addWidget(self.sidebar_stats_label)
        layout.addWidget(sidebar_panel)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pages")
        layout.addWidget(self.pages, 1)
        self.sidebar.currentRowChanged.connect(self.switch_page)
        self.sidebar.currentRowChanged.connect(lambda _: self.refresh_sidebar_styles())
        self.sidebar.itemClicked.connect(lambda item: self.switch_page(self.sidebar.row(item)))
        self.sidebar.itemClicked.connect(lambda _: self.refresh_sidebar_styles())

        self.pages.addWidget(self.build_dashboard_page())
        self.pages.addWidget(self.build_learn_page())
        self.pages.addWidget(self.build_categories_page())
        self.pages.addWidget(self.build_dictionary_page())
        self.pages.addWidget(self.build_settings_page())
        self.pages.addWidget(self.build_statistics_page())
        self.pages.addWidget(self.build_about_page())
        self.pages.addWidget(self.build_english_rules_page())
        self.sidebar.setCurrentRow(1)
        self.apply_style()
        self.apply_language(self.setting_value("ui_language", "Match system language"))

    def sidebar_item_widget(self, index: int, title: str) -> QWidget:
        row = QWidget()
        row.setObjectName("sidebarRow")
        row.setAutoFillBackground(False)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(16)

        icon = SidebarIcon(self.sidebar_icon(index))
        icon.setObjectName("sidebarIcon")

        label = QLabel()
        label.setObjectName("sidebarText")
        if index == 0:
            label.setText("<span style='color:#f2f4f8;'>Mem</span><span style='color:#6d8cff;'>Word</span>")
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setStyleSheet("font-size: 22px; font-weight: 800;")
        else:
            label.setText(title)
            label.setStyleSheet("font-size: 18px; font-weight: 600;")

        layout.addWidget(icon)
        layout.addWidget(label, 1)
        self.sidebar_rows.append({"row": row, "icon": icon, "label": label})
        return row

    def sidebar_icon(self, index: int) -> str:
        icons = ["logo", "search", "folder", "study", "rules", "stats", "book", "settings", "info"]
        return icons[index] if index < len(icons) else "•"

    def refresh_sidebar_styles(self) -> None:
        for index, parts in enumerate(getattr(self, "sidebar_rows", [])):
            row = parts["row"]
            icon = parts["icon"]
            label = parts["label"]
            selected = self.sidebar.currentRow() == index
            row_bg = COLORS["blue_soft"] if selected else "transparent"
            text_color = COLORS["blue"] if selected else COLORS["text"]
            row.setStyleSheet(f"QWidget#sidebarRow {{ background: {row_bg}; border-radius: 12px; }}")
            if isinstance(icon, SidebarIcon):
                icon.set_selected(selected)
            if index == 0:
                row_bg = "transparent"
                row.setStyleSheet("QWidget#sidebarRow { background: transparent; border-radius: 12px; }")
                label.setText("<span style='color:#f2f4f8;'>Mem</span><span style='color:#6d8cff;'>Word</span>")
                label.setStyleSheet("background: transparent; border: 0; font-size: 22px; font-weight: 800;")
            else:
                label.setStyleSheet(f"background: transparent; border: 0; color: {text_color}; font-size: 18px; font-weight: 600;")
    def apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{
                background: {COLORS['bg']};
                color: {COLORS['text']};
                font-family: Segoe UI;
                font-size: 14px;
            }}
            QWidget#sidebarPanel {{
                background: {COLORS['sidebar']};
                border-right: 0;
            }}
            QListWidget#sidebar {{
                background: {COLORS['sidebar']};
                border: 0;
                padding: 18px 10px;
                font-size: 15px;
            }}
            QListWidget#sidebar::item {{
                background: transparent;
                border: 0;
                margin: 5px 0;
            }}
            QListWidget#sidebar::item:selected {{
                background: transparent;
                border: 0;
            }}
            QListWidget#sidebar::item:hover {{
                background: transparent;
                border: 0;
            }}
            QListWidget#sidebar::item:focus {{
                outline: none;
                border: 0;
            }}
            QWidget#sidebarRow {{
                background: transparent;
                border: 0;
            }}
            QLabel#sidebarText {{
                background: transparent;
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
            QPushButton:pressed {{
                background: {COLORS['blue']};
                color: #ffffff;
                border-color: {COLORS['blue']};
            }}
            QPushButton#primary {{
                background: {COLORS['blue']};
                color: #ffffff;
                border-color: {COLORS['blue']};
            }}
            QPushButton#primary:hover {{
                background: #175ce5;
            }}
            QPushButton#primary:pressed {{
                background: #6d8cff;
                color: #ffffff;
                border-color: #6d8cff;
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
                alternate-background-color: {COLORS['panel_alt']};
                color: {COLORS['text']};
                gridline-color: {COLORS['line']};
                border: 0;
                border-radius: 10px;
                font-size: 14px;
                selection-background-color: {COLORS['blue_soft']};
                selection-color: {COLORS['text']};
            }}
            QHeaderView::section {{
                background: {COLORS['panel_alt']};
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
        self.refresh_sidebar_styles()

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
            if index < len(getattr(self, "sidebar_rows", [])):
                label = self.sidebar_rows[index]["label"]
                if index == 0:
                    label.setText("<span style='color:#f2f4f8;'>Mem</span><span style='color:#6d8cff;'>Word</span>")
                else:
                    label.setText(title)
        self.refresh_sidebar_styles()

    def apply_theme_colors(self, value: str) -> None:
        theme = DARK_COLORS if value == "Dark" else LIGHT_COLORS
        COLORS.clear()
        COLORS.update(theme)

    def apply_theme(self, value: str) -> None:
        self.apply_theme_colors(value)
        self.apply_style()
        self.update_inline_styles()
        self.refresh_sidebar_styles()

    def update_inline_styles(self) -> None:
        if hasattr(self, "category_label"):
            self.category_label.setStyleSheet(f"color: {COLORS['blue']}; font-weight: 700;")
        if hasattr(self, "sidebar_stats_label"):
            self.sidebar_stats_label.setStyleSheet(f"background: transparent; border: 0; color: {COLORS['muted']}; padding: 0 22px;")

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
        if row == 0:
            self.sidebar.setCurrentRow(1)
            return
        if row == 1:
            self.pages.setCurrentIndex(0)
            return
        if row == 2:
            self.refresh_category_list()
            self.pages.setCurrentIndex(2)
            return
        if row == 3:
            was_study_page = self.pages.currentIndex() == 1
            self.pages.setCurrentIndex(1)
            self.study_mode = "learn"
            self.refresh_study_tabs()
            if not was_study_page or not getattr(self, "current_word_id", None):
                self.pick_random_word()
            return
        if row == 4:
            self.pages.setCurrentIndex(7)
            return
        if row == 5:
            self.refresh_statistics()
            self.pages.setCurrentIndex(5)
            return
        if row == 6:
            self.refresh_dictionary_list()
            self.pages.setCurrentIndex(3)
            return
        if row == 7:
            self.pages.setCurrentIndex(4)
            return
        if row == 8:
            self.pages.setCurrentIndex(6)
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
            return "background: #6d8cff; color: #ffffff; border: 0; border-radius: 12px; padding: 8px 46px; font-size: 14px; font-weight: 900;"
        return "background: transparent; color: #cbd3df; border: 0; padding: 8px 46px; font-size: 14px; font-weight: 700;"

    def refresh_study_tabs(self) -> None:
        if hasattr(self, "learn_tab"):
            self.learn_tab.setStyleSheet(self.study_tab_style(self.study_mode == "learn"))
        if hasattr(self, "review_tab"):
            self.review_tab.setStyleSheet(self.study_tab_style(self.study_mode == "review"))
        self.update_study_queue_labels()

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
            f"""
            QWidget {{ background: {COLORS['bg']}; color: {COLORS['text']}; }}
            QLabel {{ background: transparent; }}
            QLabel#statsHeader {{ color: {COLORS['text']}; font-size: 20px; font-weight: 800; }}
            QLabel#statsMuted {{ color: {COLORS['muted']}; font-size: 12px; }}
            QLabel#statsValue {{ color: {COLORS['text']}; font-size: 26px; font-weight: 800; }}
            QLabel#statsCardTitle {{ color: {COLORS['text']}; font-size: 14px; font-weight: 700; }}
            QFrame#statsMetric, QFrame#statsChartCard {{
                background: {COLORS['panel']};
                border: 1px solid {COLORS['line']};
                border-radius: 16px;
            }}
            QPushButton#periodButton {{
                background: {COLORS['panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['line']};
                border-radius: 0;
                padding: 8px 30px;
                min-width: 58px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton#periodMiddle, QPushButton#periodLast {{
                border-left: 0;
            }}
            QPushButton#periodFirst {{
                background: {COLORS['panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['line']};
                border-top-left-radius: 10px;
                border-bottom-left-radius: 10px;
                border-top-right-radius: 0;
                border-bottom-right-radius: 0;
                padding: 8px 30px;
                min-width: 58px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton#periodMiddle {{
                background: {COLORS['panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['line']};
                border-left: 0;
                border-radius: 0;
                padding: 8px 30px;
                min-width: 58px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton#periodLast {{
                background: {COLORS['panel']};
                color: {COLORS['text']};
                border: 1px solid {COLORS['line']};
                border-left: 0;
                border-top-left-radius: 0;
                border-bottom-left-radius: 0;
                border-top-right-radius: 10px;
                border-bottom-right-radius: 10px;
                padding: 8px 30px;
                min-width: 58px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton#periodFirst:checked, QPushButton#periodMiddle:checked, QPushButton#periodLast:checked {{
                background: {COLORS['blue']};
                color: #ffffff;
                border-color: {COLORS['blue']};
            }}
            """
        )
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 26)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("Statistics")
        title.setObjectName("statsHeader")
        header.addWidget(title)
        header.addStretch(1)
        period_group = QWidget()
        period_group.setObjectName("periodGroup")
        period_group_layout = QHBoxLayout(period_group)
        period_group_layout.setContentsMargins(0, 0, 0, 0)
        period_group_layout.setSpacing(0)
        self.stats_period_buttons: dict[str, QPushButton] = {}
        period_labels = [("7", "7 days"), ("30", "30 days"), ("90", "90 days"), ("Year", "Year"), ("All", "All time")]
        for index, (text, value) in enumerate(period_labels):
            button = QPushButton(text)
            if index == 0:
                button.setObjectName("periodFirst")
            elif index == len(period_labels) - 1:
                button.setObjectName("periodLast")
            else:
                button.setObjectName("periodMiddle")
            button.setCheckable(True)
            button.clicked.connect(lambda _, period=value: self.set_stats_period(period))
            self.stats_period_buttons[value] = button
            period_group_layout.addWidget(button)
        header.addWidget(period_group)
        layout.addLayout(header)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(14)
        metrics.setVerticalSpacing(14)
        self.stats_metric_labels: dict[str, QLabel] = {}
        metric_specs = [
            ("new_learned", "New learned", "📖", "#ef6bab"),
            ("reviewed", "Reviewed", "⟳", "#ffd166"),
            ("mastered", "Mastered", "✓", "#55c583"),
            ("known", "Already known", "✓", "#cfd1d4"),
        ]
        for column, (key, title_text, icon, color) in enumerate(metric_specs):
            metrics.addWidget(self.stats_metric_card(key, title_text, icon, color), 0, column)
        layout.addLayout(metrics)

        chart_card = QFrame()
        chart_card.setObjectName("statsChartCard")
        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(22, 18, 22, 18)
        self.stats_chart = StatsChartWidget()
        chart_layout.addWidget(self.stats_chart, 1)
        layout.addWidget(chart_card, 1)

        self.stats_period = "30 days"
        self.set_stats_period(self.stats_period)
        self.refresh_statistics()
        return page

    def stats_period_days(self) -> list[str]:
        period = getattr(self, "stats_period", "30 days")
        return services.stats_period_days(period)

    def set_stats_period(self, period: str) -> None:
        self.stats_period = period
        if hasattr(self, "stats_period_buttons"):
            for value, button in self.stats_period_buttons.items():
                button.setChecked(value == period)
        self.refresh_statistics()

    def stats_metric_card(self, key: str, title_text: str, icon: str, color: str) -> QFrame:
        card = QFrame()
        card.setObjectName("statsMetric")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(18)

        top = QHBoxLayout()
        top.setSpacing(20)
        icon_box = QLabel(icon)
        icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box.setFixedSize(58, 58)
        text_color = "#ffffff" if key != "known" else "#f2f4f8"
        icon_box.setStyleSheet(f"background: {color}; color: {text_color}; border-radius: 7px; font-size: 28px; font-weight: 800;")
        labels = QVBoxLayout()
        labels.setSpacing(2)
        labels.addStretch(1)
        title_label = QLabel(title_text)
        title_label.setObjectName("statsCardTitle")
        value_label = QLabel("0")
        value_label.setObjectName("statsValue")
        labels.addWidget(title_label)
        labels.addWidget(value_label)
        labels.addStretch(1)
        top.addWidget(icon_box)
        top.addLayout(labels, 1)
        layout.addLayout(top)

        accent = QFrame()
        accent.setFixedHeight(3)
        accent.setStyleSheet(f"background: {color}; border: 0;")
        layout.addWidget(accent)

        self.stats_metric_labels[key] = value_label
        return card

    def statistics_data(self, days: list[str]) -> tuple[dict[str, dict[str, int]], dict[str, int], dict[str, int], int]:
        return services.statistics_data(days, self.chosen_categories())

    def refresh_statistics(self) -> None:
        if not hasattr(self, "stats_chart"):
            return
        days = self.stats_period_days()
        data, period_totals, total_totals, learning_now = self.statistics_data(days)
        self.stats_chart.set_stats(days, data)
        for key, label in self.stats_metric_labels.items():
            label.setText(f"{period_totals.get(key, 0):,}")

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
        all_categories_btn = QPushButton("All categories")
        all_categories_btn.clicked.connect(self.clear_category_filter)
        add_word_btn = QPushButton("Add word")
        add_word_btn.clicked.connect(self.add_word)
        import_btn = QPushButton("Import backup")
        export_btn = QPushButton("Export backup")
        import_btn.clicked.connect(self.restore_backup)
        export_btn.clicked.connect(self.create_backup)
        top.addWidget(self.search, 1)
        top.addWidget(all_categories_btn)
        top.addWidget(add_word_btn)
        top.addWidget(import_btn)
        top.addWidget(export_btn)
        return top

    def build_dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 16, 18, 18)
        layout.setSpacing(16)
        layout.addLayout(self.build_top_bar())

        table_card = QFrame()
        table_card.setObjectName("tableCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(1, 1, 1, 12)
        table_layout.setSpacing(0)
        self.build_word_table()
        table_layout.addWidget(self.table, 1)

        layout.addWidget(table_card, 1)

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
        palette = self.table.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["panel"]))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["panel_alt"]))
        palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
        self.table.setPalette(palette)
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

    def static_value_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"background: transparent; border: 0; color: {COLORS['text']}; font-size: 14px;")
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return label

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

    def switch_control(self, name: str, default: bool) -> PillSwitch:
        switch = PillSwitch()
        switch.setChecked(bool(self.setting_value(name, default)))
        switch.stateChanged.connect(lambda _, key=name, widget=switch: self.setting_changed(key, widget.isChecked()))
        return switch

    def slider_control(self, name: str, default: float, value_label: QLabel) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(50, 200)
        slider.setValue(int(float(self.setting_value(name, default)) * 100))
        slider.valueChanged.connect(lambda value, key=name, label=value_label: self.update_speech_rate(key, value, label))
        slider.setFixedWidth(170)
        slider.setStyleSheet(
            f"""
            QSlider {{ background: transparent; border: 0; }}
            QSlider::groove:horizontal {{
                background: {COLORS['line']};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {COLORS['blue']};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {COLORS['blue']};
                width: 20px;
                height: 20px;
                margin: -7px 0;
                border-radius: 10px;
            }}
            """
        )
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
                    self.setting_row("Auto translate provider", "MyMemory free API", self.static_value_label("MyMemory")),
                    self.setting_row("MyMemory source language", "English", self.choice_control("mymemory_source_lang", ["en", "ru", "de", "fr", "es"], "en")),
                    self.setting_row("MyMemory target language", "Russian", self.choice_control("mymemory_target_lang", ["ru", "en", "de", "fr", "es"], "ru")),
                    self.setting_row("MyMemory email", "Optional. Increases free daily limit.", self.text_control("mymemory_email", "")),
                    self.setting_row("Context examples", "Opens the current word in browser", self.static_value_label("Reverso Context")),
                ],
            )
        )

        rate_value = QLabel(f"{float(self.setting_value('speech_rate', 1.0)):.2g}")
        rate_value.setStyleSheet(f"background: transparent; border: 0; color: {COLORS['blue']}; font-weight: 800; min-width: 42px;")
        rate_row_control = QWidget()
        rate_row_control.setObjectName("rateControl")
        rate_layout = QHBoxLayout(rate_row_control)
        rate_layout.setContentsMargins(0, 0, 0, 0)
        rate_layout.setSpacing(12)
        rate_layout.addWidget(rate_value)
        rate_layout.addWidget(self.slider_control("speech_rate", 1.0, rate_value), 1)
        rate_row_control.setStyleSheet("QWidget#rateControl { background: transparent; border: 0; }")
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
            self.sidebar.setCurrentRow(3)

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

    def study_info_row(self, label: str, value: str) -> tuple[QWidget, QLabel]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        caption = QLabel(label)
        caption.setStyleSheet("background: transparent; color: #aeb5c2; font-size: 15px;")
        value_label = QLabel(value)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_label.setStyleSheet("background: transparent; color: #f5f6f8; font-size: 15px; font-weight: 800;")
        layout.addWidget(caption, 1)
        layout.addWidget(value_label)
        return row, value_label

    def study_queue_item(self, color: str, title: str, subtitle: str, value: int) -> tuple[QWidget, QLabel]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)
        icon = QLabel(title[:1])
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(42, 42)
        icon.setStyleSheet(f"background: {color}; color: #ffffff; border-radius: 10px; font-size: 18px; font-weight: 900;")
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title_label = QLabel(title)
        title_label.setStyleSheet("background: transparent; color: #f5f6f8; font-size: 16px; font-weight: 800;")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setStyleSheet("background: transparent; color: #9ea6b5; font-size: 13px;")
        texts.addWidget(title_label)
        texts.addWidget(subtitle_label)
        value_label = QLabel(str(value))
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_label.setStyleSheet(f"background: transparent; color: {color}; font-size: 22px; font-weight: 900;")
        layout.addWidget(icon)
        layout.addLayout(texts, 1)
        layout.addWidget(value_label)
        return row, value_label

    def update_study_queue_labels(self) -> None:
        if not hasattr(self, "study_queue_new_label"):
            return
        values = services.dashboard_stats(self.chosen_review_categories())
        self.study_queue_new_label.setText(str(values.get("new", 0)))
        self.study_queue_review_label.setText(str(values.get("due_today", 0)))
        self.study_queue_hard_label.setText(str(values.get("hard", 0)))
        if hasattr(self, "review_badge"):
            self.review_badge.setText(f"{values.get('due_today', 0)} due")

    def open_current_reverso(self) -> None:
        word = getattr(self, "current_english_word", "").strip()
        if not word:
            QMessageBox.information(self, "Reverso Context", "Choose a word first.")
            return
        QDesktopServices.openUrl(QUrl(translation_service.reverso_context_url(word)))

    def open_current_deepl(self) -> None:
        word = getattr(self, "current_english_word", "").strip()
        if not word:
            QMessageBox.information(self, "DeepL", "Choose a word first.")
            return
        QDesktopServices.openUrl(QUrl(translation_service.deepl_web_url(word)))

    def build_learn_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("studyPage")
        page.setStyleSheet("QWidget#studyPage { background: #111215; color: #f5f6f8; }")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 22, 34, 26)
        layout.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(16)
        title = QLabel("Study")
        title.setStyleSheet("background: transparent; color: #f5f6f8; font-size: 26px; font-weight: 900;")
        header.addWidget(title)

        tabs = QFrame()
        tabs.setObjectName("studyTabs")
        tabs.setStyleSheet("QFrame#studyTabs { background: #1b1e25; border: 1px solid #343946; border-radius: 16px; }")
        tabs_layout = QHBoxLayout(tabs)
        tabs_layout.setContentsMargins(4, 4, 4, 4)
        tabs_layout.setSpacing(0)
        self.learn_tab = QPushButton("Learn new")
        self.learn_tab.clicked.connect(lambda: self.set_study_mode("learn"))
        self.review_tab = QPushButton("Review")
        self.review_tab.clicked.connect(lambda: self.set_study_mode("review"))
        tabs_layout.addWidget(self.learn_tab)
        tabs_layout.addWidget(self.review_tab)
        header.addWidget(tabs)

        self.review_badge = QLabel("0 due")
        self.review_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.review_badge.setFixedHeight(36)
        self.review_badge.setMinimumWidth(78)
        self.review_badge.setStyleSheet("background: #263251; color: #6d8cff; border: 1px solid #344161; border-radius: 18px; padding: 0 16px; font-size: 14px; font-weight: 800;")
        header.addWidget(self.review_badge)
        header.addStretch(1)
        layout.addLayout(header)

        progress = QHBoxLayout()
        progress.setSpacing(16)
        progress_left = QVBoxLayout()
        progress_left.setSpacing(8)
        self.study_counter_label = QLabel("0/10 new words learned")
        self.study_counter_label.setStyleSheet("background: transparent; color: #c7cedb; font-size: 16px;")
        self.daily_goal_marks = QLabel("")
        self.daily_goal_marks.setStyleSheet("background: transparent; color: #3f434d; font-size: 20px;")
        progress_left.addWidget(self.study_counter_label)
        progress_left.addWidget(self.daily_goal_marks)
        progress.addLayout(progress_left, 1)
        layout.addLayout(progress)

        body = QHBoxLayout()
        body.setSpacing(18)

        left_card = QFrame()
        left_card.setObjectName("studyCard")
        left_card.setStyleSheet("QFrame#studyCard { background: #20232b; border: 1px solid #333846; border-radius: 12px; }")
        left_card.setMinimumWidth(520)
        left_card.setMaximumWidth(640)
        left = QVBoxLayout(left_card)
        left.setContentsMargins(22, 18, 22, 18)
        left.setSpacing(14)
        current_title = QLabel("Current word")
        current_title.setStyleSheet("background: transparent; color: #f5f6f8; font-size: 16px; font-weight: 900;")
        left.addWidget(current_title)

        self.study_category_label = QLabel("Oxford 3000 - A1")
        self.study_category_label.setStyleSheet("background: #222943; color: #83a0ff; border: 1px solid #344161; border-radius: 12px; padding: 5px 10px; font-size: 13px; font-weight: 800;")
        left.addWidget(self.study_category_label, 0, Qt.AlignmentFlag.AlignLeft)

        word_row = QHBoxLayout()
        word_row.setSpacing(10)
        word_texts = QVBoxLayout()
        word_texts.setSpacing(6)
        self.quiz_label = QLabel("Choose a word")
        self.quiz_label.setWordWrap(True)
        self.quiz_label.setStyleSheet("background: transparent; color: #f5f6f8; font-size: 34px; font-weight: 900;")
        self.transcription_label = QLabel("[ transcription ]")
        self.transcription_label.setStyleSheet("background: transparent; color: #9da5b4; font-size: 15px;")
        word_texts.addWidget(self.quiz_label)
        word_texts.addWidget(self.transcription_label)
        word_row.addLayout(word_texts, 1)
        play_word = PlayButton()
        play_word.clicked.connect(lambda: self.pronounce_english(getattr(self, "current_english_word", "")))
        self.reveal_details_btn = EyeRevealButton()
        self.reveal_details_btn.clicked.connect(self.reveal_current_word_details)
        word_row.addWidget(self.reveal_details_btn, 0, Qt.AlignmentFlag.AlignTop)
        word_row.addWidget(play_word, 0, Qt.AlignmentFlag.AlignTop)
        left.addLayout(word_row)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #303541;")
        left.addWidget(divider)

        translation_caption = QLabel("Translation")
        translation_caption.setStyleSheet("background: transparent; color: #9da5b4; font-size: 13px;")
        left.addWidget(translation_caption)
        self.translation_label = QLabel("")
        self.translation_label.setWordWrap(True)
        self.translation_label.setMinimumHeight(54)
        self.translation_label.setStyleSheet("background: #1b1e25; border: 1px solid #343946; border-radius: 8px; color: #f5f6f8; padding: 12px; font-size: 21px;")
        left.addWidget(self.translation_label)

        input_caption = QLabel("Type English word")
        input_caption.setStyleSheet("background: transparent; color: #9da5b4; font-size: 13px;")
        left.addWidget(input_caption)
        self.answer = QLineEdit()
        self.answer.setPlaceholderText("Type English word")
        self.answer.returnPressed.connect(self.start_learning_or_check)
        self.answer.setStyleSheet("background: #171a20; color: #f5f6f8; border: 1px solid #4d64a3; border-radius: 8px; padding: 10px 12px; font-size: 16px;")
        left.addWidget(self.answer)

        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        secondary_action_style = """
            QPushButton {
                background: #1b1e25;
                color: #f5f6f8;
                border: 1px solid #343946;
                border-radius: 8px;
                padding: 10px 18px;
                font-size: 15px;
                font-weight: 800;
            }
            QPushButton:hover {
                border-color: #6d8cff;
                color: #8fa6ff;
            }
            QPushButton:pressed {
                background: #6d8cff;
                color: #ffffff;
                border-color: #6d8cff;
            }
        """
        arrow_button_style = """
            QPushButton {
                background: #1b1e25;
                color: #d8deea;
                border: 1px solid #343946;
                border-radius: 8px;
                font-size: 26px;
                font-weight: 900;
            }
            QPushButton:hover {
                border-color: #6d8cff;
                color: #8fa6ff;
            }
            QPushButton:pressed {
                background: #6d8cff;
                color: #ffffff;
                border-color: #6d8cff;
            }
        """
        primary_action_style = """
            QPushButton {
                background: #6d8cff;
                color: #ffffff;
                border: 0;
                border-radius: 8px;
                padding: 10px 22px;
                font-size: 15px;
                font-weight: 900;
            }
            QPushButton:hover {
                background: #7897ff;
            }
            QPushButton:pressed {
                background: #526fd1;
            }
        """
        joined_known_style = """
            QPushButton {
                background: #1b1e25;
                color: #f5f6f8;
                border: 1px solid #343946;
                border-right: 0;
                border-top-left-radius: 8px;
                border-bottom-left-radius: 8px;
                border-top-right-radius: 0;
                border-bottom-right-radius: 0;
                padding: 10px 18px;
                font-size: 15px;
                font-weight: 800;
            }
            QPushButton:hover {
                border-color: #6d8cff;
                color: #8fa6ff;
            }
            QPushButton:pressed {
                background: #6d8cff;
                color: #ffffff;
                border-color: #6d8cff;
            }
        """
        joined_prev_style = """
            QPushButton {
                background: #1b1e25;
                color: #d8deea;
                border: 1px solid #343946;
                border-top-left-radius: 0;
                border-bottom-left-radius: 0;
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
                font-size: 26px;
                font-weight: 900;
            }
            QPushButton:hover {
                border-color: #6d8cff;
                color: #8fa6ff;
            }
            QPushButton:pressed {
                background: #6d8cff;
                color: #ffffff;
                border-color: #6d8cff;
            }
        """
        known_prev_group = QFrame()
        known_prev_group.setStyleSheet("background: transparent; border: 0;")
        known_prev_layout = QHBoxLayout(known_prev_group)
        known_prev_layout.setContentsMargins(0, 0, 0, 0)
        known_prev_layout.setSpacing(0)
        self.known_btn = QPushButton("I already know\nthis word")
        self.known_btn.setMinimumSize(176, 56)
        self.known_btn.setStyleSheet(joined_known_style)
        self.known_btn.clicked.connect(self.mark_current_known)
        self.prev_btn = QPushButton("‹")
        self.prev_btn.setFixedSize(58, 56)
        self.prev_btn.setStyleSheet(joined_prev_style)
        self.prev_btn.clicked.connect(self.pick_random_word)
        known_prev_layout.addWidget(self.known_btn)
        known_prev_layout.addWidget(self.prev_btn)
        self.next_btn = QPushButton("›")
        self.next_btn.setFixedSize(58, 56)
        self.next_btn.setStyleSheet(arrow_button_style)
        self.next_btn.clicked.connect(self.pick_random_word)
        self.check_button = QPushButton("Start learning\nthis word")
        self.check_button.setMinimumSize(182, 56)
        self.check_button.setStyleSheet(primary_action_style)
        self.check_button.clicked.connect(self.start_learning_or_check)
        bottom.addWidget(known_prev_group)
        bottom.addStretch(1)
        bottom.addWidget(self.next_btn)
        bottom.addStretch(1)
        bottom.addWidget(self.check_button)
        left.addLayout(bottom)

        self.attempts_label = QLabel("Attempts left: 3")
        self.attempts_label.hide()
        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("background: transparent; color: #6d8cff; font-size: 15px;")
        left.addWidget(self.result_label)
        self.goal_banner = QLabel("")
        self.goal_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.goal_banner.hide()
        self.goal_banner.setStyleSheet(
            "background: #263251; color: #ffffff; border: 1px solid #6d8cff; "
            "border-radius: 12px; padding: 14px; font-size: 18px; font-weight: 900;"
        )
        left.addWidget(self.goal_banner)
        left.addStretch(1)

        right_col = QVBoxLayout()
        right_col.setSpacing(14)

        details = QFrame()
        details.setObjectName("studyDetails")
        details.setStyleSheet("QFrame#studyDetails { background: #20232b; border: 1px solid #333846; border-radius: 12px; }")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(18, 16, 18, 16)
        details_layout.setSpacing(12)
        details_header = QHBoxLayout()
        details_title = QLabel("Word details")
        details_title.setStyleSheet("background: transparent; color: #f5f6f8; font-size: 16px; font-weight: 900;")
        edit_btn = QPushButton("...")
        edit_btn.setFixedSize(36, 28)
        edit_btn.setStyleSheet("background: transparent; border: 0; color: #f5f6f8; font-size: 22px; font-weight: 900;")
        edit_btn.clicked.connect(self.edit_current_word)
        details_header.addWidget(details_title)
        details_header.addStretch(1)
        details_header.addWidget(edit_btn)
        details_layout.addLayout(details_header)
        self.mnemonic_preview = QLabel("No mnemonic image")
        self.mnemonic_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mnemonic_preview.setMinimumHeight(240)
        self.mnemonic_preview.setStyleSheet("background: #1b1e25; border: 1px dashed #3d4350; border-radius: 8px; color: #9da5b4; font-size: 14px;")
        details_layout.addWidget(self.mnemonic_preview)

        example_caption = QLabel("Example sentence")
        example_caption.setStyleSheet("background: transparent; color: #9da5b4; font-size: 13px;")
        details_layout.addWidget(example_caption)
        self.example_label = QLabel("No example sentence yet. Use Edit word to add one.")
        self.example_label.setWordWrap(True)
        self.example_label.setMinimumHeight(58)
        self.example_label.setStyleSheet(
            "background: #1b1e25; color: #cdd3df; border: 1px solid #343946; "
            "border-radius: 8px; padding: 10px 12px; font-size: 14px;"
        )
        details_layout.addWidget(self.example_label)

        details_buttons = QHBoxLayout()
        detail_button_style = """
            QPushButton {
                background: #1b1e25;
                color: #dfe5f0;
                border: 1px solid #343946;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #26345b;
                color: #86a0ff;
                border-color: #6d8cff;
            }
            QPushButton:pressed {
                background: #6d8cff;
                color: #ffffff;
                border-color: #6d8cff;
            }
        """
        edit_word = QPushButton("Edit word")
        edit_word.setStyleSheet(detail_button_style)
        edit_word.clicked.connect(self.edit_current_word)
        reverso = QPushButton("Open Reverso ↗")
        reverso.setStyleSheet(detail_button_style)
        reverso.clicked.connect(self.open_current_reverso)
        deepl = QPushButton("Open DeepL ↗")
        deepl.setStyleSheet(detail_button_style)
        deepl.clicked.connect(self.open_current_deepl)
        details_buttons.addWidget(edit_word)
        details_buttons.addWidget(reverso)
        details_buttons.addWidget(deepl)
        details_layout.addLayout(details_buttons)
        right_col.addWidget(details)

        right_col.addStretch(1)

        body.addWidget(left_card, 0)
        body.addLayout(right_col, 1)
        layout.addLayout(body, 1)

        self.current_word_id = None
        self.attempts_left = 3
        self.update_daily_goal_progress()
        self.refresh_study_tabs()
        self.update_study_queue_labels()
        return page

    def open_about_page(self) -> None:
        self.sidebar.blockSignals(True)
        self.sidebar.setCurrentRow(-1)
        self.sidebar.clearSelection()
        self.sidebar.blockSignals(False)
        self.pages.setCurrentIndex(6)
        self.refresh_sidebar_styles()

    def build_about_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)

        title = QLabel("About MemWord")
        title.setStyleSheet("background: transparent; color: #f2f4f8; font-size: 28px; font-weight: 900;")
        layout.addWidget(title)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 18, 22, 18)
        card_layout.setSpacing(10)
        description = QLabel(
            "MemWord is a desktop app for learning English words with categories, spaced repetition, backups, statistics and mnemonic images."
        )
        description.setWordWrap(True)
        description.setStyleSheet("background: transparent; color: #cbd3df; font-size: 16px;")
        version = QLabel("Version 1.0.0")
        version.setStyleSheet("background: transparent; color: #8f98aa; font-size: 14px;")
        card_layout.addWidget(description)
        card_layout.addWidget(version)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def build_english_rules_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        title = QLabel("English rules")
        title.setStyleSheet("background: transparent; color: #f2f4f8; font-size: 28px; font-weight: 900;")
        subtitle = QLabel("Course-style grammar map by level. A0 Beginner is filled now.")
        subtitle.setStyleSheet("background: transparent; color: #9fa8ba; font-size: 15px;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        layout.addLayout(header)

        levels = QHBoxLayout()
        levels.setSpacing(8)
        level_items = [
            ("A0", "Beginner", True),
            ("A1", "Elementary", False),
            ("A2", "Pre-Intermediate", False),
            ("B1", "Intermediate", False),
            ("B2", "Upper-Intermediate", False),
            ("C1", "Advanced", False),
        ]
        for code, name, active in level_items:
            level = QLabel(f"{code}\n{name}")
            level.setAlignment(Qt.AlignmentFlag.AlignCenter)
            level.setMinimumHeight(56)
            if active:
                level.setStyleSheet(
                    "background: #6d8cff; color: #ffffff; border-radius: 12px; "
                    "padding: 8px 18px; font-size: 14px; font-weight: 900;"
                )
            else:
                level.setStyleSheet(
                    "background: #20232b; color: #cbd3df; border: 1px solid #333846; border-radius: 12px; "
                    "padding: 8px 18px; font-size: 14px; font-weight: 800;"
                )
            levels.addWidget(level)
        levels.addStretch(1)
        layout.addLayout(levels)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: 0; }")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        intro = QFrame()
        intro.setObjectName("card")
        intro_layout = QVBoxLayout(intro)
        intro_layout.setContentsMargins(22, 18, 22, 18)
        intro_layout.setSpacing(8)
        intro_title = QLabel("A0 Beginner")
        intro_title.setStyleSheet("background: transparent; color: #f2f4f8; font-size: 22px; font-weight: 900;")
        intro_text = QLabel(
            "Beginner grammar is organized as short files, like a course book: each file gives one small grammar step, "
            "simple examples and a clear pattern to remember."
        )
        intro_text.setWordWrap(True)
        intro_text.setStyleSheet("background: transparent; color: #cbd3df; font-size: 15px;")
        intro_layout.addWidget(intro_title)
        intro_layout.addWidget(intro_text)
        content_layout.addWidget(intro)

        files = [
            (
                "1",
                "Verb be: singular forms",
                [
                    (
                        "1A",
                        "I and you",
                        ["Use I am and you are.", "Negative forms: I am not, you are not.", "Question order: Am I...? Are you...?"],
                        ["I am Helen.", "You are Tom.", "Are you Mike?"],
                    ),
                    (
                        "1B",
                        "he, she, it",
                        ["Use he is, she is, it is.", "Negative contractions: he isn't, she isn't, it isn't.", "Use he for a man, she for a woman, it for a thing."],
                        ["He is from Italy.", "She isn't from Brazil.", "Is it good?"],
                    ),
                ],
            ),
            (
                "2",
                "Articles and plurals",
                [
                    (
                        "2A",
                        "a / an and classroom nouns",
                        ["Use a before consonant sounds.", "Use an before vowel sounds.", "Use singular nouns with a/an."],
                        ["a book", "an apple", "It is a pen."],
                    ),
                    (
                        "2B",
                        "Regular plural nouns",
                        ["Most plurals add -s.", "Add -es after s, sh, ch, x.", "Use these/those for plural things."],
                        ["two books", "three boxes", "These are chairs."],
                    ),
                ],
            ),
            (
                "3",
                "This / that and possession",
                [
                    (
                        "3A",
                        "this, that, these, those",
                        ["Use this/these for near things.", "Use that/those for far things.", "Match singular and plural forms."],
                        ["This is my phone.", "Those are keys.", "Is that your bag?"],
                    ),
                    (
                        "3B",
                        "Possessive adjectives",
                        ["Use my, your, his, her, its, our, their before nouns.", "Possessive adjectives do not change for singular/plural nouns.", "Use his for a man and her for a woman."],
                        ["This is my sister.", "His car is old.", "Their books are here."],
                    ),
                ],
            ),
            (
                "4",
                "People and family",
                [
                    (
                        "4A",
                        "Possessive 's",
                        ["Use 's after a person to show possession.", "For regular plural nouns, add only an apostrophe.", "Use it mostly with people and animals."],
                        ["Anna's brother is here.", "My parents' house is small.", "Tom's phone is new."],
                    ),
                    (
                        "4B",
                        "have / has",
                        ["Use have with I, you, we, they.", "Use has with he, she, it.", "Use don't/doesn't for negatives."],
                        ["I have two sisters.", "She has a dog.", "They don't have a car."],
                    ),
                ],
            ),
            (
                "5",
                "There is / there are",
                [
                    (
                        "5A",
                        "there is / there are",
                        ["Use there is for one thing.", "Use there are for more than one thing.", "Question order: Is there...? Are there...?"],
                        ["There is a table.", "There are two windows.", "Is there a cafe near here?"],
                    ),
                    (
                        "5B",
                        "some / any",
                        ["Use some in positive plural sentences.", "Use any in questions and negatives.", "Use any with plural countable nouns."],
                        ["There are some books.", "Are there any shops?", "There aren't any chairs."],
                    ),
                ],
            ),
            (
                "6",
                "Present Simple basics",
                [
                    (
                        "6A",
                        "I / you / we / they",
                        ["Use the base verb with I, you, we, they.", "Use don't for negatives.", "Use do for questions."],
                        ["I work in a bank.", "We don't live here.", "Do you speak English?"],
                    ),
                    (
                        "6B",
                        "he / she / it",
                        ["Add -s or -es with he, she, it.", "Use doesn't for negatives.", "Use does for questions."],
                        ["He works at home.", "She doesn't drive.", "Does it cost much?"],
                    ),
                ],
            ),
            (
                "7",
                "Daily routines and frequency",
                [
                    (
                        "7A",
                        "Adverbs of frequency",
                        ["Use always, usually, often, sometimes, never.", "Put adverbs before most verbs.", "Put adverbs after be."],
                        ["I often cook dinner.", "She is always late.", "We never watch TV."],
                    ),
                    (
                        "7B",
                        "Time expressions",
                        ["Use in for parts of the day.", "Use at for clock times.", "Use on for days."],
                        ["I study in the evening.", "He gets up at seven.", "We work on Monday."],
                    ),
                ],
            ),
            (
                "8",
                "Can and object pronouns",
                [
                    (
                        "8A",
                        "can / can't",
                        ["Use can for ability and possibility.", "Can is the same for all subjects.", "Use can + base verb."],
                        ["I can swim.", "She can't drive.", "Can you help me?"],
                    ),
                    (
                        "8B",
                        "Object pronouns",
                        ["Use me, you, him, her, it, us, them after verbs.", "Object pronouns replace object nouns.", "Use him for a man and her for a woman."],
                        ["I know him.", "She helps us.", "Can you call them?"],
                    ),
                ],
            ),
            (
                "9",
                "Present Continuous",
                [
                    (
                        "9A",
                        "Actions happening now",
                        ["Form: be + verb-ing.", "Use it for actions happening now.", "Use am/is/are before the -ing form."],
                        ["I am studying now.", "She is reading.", "They are waiting."],
                    ),
                    (
                        "9B",
                        "Questions and negatives",
                        ["Move be before the subject in questions.", "Use not after be for negatives.", "Short answers use be."],
                        ["Are you listening?", "He isn't sleeping.", "Yes, I am."],
                    ),
                ],
            ),
            (
                "10",
                "Past Simple: be and regular verbs",
                [
                    (
                        "10A",
                        "was / were",
                        ["Use was with I, he, she, it.", "Use were with you, we, they.", "Question order: Was/Were + subject."],
                        ["I was at home.", "They were tired.", "Were you late?"],
                    ),
                    (
                        "10B",
                        "Regular past verbs",
                        ["Regular past verbs usually add -ed.", "Use didn't + base verb for negatives.", "Use did + subject + base verb for questions."],
                        ["We watched a film.", "She didn't call.", "Did you work yesterday?"],
                    ),
                ],
            ),
            (
                "11",
                "Past Simple: irregular verbs",
                [
                    (
                        "11A",
                        "Common irregular verbs",
                        ["Irregular past forms do not use -ed.", "Learn them as pairs: go/went, have/had, see/saw.", "The past form is the same for all subjects."],
                        ["I went to work.", "She had coffee.", "We saw a film."],
                    ),
                    (
                        "11B",
                        "Past questions",
                        ["Use did for questions with most past verbs.", "After did, use the base verb.", "Use question words before did."],
                        ["Did you go out?", "Where did she live?", "What did they buy?"],
                    ),
                ],
            ),
            (
                "12",
                "Future plans",
                [
                    (
                        "12A",
                        "going to",
                        ["Use going to for future plans.", "Form: be + going to + base verb.", "Use not after be for negatives."],
                        ["I am going to study.", "She isn't going to drive.", "We are going to travel."],
                    ),
                    (
                        "12B",
                        "Future questions",
                        ["Move be before the subject.", "Use question words before be.", "Short answers use be."],
                        ["Are you going to work?", "Where are they going to stay?", "Yes, I am."],
                    ),
                ],
            ),
        ]

        for file_code, file_title, parts in files:
            card = QFrame()
            card.setObjectName("card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(20, 16, 20, 16)
            card_layout.setSpacing(12)

            top = QHBoxLayout()
            badge = QLabel(file_code)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(46, 34)
            badge.setStyleSheet("background: #263251; color: #83a0ff; border-radius: 17px; font-size: 14px; font-weight: 900;")
            heading = QLabel(file_title)
            heading.setStyleSheet("background: transparent; color: #f2f4f8; font-size: 18px; font-weight: 900;")
            top.addWidget(badge)
            top.addWidget(heading, 1)
            card_layout.addLayout(top)

            for part_code, part_title, rules, examples in parts:
                part = QFrame()
                part.setStyleSheet("background: #1b1e25; border: 1px solid #333846; border-radius: 10px;")
                part_layout = QVBoxLayout(part)
                part_layout.setContentsMargins(14, 12, 14, 12)
                part_layout.setSpacing(8)

                part_top = QHBoxLayout()
                part_badge = QLabel(part_code)
                part_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                part_badge.setFixedSize(46, 28)
                part_badge.setStyleSheet("background: #6d8cff; color: #ffffff; border-radius: 14px; font-size: 13px; font-weight: 900;")
                part_heading = QLabel(part_title)
                part_heading.setStyleSheet("background: transparent; color: #f2f4f8; font-size: 16px; font-weight: 900;")
                part_top.addWidget(part_badge)
                part_top.addWidget(part_heading, 1)
                part_layout.addLayout(part_top)

                rules_text = QLabel("<br>".join(f"• {rule}" for rule in rules))
                rules_text.setWordWrap(True)
                rules_text.setStyleSheet("background: transparent; border: 0; color: #cbd3df; font-size: 14px; line-height: 1.35;")
                part_layout.addWidget(rules_text)

                examples_text = QLabel("Examples: " + "  /  ".join(examples))
                examples_text.setWordWrap(True)
                examples_text.setStyleSheet(
                    "background: #15181e; color: #f2f4f8; border: 1px solid #2e3340; border-radius: 8px; "
                    "padding: 9px 11px; font-size: 13px;"
                )
                part_layout.addWidget(examples_text)
                card_layout.addWidget(part)

            content_layout.addWidget(card)

        content_layout.addStretch(1)

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
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
        categories = con.execute("SELECT COUNT(DISTINCT category) FROM words WHERE category IS NOT NULL AND TRIM(category) <> ''").fetchone()[0]
        label = f"Words: {int(total):,}    Categories: {int(categories or 0):,}"
        con.close()
        if hasattr(self, "sidebar_stats_label"):
            self.sidebar_stats_label.setText(label)

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

    def add_word(self) -> None:
        dialog = WordEditDialog(None, self)
        if dialog.exec():
            self.model.select()
            self.apply_filter(self.search.text())
            self.update_count()
            self.refresh_dictionary_list()
            self.refresh_category_list()

    def practice_selected(self) -> None:
        word_id = self.selected_word_id()
        if not word_id:
            QMessageBox.information(self, "Practice", "Select a word first.")
            return
        self.load_quiz_word(int(word_id))
        self.sidebar.setCurrentRow(3)

    def pick_random_word(self) -> None:
        categories = self.chosen_review_categories()
        if not categories:
            QMessageBox.information(self, "Study", "Choose at least one category in Categories first.")
            self.refresh_category_list()
            self.pages.setCurrentIndex(2)
            self.sidebar.setCurrentRow(2)
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
        self.current_word_row = row
        self.attempts_left = 3
        self.current_correct_answer = str(row["word"] or "").strip().lower()
        self.current_english_word = str(row["word"] or "")
        clean_transcription = str(row["transcription"] or "") if self.setting_value("show_transcription", True) else ""
        status_title = "New" if row["status"] == "new" else "Review"
        if hasattr(self, "study_category_label"):
            self.study_category_label.setText(f"{row['category']} - {row['level']}")
        if hasattr(self, "word_status_value"):
            self.word_status_value.setText(status_title)
        if hasattr(self, "word_next_review_value"):
            self.word_next_review_value.setText("Today")
        self.quiz_label.setText(str(row["word"] or ""))
        if hasattr(self, "transcription_label"):
            self.transcription_label.setText(clean_transcription)
        self.attempts_label.setText("Attempts left: 3")
        if hasattr(self, "word_attempts_value"):
            self.word_attempts_value.setText("3")
        self.answer.clear()
        self.result_label.setText("")
        if self.study_mode == "learn" and row["status"] == "new":
            self.set_learning_preview_state()
        else:
            self.begin_typing_current_word()
        self.pronounce_english(self.current_english_word)

    def set_learning_preview_state(self) -> None:
        self.learning_phase = "preview"
        row = getattr(self, "current_word_row", None)
        if not row:
            return
        self.set_study_navigation_enabled(True)
        self.quiz_label.setText(str(row["word"] or ""))
        self.answer.setEnabled(False)
        self.answer.clear()
        self.answer.setPlaceholderText("Press Start learning first")
        if hasattr(self, "check_button"):
            self.check_button.setText("Start learning\nthis word")
        self.hide_current_word_details()

    def begin_typing_current_word(self) -> None:
        self.learning_phase = "typing"
        row = getattr(self, "current_word_row", None)
        if not row:
            return
        self.set_study_navigation_enabled(False)
        self.hide_current_word_details()
        self.quiz_label.setText("Type the English word")
        if hasattr(self, "transcription_label"):
            self.transcription_label.setText(str(row["transcription"] or "") if self.setting_value("show_transcription", True) else "")
        if hasattr(self, "translation_label"):
            self.translation_label.setText(str(row["translation"] or ""))
        self.answer.setEnabled(True)
        self.answer.setPlaceholderText("Type English word")
        self.answer.clear()
        if hasattr(self, "check_button"):
            self.check_button.setText("Check answer")
        self.answer.setFocus()

    def set_study_navigation_enabled(self, enabled: bool) -> None:
        for button_name in ("known_btn", "prev_btn", "next_btn"):
            if hasattr(self, button_name):
                getattr(self, button_name).setEnabled(enabled)

    def hide_current_word_details(self) -> None:
        if hasattr(self, "translation_label"):
            self.translation_label.setText("Hidden. Click the eye icon to reveal.")
        if hasattr(self, "mnemonic_preview"):
            self.mnemonic_preview.setPixmap(QPixmap())
            self.mnemonic_preview.setText("Hidden. Click the eye icon to reveal.")
        if hasattr(self, "example_label"):
            self.example_label.setText("Hidden. Click the eye icon to reveal.")

    def reveal_current_word_details(self) -> None:
        row = getattr(self, "current_word_row", None)
        if not row:
            return
        if hasattr(self, "translation_label"):
            self.translation_label.setText(str(row["translation"] or ""))
        self.update_mnemonic_preview(row["mnemonic_image"] or "")
        self.update_examples(row["example_en"] or "", row["example_ru"] or "")

    def update_mnemonic_preview(self, image_path: str) -> None:
        if image_path and Path(image_path).exists():
            pixmap = QPixmap(image_path)
            target_size = self.mnemonic_preview.size()
            if target_size.width() < 120 or target_size.height() < 120:
                target_size = QSize(640, 240)
            self.mnemonic_preview.setPixmap(
                pixmap.scaled(target_size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
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
        self.update_study_queue_labels()
        self.pick_random_word()

    def start_learning_or_check(self) -> None:
        if not self.current_word_id:
            self.pick_random_word()
            return
        if getattr(self, "learning_phase", "preview") == "preview":
            self.begin_typing_current_word()
            return
        self.check_answer()

    def show_goal_complete_banner(self) -> None:
        goal = self.daily_goal_value()
        if not hasattr(self, "goal_banner"):
            QMessageBox.information(self, "Nice Job!", f"Nice Job! Today you learned {goal} new words.")
            return
        self.goal_banner.setText(f"Nice Job! Today you learned {goal} new words.")
        self.goal_banner.show()
        QTimer.singleShot(4500, self.goal_banner.hide)

    def check_answer(self) -> None:
        if not self.current_word_id:
            return
        if getattr(self, "learning_phase", "typing") == "preview":
            self.begin_typing_current_word()
            return
        raw_answer = self.answer.text().strip()
        row = getattr(self, "current_word_row", None)
        is_new_learning = bool(row and self.study_mode == "learn" and row["status"] == "new")
        if not raw_answer:
            self.result_label.setText("Type an answer first.")
            self.answer.setFocus()
            return
        if is_new_learning and raw_answer.lower() != getattr(self, "current_correct_answer", ""):
            self.attempts_left = max(0, int(getattr(self, "attempts_left", 3)) - 1)
            if self.attempts_left <= 0:
                self.result_label.setText(f"Answer: {getattr(self, 'current_correct_answer', '')}. Try again until correct.")
                self.reveal_current_word_details()
                self.attempts_left = 3
            else:
                self.result_label.setText(f"Try again. Attempts left: {self.attempts_left}")
            self.attempts_label.setText(f"Attempts left: {self.attempts_left}")
            if hasattr(self, "word_attempts_value"):
                self.word_attempts_value.setText(str(self.attempts_left))
            self.answer.selectAll()
            self.answer.setFocus()
            return
        result = services.check_answer(
            int(self.current_word_id),
            raw_answer,
            getattr(self, "current_correct_answer", ""),
            int(getattr(self, "attempts_left", 3)),
        )
        self.attempts_left = result.attempts_left
        self.attempts_label.setText(f"Attempts left: {self.attempts_left}")
        if hasattr(self, "word_attempts_value"):
            self.word_attempts_value.setText(str(self.attempts_left))
        message = result.message
        if not result.is_correct and self.attempts_left > 0:
            self.result_label.setText(message)
            self.answer.selectAll()
            self.answer.setFocus()
            return
        self.result_label.setText(message)
        self.model.select()
        self.refresh_statistics()
        self.update_daily_goal_progress()
        self.update_study_queue_labels()
        if result.is_correct:
            learned = self.learned_new_words_today()
            goal = self.daily_goal_value()
            if result.daily_goal_incremented and learned >= goal:
                self.show_goal_complete_banner()
                return
            QTimer.singleShot(450, self.pick_random_word)
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
        self.statusBar().showMessage("Working...")
        self.worker = BackupWorker(action, path)
        self.worker.done.connect(self.worker_done)
        self.worker.failed.connect(self.worker_failed)
        self.worker.start()

    def worker_done(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)
        self.model.select()
        self.update_count()
        self.refresh_category_list()
        self.refresh_dictionary_list()
        QMessageBox.information(self, "Done", message)

    def worker_failed(self, message: str) -> None:
        self.statusBar().showMessage("Error", 5000)
        QMessageBox.critical(self, "Error", message)


def main() -> int:
    database.ensure_database()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
