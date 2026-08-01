from dataclasses import dataclass


@dataclass
class StudySession:
    """Keeps volatile state for the currently displayed study word."""

    word_id: int | None = None
    correct_answer: str = ""
    english_word: str = ""
    status: str = "new"
    mode: str = "learn"
    phase: str = "preview"
    attempts_left: int = 3

    def start_word(self, word_id: int, word: str, status: str, mode: str) -> None:
        self.word_id = int(word_id)
        self.english_word = word or ""
        self.correct_answer = self.english_word.strip().lower()
        self.status = status or "new"
        self.mode = mode or "learn"
        self.attempts_left = 3
        self.phase = "preview" if self.is_new_learning else "typing"

    @property
    def is_new_learning(self) -> bool:
        return self.mode == "learn" and self.status == "new"

    @property
    def is_preview(self) -> bool:
        return self.phase == "preview"

    def begin_typing(self) -> None:
        self.phase = "typing"

    def reset_attempts(self) -> None:
        self.attempts_left = 3

    def fail_local_new_attempt(self) -> str:
        self.attempts_left = max(0, self.attempts_left - 1)
        if self.attempts_left <= 0:
            answer = self.correct_answer
            self.reset_attempts()
            return f"Answer: {answer}. Try again until correct."
        return f"Try again. Attempts left: {self.attempts_left}"

    def should_lock_navigation(self) -> bool:
        return self.is_new_learning and self.phase == "typing"
