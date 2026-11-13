"""Провайдери моделей: локальні (пріоритет) і хмарні (необов'язкові).

Головна ідея BlackChpok — **Local AI First**. Тому локальні inference-сервери
є повноцінними провайдерами першого класу, а хмара — додатковою опцією:

* локальний провайдер не потребує API-ключа;
* статус локального провайдера — це **реальний** результат ``GET /models``,
  а не вигаданий «онлайн»;
* характеристики моделей (вікно контексту, параметри) беруться лише з того,
  що реально відомо: з каталогу провайдера, з назви GGUF-файлу або з
  збереженого плану запуску рушія. Невідоме значення показується як ``—``.

Модуль не тягне tkinter і не робить мережевих запитів під час імпорту.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import cloud_agents, model_hub
from .llm_client import KNOWN_ENDPOINTS, LLMClient, LLMError

LOG = logging.getLogger("blackchpok.providers")

LOCAL = "local"
CLOUD = "cloud"


@dataclass(frozen=True)
class LocalProvider:
    """Локальний inference-сервер (OpenAI-сумісний)."""

    key: str
    label: str
    base_url: str
    note: str = ""
    api_key: str = "local"
    launch_hint: str = ""

    @property
    def is_local(self) -> bool:
        return True


#: Локальні провайдери. Порядок = порядок показу в селекторі.
LOCAL_PROVIDERS: tuple[LocalProvider, ...] = (
    LocalProvider(
        key="ollama",
        label="Ollama",
        base_url="http://127.0.0.1:11434/v1",
        note="Локальні моделі через ollama serve",
        launch_hint="ollama serve",
    ),
    LocalProvider(
        key="lmstudio",
        label="LM Studio",
        base_url="http://127.0.0.1:1234/v1",
        note="Server у LM Studio Developer",
        launch_hint="LM Studio → Developer → Start Server",
    ),
    LocalProvider(
        key="llamacpp",
        label="llama.cpp",
        base_url="http://127.0.0.1:8080/v1",
        note="llama-server із GGUF-моделлю",
        launch_hint="Хаб моделей → запустити локальну модель",
    ),
    LocalProvider(
        key="vllm",
        label="vLLM",
        base_url="http://127.0.0.1:8000/v1",
        note="vLLM OpenAI-сервер",
        launch_hint="vllm serve <модель>",
    ),
    LocalProvider(
        key="custom-local",
        label="Свій локальний URL",
        base_url="",
        note="Будь-який OpenAI-сумісний сервер у мережі",
        launch_hint="http://127.0.0.1:PORT/v1",
    ),
)

_LOCAL_BY_KEY = {provider.key: provider for provider in LOCAL_PROVIDERS}


@dataclass
class ModelEntry:
    """Одна модель у списку вибору."""

    name: str
    provider_key: str
    provider_label: str
    kind: str                       # local | cloud
    online: bool = False
    context: int = 0                # 0 = невідомо
    params: float = 0.0             # млрд параметрів, 0 = невідомо
    quant: str = ""
    caps: tuple[str, ...] = ()
    note: str = ""
    path: str = ""                  # локальний GGUF-файл, якщо є

    @property
    def is_local(self) -> bool:
        return self.kind == LOCAL

    @property
    def state_text(self) -> str:
        if not self.online:
            return "недоступна"
        return "готова" if self.is_local else "ключ є"

    @property
    def context_text(self) -> str:
        if self.context <= 0:
            return "—"
        if self.context >= 1000:
            return f"{self.context // 1000}K"
        return str(self.context)

    @property
    def params_text(self) -> str:
        if self.params <= 0:
            return ""
        text = f"{self.params:g}B"
        return f"{text} · {self.quant}" if self.quant else text

    @property
    def meta_text(self) -> str:
        parts = [self.provider_label, self.kind.upper()]
        if self.params_text:
            parts.append(self.params_text)
        parts.append(f"ctx {self.context_text}")
        return " · ".join(parts)

    def matches(self, query: str) -> bool:
        clean = (query or "").strip().lower()
        if not clean:
            return True
        haystack = " ".join((self.name, self.provider_label, self.kind,
                             self.quant, self.note)).lower()
        return all(token in haystack for token in clean.split())


# ─────────────────────────────────────────────────────────────────────────────
# Визначення характеристик
# ─────────────────────────────────────────────────────────────────────────────

#: Розмір параметрів із назви файлу чи моделі: «qwen2.5-coder-7b» → 7.0.
_PARAM_RE = re.compile(r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*b(?![a-z0-9])", re.IGNORECASE)


def params_from_name(name: str) -> float:
    """Параметри моделі (млрд) з назви — лише якщо вони там справді є."""
    matches = _PARAM_RE.findall(name or "")
    if not matches:
        return 0.0
    try:
        values = [float(value) for value in matches]
    except ValueError:
        return 0.0
    # Беремо найбільше правдоподібне: «1.5b» у «-1_5b-...» тощо.
    plausible = [value for value in values if 0.1 <= value <= 1000]
    return max(plausible) if plausible else 0.0


def quant_from_name(name: str) -> str:
    """Назва квантування GGUF («Q4_K_M», «Q8_0») або порожньо."""
    match = re.search(r"(iq|q)\d[_a-z0-9]*", (name or "").lower())
    return match.group(0).upper() if match else ""


def local_models() -> list[ModelEntry]:
    """Усі GGUF-моделі, які вже лежать на диску."""
    entries: list[ModelEntry] = []
    try:
        files = model_hub.local_models()
    except Exception:  # noqa: BLE001 - диск може бути недоступний
        return entries
    for path in files:
        entries.append(_local_entry(path))
    return entries


def _local_entry(path: Path) -> ModelEntry:
    from . import model_caps

    stem = path.stem
    caps: tuple[str, ...] = ()
    try:
        flags = model_caps.detect(filename=path.name, model_id=stem)
        caps = tuple(flags.icons())
    except Exception:  # noqa: BLE001 - можливості не критичні
        caps = ()
    return ModelEntry(
        name=stem,
        provider_key="llamacpp",
        provider_label="llama.cpp",
        kind=LOCAL,
        online=False,       # правдивий статус знає лише перевірка сервера
        context=0,
        params=params_from_name(stem),
        quant=quant_from_name(path.name),
        caps=caps,
        note=str(path),
        path=str(path),
    )


def cloud_models(only_configured: bool = False) -> list[ModelEntry]:
    """Моделі хмарних провайдерів із каталогу :mod:`cloud_agents`."""
    entries: list[ModelEntry] = []
    for provider in cloud_agents.PROVIDERS:
        if provider.key == "custom" and not provider.models:
            continue
        for name in provider.models:
            entries.append(ModelEntry(
                name=name,
                provider_key=provider.key,
                provider_label=provider.label,
                kind=CLOUD,
                online=False,
                context=int(provider.context or 0),
                params=params_from_name(name),
                caps=("🔨",) if provider.supports_tools else (),
                note=provider.note,
            ))
    return entries


# ─────────────────────────────────────────────────────────────────────────────
# Перевірка доступності
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProbeOutcome:
    """Результат перевірки одного провайдера."""

    key: str
    ok: bool
    detail: str = ""
    models: list[str] = field(default_factory=list)
    base_url: str = ""


class ProviderProbe:
    """Перевірка провайдерів у фоні (без tkinter).

    Використання::

        probe = ProviderProbe([("ollama", url, "local")])
        probe.start()
        ...  # у циклі подій
        for outcome in probe.drain():
            ...
    """

    def __init__(self, targets: Iterable[tuple[str, str, str]], *, timeout: int = 4) -> None:
        self.targets = [tuple(item) for item in targets]
        self.timeout = timeout
        self.results: "queue.Queue[ProbeOutcome]" = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._cancelled = False

    def start(self) -> None:
        for key, url, kind in self.targets:
            if not (url or "").strip():
                continue
            thread = threading.Thread(target=self._probe, args=(key, url, kind), daemon=True)
            thread.start()
            self._threads.append(thread)

    def _probe(self, key: str, url: str, kind: str) -> None:
        if self._cancelled:
            return
        # Вбудований рушій не має адреси в мережі: ``native://blackchpok``.
        # ``LLMClient.list_models()`` для нього повертає СПИСОК ФАЙЛІВ на
        # диску навіть тоді, коли модель не завантажена. Тому питаємо рушій
        # напряму — щоб «онлайн» означало «модель у пам'яті й відповість».
        try:
            from . import runtime

            if runtime.embedded_url(url):
                loaded = runtime.embedded_model_loaded()
                detail = ("модель у пам'яті" if loaded
                          else "рушій готовий, модель не завантажена")
                self.results.put(ProbeOutcome(key, loaded, detail, [], url))
                return
        except Exception:  # noqa: BLE001 - проба не має падати
            pass
        api_key = "local" if kind == LOCAL else ""
        try:
            client = LLMClient(url, api_key=api_key or "local", timeout=self.timeout)
            models = client.list_models()
        except LLMError as exc:
            self.results.put(ProbeOutcome(key, False, str(exc)[:160], [], url))
            return
        except Exception as exc:  # noqa: BLE001 - мережа може кинути будь-що
            self.results.put(ProbeOutcome(key, False, f"{type(exc).__name__}: {exc}"[:160],
                                          [], url))
            return
        self.results.put(ProbeOutcome(key, True, f"моделей: {len(models)}", models, url))

    def drain(self) -> list[ProbeOutcome]:
        found: list[ProbeOutcome] = []
        while True:
            try:
                found.append(self.results.get_nowait())
            except queue.Empty:
                break
        return found

    @property
    def running(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def cancel(self) -> None:
        self._cancelled = True


def probe_targets(settings: Any) -> list[tuple[str, str, str]]:
    """Що саме перевіряти: усі локальні пресети + поточний сервер."""
    targets: list[tuple[str, str, str]] = [
        (provider.key, provider.base_url, LOCAL)
        for provider in LOCAL_PROVIDERS if provider.base_url
    ]
    current = (getattr(settings.llm, "base_url", "") or "").strip()
    if current and all(current != url for _key, url, _kind in targets):
        targets.append(("current", current, _kind_of(current)))
    return targets


def _kind_of(base_url: str) -> str:
    # ``native://blackchpok`` — вбудований рушій, тобто найлокальніше з
    # можливого. Без цієї гілки адреса без «api.» вважалась локальною лише
    # випадково, а з префіксом ``blackchpok://`` — ще й невідомо чим.
    if (base_url or "").strip().lower().startswith(
            ("native://", "inproc://", "blackchpok://")):
        return LOCAL
    return CLOUD if (base_url.startswith("https://") or "api." in base_url) else LOCAL


# ─────────────────────────────────────────────────────────────────────────────
# Зведений список і вибір
# ─────────────────────────────────────────────────────────────────────────────

def detect_provider_key(base_url: str) -> tuple[str, str]:
    """(ключ, вид) провайдера за адресою. Невідоме → («custom…», local/cloud)."""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return ("", LOCAL)
    for provider in LOCAL_PROVIDERS:
        if provider.base_url and url.startswith(provider.base_url.rstrip("/")):
            return (provider.key, LOCAL)
    cloud = cloud_agents.detect(url)
    if cloud is not None:
        return (cloud.key, CLOUD)
    for label, known in KNOWN_ENDPOINTS:
        if url.startswith(known.rstrip("/")):
            return (label.lower().replace(" ", "-"), LOCAL)
    return ("custom", _kind_of(url))


def current_entry(settings: Any) -> ModelEntry:
    """Запис для моделі, яка зараз вибрана."""
    model = (getattr(settings.llm, "model", "") or "").strip()
    base_url = (getattr(settings.llm, "base_url", "") or "").strip()
    key, kind = detect_provider_key(base_url)
    # ── Вбудований рушій: модель може бути не названа, але вона Є ─────────
    # Для ``native://blackchpok`` порожня назва — нормальний стан: рушій
    # бере локальний GGUF сам. Раніше такий стан показувався як «модель не
    # вибрана» з ``online=False``, хоч шапка поруч показувала справжню назву
    # й модель відповідала — інтерфейс суперечив сам собі (перевірено
    # ``tools/check_model_labels.py``).
    if not model:
        try:
            from . import runtime

            if runtime.embedded_url(base_url):
                from .native import bridge

                engine = bridge.runtime().engine
                loaded = str(getattr(engine, "model_path", "") or "")
                if not loaded:
                    # Модель ще не в пам'яті — беремо ту, яку рушій ПІДНІМЕ:
                    # спершу збережений вибір, інакше найбільший локальний
                    # GGUF (так само робить автозапуск).
                    loaded = str(getattr(settings.engine, "native_model", "") or "")
                # ``Path(...).stem`` тут НЕ годиться: назва моделі містить
                # крапки («qwen2.5-coder-14b»), і stem обрізав би її до
                # «qwen2». Відрізаємо лише розширення.
                name = Path(loaded).name if loaded else ""
                for suffix in (".gguf", ".GGUF"):
                    if name.endswith(suffix):
                        name = name[: -len(suffix)]
                        break
                if not name:
                    entries = bridge.runtime().manager.local_models()
                    if entries:
                        name = max(entries, key=lambda item: item.size_gb).key
                if name:
                    model = name
        except Exception:  # noqa: BLE001 - підпис не має падати
            LOG.debug("Назву моделі рушія не прочитано", exc_info=True)
    if kind == CLOUD:
        provider = cloud_agents.get(key)
        label = provider.label if provider else "Хмара"
        context = int(provider.context or 0) if provider else 0
    else:
        provider_local = _LOCAL_BY_KEY.get(key)
        label = provider_local.label if provider_local else "Локальний сервер"
        context = int(getattr(settings.engine, "ctx_size", 0) or 0)
    return ModelEntry(
        name=model or "модель не вибрана",
        provider_key=key,
        provider_label=label,
        kind=kind,
        online=bool(model),
        context=context,
        params=params_from_name(model),
        quant=quant_from_name(model),
    )


def mark_resident(entries: list[ModelEntry], loaded_path: str) -> None:
    """Позначити моделі, які зараз у пам'яті рушія, як доступні.

    Файл на диску сам по собі не «онлайн». Але якщо саме він завантажений
    і щойно відповів, червона крапка в списку бреше.
    """
    loaded = str(loaded_path or "").strip()
    if not loaded:
        return
    try:
        from .native import bridge
    except Exception:  # noqa: BLE001
        return
    for entry in entries:
        token = entry.path or entry.name
        if token and bridge.same_model(loaded, token):
            entry.online = True


def catalogue(settings: Any, *, probed: Optional[dict[str, ProbeOutcome]] = None) -> list[ModelEntry]:
    """Повний список моделей: поточний сервер, локальні файли, хмара.

    ``probed`` — результати перевірки (ключ провайдера → результат), щоб
    показати справжній статус і реальні назви моделей із сервера.

    **Одна модель — один рядок.** Раніше дедуплікація порівнювала пару
    (назва, провайдер), і той самий файл, побачений через LM Studio, через
    llama.cpp і на диску, давав ТРИ рядки — саме це видно на скріншоті
    користувача. Тепер ключ — сама модель: файл розпізнається за шляхом
    або за нормалізованою назвою, і лишається НАЙКОРИСНІШИЙ запис.
    """
    probed = probed or {}
    current = current_entry(settings)
    entries: list[ModelEntry] = [current]

    # 1. Моделі, які сервер реально повідомив (найдостовірніше джерело).
    for key, outcome in probed.items():
        if not outcome.ok:
            continue
        kind = _kind_of(outcome.base_url)
        provider_label = (_LOCAL_BY_KEY.get(key).label if key in _LOCAL_BY_KEY
                          else (cloud_agents.label_for(key) if kind == CLOUD else "Сервер"))
        for name in outcome.models:
            entries.append(ModelEntry(
                name=name,
                provider_key=key,
                provider_label=provider_label,
                kind=kind,
                online=True,
                context=current.context if name == current.name else 0,
                params=params_from_name(name),
                quant=quant_from_name(name),
            ))

    # 2. Локальні файли на диску (можна запустити через хаб).
    entries.extend(local_models())

    # 3. Хмарний каталог — лише як додаткова можливість.
    entries.extend(cloud_models())

    # Проєктори зору (mmproj) — не моделі: вони не запускаються самі й
    # лише плутали список. Сховаємо їх з-поміж вибору моделей; приховане
    # лишається в :func:`projector_files` для тих, кому потрібен шлях.
    unique = _dedupe(entries)
    return [entry for entry in unique if not is_projector(entry)]


def projector_files() -> list[Path]:
    """Файли-проєктори зору на диску (потрібні при запуску VL-моделей)."""
    try:
        return [path for path in model_hub.local_models()
                if any(marker in path.name.lower() for marker in _PROJECTOR_MARKERS)]
    except Exception:                            # noqa: BLE001
        return []


#: Скільки запис моделі «корисніший» за інший (більше — краще).
#:
#: Порядок: підключений і живий сервер → є шлях до локального файлу →
#: поточна вибрана модель → решта. Саме за цим правилом обирається
#: переможець, коли одна модель прийшла з кількох джерел.
def _usefulness(entry: ModelEntry) -> tuple[int, int, int, int]:
    return (
        1 if entry.online else 0,
        1 if entry.path else 0,
        1 if entry.caps else 0,
        len(entry.note or ""),
    )


#: Ознаки файлів-проєкторів зору: це не окремі моделі, а доповнення.
_PROJECTOR_MARKERS: tuple[str, ...] = ("mmproj", "projector", "vision-projector")


def is_projector(entry: ModelEntry) -> bool:
    """Чи це файл проєктора (mmproj), а не самостійна модель."""
    low = (entry.name or "").lower()
    return any(marker in low for marker in _PROJECTOR_MARKERS)


def model_key(entry: ModelEntry) -> str:
    """Ключ ідентичності моделі — для дедуплікації.

    Ключ завжди будується з НАЗВИ, а не зі шляху. Причина: сервер
    повідомляє лише ім'я моделі (``qwen2.5-coder-14b-instruct-q4_k_m``),
    а дисковий запис має ще й шлях — і якщо порівнювати шляхи, та сама
    модель проходила як дві різні. Саме це й давало три рядки на скріншоті.

    Нормалізація прибирає роздільники й регістр: ``Qwen2.5-Coder-7B`` і
    ``qwen2.5_coder_7b`` — це та сама модель, записана по-різному.
    """
    name = (entry.name or "").strip().lower()
    # Розширення файлу не робить модель іншою.
    name = re.sub(r"\.gguf$", "", name)
    # Шлях у назві (якщо сервер віддав повний) — лишаємо тільки ім'я файлу.
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\s_\-.]+", "-", name).strip("-")
    return "name:" + name


def _dedupe(entries: list[ModelEntry]) -> list[ModelEntry]:
    """Лишити по одному запису на модель, найкорисніший.

    Порядок збереження — як у вхідному списку: користувач звик, що
    локальні моделі йдуть перед хмарними, і перемішування лише заплутує.
    """
    best: dict[str, ModelEntry] = {}
    order: list[str] = []
    for entry in entries:
        if not (entry.name or "").strip():
            continue
        key = model_key(entry)
        existing = best.get(key)
        if existing is None:
            best[key] = entry
            order.append(key)
            continue
        # Зливаємо корисні поля: «поточна» модель може не мати шляху, а
        # дисковий запис — знати статус сервера. Без цього переможець
        # втрачав би інформацію, яку мав інший запис.
        winner = entry if _usefulness(entry) > _usefulness(existing) else existing
        loser = existing if winner is entry else entry
        if not winner.path and loser.path:
            winner.path = loser.path
        if not winner.online and loser.online:
            winner.online = True
        if not winner.context and loser.context:
            winner.context = loser.context
        if not winner.caps and loser.caps:
            winner.caps = loser.caps
        if not winner.params and loser.params:
            winner.params = loser.params
        if not winner.quant and loser.quant:
            winner.quant = loser.quant
        best[key] = winner
    return [best[key] for key in order]


def group(entries: Iterable[ModelEntry]) -> list[tuple[str, list[ModelEntry]]]:
    """Згрупувати за «Локальні / Хмарні» для селектора."""
    local = [entry for entry in entries if entry.is_local]
    cloud = [entry for entry in entries if not entry.is_local]
    groups: list[tuple[str, list[ModelEntry]]] = []
    if local:
        groups.append(("ЛОКАЛЬНІ", local))
    if cloud:
        groups.append(("ХМАРНІ · необов'язково", cloud))
    return groups


def _embedded_url() -> str:
    """Псевдо-адреса вбудованого рушія (``native://blackchpok``).

    Винесено в окрему функцію, бо ``providers`` навмисно не тягне
    ``native`` на імпорті модуля: рушій підвантажує ``llama.dll``.
    """
    try:
        from .native import bridge

        return bridge.EMBEDDED_URL
    except Exception:  # noqa: BLE001 - без рушія лишається рядок-константа
        return "native://blackchpok"


def apply_choice(settings: Any, entry: ModelEntry) -> None:
    """Зробити запис активною моделлю (правильно оновлює налаштування).

    ── ЧОМУ ЛОКАЛЬНИЙ ФАЙЛ НЕ ПЕРЕМИКАЄ НА HTTP ──────────────────────────
    Кожен запис локальної моделі має ``provider_key = "llamacpp"``, а його
    ``base_url`` — ``http://127.0.0.1:8080/v1``. Тому вибір GGUF-файлу
    переписував адресу на HTTP, хоча модель вантажиться у ВБУДОВАНИЙ рушій
    (``native://blackchpok``) у цьому ж процесі.

    ЗАМІРЯНО на справжніх налаштуваннях користувача (``ide.log``):

        18:29:38  Стан сервера скинуто: перемикання на Ministral-3-14B…
        18:30:30  Адреса http://127.0.0.1:8080/v1 не слухає → пошук порту
        18:30:34  LLM недоступна: …[WinError 10061] target machine actively
                  refused it

    Тобто модель обрана, рушій увімкнений — а кожен запит ішов у мережу,
    де ніхто не слухає: на екрані це «● МОДЕЛЬ ОФЛАЙН» і «локальна модель
    недоступна», хоч файл лежить на диску й рушій готовий.

    Тепер вибір локального файлу при ВВІМКНЕНОМУ вбудованому рушії лишає
    адресу ``native://blackchpok`` і записує вибраний шлях у рушій — тобто
    модель справді стає активною, без жодних HTTP-серверів.
    """
    settings.llm.model = entry.name
    if entry.is_local:
        provider = _LOCAL_BY_KEY.get(entry.provider_key)
        want_native = bool(getattr(getattr(settings, "engine", None), "native", False))
        # Локальний ФАЙЛ (``path`` заповнений) — це те, що вантажить рушій.
        # Записи, які прийшли від живого HTTP-сервера (LM Studio, Ollama),
        # шляху не мають: їхню адресу міняти не можна.
        if want_native and entry.path:
            settings.llm.base_url = _embedded_url()
            settings.llm.api_key = "local"
            settings.llm.auto_detect = False
            settings.engine.model_path = str(entry.path)
            settings.engine.native_model = entry.name
        else:
            if provider is not None and provider.base_url:
                settings.llm.base_url = provider.base_url
            settings.llm.api_key = "local"
        if entry.context:
            settings.engine.ctx_size = int(entry.context)
    else:
        provider = cloud_agents.get(entry.provider_key)
        if provider is not None and provider.base_url:
            settings.cloud.provider = provider.key
            settings.cloud.base_url = provider.base_url
            settings.cloud.model = entry.name
            if entry.context:
                pass
        settings.llm.base_url = cloud_agents.normalise_base_url(
            provider.base_url if provider else settings.cloud.base_url)
        settings.llm.api_key = settings.cloud.api_key or settings.llm.api_key
    settings.save()


def editable_providers() -> list[tuple[str, str, str, str]]:
    """(ключ, підпис, адреса, вид) для всіх провайдерів — для налаштувань."""
    rows: list[tuple[str, str, str, str]] = []
    for provider in LOCAL_PROVIDERS:
        rows.append((provider.key, provider.label, provider.base_url, LOCAL))
    for provider in cloud_agents.PROVIDERS:
        rows.append((provider.key, provider.label, provider.base_url, CLOUD))
    return rows


__all__ = [
    "CLOUD", "LOCAL", "LocalProvider", "LOCAL_PROVIDERS", "ModelEntry", "ProviderProbe",
    "ProbeOutcome", "apply_choice", "catalogue", "cloud_models", "current_entry",
    "detect_provider_key", "editable_providers", "group", "local_models",
    "params_from_name", "probe_targets", "quant_from_name",
]
