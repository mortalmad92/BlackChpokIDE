"""Читання метаданих GGUF-файлу.

Навіщо власний читач, якщо є ``llama_model_meta_*``: щоб показати
інформацію про модель (архітектура, quantization, контекст, tokenizer,
шари) ЩЕ ДО завантаження ваг у пам'ять. Завантаження 14B-моделі займає
секунди й гігабайти RAM — для списку моделей і перевірки сумісності це
неприйнятно.

Формат GGUF v2/v3 (офіційна специфікація ggml):

* ``char magic[4]`` = ``GGUF``;
* ``uint32 version``;
* ``uint64 tensor_count``, ``uint64 kv_count``;
* далі пари «ключ-значення»: рядок = ``uint64 len`` + UTF-8 байти;
* значення має ``uint32 type`` і власне дані. Тип 9 (ARRAY) рекурсивний.

Читач навмисно не вантажить масиви токенів/мерджів у пам'ять: для них
зберігається лише довжина й позиція. Інакше 150 тисяч рядків словника
(десятки мегабайт і мільйони об'єктів Python) з'їдали б пам'ять на
кожне відкриття списку моделей.
"""

from __future__ import annotations

import mmap
import os
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Iterator

#: Магія файлу.
GGUF_MAGIC = b"GGUF"

#: Типи значень GGUF (``enum gguf_type``).
GGUF_TYPE = {
    0: "uint8",
    1: "int8",
    2: "uint16",
    3: "int16",
    4: "uint32",
    5: "int32",
    6: "float32",
    7: "bool",
    8: "string",
    9: "array",
    10: "uint64",
    11: "int64",
    12: "float64",
}

#: Скільки елементів масиву читаємо, якщо це справді потрібно.
_SMALL_ARRAY = 64


class GgufError(ValueError):
    """Файл не є коректним GGUF."""


@dataclass
class GgufMeta:
    """Розібрані метадані одного GGUF-файлу."""

    path: str = ""
    version: int = 0
    tensor_count: int = 0
    kv_count: int = 0
    values: dict[str, Any] = field(default_factory=dict)
    #: Розміри масивів для великих полів (словник, мерджі) — без самих даних.
    array_lengths: dict[str, int] = field(default_factory=dict)

    # ── зручні поля ────────────────────────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    @property
    def architecture(self) -> str:
        return str(self.get("general.architecture") or "")

    @property
    def name(self) -> str:
        return str(self.get("general.name") or "")

    @property
    def quant(self) -> str:
        """Назва quantization: спершу з файлу, далі з імені файлу."""
        explicit = self.get("general.file_type")
        if isinstance(explicit, int):
            from ._quant import ftype_name

            named = ftype_name(explicit)
            if named:
                return named
        token = self.get("general.quantization_version")
        hint = quant_from_filename(Path(self.path).name)
        if hint:
            return hint
        return f"type {token}" if token is not None else ""

    @property
    def layer_count(self) -> int:
        key = f"{self.architecture}.block_count"
        value = self.get(key)
        return int(value) if isinstance(value, (int, float)) else 0

    @property
    def context_length(self) -> int:
        for suffix in ("context_length", "n_ctx_train", "context_size"):
            key = f"{self.architecture}.{suffix}"
            value = self.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return int(value)
        return 0

    @property
    def embedding_length(self) -> int:
        key = f"{self.architecture}.embedding_length"
        value = self.get(key)
        return int(value) if isinstance(value, (int, float)) else 0

    @property
    def head_count(self) -> int:
        value = self.get(f"{self.architecture}.attention.head_count")
        return int(value) if isinstance(value, (int, float)) else 0

    @property
    def head_count_kv(self) -> int:
        value = self.get(f"{self.architecture}.attention.head_count_kv")
        if isinstance(value, (int, float)):
            return int(value)
        return self.head_count

    @property
    def parameter_count(self) -> int:
        value = self.get("general.parameter_count")
        return int(value) if isinstance(value, (int, float)) else 0

    @property
    def vocab_size(self) -> int:
        return int(self.array_lengths.get("tokenizer.ggml.tokens") or 0)

    @property
    def tokenizer_model(self) -> str:
        return str(self.get("tokenizer.ggml.model") or "")

    @property
    def has_chat_template(self) -> bool:
        return bool(self.get("tokenizer.chat_template"))

    @property
    def is_embedding_model(self) -> bool:
        """Модель створена для embeddings, а не для генерації тексту."""
        pool = self.get(f"{self.architecture}.pooling_type")
        if pool is not None:
            return True
        name = f"{Path(self.path).name} {self.name}".lower()
        return any(marker in name for marker in ("embed", "bge-", "e5-", "gte-", "nomic"))

    @property
    def is_vision_projector(self) -> bool:
        name = Path(self.path).name.lower()
        if name.startswith("mmproj"):
            return True
        return self.architecture in {"clip", "mtmd"} or bool(self.get("clip.has_vision"))


def quant_from_filename(filename: str) -> str:
    """Витягнути позначку quantization з імені файлу (``Q4_K_M`` тощо)."""
    lowered = filename.lower().replace("-", "_")
    known = (
        "q8_k", "q6_k", "q5_k_m", "q5_k_s", "q4_k_m", "q4_k_s", "q3_k_m", "q3_k_s",
        "q3_k_l", "q2_k", "iq4_nl", "iq4_xs", "iq3_xxs", "iq3_s", "iq2_xs", "iq2_xxs",
        "iq1_s", "iq1_m", "mxFP4".lower(), "q8_0", "q6_0", "q5_1", "q5_0", "q4_1",
        "q4_0", "q3_0", "q2_0", "f16", "bf16", "f32",
    )
    for token in known:
        if token in lowered:
            return token.upper()
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Низькорівневе читання
# ─────────────────────────────────────────────────────────────────────────────

class _Reader:
    """Послідовний читач GGUF поверх mmap (без копіювання великих полів)."""

    __slots__ = ("_view", "_pos")

    def __init__(self, view: "mmap.mmap") -> None:
        self._view = view
        self._pos = 0

    @property
    def pos(self) -> int:
        return self._pos

    def read(self, size: int) -> bytes:
        end = self._pos + size
        if end > len(self._view):
            raise GgufError("Файл обірвано: метадані виходять за межі файлу.")
        chunk = self._view[self._pos:end]
        self._pos = end
        return chunk

    def skip(self, size: int) -> None:
        end = self._pos + size
        if end > len(self._view):
            raise GgufError("Файл обірвано: метадані виходять за межі файлу.")
        self._pos = end

    def u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.read(8))[0]

    def string(self) -> str:
        length = self.u64()
        if length > 1 << 24:
            raise GgufError(f"Неправдоподібна довжина рядка: {length}")
        return self.read(int(length)).decode("utf-8", "replace")


_SCALAR = {
    "uint8": ("<B", 1),
    "int8": ("<b", 1),
    "uint16": ("<H", 2),
    "int16": ("<h", 2),
    "uint32": ("<I", 4),
    "int32": ("<i", 4),
    "float32": ("<f", 4),
    "bool": ("<B", 1),
    "uint64": ("<Q", 8),
    "int64": ("<q", 8),
    "float64": ("<d", 8),
}


def _read_value(reader: _Reader, kind_name: str, *, keep_arrays: bool) -> Any:
    """Прочитати значення заданого типу (рекурсивно для масивів)."""
    if kind_name == "string":
        return reader.string()
    if kind_name == "array":
        item_type = GGUF_TYPE.get(reader.u32(), "uint8")
        count = reader.u64()
        if item_type == "string":
            # Рядкові масиви (словник, мерджі) не читаємо: лише пропускаємо.
            if not keep_arrays:
                for _ in range(count):
                    reader.skip(reader.u64())
                return None
            return [reader.string() for _ in range(count)]
        if item_type == "array":
            # Вкладені масиви в GGUF практично не трапляються.
            raise GgufError("Вкладені масиви не підтримуються.")
        fmt, size = _SCALAR.get(item_type, ("<B", 1))
        if not keep_arrays or count > _SMALL_ARRAY * 1024:
            reader.skip(size * count)
            return None
        raw = reader.read(size * count)
        return list(struct.unpack("<" + fmt[1] * count, raw))
    fmt, size = _SCALAR.get(kind_name, ("<B", 1))
    return struct.unpack(fmt, reader.read(size))[0]


def read_meta(path: str | Path, *, keep_arrays: bool = False) -> GgufMeta:
    """Прочитати метадані GGUF-файлу.

    ``keep_arrays=False`` (типово) не читає великі масиви: для словника
    зберігається тільки довжина в :attr:`GgufMeta.array_lengths`.
    """
    target = Path(path)
    meta = GgufMeta(path=str(target))
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise GgufError(f"Немає доступу до файлу: {exc}") from exc
    if size < 24:
        raise GgufError("Файл замалий для GGUF.")

    with open(target, "rb") as handle:
        try:
            view = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        except (OSError, ValueError) as exc:      # pragma: no cover - екзотика
            raise GgufError(f"Не вдалось відобразити файл: {exc}") from exc
        with view:
            if view[:4] != GGUF_MAGIC:
                raise GgufError("Це не GGUF-файл (немає магії GGUF).")
            reader = _Reader(view)
            reader.skip(4)
            meta.version = reader.u32()
            if meta.version not in (1, 2, 3):
                raise GgufError(f"Непідтримувана версія GGUF: {meta.version}")
            meta.tensor_count = reader.u64()
            meta.kv_count = reader.u64()
            if meta.kv_count > 100_000:
                raise GgufError("Неправдоподібна кількість ключів GGUF.")
            for _ in range(meta.kv_count):
                key = reader.string()
                kind = GGUF_TYPE.get(reader.u32(), "uint8")
                if kind == "array":
                    item_type = GGUF_TYPE.get(reader.u32(), "uint8")
                    count = reader.u64()
                    meta.array_lengths[key] = int(count)
                    if item_type == "string":
                        if keep_arrays:
                            meta.values[key] = [reader.string() for _ in range(count)]
                        else:
                            for _ in range(count):
                                reader.skip(reader.u64())
                        continue
                    fmt, item_size = _SCALAR.get(item_type, ("<B", 1))
                    if not keep_arrays or count > _SMALL_ARRAY * 1024:
                        reader.skip(item_size * count)
                        continue
                    raw = reader.read(item_size * count)
                    meta.values[key] = list(struct.unpack("<" + fmt[1] * count, raw))
                    continue
                meta.values[key] = _read_value(reader, kind, keep_arrays=keep_arrays)
    return meta


def read_meta_safe(path: str | Path, *, keep_arrays: bool = False) -> GgufMeta:
    """Те саме, але помилки не кидають виняток, а лягають у ``values['_error']``."""
    try:
        return read_meta(path, keep_arrays=keep_arrays)
    except (GgufError, OSError) as exc:
        return GgufMeta(path=str(path), values={"_error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# Кеш метаданих
# ─────────────────────────────────────────────────────────────────────────────
#: Розбір метаданих — найдорожча операція списку моделей. Заміряно на цій
#: машині: 7 моделей = 719 мс, а під час старту IDE ``read_meta``
#: викликається **22 рази** (``ModelManager.refresh`` обходить теку кілька
#: разів, плюс ``_gguf_context`` в агенті) = **2257 мс** із 6.3 с старту.
#:
#: Кеш ключується шляхом + ``mtime`` + розміром, тому заміна або докачка
#: файлу автоматично дає новий запис — застарілих даних не буває. Пишеться
#: на диск, щоб пережити перезапуск: саме другий і наступні запуски
#: отримують нульову вартість.

_META_CACHE_NAME = ".gguf-meta-cache.json"
_META_CACHE_VERSION = 1
_META_CACHE: dict[str, dict[str, Any]] = {}
_META_CACHE_LOCK = threading.Lock()
_META_CACHE_LOADED = False
_META_CACHE_DIRTY = False


def _cache_path() -> Path:
    """Де лежить кеш: поруч із моделями, інакше в теці застосунку."""
    try:
        from ..config import app_data_dir

        return Path(app_data_dir()) / _META_CACHE_NAME
    except (ImportError, OSError):
        return Path.home() / _META_CACHE_NAME


def _fingerprint(path: Path) -> str:
    """Відбиток файлу: ``mtime_ns:size``. Змінився — кеш не діє."""
    try:
        stat = path.stat()
    except OSError:
        return ""
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _load_cache() -> None:
    """Прочитати кеш із диска (один раз за процес)."""
    global _META_CACHE_LOADED
    if _META_CACHE_LOADED:
        return
    _META_CACHE_LOADED = True
    try:
        import json

        raw = _cache_path().read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    if data.get("version") != _META_CACHE_VERSION:
        return
    entries = data.get("entries")
    if isinstance(entries, dict):
        with _META_CACHE_LOCK:
            _META_CACHE.update(
                {str(k): v for k, v in entries.items() if isinstance(v, dict)}
            )


def _save_cache() -> None:
    """Записати кеш на диск (не частіше, ніж він справді змінився)."""
    global _META_CACHE_DIRTY
    with _META_CACHE_LOCK:
        if not _META_CACHE_DIRTY:
            return
        snapshot = dict(_META_CACHE)
        _META_CACHE_DIRTY = False
    try:
        import json

        target = _cache_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp")
        temp.write_text(
            json.dumps({"version": _META_CACHE_VERSION, "entries": snapshot},
                       ensure_ascii=False),
            encoding="utf-8")
        os.replace(temp, target)
    except (OSError, ValueError):
        # Кеш — оптимізація, а не джерело істини: його відсутність не ламає
        # нічого, тому помилку тільки фіксуємо в журналі.
        import logging

        logging.getLogger("blackchpok.gguf").debug(
            "Кеш метаданих не записано", exc_info=True)


@dataclass
class _MetaSnapshot:
    """Те, що зберігається в кеші для одного файлу."""

    version: int = 0
    tensor_count: int = 0
    kv_count: int = 0
    values: dict[str, Any] = field(default_factory=dict)
    arrays: dict[str, int] = field(default_factory=dict)


def _meta_to_cache(meta: GgufMeta) -> dict[str, Any]:
    """Серіалізувати метадані (значення лише JSON-сумісні)."""
    values = {k: v for k, v in meta.values.items()
              if isinstance(v, (str, int, float, bool)) or v is None}
    return {"version": int(meta.version), "tensor_count": int(meta.tensor_count),
            "kv_count": int(meta.kv_count), "values": values,
            "arrays": dict(meta.array_lengths)}


def _meta_from_cache(data: dict[str, Any], path: str) -> GgufMeta:
    """Відновити метадані з кешу."""
    meta = GgufMeta(path=path)
    meta.version = int(data.get("version") or 0)
    meta.tensor_count = int(data.get("tensor_count") or 0)
    meta.kv_count = int(data.get("kv_count") or 0)
    values = data.get("values")
    if isinstance(values, dict):
        meta.values.update(values)
    arrays = data.get("arrays")
    if isinstance(arrays, dict):
        meta.array_lengths.update({str(k): int(v) for k, v in arrays.items()})
    return meta


def read_meta_cached(path: str | Path, *, keep_arrays: bool = False) -> GgufMeta:
    """``read_meta`` з кешем на диску.

    Поведінка ідентична :func:`read_meta` (включно з помилками в
    ``values['_error']``), але повторний виклик для того самого файлу не
    перечитує його. Це те, чим користуються список моделей і агент.
    """
    target = Path(path)
    key = str(target)
    stamp = _fingerprint(target)
    if not stamp:
        # Файлу немає або він недоступний — хай відповідає read_meta.
        return read_meta_safe(target, keep_arrays=keep_arrays)
    if not keep_arrays:
        _load_cache()
        with _META_CACHE_LOCK:
            hit = _META_CACHE.get(key)
        if isinstance(hit, dict) and hit.get("stamp") == stamp:
            payload = hit.get("meta")
            if isinstance(payload, dict):
                return _meta_from_cache(payload, key)
    meta = read_meta_safe(target, keep_arrays=keep_arrays)
    if not keep_arrays and "_error" not in meta.values:
        global _META_CACHE_DIRTY
        with _META_CACHE_LOCK:
            _META_CACHE[key] = {"stamp": stamp, "meta": _meta_to_cache(meta)}
            _META_CACHE_DIRTY = True
        _save_cache()
    return meta


def clear_meta_cache() -> None:
    """Забути кеш метаданих (напр., після видалення моделей)."""
    global _META_CACHE_DIRTY
    with _META_CACHE_LOCK:
        _META_CACHE.clear()
        _META_CACHE_DIRTY = True
    _save_cache()


def iter_meta(path: str | Path) -> Iterator[tuple[str, Any]]:
    """Потоково перебрати пари ключ-значення (для діагностики)."""
    yield from read_meta(path, keep_arrays=False).values.items()


def looks_like_gguf(path: str | Path) -> bool:
    """Швидка перевірка магії без розбору метаданих."""
    try:
        with open(path, "rb") as handle:
            return handle.read(4) == GGUF_MAGIC
    except OSError:
        return False


__all__ = [
    "GGUF_MAGIC",
    "GGUF_TYPE",
    "GgufError",
    "GgufMeta",
    "clear_meta_cache",
    "iter_meta",
    "looks_like_gguf",
    "quant_from_filename",
    "read_meta",
    "read_meta_cached",
    "read_meta_safe",
]
