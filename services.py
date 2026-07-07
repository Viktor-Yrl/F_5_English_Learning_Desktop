import json
import time
from datetime import date, timedelta

from db import APP_DB, connect_sqlite
from models import AnswerResult


EVENT_TYPES = {"new_learned", "reviewed", "known", "mastered"}


def reword_learned_series() -> int:
    return 8


def status_from_good_series(good_series: int) -> str:
    if good_series <= 0:
        return "new"
    if good_series < reword_learned_series():
        return "review"
    return "mastered"


def good_series_from_status(status: str) -> int:
    return {"new": 0, "review": 3, "mastered": 8, "known": 8}.get(status, 0)


def category_filter_sql(categories: list[str]) -> tuple[str, list[str]]:
    if not categories:
        return "", []
    return f"category IN ({','.join('?' for _ in categories)})", categories


def dashboard_stats() -> dict:
    con = connect_sqlite(APP_DB)
    total = con.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    due = con.execute("SELECT COUNT(*) FROM words WHERE status IN ('new', 'review')").fetchone()[0]
    mastered = con.execute("SELECT COUNT(*) FROM words WHERE status IN ('mastered', 'known')").fetchone()[0]
    review = con.execute("SELECT COUNT(*) FROM words WHERE status='review'").fetchone()[0]
    new = con.execute("SELECT COUNT(*) FROM words WHERE status='new'").fetchone()[0]
    hard = con.execute("SELECT COUNT(*) FROM words WHERE good_series=0 AND total_answers>0").fetchone()[0]
    con.close()
    return {"total": total, "due": due, "mastered": mastered, "review": review, "new": new, "hard": hard}


def study_status_filter(mode: str) -> str:
    return "status='review'" if mode == "review" else "status='new'"


def find_random_word_id(mode: str, categories: list[str]) -> int | None:
    con = connect_sqlite(APP_DB)
    params: list[str] = []
    filters = [study_status_filter(mode)]
    category_filter, category_params = category_filter_sql(categories)
    if category_filter:
        filters.append(category_filter)
        params.extend(category_params)
    row = con.execute(
        f"SELECT id FROM words WHERE {' AND '.join(filters)} ORDER BY RANDOM() LIMIT 1",
        params,
    ).fetchone()
    con.close()
    return int(row["id"]) if row else None


def get_word(word_id: int):
    con = connect_sqlite(APP_DB)
    row = con.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
    con.close()
    return row


def mark_known(word_id: int) -> None:
    con = connect_sqlite(APP_DB)
    con.execute(
        """
        UPDATE words
        SET total_answers=total_answers+1, good_series=?, last_repeat_time=?, status='known'
        WHERE id=?
        """,
        (reword_learned_series(), int(time.time() * 1000), word_id),
    )
    con.commit()
    con.close()
    record_study_event(word_id, "known")


def check_answer(word_id: int, answer: str, correct_answer: str, attempts_left: int) -> AnswerResult:
    con = connect_sqlite(APP_DB)
    row = con.execute("SELECT * FROM words WHERE id=?", (word_id,)).fetchone()
    if not row:
        con.close()
        return AnswerResult(False, attempts_left, "Word not found.", "new", 0)

    normalized_answer = answer.strip().lower()
    if not normalized_answer:
        con.close()
        return AnswerResult(False, attempts_left, "Type an answer first.", row["status"] or "new", int(row["good_series"] or 0))

    normalized_correct = correct_answer.strip().lower()
    now_ms = int(time.time() * 1000)
    previous_status = str(row["status"] or "new")
    event_type = ""
    became_mastered = False
    daily_goal_incremented = False

    if normalized_answer == normalized_correct:
        good_series = min(int(row["good_series"] or 0) + 1, reword_learned_series())
        status = status_from_good_series(good_series)
        message = "Correct"
        attempts_left = 3
        if previous_status == "new":
            event_type = "new_learned"
            increment_daily_learned()
            daily_goal_incremented = True
        else:
            event_type = "reviewed"
        became_mastered = status == "mastered" and previous_status not in {"mastered", "known"}
    else:
        attempts_left = max(0, attempts_left - 1)
        if attempts_left > 0:
            con.close()
            return AnswerResult(False, attempts_left, f"Try again. Attempts left: {attempts_left}", previous_status, int(row["good_series"] or 0))
        good_series = 0
        status = "review"
        message = f"Answer: {correct_answer}"

    con.execute(
        """
        UPDATE words
        SET total_answers=total_answers+1, good_series=?, last_repeat_time=?, status=?
        WHERE id=?
        """,
        (good_series, now_ms, status, word_id),
    )
    con.commit()
    con.close()

    if event_type:
        record_study_event(word_id, event_type)
    if became_mastered:
        record_study_event(word_id, "mastered")

    return AnswerResult(
        normalized_answer == normalized_correct,
        attempts_left,
        message,
        status,
        good_series,
        event_type,
        became_mastered,
        daily_goal_incremented,
    )


def daily_goal_value(default: int = 10) -> int:
    con = connect_sqlite(APP_DB)
    row = con.execute("SELECT value FROM progress WHERE name='daily_goal'").fetchone()
    con.close()
    if not row:
        return default
    try:
        return max(1, int(json.loads(row["value"])))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def set_daily_goal(value: int) -> None:
    con = connect_sqlite(APP_DB)
    con.execute(
        "INSERT OR REPLACE INTO progress(name, value) VALUES ('daily_goal', ?)",
        (json.dumps(int(value)),),
    )
    con.commit()
    con.close()


def daily_learned_key(day: date | None = None) -> str:
    return f"daily_learned.{(day or date.today()).isoformat()}"


def learned_new_words_today() -> int:
    con = connect_sqlite(APP_DB)
    row = con.execute("SELECT value FROM progress WHERE name=?", (daily_learned_key(),)).fetchone()
    con.close()
    if not row:
        return 0
    try:
        return max(0, int(json.loads(row["value"])))
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0


def increment_daily_learned() -> None:
    goal = daily_goal_value()
    learned = min(learned_new_words_today() + 1, goal)
    con = connect_sqlite(APP_DB)
    con.execute(
        "INSERT OR REPLACE INTO progress(name, value) VALUES (?, ?)",
        (daily_learned_key(), json.dumps(learned)),
    )
    con.commit()
    con.close()


def record_study_event(word_id: int | None, event_type: str) -> None:
    if event_type not in EVENT_TYPES:
        return
    con = connect_sqlite(APP_DB)
    con.execute(
        """
        INSERT INTO study_events(word_id, event_type, event_date, event_time)
        VALUES (?, ?, ?, ?)
        """,
        (int(word_id or 0), event_type, date.today().isoformat(), int(time.time() * 1000)),
    )
    con.commit()
    con.close()


def stats_period_days(period: str) -> list[str]:
    today = date.today()
    if period == "30 days":
        start = today - timedelta(days=29)
    elif period == "90 days":
        start = today - timedelta(days=89)
    elif period == "Year":
        start = today - timedelta(days=364)
    elif period == "All time":
        con = connect_sqlite(APP_DB)
        row = con.execute("SELECT MIN(event_date) FROM study_events").fetchone()
        con.close()
        start = date.fromisoformat(row[0]) if row and row[0] else today - timedelta(days=6)
    else:
        start = today - timedelta(days=6)
    days_count = (today - start).days + 1
    return [(start + timedelta(days=i)).isoformat() for i in range(days_count)]


def statistics_data(days: list[str], categories: list[str]) -> tuple[dict[str, dict[str, int]], dict[str, int], dict[str, int], int]:
    keys = ["known", "new_learned", "reviewed", "mastered"]
    blank = {key: 0 for key in keys}
    data = {day: dict(blank) for day in days}
    period_totals = dict(blank)
    total_totals = dict(blank)
    if not days:
        return data, period_totals, total_totals, 0

    con = connect_sqlite(APP_DB)
    start, end = days[0], days[-1]
    for row in con.execute(
        """
        SELECT event_date, event_type, COUNT(DISTINCT word_id) AS amount
        FROM study_events
        WHERE event_date BETWEEN ? AND ?
        GROUP BY event_date, event_type
        """,
        (start, end),
    ):
        event_type = row["event_type"]
        if event_type in data.get(row["event_date"], {}):
            amount = int(row["amount"] or 0)
            data[row["event_date"]][event_type] = amount
            period_totals[event_type] += amount

    for row in con.execute(
        """
        SELECT event_type, COUNT(DISTINCT word_id || ':' || event_date) AS amount
        FROM study_events
        GROUP BY event_type
        """
    ):
        if row["event_type"] in total_totals:
            total_totals[row["event_type"]] = int(row["amount"] or 0)

    category_filter, params = category_filter_sql(categories)
    where = "WHERE status='new'"
    if category_filter:
        where += f" AND {category_filter}"
    learning_now = con.execute(f"SELECT COUNT(*) FROM words {where}", params).fetchone()[0]
    con.close()
    return data, period_totals, total_totals, int(learning_now or 0)
