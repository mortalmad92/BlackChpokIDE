"""Менеджер моделей BLACKCHPOK: список, інспекція, завантаження, видалення.

Відмінності від наявного ``model_hub`` (він лишається для пошуку в HF):

* тут — ЖИТТЄВИЙ ЦИКЛ ФАЙЛІВ: додати локальний файл, перевірити
  цілісність, видалити з підтвердженням, показати точні метадані GGUF;
* прогноз RAM/VRAM рахується з реальних метаданих моделі, а не з назви;
* завантаження підтримує докачку, контроль вільного місця та скасування.

Модуль не залежить від tkinter і не робить мережевих запитів під час
звичайного читання списку: тільки локальний диск.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from ..hardware import GB, HardwareProfile
from . import gguf, inspect as inspect_mod

LOG = logging.getLogger("blackchpok.native.manager")

#: Розширення, які вважаємо моделями.
MODEL_SUFFIXES = (".gguf",)
#: Скільки байт лишаємо на диску після завантаження.
DISK_MARGIN_GB = 1.0
#: Розмір блоку читання при завантаженні.
CHUNK = 1 << 20


class ModelManagerError(RuntimeError):
    """Операція з моделлю неможлива."""


@dataclass
class ModelEntry:
    """Один файл моделі в теці моделей."""

    path: str
    name: str = ""
    size_gb: float = 0.0
    quant: str = ""
    architecture: str = ""
    layers: int = 0
    context: int = 0
    parameters_b: float = 0.0
    has_chat_template: bool = False
    is_projector: bool = False
    is_embedding: bool = False
    fits: str = "unknown"
    suggested_ctx: int = 0
    suggested_gpu_layers: int = 0
    vram_needed_gb: float = 0.0
    ram_needed_gb: float = 0.0
    notes: list[str] = field(default_factory=list)
    error: str = ""
    modified_at: float = 0.0
    #: Чи файл повний (магія GGUF + читабельні метадані).
    complete: bool = True
    #: Файли-проєктори поруч (mmproj) — потрібні для зору.
    projector: str = ""

    @property
    def key(self) -> str:
        return Path(self.path).stem

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["key"] = self.key
        for field_name in ("size_gb", "parameters_b", "vram_needed_gb", "ram_needed_gb"):
            data[field_name] = round(float(data[field_name] or 0.0), 2)
        return data

    def summary(self) -> str:
        bits = [self.name or self.key]
        if self.quant:
            bits.append(self.quant)
        if self.parameters_b:
            bits.append(f"{self.parameters_b:.1f}B")
        if self.context:
            bits.append(f"ctx {self.context // 1024}K")
        bits.append(f"{self.size_gb:.1f} ГБ")
        if self.fits:
            bits.append({"gpu": "GPU", "hybrid": "гібрид", "cpu": "CPU",
                         "impossible": "не влізе", "projector": "проєктор",
                         "unknown": "?"}.get(self.fits, self.fits))
        return " · ".join(bits)


# ─────────────────────────────────────────────────────────────────────────────
# Тека моделей
# ─────────────────────────────────────────────────────────────────────────────

def models_dir() -> Path:
    """Тека моделей (та сама, що бачить решта IDE)."""
    from ..model_hub import models_dir as _models_dir

    return Path(_models_dir())


def _free_gb(path: Path) -> float:
    try:
        return shutil.disk_usage(path).free / GB
    except OSError:
        return 0.0


def _drop_part(path: Path, *, reason: str = "") -> bool:
    """Прибрати недокачуваний ``.part`` і сказати про це в журналі.

    Навіщо окрема функція: ``.part`` не показується в списку моделей
    (``_scan`` фільтрує за ``.gguf``), тому пошкоджений або скасований
    файл **невидимо** займає місце. На цій машині так лежало 945 МБ.

    Мережевий обрив сюди НЕ веде: такий ``.part`` придатний для докачки
    через ``Range``, і його треба зберегти.
    """
    try:
        if not path.exists():
            return False
        size_mb = path.stat().st_size / (1024 * 1024)
        path.unlink()
    except OSError as exc:
        LOG.warning("Не вдалось прибрати %s: %s", path.name, exc)
        return False
    LOG.info("Прибрано %s (%.1f МБ) — %s", path.name, size_mb,
             reason or "недокачуваний")
    return True


def _projectors_in(folder: Path) -> list[Path]:
    return sorted(
        (item for item in folder.glob("*.gguf")
         if _is_projector(item)),
        key=lambda item: item.name,
    )


def _is_projector(path: Path) -> bool:
    """Чи це файл проєктора зору (а не модель).

    Правило беремо з :func:`blackchpok_ide.model_hub.is_projector_path`, а
    не з власної перевірки: раніше тут стояло ``startswith("mmproj")``, і
    офіційний файл mistralai ``…-BF16-mmproj.gguf`` (``mmproj`` у кінці)
    вважався МОДЕЛЛЮ. Через це список моделей показував проєктор, а вибір
    «найбільшої моделі» міг віддати шлях до нього.
    """
    from ..model_hub import is_projector_path

    return is_projector_path(path)


def _match_projector(model: Path, candidates: Iterable[Path]) -> str:
    """Підібрати файл-проєктор для мультимодальної моделі.

    Правило просте: збіг за «сімейством» у назві (``Qwen3VL``, ``Qwen2.5-VL``),
    інакше — єдиний проєктор у теці.
    """
    pool = list(candidates)
    if not pool:
        return ""
    stem = model.stem.lower()
    families = [token for token in ("qwen3vl", "qwen3-vl", "qwen2.5-vl", "qwen2vl",
                                    "llava", "minicpm", "gemma3", "internvl")
                if token in stem]
    for family in families:
        flat = family.replace(".", "").replace("-", "")
        for candidate in pool:
            name = candidate.stem.lower().replace(".", "").replace("-", "")
            if flat in name:
                return str(candidate)
    return str(pool[0]) if len(pool) == 1 else ""


# ─────────────────────────────────────────────────────────────────────────────
# Менеджер
# ─────────────────────────────────────────────────────────────────────────────

class ModelManager:
    """Керування файлами моделей у теці IDE."""

    def __init__(self, folder: str | Path | None = None) -> None:
        self.folder = Path(folder) if folder else models_dir()
        self._cache: dict[str, ModelEntry] = {}
        self._cache_time = 0.0
        self._lock = threading.RLock()

    # ── читання ───────────────────────────────────────────────────────────
    def refresh(self, *, profile: HardwareProfile | None = None,
                force: bool = True) -> list[ModelEntry]:
        """Перечитати теку моделей."""
        with self._lock:
            if not force and self._cache and (time.time() - self._cache_time) < 30:
                return list(self._cache.values())
            entries = self._scan(profile)
            self._cache = {entry.path: entry for entry in entries}
            self._cache_time = time.time()
            return entries

    def _scan(self, profile: HardwareProfile | None) -> list[ModelEntry]:
        folder = self.folder
        if not folder.exists():
            return []
        projectors = _projectors_in(folder)
        entries: list[ModelEntry] = []
        for item in sorted(folder.iterdir()):
            if not item.is_file() or item.suffix.lower() not in MODEL_SUFFIXES:
                continue
            entry = self._describe(item, profile)
            if entry.is_projector:
                continue                      # проєктори показуємо окремо
            entry.projector = _match_projector(item, projectors)
            entries.append(entry)
        entries.sort(key=lambda item: item.size_gb, reverse=True)
        return entries

    def _describe(self, path: Path, profile: HardwareProfile | None) -> ModelEntry:
        entry = ModelEntry(path=str(path), name=path.stem)
        try:
            stat = path.stat()
            entry.size_gb = stat.st_size / GB
            entry.modified_at = stat.st_mtime
        except OSError as exc:
            entry.error = str(exc)
            entry.complete = False
            return entry
        report = inspect_mod.inspect(path, profile=profile)
        entry.error = report.error
        entry.architecture = report.architecture
        entry.quant = report.quant
        entry.layers = report.layer_count
        entry.context = report.context_train
        entry.parameters_b = round(report.params_b, 2)
        entry.has_chat_template = report.has_chat_template
        entry.is_projector = report.is_vision_projector
        entry.is_embedding = report.is_embedding
        entry.fits = report.fits
        entry.suggested_ctx = report.suggested_ctx
        entry.suggested_gpu_layers = report.suggested_gpu_layers
        entry.vram_needed_gb = report.vram_needed_gb
        entry.ram_needed_gb = report.ram_needed_gb
        entry.notes = list(report.notes)
        entry.complete = not report.error
        if report.name:
            entry.name = report.name
        return entry

    def get(self, key_or_path: str) -> ModelEntry | None:
        """Знайти модель за шляхом, іменем файлу або ключем (без розширення)."""
        candidate = Path(key_or_path)
        if candidate.exists():
            return self._describe(candidate, None)
        target = (key_or_path or "").strip()
        if not target:
            return None
        with self._lock:
            for entry in self._cache.values():
                if entry.key == target or Path(entry.path).name == target:
                    return entry
        for item in self.folder.glob("*.gguf"):
            if item.stem == target or item.name == target:
                return self._describe(item, None)
        return None

    def local_models(self) -> list[ModelEntry]:
        return self.refresh()

    # ── зміни ─────────────────────────────────────────────────────────────
    def add_local(self, source: str | Path, *, copy: bool = False,
                  on_progress: Callable[[str], None] | None = None) -> ModelEntry:
        """Додати наявний локальний файл моделі.

        ``copy=False`` (типово) НЕ переносить файл: він лишається там, де
        лежить, а IDE просто бере його в обіг. Копіювання вмикають явно —
        інакше на 14-гігабайтній моделі воно б мовчки зайняло диск.
        """
        target = Path(source)
        if not target.exists() or not target.is_file():
            raise ModelManagerError(f"Файл не знайдено: {target}")
        if target.suffix.lower() not in MODEL_SUFFIXES:
            raise ModelManagerError("Підтримуються лише файли .gguf.")
        if not gguf.looks_like_gguf(target):
            raise ModelManagerError(
                f"{target.name} не є GGUF-файлом (немає магії GGUF).")
        self.folder.mkdir(parents=True, exist_ok=True)
        destination = self.folder / target.name
        if copy:
            if destination.exists() and destination.resolve() != target.resolve():
                raise ModelManagerError(f"У теці моделей уже є {destination.name}.")
            if destination.resolve() != target.resolve():
                needed = target.stat().st_size / GB
                if _free_gb(self.folder) < needed + DISK_MARGIN_GB:
                    raise ModelManagerError(
                        f"Недостатньо місця: потрібно {needed:.1f} ГБ + запас.")
                if on_progress:
                    on_progress(f"Копіюю {target.name}…")
                shutil.copy2(target, destination)
            target = destination
        if on_progress:
            on_progress(f"Модель доступна: {target.name}")
        return self._describe(target, None)

    def delete(self, key_or_path: str, *, confirm: bool = False) -> bool:
        """Видалити модель. Без ``confirm=True`` нічого не робить.

        Це навмисно: видалення ваг — незворотна дія на гігабайти. Виклик
        без підтвердження повертає ``False`` і НЕ чіпає файл.
        """
        if not confirm:
            LOG.info("Видалення %s скасовано: немає підтвердження", key_or_path)
            return False
        entry = self.get(key_or_path)
        if entry is None:
            raise ModelManagerError(f"Модель не знайдено: {key_or_path}")
        path = Path(entry.path)
        # Захист від видалення чогось поза текою моделей.
        try:
            path.resolve().relative_to(self.folder.resolve())
        except ValueError as exc:
            raise ModelManagerError(
                f"Файл поза текою моделей ({self.folder}) — не видаляю.") from exc
        try:
            path.unlink()
        except OSError as exc:
            raise ModelManagerError(f"Не вдалось видалити: {exc}") from exc
        with self._lock:
            self._cache.pop(str(path), None)
        LOG.info("Модель видалено: %s", path)
        return True

    def verify(self, key_or_path: str, *, expected_size: int = 0) -> dict[str, Any]:
        """Перевірити цілісність файлу моделі."""
        entry = self.get(key_or_path)
        if entry is None:
            raise ModelManagerError(f"Модель не знайдено: {key_or_path}")
        return inspect_mod.verify_integrity(entry.path, expected_size=expected_size)

    def rename(self, key_or_path: str, new_name: str) -> ModelEntry:
        """Перейменувати файл моделі (розширення .gguf додається саме)."""
        entry = self.get(key_or_path)
        if entry is None:
            raise ModelManagerError(f"Модель не знайдено: {key_or_path}")
        clean = new_name.strip()
        if not clean:
            raise ModelManagerError("Порожня назва.")
        if not clean.lower().endswith(".gguf"):
            clean += ".gguf"
        source = Path(entry.path)
        destination = self.folder / clean
        if destination.exists():
            raise ModelManagerError(f"Файл {clean} уже існує.")
        try:
            source.rename(destination)
        except OSError as exc:
            raise ModelManagerError(f"Не вдалось перейменувати: {exc}") from exc
        return self._describe(destination, None)

    # ── завантаження ──────────────────────────────────────────────────────
    def download(self, url: str, *, filename: str = "", on_progress=None,
                 on_status: Callable[[str], None] | None = None,
                 cancel: Callable[[], bool] | None = None) -> dict[str, Any]:
        """Завантажити модель із докачкою, перевіркою місця й цілісності.

        Файл пишеться в ``<name>.part`` і перейменовується лише після
        успішної перевірки — обірване завантаження ніколи не виглядає як
        готова модель.
        """
        self.folder.mkdir(parents=True, exist_ok=True)
        name = filename or Path(urllib.request.urlparse(url).path).name or "model.gguf"
        if not name.endswith(".gguf"):
            name += ".gguf"
        destination = self.folder / name
        part = destination.with_suffix(destination.suffix + ".part")

        total = 0
        try:
            request = urllib.request.Request(url, method="HEAD")
            request.add_header("User-Agent", "BlackChpokIDE/2.0")
            with urllib.request.urlopen(request, timeout=30) as response:
                total = int(response.headers.get("Content-Length") or 0)
        except (urllib.error.URLError, OSError):
            total = 0

        # 1. Місце на диску: рахуємо те, чого ще немає в .part.
        already = part.stat().st_size if part.exists() else 0
        needed_gb = max(0, total - already) / GB
        if needed_gb and _free_gb(self.folder) < needed_gb + DISK_MARGIN_GB:
            raise ModelManagerError(
                f"Недостатньо місця: потрібно {needed_gb + DISK_MARGIN_GB:.1f} ГБ, "
                f"вільно {_free_gb(self.folder):.1f} ГБ.")

        if on_status:
            on_status(f"Завантажую {name}"
                      f"{f' ({total / GB:.1f} ГБ)' if total else ''}…")
        request = urllib.request.Request(url, method="GET")
        request.add_header("User-Agent", "BlackChpokIDE/2.0")
        if already:
            request.add_header("Range", f"bytes={already}-")
        mode = "ab" if already else "wb"
        written = already
        condition = {"reason": ""}      # чому саме прибираємо .part

        try:
            with urllib.request.urlopen(request, timeout=60) as response, \
                    open(part, mode) as handle:
                while True:
                    if cancel is not None and cancel():
                        condition["reason"] = "скасовано"
                        raise ModelManagerError("Завантаження скасовано.")
                    block = response.read(CHUNK)
                    if not block:
                        break
                    handle.write(block)
                    written += len(block)
                    if on_progress is not None:
                        on_progress(written, total or written)
        except (urllib.error.URLError, OSError) as exc:
            # Мережа впала — .part ЛИШАЄМО: його можна докачати (Range).
            raise ModelManagerError(f"Завантаження перервано: {exc}") from exc
        except ModelManagerError:
            # Скасування користувачем — недокачаний шматок йому не потрібен.
            _drop_part(part, reason=condition["reason"] or "скасовано")
            raise

        if total and written < total:
            # Обірвано, але .part придатний для докачки — лишаємо.
            raise ModelManagerError(
                f"Файл обірвано: {written} з {total} байт. "
                "Завантаження можна продовжити — .part збережено.")

        # 2. Цілісність: магія GGUF + читабельні метадані.
        check = inspect_mod.verify_integrity(part, expected_size=total)
        if not check["ok"]:
            # Пошкоджений файл НЕ можна докачати: він займає місце (на цій
            # машині так лежало 945 МБ), а ``_scan`` його не бачить, бо
            # фільтрує за ``.gguf``. Тому прибираємо одразу.
            _drop_part(part, reason="пошкоджений файл")
            raise ModelManagerError(
                "Файл пошкоджено: " + "; ".join(check["problems"]))
        os.replace(part, destination)
        if on_status:
            on_status(f"Готово: {destination.name}")
        return {
            "path": str(destination),
            "size_bytes": written,
            "size_gb": round(written / GB, 2),
            "integrity": check,
        }

    # ── підсумки ──────────────────────────────────────────────────────────
    def summary(self, *, profile: HardwareProfile | None = None) -> dict[str, Any]:
        """Стислий стан менеджера моделей для інтерфейсу."""
        entries = self.refresh(profile=profile)
        total_gb = sum(entry.size_gb for entry in entries)
        return {
            "folder": str(self.folder),
            "count": len(entries),
            "total_gb": round(total_gb, 2),
            "free_gb": round(_free_gb(self.folder), 2),
            "models": [entry.to_dict() for entry in entries],
            "projectors": [{"path": str(item), "size_gb": round(item.stat().st_size / GB, 2)}
                           for item in _projectors_in(self.folder)],
        }

    def export_index(self, target: str | Path) -> Path:
        """Зберегти список моделей у JSON (для діагностики й бенчмарків)."""
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.summary(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path


__all__ = [
    "DISK_MARGIN_GB",
    "MODEL_SUFFIXES",
    "ModelEntry",
    "ModelManager",
    "ModelManagerError",
    "models_dir",
]
