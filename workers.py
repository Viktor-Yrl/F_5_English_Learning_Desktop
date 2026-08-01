from pathlib import Path

import audio_service
import backup_service
from PyQt6.QtCore import QThread, pyqtSignal


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

