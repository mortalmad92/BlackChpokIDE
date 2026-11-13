"""Хаб моделей: пошук на Hugging Face, GitHub, Civitai, TensorArt і завантаження.

Модуль працює на stdlib (urllib) — жодних нових залежностей, тому зібраний
.exe не «важчає». Мережеві виклики виконуються у фонових потоках, а прогрес
віддається через callback, щоб інтерфейс малював смугу в реальному часі.

Ключові можливості:
  * ``search`` — паралельний пошук по всіх джерелах;
  * ``resolve_files`` — перелік GGUF-файлів репозиторію з розмірами;
  * ``Download`` — докачуваний (HTTP Range) файл із прогресом і скасуванням.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import app_data_dir, find_data_dir

LOG = logging.getLogger("blackchpok.hub")

USER_AGENT = "BlackChpokIDE/1.0 (+local; OpenAI-compatible client)"
CHUNK = 1 << 20          # 1 МБ
TIMEOUT = 30

# Пріоритет квантувань: чим раніше, тим охочіше пропонуємо.
QUANT_ORDER = ("q4_k_m", "q4_k_s", "q4_0", "q5_k_m", "q3_k_m", "q6_k", "q8_0", "q2_k")

SOURCE_LABELS = {
    "huggingface": "Hugging Face",
    "github": "GitHub",
    "civitai": "Civitai",
    "tensorart": "TensorArt",
    "local": "Локально",
}


class HubError(RuntimeError):
    """Помилка мережі або даних хабу."""


# ─────────────────────────────────────────────────────────────────────────────
# Модель результату
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ModelHit:
    """Один результат пошуку — те, що показуємо у списку."""

    source: str                     # huggingface | github | civitai | tensorart
    model_id: str                   # Qwen/Qwen2.5-Coder-7B-Instruct-GGUF
    name: str = ""                  # людська назва
    filename: str = ""              # конкретний файл (GGUF) або ""
    size_bytes: int = 0
    downloads: int = 0
    likes: int = 0
    description: str = ""
    page_url: str = ""
    download_url: str = ""
    tags: list[str] = field(default_factory=list)
    kind: str = "llm"               # llm | lora | checkpoint | repo | runtime
    base_model: str = ""
    #: Файл візуального проєктора (``mmproj-*.gguf``) для мультимодальних
    #: моделей. llama.cpp запускається з ``--mmproj <файл>`` — без нього
    #: модель не бачить зображень узагалі.
    vision_file: str = ""

    @property
    def is_vision(self) -> bool:
        """Чи вміє ця модель бачити зображення."""
        return bool(self.vision_file)


    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    @property
    def size_gb(self) -> float:
        return round(self.size_bytes / (1024 ** 3), 2) if self.size_bytes else 0.0

    @property
    def size_text(self) -> str:
        if not self.size_bytes:
            # GitHub-репозиторії ваг не мають, зате мають зірочки.
            if self.source == "github" and self.downloads:
                return f"★ {self.downloads:,}".replace(",", " ")
            return "розмір невідомий"
        gb = self.size_bytes / (1024 ** 3)
        if gb >= 1:
            return f"{gb:.1f} ГБ"
        return f"{self.size_bytes / (1024 ** 2):.0f} МБ"

    @property
    def quant(self) -> str:
        """Квантування, витягнуте з імені файлу (Q4_K_M тощо)."""
        return (quant_of(self.filename) or "").upper()

    @property
    def ref(self) -> str:
        return f"{self.model_id}/{self.filename}" if self.filename else self.model_id

    def matches(self, *tokens: str) -> bool:
        haystack = " ".join([self.model_id, self.name, self.filename, self.base_model]).lower()
        return all(token.lower() in haystack for token in tokens if token)


def quant_of(filename: str) -> str:
    """Витягти назву квантування з імені файлу."""
    low = (filename or "").lower()
    match = re.search(r"(iq\d+_[a-z0-9_]+|q\d+_k_[msl]|q\d+_k|q\d+_\d|q\d+_k_m)", low)
    return match.group(1) if match else ""


def quant_rank(filename: str) -> int:
    """Менше — краще. Невідомі квантування в кінці."""
    quant = quant_of(filename)
    try:
        return QUANT_ORDER.index(quant)
    except ValueError:
        return len(QUANT_ORDER)


def parse_ref(text: str) -> str:
    """Прийняти посилання або «repo/file.gguf» і повернути чистий repo-id.

    Розуміє: ``Qwen/Qwen3-4B-GGUF``, ``hf.co/Qwen/Qwen3-4B-GGUF``,
    ``https://huggingface.co/Qwen/Qwen3-4B-GGUF/tree/main`` тощо.
    """
    raw = (text or "").strip().strip("'\"")
    if not raw:
        return ""
    raw = re.sub(r"^https?://", "", raw)
    raw = re.sub(r"^(www\.)?(huggingface\.co|hf\.co)/", "", raw)
    parts = [part for part in raw.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0] if parts else ""


def is_gguf(name: str) -> bool:
    return (name or "").lower().endswith(".gguf")


def is_multipart(name: str) -> bool:
    """Частина розбитого файлу (``...-00002-of-00004.gguf``)."""
    return bool(re.search(r"-\d{5}-of-\d{5}\.gguf$", name or "", re.IGNORECASE))


def is_vision_projector(name: str) -> bool:
    """Чи це файл візуального проєктора (``mmproj``).

    Без такого файлу мультимодальна модель не бачить зображень зовсім.
    llama.cpp запускає його окремим ключем ``--mmproj``, і плутати його з
    моделлю не можна: mmproj сам по собі моделлю не є.

    ВАЖЛИВО про назви. Проєктор не завжди починається з ``mmproj-``:

    * ``mmproj-Qwen3VL-8B-Instruct-F16.gguf`` — ggml-org;
    * ``Ministral-3-14B-Instruct-2512-BF16-mmproj.gguf`` — **офіційний**
      репозиторій mistralai ставить ``mmproj`` у КІНЕЦЬ.

    Раніше перевірялось лише ``"mmproj" in name``, що покривало обидва
    випадки, але крихкість лишалась: назва з ``projector`` або ``proj``
    не розпізнавалась. Тепер приймаємо обидві форми явно.
    """
    low = (name or "").lower()
    if not low.endswith(".gguf"):
        return False
    if "mmproj" in low:
        return True
    # Рідші назви того самого компонента.
    return re.search(r"(?:^|[-_.])(?:projector|vision[-_]?proj)(?:[-_.]|$)", low) is not None


def is_projector_path(path: "Path | str") -> bool:
    """Чи вказує ШЛЯХ на файл проєктора зору (а не на модель).

    Навіщо окрема функція від :func:`is_vision_projector`. Правило «це
    проєктор» повторювалось у кількох місцях, і кожне місце писало його
    по-своєму. Найдорожче це коштувало в пошуку «першої моделі»: там
    перевірялось лише ``startswith("mmproj")``, тому офіційний файл
    mistralai ``…-BF16-mmproj.gguf`` (``mmproj`` у КІНЦІ) проходив як
    модель. Наслідки були не косметичні: тести брали проєктор за модель і
    падали на «немає шарів / немає контексту», а код, що вибирав модель для
    запуску, міг віддати шлях до проєктора.

    Тепер правило одне — тут. Приймає ``Path`` або рядок, щоб викликати
    його і з переліку файлів, і з налаштувань.
    """
    name = Path(str(path or "")).name
    return is_vision_projector(name)


def pick_vision_projector(filenames: Iterable[str]) -> str:
    """Обрати файл проєктора: перевага F16, далі Q8_0, далі будь-який.

    F16 дає найкращу якість «зору»; Q8_0 — компроміс за розміром. Беремо
    НАЙБІЛЬШИЙ із доступних у межах обраного класу (у репозиторіях буває
    кілька проєкторів для різних роздільностей).
    """
    candidates = [name for name in filenames if is_vision_projector(name)]
    if not candidates:
        return ""
    def rank(name: str) -> tuple[int, int]:
        low = name.lower()
        if "f16" in low or "bf16" in low:
            return (0, -len(name))
        if "q8" in low:
            return (1, -len(name))
        if "f32" in low:
            return (2, -len(name))
        return (3, -len(name))
    return min(candidates, key=rank)


def pick_best_gguf(filenames: Iterable[str]) -> str:
    """Обрати найрозумніший файл: перевага Q4_K_M і цілим файлам.

    ВАЖЛИВО: файли ``mmproj`` тут НЕ розглядаються — це візуальний
    проєктор, а не модель. Раніше він міг потрапити у вибір, і замість
    моделі завантажувався проєктор (або навпаки).
    """
    all_names = list(filenames)
    candidates = [name for name in all_names
                  if is_gguf(name) and not is_multipart(name)
                  and not is_vision_projector(name)]
    if not candidates:
        candidates = [name for name in all_names
                      if is_gguf(name) and not is_vision_projector(name)]
    if not candidates:
        return ""
    return min(candidates, key=lambda name: (quant_rank(name), len(name)))


# ─────────────────────────────────────────────────────────────────────────────
# HTTP-утиліти
# ─────────────────────────────────────────────────────────────────────────────

def _request(url: str, *, timeout: int = TIMEOUT, headers: dict[str, str] | None = None) -> urllib.request.Request:
    request = urllib.request.Request(url, method="GET")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    return request


def fetch_json(url: str, *, timeout: int = TIMEOUT, headers: dict[str, str] | None = None) -> Any:
    try:
        with urllib.request.urlopen(_request(url, timeout=timeout, headers=headers), timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HubError(f"Доступ заборонено ({exc.code}). Модель може вимагати згоди з ліцензією.") from exc
        if exc.code == 404:
            raise HubError("Не знайдено (404).") from exc
        if exc.code == 429:
            raise HubError("Забагато запитів (429). Спробуй за хвилину.") from exc
        raise HubError(f"HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise HubError(f"Немає з'єднання: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HubError("Таймаут з'єднання.") from exc
    if not body.strip():
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise HubError(f"Відповідь не JSON: {body[:160]}") from exc


# ─────────────────────────────────────────────────────────────────────────────
# Hugging Face
# ─────────────────────────────────────────────────────────────────────────────

HF_API = "https://huggingface.co/api/models"
HF_PAGE = "https://huggingface.co"


def search_huggingface(query: str, *, limit: int = 20, gguf_only: bool = True,
                       tag: str = "", with_sizes: int = 8) -> list[ModelHit]:
    """Пошук моделей на Hugging Face (за замовчуванням — лише GGUF).

    Пошуковий endpoint не віддає розмірів файлів, тому для перших
    ``with_sizes`` результатів робимо додатковий запит по моделі. Це кілька
    секунд у фоні, натомість користувач одразу бачить «2 ГБ» чи «14 ГБ» —
    без цього вибір моделі наосліп.
    """
    params = {
        "search": query,
        "sort": "downloads",
        "direction": "-1",
        "limit": str(max(1, min(50, limit))),
        "expand[]": "siblings",
    }
    if gguf_only:
        params["filter"] = "gguf"
    if tag:
        params["filter"] = tag
    url = f"{HF_API}?{urllib.parse.urlencode(params, doseq=True)}"
    data = fetch_json(url) or []
    hits: list[ModelHit] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "")
        if not model_id:
            continue
        siblings = item.get("siblings") or []
        names = [str(s.get("rfilename", "")) for s in siblings if isinstance(s, dict)]
        filename = pick_best_gguf(names)
        vision = pick_vision_projector(names)
        tags = [str(t) for t in (item.get("tags") or []) if isinstance(t, str)][:12]
        hits.append(
            ModelHit(
                source="huggingface",
                model_id=model_id,
                name=model_id.split("/")[-1],
                filename=filename,
                downloads=int(item.get("downloads") or 0),
                likes=int(item.get("likes") or 0),
                page_url=f"{HF_PAGE}/{model_id}",
                download_url=f"{HF_PAGE}/{model_id}/resolve/main/{filename}" if filename else "",
                tags=tags,
                kind="llm",
                base_model=_base_model_from_tags(tags),
                vision_file=vision,
            )
        )

    if with_sizes > 0:
        enrich_sizes(hits, limit=with_sizes)
    return hits


def fits_hardware(hit: ModelHit, *, usable_gb: float = 0.0) -> tuple[bool, str]:
    """Чи влізе модель у пам'ять цієї машини.

    Навіщо: автоматичний вибір «найбільша з зором» вибрав 72B на 44 ГБ —
    на машині з 31 ГБ доступної пам'яті вона б або не запустилась, або
    завантажувалась годинами. Тому перед завантаженням перевіряємо розмір.

    Повертає ``(влізе, пояснення)``. Якщо розмір невідомий — вважаємо, що
    влізе (не блокуємо користувача через брак даних).
    """
    if not hit.size_bytes:
        return True, "розмір невідомий"
    need = hit.size_bytes / (1024 ** 3)
    if usable_gb <= 0:
        return True, f"{need:.1f} ГБ"
    # Модель потребує ще й місця під контекст: приблизно +15%.
    estimate = need * 1.15
    if estimate <= usable_gb:
        return True, f"{need:.1f} ГБ (влізе у {usable_gb:.0f} ГБ)"
    return False, (f"{need:.1f} ГБ — завелика для {usable_gb:.0f} ГБ "
                   f"доступної пам'яті")


def pick_for_hardware(hits: list[ModelHit], *, usable_gb: float = 0.0,
                      prefer_official: bool = True) -> ModelHit | None:
    """Обрати найкращу модель, яка СПРАВДІ влізе в пам'ять.

    Порядок переваги: офіційний репозиторій → більший розмір файлу (краща
    якість) → більше завантажень. Моделі, що не влізають, відкидаються.
    """
    usable = [hit for hit in hits if fits_hardware(hit, usable_gb=usable_gb)[0]]
    if not usable:
        return None

    def score(hit: ModelHit) -> tuple[int, int, int]:
        official = 0
        if prefer_official and hit.model_id.startswith(
                ("ggml-org/", "Qwen/", "unsloth/", "lmstudio-community/",
                 "openbmb/")):
            official = 1
        return (official, hit.size_bytes or 0, hit.downloads or 0)

    return max(usable, key=score)


def enrich_sizes(hits: list[ModelHit], *, limit: int = 8, workers: int = 4) -> None:
    """Доповнити результати розмірами файлів (по одному запиту на модель)."""
    targets = [hit for hit in hits[:limit] if hit.source == "huggingface" and hit.filename and not hit.size_bytes]
    if not targets:
        return

    def lookup(hit: ModelHit) -> None:
        try:
            for name, size in _file_sizes(hit.model_id).items():
                if name == hit.filename:
                    hit.size_bytes = size
                    return
        except HubError as exc:
            LOG.debug("Розмір для %s недоступний: %s", hit.model_id, exc)

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(targets)))) as pool:
        list(pool.map(lookup, targets))


def _file_sizes(model_id: str) -> dict[str, int]:
    """{ім'я файлу: розмір} для репозиторію."""
    data = fetch_json(f"{HF_API}/{parse_ref(model_id)}?blobs=true")
    sizes: dict[str, int] = {}
    if not isinstance(data, dict):
        return sizes
    for item in data.get("siblings") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("rfilename") or "")
        if not name:
            continue
        lfs = item.get("lfs")
        if isinstance(lfs, dict) and lfs.get("size"):
            sizes[name] = int(lfs["size"])
        elif item.get("size"):
            sizes[name] = int(item["size"])
    return sizes



def _base_model_from_tags(tags: list[str]) -> str:
    for tag in tags:
        if tag.startswith("base_model:"):
            return tag.split(":", 1)[1].split("/")[-1]
    return ""


def resolve_files(model_id: str, *, gguf_only: bool = True,
                  include_parts: bool = False) -> list[dict[str, Any]]:
    """Перелік файлів репозиторію з розмірами.

    Важливо: у багатьох репозиторіях лежать і **частини** розбитого файлу
    (``…-00001-of-00002.gguf``), і той самий файл **цілком**. Раніше панель
    показувала саме частини — і користувач завантажував шматок замість
    моделі. Тепер за замовчуванням лишаємо тільки цілі файли; частини
    показуються лише тоді, коли цілого файлу немає (тоді додаємо суму
    розмірів усіх частин і позначку ``multipart``).
    """
    clean = parse_ref(model_id)
    if not clean:
        raise HubError("Порожній ідентифікатор моделі.")
    data = fetch_json(f"{HF_API}/{clean}?blobs=true")
    if not isinstance(data, dict):
        raise HubError(f"Модель «{clean}» не знайдена.")

    raw: list[dict[str, Any]] = []
    for item in data.get("siblings") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("rfilename") or "")
        if not name:
            continue
        if gguf_only and not is_gguf(name):
            continue
        size = 0
        lfs = item.get("lfs")
        if isinstance(lfs, dict) and lfs.get("size"):
            size = int(lfs.get("size") or 0)
        elif item.get("size"):
            size = int(item.get("size") or 0)
        raw.append({"name": name, "size": size, "multipart": is_multipart(name)})

    # ── Відділяємо цілі файли від частин
    whole = [item for item in raw if not item["multipart"]]
    parts = [item for item in raw if item["multipart"]]

    # Групуємо частини за «базовою» назвою (без -00001-of-00002).
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in parts:
        base = multipart_base(item["name"])
        groups.setdefault(base, []).append(item)

    files: list[dict[str, Any]] = []
    for item in whole:
        files.append({
            "name": item["name"],
            "size": item["size"],
            "multipart": False,
            "quant": quant_of(item["name"]),
            #: mmproj — візуальний проєктор, а не модель: панель показує
            #: його окремим рядком і завантажує разом із моделлю.
            "vision": is_vision_projector(item["name"]),
        })

    # Частини показуємо лише тоді, коли цілого файлу немає.
    whole_names = {item["name"] for item in whole}
    for base, members in groups.items():
        if any(name == base or name.startswith(base) for name in whole_names):
            continue
        total = sum(member["size"] for member in members)
        first = sorted(members, key=lambda m: m["name"])[0]["name"]
        files.append({
            "name": base,
            "size": total,
            "multipart": True,
            "quant": quant_of(base),
            "part_count": len(members),
            "first_part": first,
        })

    if include_parts:
        for item in parts:
            files.append({
                "name": item["name"],
                "size": item["size"],
                "multipart": True,
                "quant": quant_of(item["name"]),
            })

    files.sort(key=lambda item: (item["size"] or 0, item["name"]))
    return files


_PART_RE = re.compile(r"(-\d{5}-of-\d{5})?\.gguf$", re.IGNORECASE)


def multipart_base(name: str) -> str:
    """``…-00001-of-00002.gguf`` → ``….gguf`` (назва цілого файлу)."""
    return _PART_RE.sub(".gguf", name or "")


def download_url_for(model_id: str, filename: str) -> str:
    clean = parse_ref(model_id)
    quoted = urllib.parse.quote(filename)
    return f"{HF_PAGE}/{clean}/resolve/main/{quoted}"


# ─────────────────────────────────────────────────────────────────────────────
# GitHub
# ─────────────────────────────────────────────────────────────────────────────

GITHUB_SEARCH = "https://api.github.com/search/repositories"


def search_github(query: str, *, limit: int = 12) -> list[ModelHit]:
    """Пошук репозиторіїв на GitHub (інструкції, рушії, колекції моделей).

    GitHub не зберігає ваги моделей, тому результат — посилання на
    репозиторій або останній реліз. Для рушія llama.cpp є окремий метод
    ``latest_runtime_releases``.
    """
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": str(max(1, min(30, limit)))}
    url = f"{GITHUB_SEARCH}?{urllib.parse.urlencode(params)}"
    data = fetch_json(url, headers={"Accept": "application/vnd.github+json"}) or {}
    items = data.get("items") if isinstance(data, dict) else []
    hits: list[ModelHit] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        full_name = str(item.get("full_name") or "")
        if not full_name:
            continue
        hits.append(
            ModelHit(
                source="github",
                model_id=full_name,
                name=full_name,
                description=str(item.get("description") or "")[:300],
                downloads=int(item.get("stargazers_count") or 0),
                page_url=str(item.get("html_url") or f"https://github.com/{full_name}"),
                tags=[str(t) for t in (item.get("topics") or [])][:8],
                kind="repo",
            )
        )
    return hits


def latest_runtime_releases(*, limit: int = 5) -> list[dict[str, Any]]:
    """Останні збірки llama.cpp для Windows (для авто-встановлення рушія)."""
    url = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=" + str(max(1, limit))
    data = fetch_json(url, headers={"Accept": "application/vnd.github+json"}) or []
    releases: list[dict[str, Any]] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        assets = []
        for asset in item.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "")
            if not name.endswith(".zip") or "win" not in name:
                continue
            assets.append(
                {
                    "name": name,
                    "size": int(asset.get("size") or 0),
                    "url": str(asset.get("browser_download_url") or ""),
                }
            )
        if assets:
            releases.append(
                {
                    "tag": str(item.get("tag_name") or ""),
                    "published": str(item.get("published_at") or ""),
                    "assets": assets,
                }
            )
    return releases


# ─────────────────────────────────────────────────────────────────────────────
# Civitai / TensorArt (моделі для генерації зображень)
# ─────────────────────────────────────────────────────────────────────────────

CIVITAI_API = "https://civitai.com/api/v1/models"


def search_civitai(query: str, *, limit: int = 15, kinds: str = "Checkpoint,LORA",
                   nsfw: bool = False) -> list[ModelHit]:
    """Пошук контрольних точок і LoRA на Civitai.

    API Civitai приймає лише одне значення ``types`` за запит (кома дає
    400), тому робимо окремий запит на кожен тип і зливаємо результати.
    """
    type_list = [item.strip() for item in (kinds or "").split(",") if item.strip()] or ["Checkpoint"]
    per_type = max(1, limit // max(1, len(type_list)))
    hits: list[ModelHit] = []
    seen: set[str] = set()
    last_error: HubError | None = None

    for kind in type_list:
        params = {
            "query": query,
            "limit": str(per_type),
            "types": kind,
            "sort": "Highest Rated",
            "nsfw": "true" if nsfw else "false",
        }
        url = f"{CIVITAI_API}?{urllib.parse.urlencode(params)}"
        try:
            data = fetch_json(url, headers={"Accept": "application/json"}) or {}
        except HubError as exc:
            last_error = exc
            LOG.info("Civitai (%s) недоступний: %s", kind, exc)
            continue
        for hit in _civitai_items(data):
            if hit.model_id in seen:
                continue
            seen.add(hit.model_id)
            hits.append(hit)

    if not hits and last_error is not None:
        raise last_error
    hits.sort(key=lambda hit: hit.likes, reverse=True)
    return hits[:limit]


def _civitai_items(data: Any) -> list[ModelHit]:
    hits: list[ModelHit] = []
    for item in (data.get("items") if isinstance(data, dict) else []) or []:
        if not isinstance(item, dict):
            continue
        versions = item.get("modelVersions") or []
        version = versions[0] if versions and isinstance(versions[0], dict) else {}
        files = version.get("files") or []
        primary = next((f for f in files if isinstance(f, dict) and f.get("primary")), files[0] if files else {})
        size = int(float(primary.get("sizeKB") or 0) * 1024) if isinstance(primary, dict) else 0
        model_id = str(item.get("id") or "")
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        hits.append(
            ModelHit(
                source="civitai",
                model_id=model_id,
                name=str(item.get("name") or model_id),
                filename=str(primary.get("name") or "") if isinstance(primary, dict) else "",
                size_bytes=size,
                downloads=int(stats.get("downloadCount") or 0),
                likes=int(stats.get("thumbsUpCount") or 0),
                description=_strip_html(str(item.get("description") or ""))[:300],
                page_url=f"https://civitai.com/models/{model_id}",
                download_url=str(primary.get("downloadUrl") or "") if isinstance(primary, dict) else "",
                tags=[str(t) for t in (item.get("tags") or [])][:10],
                kind=str(item.get("type") or "checkpoint").lower(),
                base_model=str(version.get("baseModel") or ""),
            )
        )
    return hits


def search_tensorart(query: str, *, limit: int = 15) -> list[ModelHit]:
    """TensorArt не має відкритого API для пошуку (станом на 2026 — 403).

    Замість того, щоб вдавати результат, повертаємо порожній список: панель
    покаже пояснення і кнопку «Відкрити TensorArt у браузері».
    """
    LOG.info("TensorArt: відкритого API немає, пошук пропущено («%s»)", query)
    return []


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").replace("&quot;", '"').replace("&amp;", "&").strip()


# ─────────────────────────────────────────────────────────────────────────────
# Агрегований пошук
# ─────────────────────────────────────────────────────────────────────────────

SOURCES = ("huggingface", "github", "civitai", "tensorart")


def source_available(source: str) -> tuple[bool, str]:
    """Чи можна користуватися джерелом (для підписів у панелі)."""
    if source == "tensorart":
        return False, "Немає відкритого API — відкриваємо сайт у браузері"
    return True, SOURCE_LABELS.get(source, source)


class SearchJob:
    """Паралельний пошук по кількох джерелах зі стрімінгом результатів.

    Використання::

        job = SearchJob("qwen coder", sources=("huggingface", "civitai"))
        job.start()
        while job.running or not job.results.empty():
            batch, source, error = job.results.get()
    """

    def __init__(self, query: str, sources: Iterable[str] = SOURCES, *, limit: int = 15) -> None:
        self.query = (query or "").strip()
        self.sources = tuple(s for s in sources if s in SOURCES)
        self.limit = limit
        self.results: "queue.Queue[tuple[str, list[ModelHit], str]]" = queue.Queue()
        self._cancel = threading.Event()
        self._threads: list[threading.Thread] = []
        self.errors: dict[str, str] = {}

    @property
    def running(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def start(self) -> None:
        for source in self.sources:
            thread = threading.Thread(target=self._run_source, args=(source,), daemon=True)
            thread.start()
            self._threads.append(thread)

    def cancel(self) -> None:
        self._cancel.set()

    def run_blocking(self, timeout: float = 40.0) -> list[ModelHit]:
        """Синхронний варіант (для самоперевірки та тестів)."""
        collected: list[ModelHit] = []
        self.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                _source, hits, _error = self.results.get(timeout=0.2)
                collected.extend(hits)
            except queue.Empty:
                if not self.running:
                    break
        return collected

    def _run_source(self, source: str) -> None:
        if self._cancel.is_set():
            return
        try:
            hits = _search_one(source, self.query, self.limit)
            error = ""
        except HubError as exc:
            hits, error = [], str(exc)
        except Exception as exc:  # noqa: BLE001 - джерело не має валити пошук
            LOG.exception("Пошук %s впав", source)
            hits, error = [], f"{type(exc).__name__}: {exc}"
        if error:
            self.errors[source] = error
        self.results.put((source, hits, error))


def _search_one(source: str, query: str, limit: int) -> list[ModelHit]:
    if source == "huggingface":
        return search_huggingface(query, limit=limit)
    if source == "github":
        return search_github(query, limit=min(limit, 12))
    if source == "civitai":
        return search_civitai(query, limit=limit)
    if source == "tensorart":
        return search_tensorart(query, limit=limit)
    return []


def search(query: str, sources: Iterable[str] = SOURCES, *, limit: int = 15) -> list[ModelHit]:
    """Синхронний пошук по всіх джерелах (зручно для тестів і CLI)."""
    job = SearchJob(query, sources, limit=limit)
    return job.run_blocking()


# ─────────────────────────────────────────────────────────────────────────────
# Тека моделей і завантаження
# ─────────────────────────────────────────────────────────────────────────────

def models_dir() -> Path:
    """Тека, куди складаємо завантажені моделі.

    Якщо моделі вже лежать у портативній теці ``userdata/models`` (поруч із
    кодом або .exe), використовуємо її — інакше зібрана програма «не бачила б»
    щойно завантажену модель.
    """
    target = find_data_dir("models", marker=".gguf")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return target


def safe_filename(name: str) -> str:
    """Прибрати з імені символи, заборонені у Windows."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (name or "").strip())
    cleaned = cleaned.strip(" .")
    return cleaned or "model.gguf"


def delete_local_model(path: Path | str) -> Path:
    """Видалити файл моделі з диска.

    Лише ``.gguf``. Каталог, проєкт і будь-який інший файл цей метод
    не чіпає — виклик із селектора вже показав вікно підтвердження.
    """
    target = Path(path)
    if not target.is_file() or not is_gguf(target.name):
        raise OSError(f"Це не файл моделі: {target}")
    target.unlink()
    return target


def local_models() -> list[Path]:
    """Уже завантажені GGUF-файли."""
    folder = models_dir()
    try:
        return sorted(path for path in folder.iterdir() if path.is_file() and is_gguf(path.name))
    except OSError:
        return []


@dataclass
class Progress:
    """Знімок стану завантаження для інтерфейсу."""

    downloaded: int = 0
    total: int = 0
    speed_bps: float = 0.0
    done: bool = False
    error: str = ""
    path: str = ""

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 0.0
        return min(100.0, self.downloaded * 100.0 / self.total)

    @property
    def speed_text(self) -> str:
        if self.speed_bps <= 0:
            return ""
        mb = self.speed_bps / (1024 ** 2)
        if mb >= 1:
            return f"{mb:.1f} МБ/с"
        return f"{self.speed_bps / 1024:.0f} КБ/с"

    @property
    def eta_text(self) -> str:
        if self.speed_bps <= 0 or self.total <= 0:
            return ""
        left = max(0, self.total - self.downloaded)
        seconds = int(left / self.speed_bps)
        if seconds >= 3600:
            return f"{seconds // 3600} год {seconds % 3600 // 60} хв"
        if seconds >= 60:
            return f"{seconds // 60} хв {seconds % 60} с"
        return f"{seconds} с"


class Download:
    """Завантаження файлу з докачкою (HTTP Range) і живим прогресом.

    Приклад::

        task = Download(url, dest, on_progress=print)
        task.start()
        while task.running:
            time.sleep(0.1)
        if task.error: ...
    """

    def __init__(
        self,
        url: str,
        dest: Path,
        *,
        on_progress: Callable[[Progress], None] | None = None,
        expected_size: int = 0,
    ) -> None:
        self.url = url
        self.dest = Path(dest)
        self.on_progress = on_progress
        self.expected_size = expected_size
        self.state = Progress(total=expected_size, path=str(self.dest))
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self) -> str:
        return self.state.error

    @property
    def finished(self) -> bool:
        return self.state.done

    def cancel(self) -> None:
        self._cancel.set()

    def start(self) -> None:
        if self.running:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def run_blocking(self) -> bool:
        """Синхронне завантаження (тести, CLI)."""
        self._run()
        return self.state.done

    # ── робота у потоці ────────────────────────────────────────────────────
    def _emit(self, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self.state, key, value)
            snapshot = Progress(**vars(self.state))
        if self.on_progress:
            try:
                self.on_progress(snapshot)
            except Exception:  # noqa: BLE001 - інтерфейс не має ламати завантаження
                LOG.debug("on_progress впав", exc_info=True)

    def _finalise(self, part: Path, total: int) -> None:
        """Перевірити повноту .part і перетворити його на цільовий файл."""
        if not part.exists() or part.stat().st_size == 0:
            self._emit(error="Файл не завантажено (порожня відповідь).")
            return
        size = part.stat().st_size
        if total and size < total:
            self._emit(downloaded=size, total=total,
                       error=f"Файл обірвано: {size} з {total} байт. Спробуй ще раз.")
            return
        try:
            os.replace(part, self.dest)
        except OSError as exc:
            self._emit(error=f"Не вдалось зберегти файл: {exc}")
            return
        self._emit(done=True, downloaded=self.dest.stat().st_size, total=total or size,
                   path=str(self.dest), speed_bps=0.0)
        LOG.info("Модель завантажено: %s", self.dest)

    def _run(self) -> None:
        part = self.dest.with_suffix(self.dest.suffix + ".part")
        try:
            part.parent.mkdir(parents=True, exist_ok=True)
            already = part.stat().st_size if part.exists() else 0
            total = self.expected_size

            # Докачка з повного файлу: сервер відповів би 416, тож просто
            # доводимо справу до кінця — файл уже цілий.
            if already and total and already >= total:
                self._finalise(part, total)
                return
            if already and not total:
                remote = size_of_url(self.url)
                if remote and already >= remote:
                    self._finalise(part, remote)
                    return

            request = urllib.request.Request(self.url, method="GET")
            request.add_header("User-Agent", USER_AGENT)
            if already:
                request.add_header("Range", f"bytes={already}-")

            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                status = getattr(response, "status", 200)
                if already and status != 206:
                    # Сервер не вміє докачування — починаємо з нуля.
                    already = 0
                    part.unlink(missing_ok=True)
                length = int(response.headers.get("Content-Length") or 0)
                total = total or (length + already)
                self._emit(total=total, downloaded=already)

                started = time.monotonic()
                last_emit = 0.0
                downloaded = already
                mode = "ab" if already else "wb"
                with open(part, mode) as handle:
                    while True:
                        if self._cancel.is_set():
                            self._emit(error="Скасовано")
                            return
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        now = time.monotonic()
                        if now - last_emit >= 0.25:
                            elapsed = max(1e-6, now - started)
                            self._emit(downloaded=downloaded, speed_bps=(downloaded - already) / elapsed)
                            last_emit = now
                self._emit(downloaded=downloaded, speed_bps=0.0)

            self._finalise(part, total)
        except urllib.error.HTTPError as exc:
            # 416 під час докачки означає, що .part уже містить увесь файл.
            if exc.code == 416 and part.exists() and part.stat().st_size > 0:
                self._finalise(part, self.expected_size or part.stat().st_size)
                return
            self._emit(error=f"HTTP {exc.code}: {exc.reason}")
        except urllib.error.URLError as exc:
            self._emit(error=f"Немає з'єднання: {exc.reason}")
        except TimeoutError:
            self._emit(error="Таймаут завантаження.")
        except OSError as exc:

            self._emit(error=f"Помилка запису: {exc}")
        except Exception as exc:  # noqa: BLE001 - показуємо користувачу
            LOG.exception("Завантаження впало")
            self._emit(error=f"{type(exc).__name__}: {exc}")


def download_model(hit: ModelHit, *, on_progress: Callable[[Progress], None] | None = None,
                   target_dir: Path | None = None) -> Download:
    """Підготувати завантаження конкретного результату пошуку."""
    url = hit.download_url
    if not url:
        if hit.source == "huggingface" and hit.filename:
            url = download_url_for(hit.model_id, hit.filename)
        else:
            raise HubError("Для цього результату немає прямого посилання на файл.")
    folder = target_dir or models_dir()
    name = safe_filename(hit.filename or f"{hit.model_id.split('/')[-1]}.gguf")
    return Download(url, folder / name, on_progress=on_progress, expected_size=hit.size_bytes)


def download_vision_projector(hit: ModelHit, *,
                              on_progress: Callable[[Progress], None] | None = None,
                              target_dir: Path | None = None) -> Download:
    """Підготувати завантаження файлу візуального проєктора (``mmproj``).

    Без нього мультимодальна модель не бачить зображень: llama.cpp
    приймає картинку в запиті, але модель її «не читає». Тому для
    VL-моделей завантажуємо ДВА файли — модель і проєктор.
    """
    if not hit.vision_file:
        raise HubError("У цієї моделі немає файлу візуального проєктора (mmproj).")
    url = download_url_for(hit.model_id, hit.vision_file)
    folder = target_dir or models_dir()
    size = 0
    try:
        for item in resolve_files(hit.model_id, gguf_only=False):
            if item.get("name") == hit.vision_file:
                size = int(item.get("size") or 0)
                break
    except HubError:
        size = 0
    return Download(url, folder / safe_filename(hit.vision_file),
                    on_progress=on_progress, expected_size=size)


def vision_projector_for(model_path: Path | str) -> Path | None:
    """Знайти файл проєктора, що відповідає завантаженій моделі.

    Шукаємо в тій самій теці файл ``mmproj*.gguf``. Якщо в теці кілька
    проєкторів (різні моделі), віддаємо перевагу тому, чия назва містить
    основу імені моделі (напр. ``Qwen2.5-VL-3B``).

    ВАЖЛИВО: проєктор підходить ЛИШЕ мультимодальній моделі. Звичайна
    текстова модель (``qwen2.5-coder-14b``) не має зору взагалі, і
    приєднувати до неї чужий ``mmproj`` не можна — llama.cpp падав би на
    несумісності. Раніше функція повертала будь-який наявний проєктор, і
    текстова 14B-модель вважалась «зоровою».
    """
    target = Path(model_path)
    folder = target.parent
    if not folder.is_dir():
        return None
    stem = target.stem.lower()
    # Модель має бути мультимодальною за назвою: vl / vision / multimodal.
    #
    # Раніше список маркерів не знав про родини, де мультимодальність не
    # позначена в імені файлу. Через це «Ministral-3-14B-Instruct» (модель
    # із зором) НІКОЛИ не отримувала проєктор: автозапуск піднімав її без
    # ``--mmproj``, значок Vision у хабі світився, а знімки не передавались.
    # Список розширено, але рішення все одно ухвалює наявність файлу нижче:
    # без фактичного ``mmproj`` зору не буде.
    if not any(marker in stem for marker in (
            "-vl", "_vl", "vl-", "vision", "multimodal", "llava", "minicpm-v",
            "ministral", "mistral-3", "mistral3", "pixtral", "magistral",
            "gemma-3", "gemma3")):
        LOG.debug("Модель %s не мультимодальна — проєктор не потрібен", target.name)
        return None
    candidates = sorted(folder.glob("*mmproj*.gguf"))
    if not candidates:
        # Офіційний репозиторій mistralai кладе проєктор як
        # ``…-mmproj.gguf`` (mmproj у кінці) — glob це покриває. Але буває й
        # ``…projector….gguf``, тому додаємо другий пошук за розпізнаванням
        # через :func:`is_vision_projector`, а не лише за підрядком.
        candidates = sorted(
            item for item in folder.glob("*.gguf")
            if is_vision_projector(item.name))
    if not candidates:
        return None
    if len(candidates) == 1:
        candidate = candidates[0]
        # Єдиний проєктор теж має стосуватись цієї моделі (та сама основа).
        return candidate if _same_family(stem, candidate.stem.lower()) else None
    # Основа без квантування: qwen2.5-vl-3b-instruct-q4_k_m → qwen2.5-vl-3b
    base = re.sub(r"[-_.](q\d|iq\d|ud|f16|f32|bf16).*$", "", stem)
    for candidate in candidates:
        name = candidate.stem.lower()
        if base and base in name:
            return candidate
        if _same_family(stem, name):
            return candidate
    return None


def _same_family(model_stem: str, projector_stem: str) -> bool:
    """Чи стосуються модель і проєктор однієї родини (qwen2.5-vl-3b).

    Порівнюємо «сімейні» частини назви: марку й розмір. ``Qwen2.5-VL-3B``
    і ``mmproj-Qwen2.5-VL-3B-Instruct-f16`` — одна родина, а
    ``qwen2.5-coder-14b`` — ні.
    """
    def family(text: str) -> str:
        clean = text.replace("mmproj", "").replace("_", "-").lower()
        parts = re.split(r"[-.]", clean)
        marker = next((part for part in parts
                       if part in ("vl", "vision", "multimodal", "llava")), "")
        size = next((part for part in parts
                     if re.fullmatch(r"\d+(\.\d+)?b", part)), "")
        return f"{marker}|{size}"

    model_family = family(model_stem)
    return bool(model_family.strip("|")) and model_family == family(projector_stem)


def size_of_url(url: str) -> int:
    """Дізнатися розмір файлу без завантаження (HEAD-запит)."""
    request = urllib.request.Request(url, method="HEAD")
    request.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return int(response.headers.get("Content-Length") or 0)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        LOG.debug("HEAD не вдався для %s: %s", url, exc)
        return 0


__all__ = [
    "Download",
    "HubError",
    "ModelHit",
    "Progress",
    "SOURCES",
    "SearchJob",
    "download_model",
    "download_url_for",
    "download_vision_projector",
    "fits_hardware",
    "is_projector_path",
    "is_vision_projector",
    "pick_for_hardware",
    "pick_vision_projector",
    "vision_projector_for",
    "fetch_json",
    "latest_runtime_releases",
    "local_models",
    "models_dir",
    "parse_ref",
    "pick_best_gguf",
    "quant_of",
    "safe_filename",
    "search",
    "search_civitai",
    "search_github",
    "search_huggingface",
    "search_tensorart",
    "resolve_files",
    "size_of_url",
    "source_available",
]
