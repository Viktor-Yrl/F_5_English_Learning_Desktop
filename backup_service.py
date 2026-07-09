import json
import sqlite3
import time
from pathlib import Path

from db import APP_DB, DATA_DIR, connect_sqlite
from services import good_series_from_status, reword_learned_series, status_from_good_series


MNEMONIC_DIR = DATA_DIR / "mnemonic_images"


def slugify_category(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "custom"


def image_extension_from_bytes(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return ".img"


def save_picture_blob(word_id: int, picture_id: int, content: bytes) -> str:
    MNEMONIC_DIR.mkdir(parents=True, exist_ok=True)
    suffix = image_extension_from_bytes(content)
    image_path = MNEMONIC_DIR / f"word_{word_id}_picture_{picture_id}{suffix}"
    image_path.write_bytes(content)
    return str(image_path)


def existing_image_path(value: str) -> Path | None:
    if not value:
        return None
    image_path = Path(value)
    candidates = [image_path]
    if not image_path.is_absolute():
        candidates.append(DATA_DIR / image_path)
        candidates.append(DATA_DIR.parent / image_path)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def import_reword_backup(path: Path) -> None:
    source = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "WORD" not in tables:
        raise ValueError("Backup does not contain WORD table.")

    category_map = {}
    if "CATEGORY" in tables:
        for row in source.execute("SELECT ID, NAME_RUS FROM CATEGORY"):
            category_map[row["ID"]] = row["NAME_RUS"] or row["ID"]

    word_categories = {}
    if "WORD_CATEGORY" in tables:
        for row in source.execute("SELECT WORD_ID, CATEGORY_ID FROM WORD_CATEGORY"):
            word_categories.setdefault(row["WORD_ID"], category_map.get(row["CATEGORY_ID"], row["CATEGORY_ID"]))

    word_columns = {row["name"] for row in source.execute("PRAGMA table_info(WORD)")}
    picture_column = "PICTURE_ID" if "PICTURE_ID" in word_columns else "NULL AS PICTURE_ID"

    word_stats = {}
    if "WordStat" in tables:
        for row in source.execute("SELECT KeyWord, LastRepeatTime, TotalAnswerNumbers, GoodSeries FROM WordStat"):
            word_stats[row["KeyWord"]] = row

    pictures = {}
    if "PICTURE" in tables:
        for row in source.execute("SELECT ID, CONTENT FROM PICTURE WHERE CONTENT IS NOT NULL"):
            pictures[int(row["ID"])] = bytes(row["CONTENT"])

    target = connect_sqlite(APP_DB)
    target.execute("DELETE FROM words")
    rows_to_insert = []
    for row in source.execute(f"SELECT ID, WORD, {picture_column}, RUS, EXT_SOURCE_ID, Q_REP, S_REP, F_REC FROM WORD ORDER BY ID"):
        english = row["WORD"]
        if not english:
            continue
        stat = word_stats.get(english)
        if stat:
            good_series = int(stat["GoodSeries"] or 0)
            total_answers = int(stat["TotalAnswerNumbers"] or 0)
            last_repeat_time = int(stat["LastRepeatTime"] or 0)
            status = status_from_good_series(good_series)
        else:
            good_series = good_series_from_status("mastered" if row["S_REP"] else "review" if row["Q_REP"] else "new")
            total_answers = 1 if good_series else 0
            last_repeat_time = 0
            status = "known" if row["F_REC"] else "mastered" if row["S_REP"] else "review" if row["Q_REP"] else "new"
        picture_id = int(row["PICTURE_ID"] or 0)
        mnemonic_image = ""
        if picture_id and picture_id in pictures:
            mnemonic_image = save_picture_blob(int(row["ID"] or 0), picture_id, pictures[picture_id])
        rows_to_insert.append(
            (
                english,
                row["RUS"] or "",
                row["EXT_SOURCE_ID"] or "A1",
                word_categories.get(row["ID"], "Imported"),
                status,
                int(row["ID"] or 0),
                total_answers,
                good_series,
                last_repeat_time,
                mnemonic_image,
            )
        )

    target.executemany(
        """
        INSERT INTO words(
            word, translation, level, category, status, reword_id,
            total_answers, good_series, last_repeat_time, mnemonic_image
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows_to_insert,
    )
    if "DAILY_GOAL" in tables:
        row = source.execute("SELECT GOAL FROM DAILY_GOAL ORDER BY DATE DESC LIMIT 1").fetchone()
        if row and row["GOAL"]:
            target.execute(
                "INSERT OR REPLACE INTO progress(name, value) VALUES ('daily_goal', ?)",
                (json.dumps(int(row["GOAL"])),),
            )
    target.commit()
    source.close()
    target.close()


def export_reword_backup(path: Path) -> None:
    if path.exists():
        path.unlink()
    app_con = connect_sqlite(APP_DB)
    backup = sqlite3.connect(path)
    backup.executescript(
        """
        CREATE TABLE android_metadata (locale TEXT);
        CREATE TABLE SETTINGS (NAME TEXT NOT NULL PRIMARY KEY, VALUE TEXT);
        CREATE TABLE DAILY_GOAL (DATE TEXT NOT NULL PRIMARY KEY, GOAL INTEGER DEFAULT NULL, ADJUSTED_GOAL INTEGER DEFAULT NULL);
        CREATE TABLE CATEGORY (
            ID TEXT NOT NULL PRIMARY KEY,
            NAME_RUS TEXT, NAME_TUR TEXT, NAME_KOR TEXT, NAME_ARA TEXT, NAME_SPA TEXT,
            NAME_POR TEXT, NAME_ITA TEXT, NAME_DEU TEXT, NAME_FRA TEXT, NAME_UKR TEXT,
            NAME_JPN TEXT, NAME_ZHS TEXT, NAME_ZHT TEXT,
            IS_CUSTOM INTEGER NOT NULL, IS_SELECTED INTEGER NOT NULL,
            CUSTOM_ICON TEXT DEFAULT NULL, REG INTEGER DEFAULT NULL
        );
        CREATE TABLE WORD (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            WORD TEXT NOT NULL,
            REG INTEGER DEFAULT NULL,
            PICTURE_ID INTEGER DEFAULT NULL,
            RUS TEXT, TUR TEXT, KOR TEXT, ARA TEXT, SPA TEXT, POR TEXT, ITA TEXT,
            DEU TEXT, FRA TEXT, UKR TEXT, JPN TEXT, ZHS TEXT, ZHT TEXT,
            EXAMPLES_RUS TEXT, EXAMPLES_TUR TEXT, EXAMPLES_KOR TEXT, EXAMPLES_ARA TEXT,
            EXAMPLES_SPA TEXT, EXAMPLES_POR TEXT, EXAMPLES_ITA TEXT, EXAMPLES_DEU TEXT,
            EXAMPLES_FRA TEXT, EXAMPLES_UKR TEXT, EXAMPLES_JPN TEXT, EXAMPLES_ZHS TEXT,
            EXAMPLES_ZHT TEXT,
            POS INTEGER, EXT_SOURCE TEXT, EXT_SOURCE_ID TEXT,
            TRANSCRIPTION TEXT DEFAULT NULL, TRANSCRIPTION_US TEXT DEFAULT NULL, TRANSCRIPTION_BR TEXT DEFAULT NULL,
            Q_REC INTEGER NOT NULL DEFAULT 0, Q_REP INTEGER NOT NULL DEFAULT 0,
            T_REC INTEGER DEFAULT NULL, T_REP INTEGER DEFAULT NULL,
            I_REC INTEGER DEFAULT NULL, I_REP INTEGER DEFAULT NULL,
            S_REC INTEGER NOT NULL DEFAULT 0, S_REP INTEGER NOT NULL DEFAULT 0,
            E_REC REAL NOT NULL DEFAULT 2.5, E_REP REAL NOT NULL DEFAULT 2.5,
            F_REC INTEGER NOT NULL DEFAULT 0, F_REP INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE WORD_CATEGORY (ID INTEGER PRIMARY KEY AUTOINCREMENT, WORD_ID INTEGER NOT NULL, CATEGORY_ID TEXT NOT NULL);
        CREATE TABLE WordStat (
            Id INTEGER PRIMARY KEY AUTOINCREMENT,
            KeyWord NVARCHAR(64) NOT NULL,
            LastRepeatTime BIGINT NOT NULL,
            TotalAnswerNumbers INTEGER NOT NULL,
            GoodSeries INTEGER NOT NULL
        );
        CREATE TABLE UserWordSets (Id INTEGER, UserWordSetId INTEGER);
        CREATE TABLE Dictionaries (Id INTEGER PRIMARY KEY AUTOINCREMENT, Uuid NVARCHAR(128), DictionaryType INTEGER);
        CREATE TABLE LOG (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            TIMESTAMP INTEGER NOT NULL,
            LOCAL_DATE TEXT NOT NULL,
            WORD_ID INTEGER NOT NULL,
            MODE INTEGER NOT NULL,
            QUEUE INTEGER NOT NULL,
            STEP INTEGER NOT NULL,
            NQUEUE INTEGER NOT NULL,
            FLAGS INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE AUDIO (ID TEXT PRIMARY KEY, IS_CUSTOM INTEGER NOT NULL DEFAULT 0, CONTENT BLOB DEFAULT NULL, VAR INTEGER DEFAULT NULL);
        CREATE TABLE PICTURE (ID INTEGER PRIMARY KEY AUTOINCREMENT, SOURCE TEXT NOT NULL, SOURCE_ID TEXT NOT NULL, CONTENT BLOB DEFAULT NULL, IS_CUSTOM INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE WORD_AUDIO (ID INTEGER PRIMARY KEY AUTOINCREMENT, WORD_ID INTEGER NOT NULL, AUDIO_ID TEXT NOT NULL, ORD INTEGER NOT NULL);
        CREATE TABLE POLYGLOT_SYNC (NAME TEXT NOT NULL PRIMARY KEY, DATA TEXT NOT NULL);
        CREATE INDEX IDX_WORD_WORD ON WORD(WORD);
        CREATE INDEX WordStat_KeyWord ON WordStat(KeyWord);
        """
    )
    backup.execute("INSERT INTO android_metadata(locale) VALUES ('en_US')")
    backup.executemany(
        "INSERT INTO SETTINGS(NAME, VALUE) VALUES (?, ?)",
        [
            ("native_language", "RUS"),
            ("capability_regions", "us,br"),
            ("capability_pronunciation_variants", "us,br"),
            ("desktop_exporter", "EnglishLearningDesktop-PyQt6"),
            ("backup_format", "application/vnd.polyglot.backup"),
            ("db_backup_name", "WordStatistics"),
        ],
    )
    goal_row = app_con.execute("SELECT value FROM progress WHERE name='daily_goal'").fetchone()
    goal = int(json.loads(goal_row["value"])) if goal_row else 10
    backup.execute("INSERT INTO DAILY_GOAL(DATE, GOAL, ADJUSTED_GOAL) VALUES (?, ?, ?)", (time.strftime("%Y-%m-%d"), goal, goal))
    backup.execute("INSERT INTO Dictionaries(Uuid, DictionaryType) VALUES ('StdDictionary', 1)")

    rows = list(app_con.execute("SELECT * FROM words ORDER BY id"))
    category_ids = {row["category"]: slugify_category(row["category"]) for row in rows}
    for category, category_id in sorted(category_ids.items()):
        backup.execute(
            """
            INSERT OR IGNORE INTO CATEGORY(
                ID, NAME_RUS, NAME_TUR, NAME_KOR, NAME_ARA, NAME_SPA, NAME_POR, NAME_ITA,
                NAME_DEU, NAME_FRA, NAME_UKR, NAME_JPN, NAME_ZHS, NAME_ZHT,
                IS_CUSTOM, IS_SELECTED, CUSTOM_ICON, REG
            ) VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, 1, NULL, NULL)
            """,
            (category_id, category),
        )

    now_ms = int(time.time() * 1000)
    sync_words = []
    learned_words = []
    for row in rows:
        good_series = int(row["good_series"] or good_series_from_status(row["status"]))
        total_answers = int(row["total_answers"] or (1 if good_series else 0))
        last_repeat_time = int(row["last_repeat_time"] or (now_ms if total_answers else 0))
        q_rep = 1 if row["status"] == "review" else 0
        s_rep = 1 if row["status"] in {"mastered", "known"} else 0
        f_rec = 1 if row["status"] == "known" else 0
        picture_id = None
        image_path = existing_image_path(row["mnemonic_image"] or "")
        if image_path:
            picture_content = image_path.read_bytes()
            backup.execute(
                "INSERT INTO PICTURE(SOURCE, SOURCE_ID, CONTENT, IS_CUSTOM) VALUES (?, ?, ?, 1)",
                ("MemWord", image_path.name, sqlite3.Binary(picture_content)),
            )
            picture_id = int(backup.execute("SELECT last_insert_rowid()").fetchone()[0])
        backup.execute(
            """
            INSERT INTO WORD(
                WORD, REG, PICTURE_ID, RUS, POS, EXT_SOURCE, EXT_SOURCE_ID,
                Q_REC, Q_REP, S_REC, S_REP, E_REC, E_REP, F_REC, F_REP
            ) VALUES (?, NULL, ?, ?, 1, 'EnglishLearningDesktop-PyQt6', ?, ?, ?, ?, ?, 2.5, 2.5, ?, 0)
            """,
            (row["word"], picture_id, row["translation"], row["level"], 1 if q_rep or s_rep else 0, q_rep, s_rep, s_rep, f_rec),
        )
        word_id = backup.execute("SELECT last_insert_rowid()").fetchone()[0]
        backup.execute("INSERT INTO WORD_CATEGORY(WORD_ID, CATEGORY_ID) VALUES (?, ?)", (word_id, category_ids[row["category"]]))
        backup.execute(
            "INSERT INTO WordStat(KeyWord, LastRepeatTime, TotalAnswerNumbers, GoodSeries) VALUES (?, ?, ?, ?)",
            (row["word"], last_repeat_time, total_answers, good_series),
        )
        export_id = int(row["reword_id"] or word_id)
        if total_answers:
            if good_series >= reword_learned_series():
                learned_words.append(str(export_id))
            else:
                item = {"id": export_id, "c": total_answers}
                if good_series:
                    item["r"] = good_series
                sync_words.append(item)
    backup.execute(
        "INSERT INTO POLYGLOT_SYNC(NAME, DATA) VALUES (?, ?)",
        (
            "cloud_data_json",
            json.dumps({"version": 2, "time": now_ms, "words": sync_words, "learned": ",".join(learned_words)}, ensure_ascii=False),
        ),
    )
    backup.commit()
    app_con.close()
    backup.close()
