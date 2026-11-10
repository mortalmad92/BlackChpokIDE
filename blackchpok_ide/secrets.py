"""Безпечне зберігання секретів: шифрування ключів через Windows DPAPI.

Проблема. ``settings.json`` зберігав ``api_key`` ВІДКРИТИМ текстом. Ключ
потрапляв у резервні копії (``settings.json.bak``, ``.backup-stress-test``),
у синхронізацію ``%APPDATA%`` і в будь-який архів профілю. Це неприйнятно
для продукту, який зберігає чужі платні ключі.

Рішення — DPAPI (Data Protection API) Windows: ``CryptProtectData`` /
``CryptUnprotectData``. Ключ шифрується ключем КОРИСТУВАЧА ОС, тому:

* інший користувач машини не розшифрує файл;
* копія ``settings.json`` на іншій машині марна;
* окремий пароль не потрібен — розшифрування прозоре.

Залежностей немає: усе через ``ctypes``.

Формат у файлі::

    "api_key_enc": "dpapi:v1:<base64>"

Порядок читання: ``api_key_enc`` → (застаріле) ``api_key`` у відкритому
вигляді → порожньо. Застарілий ключ ПЕРЕШИФРОВУЄТЬСЯ й видаляється під час
збереження, тож після першого запуску нової версії відкритих ключів у
файлі не лишається.

Модуль не тягне tkinter і не робить нічого під час імпорту.
"""

from __future__ import annotations

import base64
import ctypes
import logging
import os
import sys
from ctypes import wintypes
from typing import Optional

LOG = logging.getLogger("blackchpok.secrets")

#: Префікс зашифрованого значення (щоб відрізняти від старого відкритого).
PREFIX = "dpapi:v1:"

#: Опис, який DPAPI додає до зашифрованого блоку (не секрет).
_DESCRIPTION = "BlackChpokIDE"

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    class _DataBlob(ctypes.Structure):
        """``DATA_BLOB`` із ``dpapi.h``."""

        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    try:
        _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:                              # pragma: no cover - без crypt32
        _crypt32 = None
        _kernel32 = None
else:                                            # pragma: no cover - не Windows
    _crypt32 = None
    _kernel32 = None


def available() -> bool:
    """Чи можна шифрувати (Windows із crypt32)."""
    return bool(_crypt32 is not None and _kernel32 is not None)


def redact(text: str) -> str:
    """Прибрати схожі на ключі рядки з тексту (для логів і повідомлень).

    Провайдери іноді повертають у тілі помилки фрагмент ключа. Логи й
    історія чатів не мають його зберігати.
    """
    import re

    if not text:
        return ""
    cleaned = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]{6,}", r"\1•••", text)
    cleaned = re.sub(r"\bsk-[A-Za-z0-9._\-]{6,}", "sk-•••", cleaned)
    cleaned = re.sub(r"\b(api[_-]?key[\"'=:\s]+)[A-Za-z0-9._\-]{6,}",
                     r"\1•••", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"([?&]key=)[^&\s]{6,}", r"\1•••", cleaned)
    return cleaned


def _to_blob(data: bytes) -> "_DataBlob":
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _from_blob(blob: "_DataBlob") -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if blob.pbData:
            _kernel32.LocalFree(blob.pbData)


def encrypt(secret: str) -> str:
    """Зашифрувати секрет. Повертає ``dpapi:v1:…`` або ``""``.

    ``""`` — якщо шифрування недоступне АБО секрет порожній. Порожній
    результат означає «не зберігати»: відкритий текст не пишемо ніколи,
    краще попросити користувача ввести ключ знову, ніж злити його.
    """
    text = (secret or "").strip()
    if not text:
        return ""
    if not available():
        LOG.warning("DPAPI недоступний: ключ не збережено у файл "
                    "(введіть його знову після перезапуску)")
        return ""
    try:
        data_in = _to_blob(text.encode("utf-8"))
        data_out = _DataBlob()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(data_in),
            _DESCRIPTION,
            None,               # додатковий «entropy» не використовуємо
            None, None,
            0x1,                # CRYPTPROTECT_UI_FORBIDDEN — без діалогів
            ctypes.byref(data_out),
        )
        if not ok:
            LOG.warning("CryptProtectData не вдалась: код %s",
                        ctypes.get_last_error())
            return ""
        blob = _from_blob(data_out)
    except (OSError, AttributeError, ctypes.ArgumentError) as exc:
        LOG.warning("Шифрування ключа не вдалось: %s", exc)
        return ""
    return PREFIX + base64.b64encode(blob).decode("ascii")


def decrypt(value: str) -> str:
    """Розшифрувати ``dpapi:v1:…``. Порожньо — якщо не вдалось."""
    text = (value or "").strip()
    if not text:
        return ""
    if not text.startswith(PREFIX):
        # Старий формат: відкритий ключ. Повертаємо як є, щоб він
        # продовжував працювати й був перешифрований під час збереження.
        return text
    if not available():
        LOG.warning("DPAPI недоступний: збережений ключ не прочитано")
        return ""
    try:
        raw = base64.b64decode(text[len(PREFIX):].encode("ascii"))
    except (ValueError, TypeError) as exc:
        LOG.warning("Зашифрований ключ пошкоджено: %s", exc)
        return ""
    try:
        data_in = _to_blob(raw)
        data_out = _DataBlob()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(data_in),
            None, None, None, None,
            0x1,                # CRYPTPROTECT_UI_FORBIDDEN
            ctypes.byref(data_out),
        )
        if not ok:
            LOG.warning("CryptUnprotectData не вдалась: код %s "
                        "(ключ зашифровано іншим користувачем?)",
                        ctypes.get_last_error())
            return ""
        blob = _from_blob(data_out)
    except (OSError, AttributeError, ctypes.ArgumentError) as exc:
        LOG.warning("Розшифрування ключа не вдалось: %s", exc)
        return ""
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        LOG.warning("Розшифрований ключ не є текстом")
        return ""


def is_encrypted(value: str) -> bool:
    """Чи це вже зашифроване значення."""
    return str(value or "").strip().startswith(PREFIX)


def looks_like_secret(value: str) -> bool:
    """Чи схоже значення на справжній секрет (а не «local»/«lm-studio»)."""
    text = (value or "").strip()
    if len(text) < 12:
        return False
    lowered = text.lower()
    if lowered in ("local", "none", "lm-studio", "no-key", "not-needed"):
        return False
    return True


__all__ = [
    "PREFIX",
    "available",
    "decrypt",
    "encrypt",
    "is_encrypted",
    "looks_like_secret",
    "redact",
]
