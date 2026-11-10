"""Наглядач за MCP-серверами: здоров'я, зависання, відновлення.

Навіщо. ``McpManager.start_all`` вважає сервер робочим, якщо ``initialize``
не кинув виняток. Це слабка перевірка:

* сервер може стартувати з мертвими змінними середовища (як у цьому проєкті,
  де ``.cursor/mcp.json`` посилався на LM Studio на порту 1235) — статус
  «працює», а виклики не працюють;
* дочірній процес може померти через годину — ніхто цього не помітить;
* завислий сервер (не відповідає на запит) виглядає як живий.

Наглядач періодично перевіряє КОЖЕН сервер і:

1. виявляє смерть процесу;
2. виявляє зависання (перевірка відповіді з таймаутом);
3. перезапускає з обмеженою кількістю спроб;
4. повторно реєструє інструменти;
5. веде діагностику (остання помилка, кількість спроб, час перевірки).

ГОЛОВНЕ ПРАВИЛО: **успішно працюючий сервер не чіпаємо**. Перезапуск лише
тоді, коли є доведена проблема.

Модуль не залежить від tkinter.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

LOG = logging.getLogger("blackchpok.mcpwatch")

#: Скільки разів перезапускати сервер (з наростаючою паузою).
MAX_RESTARTS = 3
#: Паузи між спробами перезапуску (секунди).
BACKOFF = (2.0, 5.0, 15.0)
#: Через скільки секунд після перезапуску вважати сервер «під підозрою».
SUSPECT_SECONDS = 30.0

HEALTHY = "працює"
DEAD = "процес завершився"
HUNG = "не відповідає"
DISABLED = "вимкнено"
RECOVERED = "відновлено"
FAILED = "не вдалось відновити"


@dataclass
class Health:
    """Стан одного MCP-сервера."""

    name: str
    status: str = HEALTHY
    ok: bool = True
    restarts: int = 0
    checked_at: float = 0.0
    last_error: str = ""
    tools: int = 0
    detail: str = ""

    def summary(self) -> str:
        parts = [f"{self.name}: {self.status}"]
        if self.tools:
            parts.append(f"інструментів {self.tools}")
        if self.restarts:
            parts.append(f"перезапусків {self.restarts}")
        if self.last_error:
            parts.append(self.last_error[:90])
        return " · ".join(parts)


@dataclass
class WatchReport:
    """Підсумок одного циклу перевірки."""

    checked: int = 0
    healthy: int = 0
    restarted: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def text(self) -> str:
        if not self.checked:
            return "MCP: серверів немає"
        parts = [f"MCP: {self.healthy} з {self.checked} працює"]
        if self.restarted:
            parts.append(f"перезапущено: {', '.join(self.restarted)}")
        if self.failed:
            parts.append(f"не вдалось: {', '.join(self.failed)}")
        return " · ".join(parts)


class Watcher:
    """Періодична перевірка й відновлення MCP-серверів."""

    def __init__(self, manager: Any, *, interval: float = 45.0,
                 on_status: Optional[Callable[[str], None]] = None) -> None:
        self.manager = manager
        self.interval = max(5.0, float(interval))
        self.on_status = on_status
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._health: dict[str, Health] = {}
        self._configs: dict[str, Any] = {}
        #: Коли сервер перезапускали — щоб не смикати його повторно.
        self._restarted_at: dict[str, float] = {}

    # ── реєстрація конфігів ────────────────────────────────────────────────

    def remember(self, configs: list[Any]) -> None:
        """Запам'ятати конфіги, щоб уміти перезапустити сервер."""
        with self._lock:
            for config in configs or []:
                name = str(getattr(config, "name", "") or "").strip()
                if name:
                    self._configs[name] = config

    # ── життєвий цикл ──────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="mcp-watchdog")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        # Перша перевірка — не одразу: сервери щойно стартували.
        if self._stop.wait(min(20.0, self.interval)):
            return
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:  # noqa: BLE001 - наглядач не має падати
                LOG.exception("Цикл MCP-watchdog впав")
            if self._stop.wait(self.interval):
                break

    # ── перевірка ──────────────────────────────────────────────────────────

    def check_once(self) -> WatchReport:
        """Перевірити всі сервери один раз (синхронно)."""
        report = WatchReport()
        try:
            servers = dict(getattr(self.manager, "servers", {}) or {})
        except Exception:  # noqa: BLE001
            servers = {}
        for name, client in servers.items():
            report.checked += 1
            health = self._inspect(name, client)
            # ЛІЧИЛЬНИК СПРОБ має переживати перевірки. ``_inspect`` створює
            # новий об'єкт, тому без перенесення ``restarts`` втрачався б і
            # наглядач перезапускав сервер НЕСКІНЧЕННО. Саме так і було:
            # значення завжди лишалось 1.
            with self._lock:
                previous = self._health.get(name)
            if previous is not None and health.restarts == 0:
                health.restarts = int(previous.restarts)
            with self._lock:
                self._health[name] = health
            if health.ok:
                report.healthy += 1
                continue
            if health.status == DISABLED:
                report.skipped.append(name)
                continue
            # Хворий сервер — пробуємо відновити (з обмеженням).
            if self._recover(name, client, health):
                report.restarted.append(name)
            else:
                report.failed.append(name)
        if report.restarted or report.failed:
            self._notify(report.text())
        return report

    def _inspect(self, name: str, client: Any) -> Health:
        """Оцінити стан сервера."""
        health = Health(name=name, checked_at=time.time())
        try:
            config = getattr(client, "config", None)
            if config is not None and not getattr(config, "enabled", True):
                health.status = DISABLED
                health.ok = True
                return health
            # 1. Чи живий процес.
            if not getattr(client, "running", False):
                health.status = DEAD
                health.ok = False
                health.last_error = "процес завершився"
                return health
            # 2. Чи відповідає (зависання ловимо таймаутом).
            tools = client.list_tools() if hasattr(client, "list_tools") else None
            if tools is None:
                tools = getattr(client, "tools", []) or []
            health.tools = len(tools)
            # 3. Схеми мають бути валідні.
            broken = 0
            for tool in tools:
                if not isinstance(tool, dict) or not tool.get("name"):
                    broken += 1
                elif not isinstance(tool.get("inputSchema"), dict):
                    broken += 1
            if broken:
                health.detail = f"невалідних схем: {broken}"
                LOG.info("MCP «%s»: %s", name, health.detail)
            if not tools:
                # Нуль інструментів — це проблема, і її треба ПОКАЗАТИ: без
                # інструментів сервер для агента марний (перевірено
                # tests/test_mcp_watch.py). Але перезапускати його щосекунди
                # теж не можна: цикл падінь обмежує вікно підозри
                # (:data:`SUSPECT_SECONDS`) і лічильник спроб.
                health.status = "без інструментів"
                health.ok = False
                health.last_error = "сервер не повернув жодного інструмента"
                return health
            health.status = HEALTHY
            health.ok = True
            return health
        except Exception as exc:  # noqa: BLE001 - будь-який збій = хворий
            health.ok = False
            health.status = HUNG
            health.last_error = str(exc)[:160]
            return health

    def _recover(self, name: str, client: Any, health: Health) -> bool:
        """Спробувати підняти сервер. ``True`` — якщо вдалось."""
        with self._lock:
            config = self._configs.get(name)
            health.restarts = int(health.restarts)
            restarted_at = float(self._restarted_at.get(name, 0.0) or 0.0)
        if config is None:
            health.last_error = health.last_error or "немає конфігу для перезапуску"
            return False
        # ── Вікно підозри ──────────────────────────────────────────────────
        # Якщо сервер упав ЗНОВУ невдовзі після перезапуску, це цикл
        # падінь: миттєвий повтор лише крутить його по колу. ``BACKOFF``
        # задає паузу, але раніше вона ніколи не спрацьовувала, бо
        # ``_restarted_at`` лише записувався й ніде не читався.
        if restarted_at:
            since = time.time() - restarted_at
            if since < SUSPECT_SECONDS:
                health.status = FAILED
                health.last_error = (
                    f"впав через {since:.0f} с після перезапуску — "
                    f"цикл падінь, повторю пізніше")
                LOG.info("MCP «%s»: %s", name, health.last_error)
                return False
        if health.restarts >= MAX_RESTARTS:
            health.status = FAILED
            health.last_error = (f"вичерпано спроби ({MAX_RESTARTS}): "
                                 f"{health.last_error[:100]}")
            LOG.warning("MCP «%s»: %s", name, health.last_error)
            return False
        pause = BACKOFF[min(health.restarts, len(BACKOFF) - 1)]
        LOG.info("MCP «%s»: відновлення через %.0f с (спроба %s)",
                 name, pause, health.restarts + 1)
        self._notify(f"MCP «{name}» не відповідає — перезапускаю…")
        time.sleep(min(pause, 5.0))     # не блокуємо наглядач надовго
        try:
            new_client = self.manager.add(config, start=True)
        except Exception as exc:  # noqa: BLE001
            health.last_error = str(exc)[:160]
            health.restarts += 1
            return False
        try:
            tools = new_client.list_tools() if hasattr(new_client, "list_tools") else []
        except Exception as exc:  # noqa: BLE001
            health.last_error = str(exc)[:160]
            health.restarts += 1
            return False
        health.restarts += 1
        if not tools:
            health.last_error = "після перезапуску немає інструментів"
            health.status = FAILED
            return False
        health.ok = True
        health.status = RECOVERED
        health.tools = len(tools)
        health.last_error = ""
        self._restarted_at[name] = time.time()
        LOG.info("MCP «%s» відновлено: інструментів %s", name, len(tools))
        self._notify(f"MCP «{name}» відновлено ({len(tools)} інструментів)")
        return True

    # ── діагностика ────────────────────────────────────────────────────────

    def report(self) -> list[Health]:
        with self._lock:
            return list(self._health.values())

    def diagnostics(self) -> str:
        """Багаторядковий звіт для панелі «Діагностика»."""
        items = self.report()
        if not items:
            return "MCP: серверів не підключено, перевірок ще не було."
        lines = ["Стан MCP-серверів:"]
        for health in items:
            mark = "✓" if health.ok else "✗"
            lines.append(f" {mark} {health.summary()}")
            if health.detail:
                lines.append(f"     {health.detail}")
        return "\n".join(lines)

    def _notify(self, text: str) -> None:
        if not self.on_status:
            return
        try:
            self.on_status(text)
        except Exception:  # noqa: BLE001 - інтерфейс не має ламати наглядач
            LOG.debug("on_status наглядача впав", exc_info=True)


__all__ = [
    "BACKOFF",
    "DEAD",
    "DISABLED",
    "FAILED",
    "HEALTHY",
    "HUNG",
    "Health",
    "MAX_RESTARTS",
    "RECOVERED",
    "SUSPECT_SECONDS",
    "WatchReport",
    "Watcher",
]
