import asyncio
import hashlib
import subprocess
from pathlib import Path

from db import DATA_DIR


AUDIO_CACHE_DIR = DATA_DIR / "audio_cache"

EDGE_VOICES = {
    "Edge Jenny Natural": "en-US-JennyNeural",
    "Edge Guy Natural": "en-US-GuyNeural",
    "Edge Aria Natural": "en-US-AriaNeural",
    "Edge Sonia Natural": "en-GB-SoniaNeural",
    "Edge Ryan Natural": "en-GB-RyanNeural",
}


def cache_path(text: str, voice: str, rate: float) -> Path:
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = f"{voice}|{rate:.2f}|{text.strip().lower()}".encode("utf-8")
    digest = hashlib.sha1(key).hexdigest()
    return AUDIO_CACHE_DIR / f"{digest}.mp3"


def edge_rate_value(rate: float) -> str:
    percent = round((float(rate) - 1.0) * 100)
    percent = max(-50, min(100, percent))
    return f"{percent:+d}%"


async def _save_edge_tts(text: str, output: Path, voice: str, rate: float) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=edge_rate_value(rate))
    await communicate.save(str(output))


def synthesize_edge_tts(text: str, voice_label: str, rate: float) -> Path:
    voice = EDGE_VOICES.get(voice_label, "en-US-JennyNeural")
    output = cache_path(text, voice, rate)
    if output.exists() and output.stat().st_size > 0:
        return output
    asyncio.run(_save_edge_tts(text, output, voice, rate))
    return output


def speak_with_windows_sapi(text: str, voice: str, rate: float) -> None:
    safe_text = text.replace("'", "''")
    sapi_rate = int((float(rate) - 1.0) * 10)
    sapi_rate = max(-10, min(10, sapi_rate))
    select_voice = ""
    if voice and voice != "System text-to-speech engine":
        select_voice = f"try {{ $s.SelectVoice('{voice.replace(chr(39), chr(39) + chr(39))}') }} catch {{ }}"
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Rate = {sapi_rate}; "
        f"{select_voice} "
        f"$s.Speak('{safe_text}');"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
