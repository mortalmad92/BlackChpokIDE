"""Супервізор MCP-серверів: health-check, ретрай із бекофом, watchdog.

``docs/MCP_SUPERVISOR.md`` §5 перелічує, чого не було (дослівно):

    | health check після `initialize` | немає: не перевіряється `list_tools()
      і валідність схем |
    | ретрай старту з бекофом | немає: одна спроба через 400 мс |
    | watchdog (виявлення смерті процесу) | немає |
    | restart policy | немає |
    | graceful shutdown із очікуванням | частково: `stop_all` у потоці без
      очікування |
    | прогрів інструмента end-to-end | немає |

Цей модуль закриває перші чотири пункти. Він **не переписує** транспорт
(``McpClient``), а працює поверх нього: бере фабрику клієнта й керує
життєвим циклом.

Ключове рішення — §3 того ж документа: статус «працює» означав лише
«процес піднявся й відповів на handshake». Тому ``health_check()`` не
вірить статусу, а питає сервер про список інструментів і перевіряє, що
схеми придатні. Сервер може відповісти на ``initialize`` і при цьому мати
несправний LLM-бекенд — саме ця пастка й описана в документі.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

LOG = logging.getLogger("blackchpok.mcp_supervisor")

#: Затримки перед повторним стартом (секунди). Далі — останнє значення.
BACKOFF: tuple[float, ...] = (1.0, 2.0, 4.0)

#: Скільки чекати відповіді на ``tools/list`` під час health-check.
HEALTH_TIMEOUT = 10.0

#: Період перевірки «чи живий процес» у watchdog.
WATCH_INTERVAL = 5.0

#: Скільки чекати коректної зупинки перед тим, як вважати її проваленою.
STOP_TIMEOUT = 5.0


@dataclass
class HealthReport:
    """Результат health-check одного сервера."""

    name: str
    ok: bool = False
    reason: str = ""
    tools: int = 0
    #: Скільки схем придатні до використання (мають ім'я й object-параметри).
    valid_schemas: int = 0
    checked_at: float = field(default_factory=time.time)

    def text(self) -> str:
        if self.ok:
            return (f"{self.name}: ✓ {self.tools} інструментів "
                    f"(схем придатних {self.valid_schemas})")
        return f"{self.name}: ✗ {self.reason}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "ok": self.ok, "reason": self.reason,
            "tools": self.tools, "valid_schemas": self.valid_schemas,
            "checked_at": self.checked_at,
        }


def schema_is_usable(schema: Any) -> bool:
    """Чи придатна схема інструмента до передачі моделі.

    Перевіряємо рівно те, через що модель ламається: немає імені, немає
    ``inputSchema``, або ``inputSchema`` не є об'єктом. Раніше такі схеми
    потрапляли в каталог, і модель отримувала інструмент, який неможливо
    викликати.
    """
    if not isinstance(schema, dict):
        return False
    name = schema.get("name")
    if not isinstance(name, str) or not name.strip():
        return False
    params = schema.get("inputSchema")
    if params is None:
        params = schema.get("parameters")
    if not isinstance(params, dict):
        return False
    kind = params.get("type")
    # ``type`` може бути відсутнім (деякі сервери так роблять) — тоді
    # вважаємо схему придатною, якщо є словник властивостей.
    if kind is None:
        return "properties" in params or params == {}
    return kind == "object"


class MpcSupervisor:
    """Керує життєвим циклом MCP-серверів поверх ``McpClient``."""

    def __init__(self, factory: Callable[[Any], Any]) -> None:
        #: ``factory(config) -> client``; зазвичай це ``McpClient``.
        self._factory = factory
        self._clients: dict[str, Any] = {}
        self._configs: dict[str, Any] = {}
        self._backoff_index: dict[str, int] = {}
        self._reports: dict[str, HealthReport] = {}
        self._lock = threading.RLock()
        self._watchdog: Optional[threading.Thread] = None
        self._stop_watchdog = threading.Event()
        self._restarting: set[str] = set()
        self.on_status: Optional[Callable[[str], None]] = None

    # ── допоміжне ────────────────────────────────────────────────────────
    def _status(self, text: str) -> None:
        LOG.info("%s", text)
        if self.on_status is not None:
            try:
                self.on_status(text)
            except Exception:  # noqa: BLE001 - звіт не має ламати роботу
                LOG.debug("on_status впав", exc_info=True)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._clients)

    def client(self, name: str) -> Any:
        with self._lock:
            return self._clients.get(name)

    def reports(self) -> dict[str, HealthReport]:
        with self._lock:
            return dict(self._reports)

    # ── health-check ─────────────────────────────────────────────────────
    def health_check(self, name: str) -> HealthReport:
        """Справжня перевірка сервера, а не довіра до статусу.

        Питаємо ``tools/list`` і перевіряємо схеми. Це ловить випадок із
        ``MCP_SUPERVISOR.md`` §3: сервер відповів на ``initialize``, але
        його інструменти несправні.
        """
        with self._lock:
            client = self._clients.get(name)
        report = HealthReport(name=name)
        if client is None:
            report.reason = "клієнта не створено"
            with self._lock:
                self._reports[name] = report
            return report
        try:
            running = bool(getattr(client, "running", False))
        except Exception:  # noqa: BLE001
            running = False
        if not running:
            report.reason = "процес не працює"
            with self._lock:
                self._reports[name] = report
            return report
        try:
            schemas = client.list_tools() or []
        except Exception as exc:  # noqa: BLE001 - причина йде у звіт
            report.reason = f"tools/list не відповів: {exc}"
            with self._lock:
                self._reports[name] = report
            return report

        usable = [s for s in schemas if schema_is_usable(s)]
        report.tools = len(schemas)
        report.valid_schemas = len(usable)
        if not schemas:
            report.reason = "сервер не віддав жодного інструмента"
        elif not usable:
            report.reason = (f"{len(schemas)} схем, жодна не придатна "
                             f"(немає імені або inputSchema)")
        else:
            report.ok = True
            if len(usable) < len(schemas):
                report.reason = (f"придатних {len(usable)} з {len(schemas)} — "
                                 f"решту відкинуто")
        with self._lock:
            self._reports[name] = report
        return report

    def health_check_all(self) -> dict[str, HealthReport]:
        return {name: self.health_check(name) for name in self.names()}

    # ── старт із бекофом ─────────────────────────────────────────────────
    def start(self, name: str, config: Any, *, attempts: int = 3,
              sleep: Optional[Callable[[float], None]] = None) -> HealthReport:
        """Підняти сервер із ретраями 1 с / 2 с / 4 с.

        Після кожного підйому робимо health-check. Якщо сервер піднявся, але
        health-check провалився — це теж привід повторити (саме так ловиться
        «handshake є, інструменти зламані»).
        """
        wait = sleep or time.sleep
        last = HealthReport(name=name, reason="спроб не було")
        for attempt in range(max(1, attempts)):
            with self._lock:
                previous = self._clients.get(name)
                self._configs[name] = config
            if previous is not None:
                try:
                    previous.stop()
                except Exception:  # noqa: BLE001
                    LOG.debug("попередній клієнт не зупинився", exc_info=True)
            client = self._factory(config)
            with self._lock:
                self._clients[name] = client
            try:
                client.start()
                client.initialize()
            except Exception as exc:  # noqa: BLE001 - причина у звіт
                last = HealthReport(name=name, reason=f"старт: {exc}")
                LOG.warning("MCP «%s», спроба %s: %s", name, attempt + 1, exc)
                try:
                    client.stop()
                except Exception:  # noqa: BLE001
                    LOG.debug("зупинка після збою впала", exc_info=True)
            else:
                last = self.health_check(name)
                if last.ok:
                    with self._lock:
                        self._backoff_index[name] = 0
                    self._status(f"MCP «{name}»: {last.text()}")
                    return last
                LOG.warning("MCP «%s», спроба %s: health-check провалено (%s)",
                            name, attempt + 1, last.reason)
                try:
                    client.stop()
                except Exception:  # noqa: BLE001
                    LOG.debug("зупинка після невдалого health-check", exc_info=True)

            if attempt + 1 < attempts:
                delay = BACKOFF[min(attempt, len(BACKOFF) - 1)]
                self._status(
                    f"MCP «{name}» не піднявся — повтор через {delay:.0f} с")
                wait(delay)

        with self._lock:
            self._reports[name] = last
        self._status(f"MCP «{name}»: не вдалось підняти ({last.reason})")
        return last

    def start_all(self, configs: list[Any], *, attempts: int = 3,
                  sleep: Optional[Callable[[float], None]] = None
                  ) -> dict[str, HealthReport]:
        results: dict[str, HealthReport] = {}
        for config in configs or []:
            name = str(getattr(config, "name", "") or "mcp-server")
            enabled = bool(getattr(config, "enabled", True))
            if not enabled:
                results[name] = HealthReport(name=name, reason="вимкнено")
                with self._lock:
                    self._reports[name] = results[name]
                continue
            results[name] = self.start(name, config, attempts=attempts, sleep=sleep)
        return results

    # ── watchdog ─────────────────────────────────────────────────────────
    def start_watchdog(self, interval: float = WATCH_INTERVAL) -> None:
        """Стежити за процесами; померлий — підняти з бекофом."""
        with self._lock:
            if self._watchdog is not None and self._watchdog.is_alive():
                return
            self._stop_watchdog.clear()

            def _watch() -> None:
                while not self._stop_watchdog.wait(interval):
                    for name in self.names():
                        with self._lock:
                            client = self._clients.get(name)
                        if client is None:
                            continue
                        try:
                            alive = bool(getattr(client, "running", False))
                        except Exception:  # noqa: BLE001
                            alive = False
                        if alive:
                            continue
                        self._handle_death(name)

            self._watchdog = threading.Thread(
                target=_watch, name="mcp-watchdog", daemon=True)
            self._watchdog.start()

    def _handle_death(self, name: str) -> None:
        """Процес помер — перезапустити з бекофом (не нескінченно)."""
        with self._lock:
            if name in self._restarting:
                return
            self._restarting.add(name)
            config = self._configs.get(name)
            index = self._backoff_index.get(name, 0)
        try:
            self._status(f"MCP «{name}»: процес помер — перезапускаю")
            if config is None:
                LOG.warning("MCP «%s»: конфіг невідомий, перезапуск неможливий", name)
                return
            delay = BACKOFF[min(index, len(BACKOFF) - 1)]
            with self._lock:
                self._backoff_index[name] = index + 1
            self._stop_watchdog.wait(delay)
            if self._stop_watchdog.is_set():
                return
            report = self.start(name, config, attempts=1, sleep=lambda _s: None)
            if report.ok:
                with self._lock:
                    self._backoff_index[name] = 0
        finally:
            with self._lock:
                self._restarting.discard(name)

    def stop_watchdog(self) -> None:
        self._stop_watchdog.set()
        with self._lock:
            thread = self._watchdog
            self._watchdog = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    # ── зупинка ──────────────────────────────────────────────────────────
    def stop_all(self, timeout: float = STOP_TIMEOUT) -> dict[str, bool]:
        """Зупинити всі сервери й ДОЧЕКАТИСЬ (раніше не чекали).

        Повертає ``{ім'я: чи зупинився}``. Сервер, що не відповів на
        ``stop()`` за ``timeout``, вважається незупиненим — краще сказати
        це чесно, ніж показати «зупинено» й лишити процес живим.
        """
        self.stop_watchdog()
        with self._lock:
            clients = dict(self._clients)
            self._clients.clear()
            self._reports.clear()
        results: dict[str, bool] = {}
        for name, client in clients.items():
            stopped = _stop_with_timeout(client, timeout)
            results[name] = stopped
            if not stopped:
                LOG.warning("MCP «%s» не зупинився за %.0f с", name, timeout)
        return results


def _stop_with_timeout(client: Any, timeout: float) -> bool:
    """Викликати ``stop()`` і дочекатися, не блокуючи назавжди."""
    done = threading.Event()
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            client.stop()
            box["ok"] = True
        except Exception as exc:  # noqa: BLE001 - причина у результат
            box["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_run, name="mcp-stop", daemon=True)
    thread.start()
    thread.join(timeout=max(0.1, timeout))
    return bool(done.is_set() and box.get("ok"))


__all__ = [
    "BACKOFF",
    "HEALTH_TIMEOUT",
    "HealthReport",
    "MpcSupervisor",
    "STOP_TIMEOUT",
    "WATCH_INTERVAL",
    "schema_is_usable",
]
