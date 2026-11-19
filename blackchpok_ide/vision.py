"""Чи бачить модель зображення — для ЛОКАЛЬНИХ і ХМАРНИХ моделей.

Навіщо окремий модуль. Донедавна ``vision_enabled`` вмикався лише тоді,
коли поруч із GGUF-файлом лежав ``mmproj``. Це правило правильне для
llama.cpp, але хмарна модель не має жодного mmproj — вона бачить
зображення сама. Через це будь-яка хмарна модель (DeepSeek, GPT-4o,
Claude, Gemini) у нашій IDE вважалась «без зору»: користувач бачив
«Поточна модель не має зору (немає mmproj)» і не міг прикріпити картинку.

Три рівні перевірки, від найнадійнішого:

1. **Факт для локальної моделі** — чи лежить ``mmproj`` поруч із файлом.
   Це єдине, що справді визначає зір у llama.cpp.
2. **Каталог для хмари** — чи відома ця модель як мультимодальна
   (:data:`VISION_MODELS`) або чи її провайдер приймає зображення завжди.
3. **Назва** — ознаки ``vision`` / ``-vl`` / ``-4o`` тощо.

Порядок важливий: локальна модель із назвою «vision», але без файлу
проєктора, зору НЕ має. Тому перевірка за назвою стоїть останньою й
застосовується лише до хмарних адрес.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Iterable

LOG = logging.getLogger("blackchpok.vision")

__all__ = [
    "CLOUD_VISION_MARKERS",
    "VISION_MODELS",
    "describe",
    "is_local_url",
    "model_sees_images",
]

#: Адреси, які вважаємо локальними (той самий набір, що в ``agent``).
_LOCAL_MARKERS: tuple[str, ...] = (
    "127.0.0.1", "localhost", "0.0.0.0", "::1", "192.168.", "10.",
    "native://", "inproc://", "blackchpok://",
)

#: Ознаки мультимодальності в НАЗВІ хмарної моделі.
#:
#: Список навмисно короткий і точний: зайва ознака тут означала б запит
#: із картинкою до моделі, яка її не приймає, — а це помилка 400 замість
#: відповіді.
CLOUD_VISION_MARKERS: tuple[str, ...] = (
    "gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-5", "o3", "o4-mini",
    "claude-3", "claude-4", "claude-sonnet", "claude-opus", "claude-haiku",
    "gemini", "gemma-3", "gemma3",
    "pixtral", "mistral-large", "mistral-small", "ministral-3",
    "qwen2-vl", "qwen2.5-vl", "qwen3-vl", "-vl-", "-vl", "vl-",
    "llava", "internvl", "minicpm-v", "moondream",
    "llama-3.2-11b-vision", "llama-3.2-90b-vision", "llama-4",
    "grok-2-vision", "grok-4", "glm-4v", "glm-4.5v", "internlm-xcomposer",
)

#: Моделі, про які точно відомо, що вони читають зображення, навіть якщо
#: назва не містить жодної ознаки з :data:`CLOUD_VISION_MARKERS`.
#:
#: Ключ — підрядок назви в нижньому регістрі.
VISION_MODELS: dict[str, str] = {
    "deepseek-vl": "DeepSeek-VL",
    "deepseek-vl2": "DeepSeek-VL2",
    "deepseek-ocr": "DeepSeek-OCR",
    # Deploy-каталог: на момент перевірки ці моделі мультимодальні.
    "glm-5v": "GLM-5V",
}

#: Провайдери, чиї OpenAI-сумісні моделі приймають зображення ЗАВЖДИ.
#:
#: OpenRouter приймає картинки для більшості моделей і сам відхиляє
#: невідповідні — але тоді користувач дістає чесну помилку від сервера,
#: а не нашу вигадану заборону. Тому тут його немає: зайва спроба краще
#: за хибну відмову лише там, де ми точно знаємо відповідь.
_ALWAYS_VISION_PROVIDERS: tuple[str, ...] = ()


def is_local_url(base_url: str) -> bool:
    """Чи адреса належить локальному рушію (а не хмарі)."""
    clean = (base_url or "").strip().lower()
    if not clean:
        return False
    return any(marker in clean for marker in _LOCAL_MARKERS)


def _name_sees_images(name: str) -> bool:
    """Чи назва моделі свідчить про підтримку зображень."""
    low = (name or "").strip().lower()
    if not low:
        return False
    for marker, _label in VISION_MODELS.items():
        if marker in low:
            return True
    return any(marker in low for marker in CLOUD_VISION_MARKERS)


def model_sees_images(
    model: str,
    base_url: str,
    *,
    local_path: Any = None,
    provider: str = "",
    override: Any = None,
) -> bool:
    """Чи можна надсилати цій моделі зображення.

    ``local_path`` — файл GGUF, якщо модель локальна. Коли він переданий,
    відповідь визначає НАЯВНІСТЬ ``mmproj``: назва нічого не важить.

    ``override`` — ручний вибір користувача (``True`` / ``False``). Має
    найвищий пріоритет: нові або власні моделі провайдера часто не мають
    у назві жодної ознаки, і вгадувати за нею означало б відмовляти в
    картинках робочій моделі. ``None`` — «визнач сам».
    """
    if override is not None:
        return bool(override)
    if is_local_url(base_url):
        if local_path is None:
            # Локальна адреса без відомого файлу: довіряємо назві, бо
            # рушій міг бути запущений ззовні (LM Studio, Ollama) і сам
            # вирішує, чи має проєктор.
            return _name_sees_images(model)
        return _local_projector(local_path) is not None
    if (provider or "").strip().lower() in _ALWAYS_VISION_PROVIDERS:
        return True
    return _name_sees_images(model)


def _local_projector(local_path: Any) -> Path | None:
    """Знайти ``mmproj`` поруч із локальним файлом моделі."""
    try:
        from . import model_hub
    except ImportError:               # pragma: no cover - модуль завжди є
        return None
    try:
        return model_hub.vision_projector_for(local_path)
    except Exception:                 # noqa: BLE001 - перевірка не має падати
        LOG.debug("Проєктор не визначено для %s", local_path, exc_info=True)
        return None


def describe(
    model: str,
    base_url: str,
    *,
    local_path: Any = None,
    provider: str = "",
    override: Any = None,
) -> str:
    """Коротке пояснення для статусу й журналу (не для логіки)."""
    if override is not None:
        return ("зір: увімкнено вручну" if override
                else "зір: вимкнено вручну в налаштуваннях")
    if not model_sees_images(model, base_url, local_path=local_path,
                             provider=provider):
        if is_local_url(base_url):
            return "без зору: немає mmproj поруч із моделлю"
        return "модель не заявлена як мультимодальна"
    if is_local_url(base_url):
        return "зір: локальний проєктор (mmproj)"
    return "зір: хмарна мультимодальна модель"


def known_vision_models(models: Iterable[str]) -> list[str]:
    """Відфільтрувати назви, які точно читають зображення (для панелей)."""
    return [name for name in models or () if _name_sees_images(name)]


#: Регулярка на ``data:image/…;base64,…`` — щоб відрізняти картинку від
#: звичайного посилання (посилання Claude і Gemini не приймають).
DATA_URL_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,", re.IGNORECASE)
