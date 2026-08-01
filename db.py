import json
import sqlite3
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
WORDS_JSON = DATA_DIR / "words.json"
PROGRESS_JSON = DATA_DIR / "progress.json"
APP_DB = DATA_DIR / "english_learning.sqlite"


KNOWN_CATEGORY_LEVELS = {
    "Oxford 3000 - A1": "A1",
    "Oxford 3000 - A2": "A2",
    "Oxford 3000 - B1": "B1",
    "Oxford 3000 - B2": "B2",
    "Oxford 5000 - B2": "B2",
    "Oxford 5000 - C1": "C1",
}
CEFR_LEVEL_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4}


def normalized_word_level(category: str, level: str = "A1") -> str:
    """Return the explicit CEFR level for categories that define one."""
    return KNOWN_CATEGORY_LEVELS.get(category, level or "A1")


def normalized_word_key(word: str) -> str:
    return " ".join((word or "").strip().lower().split())


def propagate_known_word_levels(con: sqlite3.Connection) -> int:
    """Copy reliable Oxford levels to exact matches in other categories."""
    placeholders = ",".join("?" for _ in KNOWN_CATEGORY_LEVELS)
    source_levels: dict[str, set[str]] = {}
    for row in con.execute(
        f"SELECT word, category FROM words WHERE category IN ({placeholders})",
        tuple(KNOWN_CATEGORY_LEVELS),
    ):
        key = normalized_word_key(row["word"])
        if key:
            source_levels.setdefault(key, set()).add(KNOWN_CATEGORY_LEVELS[row["category"]])

    inferred_levels = {
        key: min(levels, key=CEFR_LEVEL_ORDER.__getitem__)
        for key, levels in source_levels.items()
    }
    updates: list[tuple[str, int]] = []
    for row in con.execute(
        f"SELECT id, word, level FROM words WHERE category NOT IN ({placeholders})",
        tuple(KNOWN_CATEGORY_LEVELS),
    ):
        inferred = inferred_levels.get(normalized_word_key(row["word"]))
        if inferred and inferred != (row["level"] or "A1"):
            updates.append((inferred, int(row["id"])))
    con.executemany("UPDATE words SET level = ? WHERE id = ?", updates)
    return len(updates)


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
            example_ru TEXT DEFAULT '',
            learning_selected INTEGER DEFAULT 0
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
        "learning_selected": "INTEGER DEFAULT 0",
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
                    normalized_word_level(
                        row.get("category", "Imported"),
                        row.get("level", "A1"),
                    ),
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
    propagate_known_word_levels(con)
    con.commit()
    con.close()
