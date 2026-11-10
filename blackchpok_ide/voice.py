"""Голосове керування агентом: запис, розпізнавання мовлення, озвучення.

Працює на тому, що вже є в системі, без обов'язкових сторонніх пакетів:

* **Розпізнавання** — вбудований рушій Windows (``System.Speech``) через
  PowerShell; якщо в системі є ``whisper.cpp`` (``whisper-cli.exe``) у теці
  рушія, використовується він — він точніший і не потребує мережі.
* **Запис** — ``winmm`` (``waveInOpen``) нативно, без pyaudio.
* **Озвучення** — SAPI (``SpeechSynthesizer``): агент може відповідати
  голосом.

Модуль не тягне tkinter; усі важкі операції — окремі функції, які можна
викликати з робочого потоку.
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

LOG = logging.getLogger("blackchpok.voice")

IS_WINDOWS = os.name == "nt"

#: Частота й розрядність запису (16 кГц моно — стандарт для мовлення).
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2


# ─────────────────────────────────────────────────────────────────────────────
# Стан і налаштування
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VoiceSettings:
    """Параметри голосового керування."""

    enabled: bool = False
    auto_send: bool = True          # надсилати розпізнане агенту одразу
    speak_replies: bool = False     # озвучувати відповіді агента
    language: str = "uk-UA"
    whisper_dir: str = ""           # тека з whisper-cli.exe (необов'язково)
    model_path: str = ""            # файл моделі whisper (ggml-*.bin)
    seconds: float = 5.0            # типова тривалість запису


@dataclass
class SpeechResult:
    """Результат розпізнавання."""

    ok: bool
    text: str = ""
    engine: str = ""
    detail: str = ""
    duration: float = 0.0

    def __bool__(self) -> bool:
        return self.ok and bool(self.text.strip())


# ─────────────────────────────────────────────────────────────────────────────
# Наявність рушіїв
# ─────────────────────────────────────────────────────────────────────────────

def _powershell() -> str:
    """Шлях до PowerShell (у Windows є завжди)."""
    for name in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def windows_speech_available() -> bool:
    """Чи є вбудований рушій розпізнавання Windows."""
    return IS_WINDOWS and bool(_powershell())


def whisper_cli(directory: str = "") -> Optional[Path]:
    """Знайти ``whisper-cli.exe`` у вказаній теці або поряд із рушієм."""
    candidates: list[Path] = []
    if directory:
        candidates.append(Path(directory))
    try:
        from . import runtime

        candidates.append(runtime.runtime_dir())
        candidates.append(runtime.runtime_dir() / "whisper")
    except Exception:  # noqa: BLE001 - модуль може бути недоступний
        pass
    for folder in candidates:
        for name in ("whisper-cli.exe", "main.exe", "whisper.exe"):
            path = folder / name
            if path.exists():
                return path
    return None


def engines() -> list[tuple[str, bool, str]]:
    """Доступні рушії: (ключ, доступний, опис)."""
    return [
        ("whisper", whisper_cli() is not None,
         "whisper.cpp — точніше, працює офлайн"),
        ("windows", windows_speech_available(),
         "Вбудований рушій Windows — без налаштувань"),
    ]


def best_engine(whisper_dir: str = "") -> str:
    """Який рушій використати: спершу whisper, потім Windows."""
    if whisper_cli(whisper_dir) is not None:
        return "whisper"
    if windows_speech_available():
        return "windows"
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Запис звуку (winmm, без сторонніх пакетів)
# ─────────────────────────────────────────────────────────────────────────────

def record_wav(target: Path, seconds: float = 5.0,
               on_tick: Optional[Callable[[float], None]] = None) -> tuple[bool, str]:
    """Записати мікрофон у WAV-файл. Повертає (успіх, пояснення)."""
    if not IS_WINDOWS:
        return False, "Запис підтримується лише у Windows."
    try:
        winmm = ctypes.WinDLL("winmm")
    except OSError as exc:
        return False, f"Немає доступу до winmm: {exc}"

    seconds = max(0.5, min(60.0, float(seconds)))
    frames = int(SAMPLE_RATE * seconds)
    buffer = ctypes.create_string_buffer(frames * SAMPLE_WIDTH * CHANNELS)

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [
            ("wFormatTag", ctypes.c_ushort),
            ("nChannels", ctypes.c_ushort),
            ("nSamplesPerSec", ctypes.c_uint32),
            ("nAvgBytesPerSec", ctypes.c_uint32),
            ("nBlockAlign", ctypes.c_ushort),
            ("wBitsPerSample", ctypes.c_ushort),
            ("cbSize", ctypes.c_ushort),
        ]

    class WAVEHDR(ctypes.Structure):
        _fields_ = [
            ("lpData", ctypes.c_void_p),
            ("dwBufferLength", ctypes.c_uint32),
            ("dwBytesRecorded", ctypes.c_uint32),
            ("dwUser", ctypes.c_void_p),
            ("dwFlags", ctypes.c_uint32),
            ("dwLoops", ctypes.c_uint32),
            ("lpNext", ctypes.c_void_p),
            ("reserved", ctypes.c_void_p),
        ]

    fmt = WAVEFORMATEX(
        wFormatTag=1,  # PCM
        nChannels=CHANNELS,
        nSamplesPerSec=SAMPLE_RATE,
        nAvgBytesPerSec=SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH,
        nBlockAlign=CHANNELS * SAMPLE_WIDTH,
        wBitsPerSample=SAMPLE_WIDTH * 8,
        cbSize=0,
    )
    handle = ctypes.c_void_p()
    try:
        result = winmm.waveInOpen(ctypes.byref(handle), ctypes.c_uint(0),
                                  ctypes.byref(fmt), None, None, 0)
        if result != 0:
            return False, f"Мікрофон недоступний (код {result}). Перевір дозволи."
        header = WAVEHDR(
            lpData=ctypes.cast(buffer, ctypes.c_void_p),
            dwBufferLength=len(buffer),
            dwBytesRecorded=0, dwUser=None, dwFlags=0, dwLoops=1,
            lpNext=None, reserved=None,
        )
        winmm.waveInPrepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
        winmm.waveInStart(handle)
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            time.sleep(0.05)
            if on_tick is not None:
                on_tick(time.monotonic() - started)
        winmm.waveInStop(handle)
        winmm.waveInUnprepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
    except Exception as exc:  # noqa: BLE001 - показуємо причину
        return False, f"Помилка запису: {type(exc).__name__}: {exc}"
    finally:
        if handle:
            try:
                winmm.waveInClose(handle)
            except Exception:  # noqa: BLE001
                pass

    try:
        with wave.open(str(target), "wb") as wav:
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(SAMPLE_WIDTH)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(buffer.raw)
    except OSError as exc:
        return False, f"Не вдалось зберегти запис: {exc}"
    return True, f"Записано {seconds:.1f} с"


# ─────────────────────────────────────────────────────────────────────────────
# Розпізнавання
# ─────────────────────────────────────────────────────────────────────────────

_PS_RECOGNISE = """
Add-Type -AssemblyName System.Speech
$engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine
$engine.SetInputToDefaultAudioDevice()
$dictation = New-Object System.Speech.Recognition.DictationGrammar
$engine.LoadGrammar($dictation)
$result = $engine.Recognize([TimeSpan]::FromSeconds({seconds}))
if ($result -ne $null) {
    Write-Output ("TEXT:" + $result.Text)
} else {
    Write-Output "TEXT:"
}
$engine.Dispose()
"""

_PS_RECOGNISE_FILE = """
param([string]$Path)
Add-Type -AssemblyName System.Speech
$engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine
$engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
$engine.SetInputToWaveFile($Path)
$result = $engine.Recognize([TimeSpan]::FromSeconds({seconds}))
if ($result -ne $null) { Write-Output ("TEXT:" + $result.Text) } else { Write-Output "TEXT:" }
$engine.Dispose()
"""


def recognize_with_windows(seconds: float = 5.0,
                           wav_path: Optional[Path] = None) -> SpeechResult:
    """Розпізнати мовлення вбудованим рушієм Windows."""
    shell = _powershell()
    if not shell:
        return SpeechResult(False, detail="PowerShell не знайдено.")
    script = _PS_RECOGNISE_FILE if wav_path is not None else _PS_RECOGNISE
    script = script.replace("{seconds}", f"{max(1.0, float(seconds)):.0f}")
    command = [shell, "-NoProfile", "-NonInteractive", "-Command", script]
    if wav_path is not None:
        command.extend(["-Path", str(wav_path)])
    started = time.monotonic()
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=max(20.0, float(seconds) + 20), shell=False)
    except subprocess.TimeoutExpired:
        return SpeechResult(False, detail="Розпізнавання не завершилось вчасно.")
    except OSError as exc:
        return SpeechResult(False, detail=f"Не вдалось запустити рушій: {exc}")

    elapsed = time.monotonic() - started
    out = (proc.stdout or "").strip()
    for line in out.splitlines():
        if line.startswith("TEXT:"):
            text = line[5:].strip()
            if text:
                return SpeechResult(True, text, "windows", duration=elapsed)
            return SpeechResult(False, detail="Нічого не розпізнано — спробуй ще раз.",
                                engine="windows", duration=elapsed)
    detail = (proc.stderr or out or "Порожня відповідь рушія.").strip()[:200]
    return SpeechResult(False, detail=detail, engine="windows", duration=elapsed)


def recognize_with_whisper(wav_path: Path, *, cli: Path,
                           model: str = "", language: str = "uk",
                           timeout: float = 180.0) -> SpeechResult:
    """Розпізнати записаний файл через whisper.cpp."""
    if not wav_path.exists():
        return SpeechResult(False, detail=f"Немає файлу запису: {wav_path}")
    command = [str(cli), "-f", str(wav_path), "-nt", "-l", (language or "uk")[:2]]
    if model:
        command.extend(["-m", str(model)])
    started = time.monotonic()
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return SpeechResult(False, detail=f"whisper недоступний: {exc}")
    elapsed = time.monotonic() - started
    text = " ".join(
        line.strip() for line in (proc.stdout or "").splitlines()
        if line.strip() and not line.startswith("[")
    ).strip()
    if proc.returncode != 0 and not text:
        return SpeechResult(False, detail=(proc.stderr or "")[:200],
                            engine="whisper", duration=elapsed)
    if not text:
        return SpeechResult(False, detail="whisper не розпізнав мовлення.",
                            engine="whisper", duration=elapsed)
    return SpeechResult(True, text, "whisper", duration=elapsed)


def listen(settings: VoiceSettings, *, on_tick: Optional[Callable[[float], None]] = None) -> SpeechResult:
    """Записати й розпізнати одну фразу.

    Спершу пробуємо whisper (якщо налаштований), інакше — вбудований рушій
    Windows. Запис іде в тимчасовий файл, який потім видаляється.
    """
    engine = best_engine(settings.whisper_dir)
    if not engine:
        return SpeechResult(
            False,
            detail=("Немає рушія розпізнавання. У Windows має працювати "
                    "вбудований; перевір, чи доступний мікрофон."),
        )

    seconds = max(1.0, min(60.0, float(settings.seconds or 5.0)))
    handle, name = tempfile.mkstemp(prefix="bchpok-voice-", suffix=".wav")
    os.close(handle)
    path = Path(name)
    try:
        if engine == "whisper":
            ok, detail = record_wav(path, seconds, on_tick)
            if not ok:
                return SpeechResult(False, detail=detail, engine=engine)
            cli = whisper_cli(settings.whisper_dir)
            if cli is None:
                return SpeechResult(False, detail="whisper-cli.exe не знайдено.")
            return recognize_with_whisper(path, cli=cli, model=settings.model_path,
                                          language=(settings.language or "uk")[:2])
        # Вбудований рушій Windows пише й розпізнає сам.
        return recognize_with_windows(seconds)
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Озвучення відповідей
# ─────────────────────────────────────────────────────────────────────────────

_PS_SPEAK = """
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
{speed}
try {
    $synth.Speak([Console]::In.ReadToEnd())
} finally {
    $synth.Dispose()
}
"""


def speak(text: str, *, rate: int = 0) -> tuple[bool, str]:
    """Озвучити текст через SAPI (не блокує виклик довго — у потоці)."""
    body = (text or "").strip()
    if not body:
        return False, "Порожній текст."
    if not IS_WINDOWS:
        return False, "Озвучення підтримується лише у Windows."
    shell = _powershell()
    if not shell:
        return False, "PowerShell не знайдено."
    script = _PS_SPEAK.replace("{speed}", f"$synth.Rate = {max(-10, min(10, int(rate)))};")
    try:
        proc = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", script],
            input=body[:4000], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Не вдалось озвучити: {exc}"
    if proc.returncode != 0:
        return False, (proc.stderr or "")[:200]
    return True, "озвучено"


def voices() -> list[str]:
    """Список голосів SAPI (для налаштувань)."""
    if not IS_WINDOWS:
        return []
    shell = _powershell()
    if not shell:
        return []
    script = ("Add-Type -AssemblyName System.Speech; "
              "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
              ".GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }")
    try:
        proc = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# Голосові команди → дія
# ─────────────────────────────────────────────────────────────────────────────

#: Фрази, які перетворюються на дію замість надсилання агенту.
COMMANDS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("стоп", "зупинись", "зупини", "stop", "зупинися"), "stop", "Зупинити агента"),
    (("новий чат", "новий", "new chat", "очисти"), "new_chat", "Новий чат"),
    (("покажи файли", "файли", "show files"), "files", "Показати файли"),
    (("термінал", "terminal"), "terminal", "Відкрити термінал"),
    (("читай", "озвуч", "speak", "голос"), "speak", "Озвучити відповідь"),
    (("стоп голос", "тихо", "мовчи", "silence"), "mute", "Вимкнути озвучення"),
    (("черга", "queue"), "queue", "Показати чергу"),
    (("скіли", "skills"), "skills", "Показати скіли"),
    (("допомога", "help", "команди"), "help", "Показати команди"),
)


def parse_command(text: str) -> tuple[str, str]:
    """Розпізнати голосову команду. Повертає (дія, опис) або ("", "")."""
    low = (text or "").lower().strip()
    if not low:
        return "", ""
    for phrases, action, label in COMMANDS:
        for phrase in phrases:
            if low == phrase or low.startswith(phrase + " ") or low.endswith(" " + phrase):
                return action, label
    return "", ""


def is_wake_word(text: str) -> bool:
    """Чи починається фраза зі звертання до асистента."""
    low = (text or "").lower().strip()
    return low.startswith(("агент", "агенте", "assistant", "гей агент", "hey"))


def strip_wake_word(text: str) -> str:
    """Прибрати звертання на початку фрази."""
    low = (text or "").strip()
    for prefix in ("Гей, агент", "Гей агент", "Агент,", "Агент ", "Агенте,",
                   "Агенте ", "Assistant", "Hey"):
        if low.lower().startswith(prefix.lower()):
            rest = low[len(prefix):].lstrip(" ,.!?:—")
            return rest or low
    return low


_SPEECH_CLEAN = (
    ("```", " "), ("**", ""), ("__", ""), ("`", ""), ("#", ""),
    ("→", " "), ("←", " "), ("✓", " "), ("✗", " "), ("·", ","),
    ("🔨", ""), ("🧠", ""), ("🖼", ""), ("🎙", ""), ("⊟", ""), ("⚙", ""),
)


def clean_for_speech(text: str) -> str:
    """Прибрати з відповіді те, що погано читається вголос.

    Блоки коду й таблиці озвучувати безглуздо, тому лишаємо лише звичайний
    текст; решту замінюємо коротким «див. екран».
    """
    import re as _re

    body = text or ""
    # Блоки коду — прибираємо цілком.
    body = _re.sub(r"```[\s\S]*?```", " (код на екрані) ", body)
    # Довгі шляхи й URL не читаємо.
    body = _re.sub(r"\bhttps?://\S+", " (посилання) ", body)
    for old, new in _SPEECH_CLEAN:
        body = body.replace(old, new)
    body = _re.sub(r"\n{2,}", ". ", body)
    body = _re.sub(r"\s{2,}", " ", body)
    body = body.strip()
    if len(body) > 900:
        body = body[:900].rsplit(" ", 1)[0] + " …"
    return body


def voice_commands_text() -> str:
    """Довідка голосових команд."""
    lines = ["Голосові команди:"]
    for phrases, _action, label in COMMANDS:
        lines.append(f"  «{phrases[0]}» — {label}")
    lines.append("")
    lines.append("Будь-яка інша фраза йде агенту як запит.")
    return "\n".join(lines)


def short_text(text: str, limit: int = 120) -> str:
    """Скоротити текст для журналу."""
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


__all__ = [
    "COMMANDS",
    "IS_WINDOWS",
    "SAMPLE_RATE",
    "SpeechResult",
    "VoiceSettings",
    "best_engine",
    "clean_for_speech",
    "engines",
    "is_wake_word",
    "listen",
    "parse_command",
    "record_wav",
    "recognize_with_whisper",
    "recognize_with_windows",
    "short_text",
    "speak",
    "strip_wake_word",
    "voice_commands_text",
    "voices",
    "whisper_cli",
    "windows_speech_available",
]
