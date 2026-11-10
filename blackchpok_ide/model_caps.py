"""Можливості моделей: інструменти, міркування, зображення, голос.

Моделі в хабі показуються з позначками, щоб користувач одразу бачив, що
вона вміє:

* 🔨 — підтримує виклик інструментів (tool calling);
* 🧠 — «думаюча» модель (reasoning);
* 🖼 — читає зображення (vision);
* 🎙 — працює з голосом (audio / speech).

Визначення йде за назвою моделі, тегами й описом із репозиторію — без
вигаданих даних: якщо ознак немає, позначки не ставимо.

Модуль не тягне tkinter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

# ── Позначки ────────────────────────────────────────────────────────────────

TOOLS = "tools"
REASONING = "reasoning"
VISION = "vision"
AUDIO = "audio"

ICONS: dict[str, str] = {
    TOOLS: "🔨",
    REASONING: "🧠",
    VISION: "🖼",
    AUDIO: "🎙",
}

LABELS: dict[str, str] = {
    TOOLS: "Підтримує інструменти",
    REASONING: "Думаюча модель",
    VISION: "Читає зображення",
    AUDIO: "Працює з голосом",
}

#: Порядок показу позначок.
ORDER: tuple[str, ...] = (TOOLS, REASONING, VISION, AUDIO)


# ── Ознаки в назві ──────────────────────────────────────────────────────────

#: Родини моделей, які точно вміють викликати інструменти.
TOOL_FAMILIES: tuple[str, ...] = (
    "qwen", "hermes", "mistral", "mixtral", "llama-3", "llama3", "deepseek",
    "granite", "command-r", "firefunction", "functionary", "nous", "dolphin",
    "internlm", "glm", "yi", "phi-3", "phi-4", "gpt", "claude", "gemini",
    "saiga", "vikhr", "t-lite", "aya", "solar", "gemma", "ministral",
)

#: Ознаки «думаючих» моделей.
REASONING_MARKERS: tuple[str, ...] = (
    "reasoner", "reasoning", "thinking", "-r1", "deepseek-r1", "qwq",
    "o1-", "o3-", "o4-", "magistral", "marco-o", "reflection",
)

#: Ознаки моделей, що читають зображення.
VISION_MARKERS: tuple[str, ...] = (
    "vision", "-vl", "vl-", "llava", "bakllava", "pixtral", "moondream",
    "minicpm-v", "internvl", "qwen2-vl", "qwen2.5-vl", "gemma3", "gemma-3",
    "idefics",
    "cogvlm", "paligemma", "florence", "smolvlm", "phi-3.5-vision",
    "llama-3.2-11b-vision", "llama-3.2-90b-vision",
)

#: Ознаки голосових моделей.
AUDIO_MARKERS: tuple[str, ...] = (
    "whisper", "audio", "speech", "voice", "bark", "tortoise", "coqui",
    "parakeet", "wav2vec", "hubert", "seamless", "moshi", "qwen-audio",
    "qwen2-audio", "voxtral", "ultravox", "piper", "kokoro",
)


@dataclass
class Capabilities:
    """Набір можливостей однієї моделі."""

    flags: dict[str, bool] = field(default_factory=dict)
    source: dict[str, str] = field(default_factory=dict)

    def has(self, key: str) -> bool:
        return bool(self.flags.get(key))

    def set(self, key: str, value: bool, why: str = "") -> None:
        if value:
            self.flags[key] = True
            if why:
                self.source[key] = why

    @property
    def any(self) -> bool:
        return any(self.flags.get(key) for key in ORDER)

    def icons(self) -> list[str]:
        """Позначки в сталому порядку."""
        return [ICONS[key] for key in ORDER if self.flags.get(key)]

    def icon_text(self) -> str:
        """Рядок позначок для списку (через пробіл)."""
        return " ".join(self.icons())

    def labels(self) -> list[str]:
        return [LABELS[key] for key in ORDER if self.flags.get(key)]

    def tooltip(self) -> str:
        found = self.labels()
        return " · ".join(found) if found else "Можливості не визначені"

    def to_dict(self) -> dict[str, Any]:
        return {"flags": dict(self.flags), "source": dict(self.source)}


def _text_blob(*parts: Any) -> str:
    """Склеїти все, за чим шукаємо ознаки, в один рядок у нижньому регістрі."""
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, (list, tuple, set)):
            chunks.extend(str(item) for item in part if item)
        elif part:
            chunks.append(str(part))
    return " ".join(chunks).lower()


def _find_marker(blob: str, markers: Iterable[str]) -> str:
    for marker in markers:
        if marker in blob:
            return marker
    return ""


def detect(
    name: str = "",
    *,
    model_id: str = "",
    filename: str = "",
    tags: Iterable[str] = (),
    description: str = "",
    local_path: Any = None,
) -> Capabilities:
    """Визначити можливості моделі за назвою, тегами й описом.

    ``local_path`` — шлях до GGUF-файлу на диску (якщо модель уже
    завантажена). Для нього додатково перевіряємо ФАКТ: чи лежить поруч
    сумісний візуальний проєктор. Без нього зір не працює, хоч би що
    було в назві.
    """
    blob = _text_blob(name, model_id, filename, list(tags), description)
    caps = Capabilities()

    # ── інструменти
    tool_tag = any(str(tag).lower() in {"tool", "tools", "function-calling",
                                        "tool-calling", "agent", "agents"}
                   for tag in (tags or ()))
    if tool_tag:
        caps.set(TOOLS, True, "тег репозиторію")
    else:
        marker = _find_marker(blob, TOOL_FAMILIES)
        if marker:
            caps.set(TOOLS, True, f"родина «{marker}»")

    # ── міркування
    marker = _find_marker(blob, REASONING_MARKERS)
    if marker:
        caps.set(REASONING, True, f"ознака «{marker}»")

    # ── зображення
    marker = _find_marker(blob, VISION_MARKERS)
    if marker:
        caps.set(VISION, True, f"ознака «{marker}»")
    elif _declares_vision(blob):
        # Мультимодальні родини без маркера в назві (Ministral, Pixtral-12B,
        # Mistral-3 тощо): проєктор їм потрібен обов'язково, тому нижче
        # вирішує фактична наявність файлу.
        caps.set(VISION, True, "мультимодальна родина")

    # ── ФАКТ замість назви: чи є проєктор на диску ────────────────────────
    if caps.has(VISION) and local_path is not None:
        _verify_vision(caps, local_path)

    # ── голос
    marker = _find_marker(blob, AUDIO_MARKERS)
    if marker:
        caps.set(AUDIO, True, f"ознака «{marker}»")

    return caps


def _declares_vision(blob: str) -> bool:
    """Чи належить модель до мультимодальної родини без слова «vision»."""
    return any(marker in blob for marker in (
        "ministral", "mistral-3", "mistral3", "pixtral", "magistral",
    ))


def _verify_vision(caps: "Capabilities", local_path: Any) -> None:
    """Зняти значок Vision, якщо проєктора немає або він несумісний.

    Навіщо. Раніше значок ставився ЛИШЕ за назвою. Користувач бачив зелений
    «🖼» у хаба, вибирав модель — а llama-server стартував без ``--mmproj``.
    Знімки далі тихо не передавались у модель (``vision_enabled = False``),
    і знайти причину було неможливо.

    Тепер значок означає «зір СПРАВДІ підключиться», а не «у назві було vl».
    """
    try:
        from . import model_hub

        path = Path(local_path) if not isinstance(local_path, Path) else local_path
        projector = model_hub.vision_projector_for(path)
    except Exception:  # noqa: BLE001 - перевірка не має ламати список
        caps.flags[VISION] = False
        caps.source[VISION] = "перевірка проєктора не вдалась"
        return
    if projector is None:
        caps.flags[VISION] = False
        caps.source[VISION] = "немає файлу mmproj поруч із моделлю"
    else:
        caps.set(VISION, True, f"проєктор {projector.name}")


def from_hit(hit: Any) -> Capabilities:
    """Можливості для об'єкта ``ModelHit`` (або словника)."""
    def _get(key: str, default: Any = "") -> Any:
        if isinstance(hit, dict):
            return hit.get(key, default)
        return getattr(hit, key, default)

    caps = detect(
        name=_get("name"),
        model_id=_get("model_id"),
        filename=_get("filename"),
        tags=_get("tags") or (),
        description=_get("description"),
        local_path=_get("path", None),
    )
    # Уже збережене ручне виправлення користувача має вищий пріоритет за
    # автоматичне вгадування: людина могла перевірити модель на практиці.
    stored = _get("capabilities", None)
    if isinstance(stored, dict) and stored:
        for key in ORDER:
            if key in stored:
                caps.flags[key] = bool(stored[key])
    return caps


# ── Голосові моделі: окремий підбір ─────────────────────────────────────────

#: Локальні моделі, придатні для розпізнавання мовлення (whisper.cpp).
SPEECH_HINTS: tuple[tuple[str, str], ...] = (
    ("ggml-base.bin", "Whisper base — швидко, ~150 МБ"),
    ("ggml-small.bin", "Whisper small — баланс, ~480 МБ"),
    ("ggml-medium.bin", "Whisper medium — точніше, ~1.5 ГБ"),
    ("ggml-large-v3-turbo.bin", "Whisper large-v3-turbo — найкраще, ~1.6 ГБ"),
)


def speech_models() -> list[tuple[str, str]]:
    """Перелік рекомендованих голосових моделей (файл, опис)."""
    return list(SPEECH_HINTS)


def is_speech_model(name: str) -> bool:
    """Чи це модель для мовлення (а не для чату)."""
    return bool(_find_marker((name or "").lower(), AUDIO_MARKERS))


def split_icons(flags: Capabilities) -> str:
    """Компактний рядок для рядка списку."""
    return flags.icon_text() or "·"


__all__ = [
    "AUDIO",
    "AUDIO_MARKERS",
    "Capabilities",
    "ICONS",
    "LABELS",
    "ORDER",
    "REASONING",
    "REASONING_MARKERS",
    "SPEECH_HINTS",
    "TOOLS",
    "TOOL_FAMILIES",
    "VISION",
    "VISION_MARKERS",
    "detect",
    "from_hit",
    "is_speech_model",
    "speech_models",
    "split_icons",
]
