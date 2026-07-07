from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerResult:
    is_correct: bool
    attempts_left: int
    message: str
    status: str
    good_series: int
    event_type: str = ""
    became_mastered: bool = False
    daily_goal_incremented: bool = False


@dataclass(frozen=True)
class StudyWord:
    id: int
    word: str
    translation: str
    level: str
    category: str
    status: str
    transcription: str = ""
    mnemonic_image: str = ""
    example_en: str = ""
    example_ru: str = ""
