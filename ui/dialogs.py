import urllib.error
from pathlib import Path

import db as database
import translation_service
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QColor, QDesktopServices, QPalette, QPixmap
from PyQt6.QtSql import QSqlDatabase, QSqlTableModel
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from ui.table_model import WordTableModel, sql_quote
from ui.theme import COLORS

APP_DIR = Path(__file__).resolve().parents[1]
APP_DB = APP_DIR / "data" / "english_learning.sqlite"
connect_sqlite = database.connect_sqlite


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
