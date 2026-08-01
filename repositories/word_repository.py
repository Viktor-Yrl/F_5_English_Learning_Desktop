import json
from datetime import date
from typing import Any

from db import APP_DB, connect_sqlite


def category_filter_sql(categories: list[str]) -> tuple[str, list[str]]:
    if not categories:
        return "", []
    return f"category IN ({','.join('?' for _ in categories)})", categories


def word_count_where(where: str = "", params: list[Any] | tuple[Any, ...] = ()) -> int:
    con = connect_sqlite(APP_DB)
    row = con.execute(f"SELECT COUNT(*) FROM words {where}", params).fetchone()
    con.close()
    return int(row[0] or 0)


def dashboard_counts(categories: list[str] | None = None) -> dict[str, int]:
    params: list[Any] = []
    filters: list[str] = []
    category_filter, category_params = category_filter_sql(categories or [])
    if category_filter:
        filters.append(category_filter)
        params.extend(category_params)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    prefix = f"{where} AND" if where else "WHERE"
    con = connect_sqlite(APP_DB)
    result = {
        "total": con.execute(f"SELECT COUNT(*) FROM words {where}", params).fetchone()[0],
        "due": con.execute(f"SELECT COUNT(*) FROM words {prefix} status IN ('new', 'review')", params).fetchone()[0],
        "mastered": con.execute(f"SELECT COUNT(*) FROM words {prefix} status IN ('mastered', 'known')", params).fetchone()[0],
        "review": con.execute(f"SELECT COUNT(*) FROM words {prefix} status='review'", params).fetchone()[0],
        "new": con.execute(f"SELECT COUNT(*) FROM words {prefix} status='new'", params).fetchone()[0],
        "hard": con.execute(f"SELECT COUNT(*) FROM words {prefix} good_series=0 AND total_answers>0", params).fetchone()[0],
    }
    con.close()
    return {key: int(value or 0) for key, value in result.items()}


def review_candidates(categories: list[str] | None = None):
    params: list[Any] = []
    filters = ["status='review'"]
    category_filter, category_params = category_filter_sql(categories or [])
    if category_filter:
        filters.append(category_filter)
        params.extend(category_params)
    con = connect_sqlite(APP_DB)
    rows = con.execute(
        f"SELECT id, last_repeat_time, good_series FROM words WHERE {' AND '.join(filters)}",
        params,
    ).fetchall()
    con.close()
    return rows


def random_new_word_id(categories: list[str] | None = None) -> int | None:
    params: list[Any] = []
    filters = ["status='new'"]
    category_filter, category_params = category_filter_sql(categories or [])
    if category_filter:
        filters.append(category_filter)
        params.extend(category_params)
    con = connect_sqlite(APP_DB)
    row = con.execute(
        f"SELECT id FROM words WHERE {' AND '.join(filters)} ORDER BY RANDOM() LIMIT 1",
        params,
    ).fetchone()
    con.close()
    return int(row["id"]) if row else None


def get_word(word_id: int):
    con = connect_sqlite(APP_DB)
    row = con.execute("SELECT * FROM words WHERE id=?", (int(word_id),)).fetchone()
    con.close()
    return row

def mark_learning_selected(word_id: int) -> None:
    con = connect_sqlite(APP_DB)
    con.execute("UPDATE words SET learning_selected=1 WHERE id=?", (int(word_id),))
    con.commit()
    con.close()



def mark_known(word_id: int, learned_series: int, now_ms: int) -> None:
    con = connect_sqlite(APP_DB)
    con.execute(
        """
        UPDATE words
        SET total_answers=total_answers+1, good_series=?, last_repeat_time=?, status='known'
        WHERE id=?
        """,
        (int(learned_series), int(now_ms), int(word_id)),
    )
    con.commit()
    con.close()


def update_answer_result(word_id: int, good_series: int, now_ms: int, status: str) -> None:
    con = connect_sqlite(APP_DB)
    con.execute(
        """
        UPDATE words
        SET total_answers=total_answers+1, good_series=?, last_repeat_time=?, status=?
        WHERE id=?
        """,
        (int(good_series), int(now_ms), status, int(word_id)),
    )
    con.commit()
    con.close()


def get_progress(name: str):
    con = connect_sqlite(APP_DB)
    row = con.execute("SELECT value FROM progress WHERE name=?", (name,)).fetchone()
    con.close()
    if not row:
        return None
    return row["value"]


def set_progress(name: str, value) -> None:
    con = connect_sqlite(APP_DB)
    con.execute(
        "INSERT OR REPLACE INTO progress(name, value) VALUES (?, ?)",
        (name, json.dumps(value, ensure_ascii=False)),
    )
    con.commit()
    con.close()


def record_event(word_id: int | None, event_type: str, event_date: date, event_time: int) -> None:
    con = connect_sqlite(APP_DB)
    con.execute(
        """
        INSERT INTO study_events(word_id, event_type, event_date, event_time)
        VALUES (?, ?, ?, ?)
        """,
        (int(word_id or 0), event_type, event_date.isoformat(), int(event_time)),
    )
    con.commit()
    con.close()


def first_event_date() -> str | None:
    con = connect_sqlite(APP_DB)
    row = con.execute("SELECT MIN(event_date) FROM study_events").fetchone()
    con.close()
    return row[0] if row and row[0] else None


def event_counts_between(start: str, end: str):
    con = connect_sqlite(APP_DB)
    rows = con.execute(
        """
        SELECT event_date, event_type, COUNT(DISTINCT word_id) AS amount
        FROM study_events
        WHERE event_date BETWEEN ? AND ?
        GROUP BY event_date, event_type
        """,
        (start, end),
    ).fetchall()
    con.close()
    return rows


def event_totals():
    con = connect_sqlite(APP_DB)
    rows = con.execute(
        """
        SELECT event_type, COUNT(DISTINCT word_id || ':' || event_date) AS amount
        FROM study_events
        GROUP BY event_type
        """
    ).fetchall()
    con.close()
    return rows


def count_new_words(categories: list[str] | None = None) -> int:
    category_filter, params = category_filter_sql(categories or [])
    where = "WHERE status='new'"
    if category_filter:
        where += f" AND {category_filter}"
    return word_count_where(where, params)
