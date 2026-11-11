"""Єдине джерело правди про стан inference-сервера.

Навіщо окремий модуль. Раніше стан сервера збирали НЕЗАЛЕЖНО в кількох
місцях, і кожне місце відповідало по-своєму:

* вікно IDE показувало модель із налаштувань (``settings.llm.model``);
* агент питав ``/props`` і брав ``n_ctx`` звідти;
* ``_server_alive`` робив ``/v1/models`` із таймаутом 4 с;
* ``_probe_context_async`` робив ``/props`` у фоні;
* ``model_keeper`` дивився на ``server.running``.

Результат — розбіжності, які користувач бачив як «модель не працює»:

* інтерфейс показує одну модель, а запити йдуть до іншої;
* у налаштуваннях 32768, сервер реально дає 16384, і контекст переповнюється;
* «online» світиться, хоч сервер уже помер;
* «offline», хоч сервер піднявся у фоні.

Цей модуль збирає ВСІ факти в один знімок (:class:`ServerState`) і кешує
його на короткий час. Усі, кому потрібен стан, питають ОДНЕ місце — і
отримують узгоджену відповідь.

Ключові принципи:

1. **Мережа — ніколи в потоці інтерфейсу.** ``snapshot()`` повертає те, що
   вже відомо; оновлення запускається окремо (:meth:`ServerStateCache.refresh`).
2. **Чесність про джерело.** ``context_source`` каже, ЗВІДКИ взято число:
   сервер, метадані моделі, налаштування або запас.
3. **Найменше підтверджене значення.** Якщо джерела суперечать, беремо
   менше — інакше запит переповнить вікно й сервер обірве з'єднання.
4. **Інвалідація за подією.** Зміна моделі, перезапуск, зміна порту
   скидають кеш — старі числа після цього не використовуються.

Модуль не тягне tkinter. Мережеві виклики — лише в ``_probe``.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

LOG = logging.getLogger("blackchpok.server_state")

__all__ = [
    "STALE_SECONDS",
    "ServerState",
    "ServerStateCache",
    "probe_server",
    "state_cache",
]

#: Скільки секунд знімок вважається свіжим.
STALE_SECONDS = 5.0

#: Таймаут одного мережевого запиту (секунди). Короткий навмисно: це
#: перевірка стану, а не робота з моделлю.
PROBE_TIMEOUT = 2.5


@dataclass
class ServerState:
    """Узгоджений знімок стану inference-сервера.

    Усі поля — ФАКТИ на момент ``at``. Поле ``source`` описує, звідки взято
    кожне число, щоб інтерфейс не видавав здогад за істину.
    """

    #: Чи відповідає endpoint (``/health`` або ``/v1/models``).
    reachable: bool = False
    #: Чи процес сервера живий (за даними runtime, а не мережі).
    running: bool = False
    #: Реальна модель, яку повідомив сервер (``/v1/models`` або ``/props``).
    model_loaded: str = ""
    #: Модель, вибрана в налаштуваннях.
    model_configured: str = ""
    #: Адреса, до якої йдуть запити.
    base_url: str = ""
    #: Порт із базової адреси.
    port: int = 0
    #: Реальне вікно контексту (найменше підтверджене).
    context: int = 0
    #: Звідки взято ``context``: сервер / метадані / налаштування / запас.
    context_source: str = ""
    #: Чи модель з налаштувань збігається з тим, що реально завантажено.
    model_matches: bool = True
    #: Сервер зараз перезавантажується.
    reloading: bool = False
    #: Остання помилка (порожньо, якщо все гаразд).
    error: str = ""
    #: Час знімка (``time.time()``).
    at: float = field(default_factory=time.time)
    #: Чи це оцінка (сервер не підтвердив), а не виміряний факт.
    estimated: bool = False

    @property
    def online(self) -> bool:
        """Чи можна зараз надсилати запит моделі."""
        return bool(self.reachable and not self.error)

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.at)

    def note(self) -> str:
        """Один рядок для людини: що насправді відбувається."""
        if self.reloading:
            return "сервер перезавантажується…"
        if not self.reachable:
            if self.error:
                return f"сервер недоступний: {self.error}"
            return "сервер не відповідає"
        if self.model_matches:
            head = f"працює · {self.model_loaded or 'модель невідома'}"
        else:
            head = (f"працює, але завантажено "
                    f"«{self.model_loaded or '—'}» замість "
                    f"«{self.model_configured or '—'}»")
        if self.context:
            head += f" · контекст {self.context:,}".replace(",", " ")
            if self.context_source:
                head += f" ({self.context_source})"
        return head

    def to_dict(self) -> dict[str, Any]:
        return {
            "reachable": self.reachable,
            "running": self.running,
            "model_loaded": self.model_loaded,
            "model_configured": self.model_configured,
            "base_url": self.base_url,
            "port": self.port,
            "context": self.context,
            "context_source": self.context_source,
            "model_matches": self.model_matches,
            "reloading": self.reloading,
            "error": self.error,
            "age": round(self.age, 2),
            "estimated": self.estimated,
        }


def _port_of(base_url: str) -> int:
    """Порт із адреси (0, якщо не вдалось)."""
    import re

    match = re.search(r":(\d{2,5})(?:/|$)", str(base_url or ""))
    return int(match.group(1)) if match else 0


def _origin(base_url: str) -> str:
    """Корінь сервера без ``/v1`` — для ``/props`` і ``/health``."""
    root = str(base_url or "").rstrip("/")
    return root[:-3] if root.endswith("/v1") else root


def _get_json(url: str, *, api_key: str = "", timeout: float = PROBE_TIMEOUT
              ) -> tuple[bool, Any]:
    """GET JSON. Повертає ``(успіх, дані)``; не кидає винятків."""
    headers = {"User-Agent": "BlackChpok-IDE"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # 401/403 означають «сервер Є, ключ інший» — для стану це успіх.
        return (int(exc.code) in (401, 403), None)
    except (urllib.error.URLError, OSError, ValueError):
        return (False, None)
    try:
        return (True, json.loads(body))
    except ValueError:
        return (True, None)


def probe_server(base_url: str, *, api_key: str = "",
                 timeout: float = PROBE_TIMEOUT) -> ServerState:
    """Спитати сервер напряму: чи живий, яка модель, яке вікно.

    Це ЄДИНЕ місце, яке робить ці запити. Раніше їх робили чотири різні
    функції з різними таймаутами й різними правилами — і показували різні
    результати для того самого сервера.
    """
    state = ServerState(base_url=str(base_url or ""),
                        port=_port_of(base_url), at=time.time())
    if not state.base_url:
        state.error = "адреса сервера не задана"
        return state

    # ── Вбудований рушій: це не HTTP-сервер ──────────────────────────────
    # ``native://blackchpok`` живе в ЦЬОМУ процесі: у нього немає ні порту,
    # ні ``/health``, ні ``/props``. Раніше функція все одно робила HTTP-
    # запити, діставала «немає відповіді» й показувала робочий рушій як
    # офлайн (саме через це ``tools/check_live_lazy.py`` мовчки
    # пропускав усі перевірки). Тепер питаємо сам рушій.
    from . import runtime

    if runtime.embedded_url(state.base_url):
        try:
            from .native import bridge

            engine = bridge.runtime().engine
            state.reachable = True
            state.running = True
            loaded = str(getattr(engine, "model_path", "") or "")
            state.model_loaded = Path(loaded).stem if loaded else ""
            # Вікно беремо з САМОГО рушія. ``engine.context`` — об'єкт
            # контексту, тому питаємо його ``n_ctx``; ``context_actual``
            # лишаємо як запасне джерело (воно є в інших версіях).
            context = 0
            holder = getattr(engine, "context", None)
            for attribute in ("n_ctx", "context_actual", "n_ctx_train"):
                try:
                    value = getattr(holder, attribute, None)
                    if value is None:
                        value = getattr(engine, attribute, None)
                except Exception:  # noqa: BLE001 - читання не має падати
                    value = None
                try:
                    context = int(value or 0)
                except (TypeError, ValueError):
                    context = 0
                if context > 0:
                    break
            state.context = context
            state.context_source = "вбудований рушій"
            # Вікно взяте з рушія — це виміряний факт, не оцінка.
            state.estimated = context <= 0
            if not getattr(engine, "loaded", False):
                state.error = "рушій готовий, модель не завантажена"
        except Exception as exc:  # noqa: BLE001 - стан не має падати
            state.error = f"вбудований рушій недоступний: {exc}"
        return state

    origin = _origin(state.base_url)
    # 1. Живий? ``/health`` відкритий навіть із ``--api-key``.
    healthy, _payload = _get_json(f"{origin}/health", timeout=timeout)
    if not healthy:
        # 2. Запасна перевірка: ``/v1/models`` (з ключем і без).
        listed, payload = _get_json(f"{state.base_url}/models",
                                    api_key=api_key, timeout=timeout)
        if not listed:
            listed, payload = _get_json(f"{state.base_url}/models",
                                        timeout=timeout)
        if not listed:
            state.error = "немає відповіді"
            return state
    state.reachable = True

    # 3. Яка модель РЕАЛЬНО завантажена.
    _ok, models = _get_json(f"{state.base_url}/models", api_key=api_key,
                            timeout=timeout)
    if isinstance(models, dict):
        data = models.get("data")
        if isinstance(data, list) and data:
            first = data[0] if isinstance(data[0], dict) else {}
            state.model_loaded = str(
                first.get("id") or first.get("name") or "").strip()

    # 4. Вікно контексту з ``/props``. Це єдине джерело, яке знає про поділ
    #    на слоти: ``--ctx-size 32768`` при двох слотах дає ``n_ctx = 16384``.
    _ok, props = _get_json(f"{origin}/props", api_key=api_key, timeout=timeout)
    if isinstance(props, dict):
        block = props.get("default_generation_settings") or {}
        value = 0
        if isinstance(block, dict):
            try:
                value = int(block.get("n_ctx") or 0)
            except (TypeError, ValueError):
                value = 0
        if value <= 0:
            try:
                value = int(props.get("n_ctx") or 0)
            except (TypeError, ValueError):
                value = 0
        if value > 0:
            state.context = value
            state.context_source = "сервер /props"
        # Модель із ``/props`` — теж факт, іноді єдина інформація.
        if not state.model_loaded and isinstance(block, dict):
            state.model_loaded = str(block.get("model") or "").strip()
    return state


class ServerStateCache:
    """Кеш знімка стану з фоновим оновленням.

    Головне правило: ``snapshot()`` НІКОЛИ не ходить у мережу. Він повертає
    останній відомий стан, а оновлення запускає у фоні. Інакше перший кадр
    інтерфейсу застигав на таймауті з'єднання (заміряно: 2.4 с).
    """

    def __init__(
        self,
        *,
        settings_provider: Optional[Callable[[], Any]] = None,
        server_provider: Optional[Callable[[], Any]] = None,
        on_update: Optional[Callable[[ServerState], None]] = None,
        stale_seconds: float = STALE_SECONDS,
    ) -> None:
        self.settings_provider = settings_provider
        self.server_provider = server_provider
        self.on_update = on_update
        self.stale_seconds = max(0.5, float(stale_seconds))
        self._state = ServerState()
        self._lock = threading.Lock()
        self._probing = False
        #: Лічильник поколінь: результат застарілого опитування відкидається.
        self._generation = 0

    # ── читання ─────────────────────────────────────────────────────────────
    def snapshot(self) -> ServerState:
        """Останній відомий стан (без мережі)."""
        with self._lock:
            return self._state

    @property
    def stale(self) -> bool:
        return self.snapshot().age > self.stale_seconds

    def configured_model(self) -> str:
        """Модель із налаштувань (може не збігатись із завантаженою)."""
        settings = self._settings()
        try:
            return str(getattr(settings.llm, "model", "") or "").strip()
        except AttributeError:
            return ""

    # ── запис ───────────────────────────────────────────────────────────────
    def set_local(self, *, running: bool, reloading: bool = False,
                  error: str = "") -> ServerState:
        """Оновити те, що відомо БЕЗ мережі (стан процесу, помилки)."""
        with self._lock:
            self._state.running = bool(running)
            self._state.reloading = bool(reloading)
            if error:
                self._state.error = str(error)
            state = self._state
        self._notify(state)
        return state

    def invalidate(self, *, reason: str = "") -> None:
        """Скинути кеш: наступний опитування дасть свіжі числа.

        Викликається після зміни моделі, перезапуску сервера, зміни порту,
        аварійного відновлення й зміни налаштувань рушія. Без цього
        інтерфейс показував старе вікно контексту вже після перемикання.
        """
        with self._lock:
            self._generation += 1
            window = self._state.context
            self._state = ServerState(
                base_url=self._state.base_url,
                port=self._state.port,
                model_configured=self._state.model_configured,
                running=self._state.running,
                reloading=self._state.reloading,
            )
            if window:
                # Число зберігаємо з явною позначкою «застаріло»: краще
                # показати приблизне, ніж порожнечу, доки йде опитування.
                self._state.context = window
                self._state.context_source = "застаріле (оновлюється)"
        LOG.info("Стан сервера скинуто: %s", reason or "зміна конфігурації")

    def refresh(self, *, background: bool = True,
                timeout: float = PROBE_TIMEOUT) -> ServerState:
        """Опитати сервер. У фоні (типово) або синхронно."""
        if background:
            self._spawn_probe(timeout=timeout)
            return self.snapshot()
        return self._probe(timeout=timeout)

    # ── внутрішнє ───────────────────────────────────────────────────────────
    def _settings(self) -> Any:
        if self.settings_provider is None:
            return None
        try:
            return self.settings_provider()
        except Exception:  # noqa: BLE001 - стан не має ламати вікно
            LOG.debug("Налаштування недоступні", exc_info=True)
            return None

    def _server(self) -> Any:
        if self.server_provider is None:
            return None
        try:
            return self.server_provider()
        except Exception:  # noqa: BLE001
            LOG.debug("Провайдер сервера впав", exc_info=True)
            return None

    def _spawn_probe(self, *, timeout: float) -> None:
        with self._lock:
            if self._probing:
                return
            self._probing = True
            generation = self._generation

        def work() -> None:
            try:
                state = self._probe(timeout=timeout, generation=generation)
            except Exception:  # noqa: BLE001 - фон не має падати
                LOG.debug("Фонове опитування стану впало", exc_info=True)
                state = None
            finally:
                with self._lock:
                    self._probing = False
            if state is not None:
                self._notify(state)

        threading.Thread(target=work, daemon=True,
                         name="server-state-probe").start()

    def _probe(self, *, timeout: float,
               generation: int = -1) -> Optional[ServerState]:
        settings = self._settings()
        base_url = ""
        api_key = ""
        configured = ""
        if settings is not None:
            try:
                base_url = str(settings.llm.base_url or "")
                api_key = str(settings.llm.api_key or "")
                configured = str(settings.llm.model or "").strip()
            except AttributeError:
                base_url = ""
        state = probe_server(base_url, api_key=api_key, timeout=timeout)
        state.model_configured = configured
        server = self._server()
        if server is not None:
            try:
                state.running = bool(getattr(server, "running", False))
            except Exception:  # noqa: BLE001 - стан не має падати
                state.running = False
        if state.reachable and configured and state.model_loaded:
            state.model_matches = _models_match(configured, state.model_loaded)
        if not state.reachable:
            state.model_matches = False
        with self._lock:
            if generation >= 0 and generation != self._generation:
                # Поки йшло опитування, конфігурацію змінили: результат
                # описує СТАРИЙ стан, і показувати його не можна.
                LOG.info("Результат опитування відкинуто: конфігурація змінилась")
                return None
            # Контекст, який сервер НЕ підтвердив, лишаємо лише як оцінку.
            if not state.context:
                previous = self._state
                if previous.context and previous.context_source not in (
                        "", "застаріле (оновлюється)"):
                    state.context = previous.context
                    state.context_source = previous.context_source
                    state.estimated = True
            self._state = state
        return state

    def _notify(self, state: ServerState) -> None:
        if self.on_update is None:
            return
        try:
            self.on_update(state)
        except Exception:  # noqa: BLE001 - підписник не має ламати стан
            LOG.debug("on_update стану сервера впав", exc_info=True)


def _models_match(configured: str, loaded: str) -> bool:
    """Чи це та сама модель (різні позначення того самого файлу).

    Сервер віддає ``qwen2.5-coder-14b-instruct-q4_k_m``, налаштування
    зберігають ``qwen2.5-coder-14b-instruct-q4_k_m`` або шлях до файлу.
    Порівнюємо нормалізовано: без шляху, розширення, регістру й
    роздільників.
    """
    def norm(text: str) -> str:
        name = Path(str(text or "")).stem.lower()
        for char in ("-", "_", ".", " "):
            name = name.replace(char, "")
        return name

    left, right = norm(configured), norm(loaded)
    if not left or not right:
        return True
    return left == right or left in right or right in left


#: Глобальний кеш для тих, кому нічого не передали явно (тести, скрипти).
_GLOBAL: Optional[ServerStateCache] = None
_GLOBAL_LOCK = threading.Lock()


def state_cache(**kwargs: Any) -> ServerStateCache:
    """Глобальний кеш стану (створюється один раз)."""
    global _GLOBAL
    with _GLOBAL_LOCK:
        if _GLOBAL is None:
            _GLOBAL = ServerStateCache(**kwargs)
        return _GLOBAL
