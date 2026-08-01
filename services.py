import json
import random
import time
from datetime import date, timedelta

from models import AnswerResult
from repositories import word_repository as words


EVENT_TYPES = {"new_learned", "reviewed", "known", "mastered"}

MINUTE_MS = 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000
REVIEW_INTERVAL_MS = [
    0,
    10 * MINUTE_MS,
    1 * DAY_MS,
    3 * DAY_MS,
    7 * DAY_MS,
    14 * DAY_MS,
    30 * DAY_MS,
    90 * DAY_MS,
]


def review_interval_ms(good_series: int) -> int:
    index = max(0, min(int(good_series or 0), len(REVIEW_INTERVAL_MS) - 1))
    return REVIEW_INTERVAL_MS[index]


def next_review_time_ms(last_repeat_time: int, good_series: int) -> int:
    if not last_repeat_time:
        return 0
    return int(last_repeat_time) + review_interval_ms(good_series)


def end_of_today_ms() -> int:
    tomorrow = date.today() + timedelta(days=1)
    return int(time.mktime(tomorrow.timetuple()) * 1000) - 1


def review_due_count(categories: list[str] | None = None, cutoff_ms: int | None = None) -> int:
    cutoff = int(cutoff_ms if cutoff_ms is not None else time.time() * 1000)
    return sum(
        1
        for row in words.review_candidates(categories or [])
        if next_review_time_ms(int(row["last_repeat_time"] or 0), int(row["good_series"] or 0)) <= cutoff
    )


def review_due_today_count(categories: list[str] | None = None) -> int:
    return review_due_count(categories, end_of_today_ms())


def review_due_now_count(categories: list[str] | None = None) -> int:
    return review_due_count(categories, int(time.time() * 1000))


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
    return words.category_filter_sql(categories)


def dashboard_stats(categories: list[str] | None = None) -> dict:
    result = words.dashboard_counts(categories or [])
    result["due_today"] = review_due_today_count(categories or [])
    result["due_now"] = review_due_now_count(categories or [])
    return result


def find_random_word_id(mode: str, categories: list[str]) -> int | None:
    if mode != "review":
        return words.random_new_word_id(categories)
    now_ms = int(time.time() * 1000)
    due_ids = [
        int(row["id"])
        for row in words.review_candidates(categories)
        if next_review_time_ms(int(row["last_repeat_time"] or 0), int(row["good_series"] or 0)) <= now_ms
    ]
    return random.choice(due_ids) if due_ids else None


def get_word(word_id: int):
    return words.get_word(word_id)


def mark_learning_selected(word_id: int) -> None:
    words.mark_learning_selected(word_id)


def mark_known(word_id: int) -> None:
    words.mark_known(word_id, reword_learned_series(), int(time.time() * 1000))
    record_study_event(word_id, "known")


def check_answer(word_id: int, answer: str, correct_answer: str, attempts_left: int) -> AnswerResult:
    row = words.get_word(word_id)
    if not row:
        return AnswerResult(False, attempts_left, "Word not found.", "new", 0)

    normalized_answer = answer.strip().lower()
    if not normalized_answer:
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
            return AnswerResult(False, attempts_left, f"Try again. Attempts left: {attempts_left}", previous_status, int(row["good_series"] or 0))
        good_series = 0
        status = "review"
        message = f"Answer: {correct_answer}"

    words.update_answer_result(word_id, good_series, now_ms, status)

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
    value = words.get_progress("daily_goal")
    if value is None:
        return default
    try:
        return max(1, int(json.loads(value)))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def set_daily_goal(value: int) -> None:
    words.set_progress("daily_goal", int(value))


def daily_learned_key(day: date | None = None) -> str:
    return f"daily_learned.{(day or date.today()).isoformat()}"


def learned_new_words_today() -> int:
    value = words.get_progress(daily_learned_key())
    if value is None:
        return 0
    try:
        return max(0, int(json.loads(value)))
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0


def increment_daily_learned() -> None:
    goal = daily_goal_value()
    learned = min(learned_new_words_today() + 1, goal)
    words.set_progress(daily_learned_key(), learned)


def record_study_event(word_id: int | None, event_type: str) -> None:
    if event_type not in EVENT_TYPES:
        return
    words.record_event(word_id, event_type, date.today(), int(time.time() * 1000))


def stats_period_days(period: str) -> list[str]:
    today = date.today()
    if period == "30 days":
        start = today - timedelta(days=29)
    elif period == "90 days":
        start = today - timedelta(days=89)
    elif period == "Year":
        start = today - timedelta(days=364)
    elif period == "All time":
        first = words.first_event_date()
        start = date.fromisoformat(first) if first else today - timedelta(days=6)
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

    start, end = days[0], days[-1]
    for row in words.event_counts_between(start, end):
        event_type = row["event_type"]
        if event_type in data.get(row["event_date"], {}):
            amount = int(row["amount"] or 0)
            data[row["event_date"]][event_type] = amount
            period_totals[event_type] += amount

    for row in words.event_totals():
        if row["event_type"] in total_totals:
            total_totals[row["event_type"]] = int(row["amount"] or 0)

    return data, period_totals, total_totals, words.count_new_words(categories)
