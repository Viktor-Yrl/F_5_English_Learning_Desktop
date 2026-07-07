import json
import sqlite3
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
WORDS_JSON = DATA_DIR / "words.json"
PROGRESS_JSON = DATA_DIR / "progress.json"
APP_DB = DATA_DIR / "english_learning.sqlite"


def connect_sqlite(path: Path = APP_DB) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def ensure_database() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    con = connect_sqlite(APP_DB)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL,
            translation TEXT DEFAULT '',
            level TEXT DEFAULT 'A1',
            category TEXT DEFAULT 'Imported',
            status TEXT DEFAULT 'new',
            reword_id INTEGER DEFAULT 0,
            total_answers INTEGER DEFAULT 0,
            good_series INTEGER DEFAULT 0,
            last_repeat_time INTEGER DEFAULT 0,
            transcription TEXT DEFAULT '',
            mnemonic_image TEXT DEFAULT '',
            example_en TEXT DEFAULT '',
            example_ru TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_words_word ON words(word);
        CREATE INDEX IF NOT EXISTS idx_words_category ON words(category);
        CREATE INDEX IF NOT EXISTS idx_words_status ON words(status);
        CREATE TABLE IF NOT EXISTS progress (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS study_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER DEFAULT 0,
            event_type TEXT NOT NULL,
            event_date TEXT NOT NULL,
            event_time INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_study_events_date ON study_events(event_date);
        CREATE INDEX IF NOT EXISTS idx_study_events_type_date ON study_events(event_type, event_date);
        """
    )
    existing_columns = {row["name"] for row in con.execute("PRAGMA table_info(words)")}
    for column, definition in {
        "transcription": "TEXT DEFAULT ''",
        "mnemonic_image": "TEXT DEFAULT ''",
        "example_en": "TEXT DEFAULT ''",
        "example_ru": "TEXT DEFAULT ''",
    }.items():
        if column not in existing_columns:
            con.execute(f"ALTER TABLE words ADD COLUMN {column} {definition}")

    count = con.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    if count == 0 and WORDS_JSON.exists():
        rows = json.loads(WORDS_JSON.read_text(encoding="utf-8"))
        con.executemany(
            """
            INSERT INTO words(
                word, translation, level, category, status, reword_id,
                total_answers, good_series, last_repeat_time,
                transcription, mnemonic_image, example_en, example_ru
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("word", ""),
                    row.get("translation", ""),
                    row.get("level", "A1"),
                    row.get("category", "Imported"),
                    row.get("status", "new"),
                    int(row.get("reword_id", 0) or 0),
                    int(row.get("total_answers", 0) or 0),
                    int(row.get("good_series", 0) or 0),
                    int(row.get("last_repeat_time", 0) or 0),
                    row.get("transcription", ""),
                    row.get("mnemonic_image", ""),
                    row.get("example_en", ""),
                    row.get("example_ru", ""),
                )
                for row in rows
                if row.get("word")
            ],
        )

    if PROGRESS_JSON.exists():
        progress = json.loads(PROGRESS_JSON.read_text(encoding="utf-8"))
        for key, value in progress.items():
            con.execute(
                "INSERT OR REPLACE INTO progress(name, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
    else:
        con.execute("INSERT OR IGNORE INTO progress(name, value) VALUES ('daily_goal', '10')")
    con.commit()
    con.close()
