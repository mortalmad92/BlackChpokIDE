"""Панель «Сайт»: запуск проєкту, вбудований браузер і живе оновлення.

Поєднує два шари: ``web_server`` (піднімає сервер під стек проєкту) і
``browser_panel`` (показує сторінку у вікні). Після збереження файлу сторінка
перезавантажується сама.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from . import browser_panel, hmr, theme, web_server, widgets

LOG = __import__("logging").getLogger("blackchpok.preview")


class PreviewPanel(tk.Frame):
    """Керування сайтом проєкту й показ його у вікні."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        root_provider: Callable[[], Optional[Path]],
        *,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.root_provider = root_provider
        self.on_status = on_status
        self.server: Optional[web_server.DevServer] = None
        self.recipe: Optional[web_server.Recipe] = None
        self._watcher_after: Optional[str] = None
        self._snapshot: dict[str, float] = {}
        self._build()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        bar = tk.Frame(self, bg=theme.BG_ALT)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(3, weight=1)

        self.run_btn = tk.Label(bar, text="▶ Запустити сайт", bg=theme.ACCENT,
                                fg=theme.ON_ACCENT, font=("Segoe UI", 9, "bold"),
                                padx=12, pady=4, cursor="hand2")
        self.run_btn.grid(row=0, column=0, padx=(10, 6), pady=6)
        self.run_btn.bind("<Button-1>", lambda _e: self.toggle_server())
        widgets.Tip(self.run_btn, "Запустити сервер проєкту (Ctrl+Alt+P)")

        self.stop_btn = widgets.IconButton(bar, "■", self.stop_all, bg=theme.BG_ALT,
                                           fg=theme.ERROR, font=("Segoe UI", 9),
                                           tooltip="Зупинити сервер і браузер")
        self.stop_btn.grid(row=0, column=1, padx=(0, 6))

        widgets.IconButton(bar, "⟳", self.reload_page, bg=theme.BG_ALT, fg=theme.FG_DIM,
                           font=("Segoe UI", 9), tooltip="Перезавантажити сторінку").grid(
            row=0, column=2, padx=(0, 8))

        self.kind_label = tk.Label(bar, text="Стек не визначено", bg=theme.BG_ALT,
                                   fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w")
        self.kind_label.grid(row=0, column=3, sticky="ew")

        self.url_label = tk.Label(bar, text="—", bg=theme.BG_ALT, fg=theme.FG_DIM,
                                  font=("Segoe UI", 8), cursor="hand2")
        self.url_label.grid(row=0, column=4, padx=(6, 10))
        # Клік по адресі копіює її, а не відкриває системний браузер: раніше
        # випадковий клік по підпису викидав користувача з IDE в Chrome.
        # Системний браузер лишається доступним лише через явну кнопку «↗».
        self.url_label.bind("<Button-1>", lambda _e: self._copy_address())
        widgets.Tip(self.url_label, "Клік — скопіювати адресу")

        # рядок підказки/помилки
        self.info_label = tk.Label(self, text="", bg=theme.BG, fg=theme.FG_FAINT,
                                   font=("Segoe UI", 8), anchor="w", justify="left")
        self.info_label.grid(row=1, column=0, sticky="ew", padx=(10, 8), pady=(0, 4))

        self.view = browser_panel.BrowserView(self, self.fonts, on_status=self.set_status)
        self.view.grid(row=2, column=0, sticky="nsew")

    # ── сервіс ─────────────────────────────────────────────────────────────
    def _copy_address(self) -> None:
        """Скопіювати адресу сторінки в буфер обміну."""
        url = self.view.url or ""
        if not url:
            self.set_status("Сторінка ще не відкрита.")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(url)
        except tk.TclError:
            return
        self.set_status(f"Адресу скопійовано: {url}")

    def set_status(self, text: str) -> None:
        try:
            self.info_label.configure(text=text)
        except tk.TclError:
            pass
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:  # noqa: BLE001
                pass

    def detect(self) -> Optional[web_server.Recipe]:
        """Визначити стек проєкту (без запуску)."""
        root = self.root_provider() if self.root_provider else None
        if not root:
            self.set_status("Спочатку відкрий теку проєкту.")
            return None
        recipe = web_server.detect(Path(root))
        self.recipe = recipe
        text = f"{recipe.icon} {recipe.label}"
        if recipe.reason:
            text += f" · {recipe.reason}"
        try:
            self.kind_label.configure(text=text)
            self.kind_label.configure(
                fg=theme.SUCCESS if recipe.ok else theme.WARN)
        except tk.TclError:
            pass
        if not recipe.ok:
            # Пояснюємо не лише «не вдалось», а й що зробити: інакше
            # панель виглядає як заглушка, з якою нічого не поробиш.
            self.set_status(
                "У цьому проєкті не знайдено сайту (немає index.html, "
                "Flask/FastAPI, package.json). Панель стане активною, "
                "щойно агент створить сайт — або впиши адресу в полі вище, "
                "щоб відкрити будь-який сайт.")
        return recipe

    # ── запуск ─────────────────────────────────────────────────────────────
    def toggle_server(self) -> None:
        if self.server is not None and self.server.running:
            self.stop_all()
            return
        self.start_server()

    def start_server(self) -> None:
        recipe = self.detect()
        if recipe is None or not recipe.ok:
            return

        missing = web_server.missing_tools(recipe)
        if missing:
            self.set_status(f"Бракує програми: {', '.join(missing)} — встанови й спробуй знову.")
            return

        if self.server is not None:
            self.server.stop()
        recipe.port = web_server.free_port(recipe.port or 8000)
        server = web_server.DevServer(recipe, on_output=lambda line: None)
        ok, detail = server.start()
        if not ok:
            self.set_status(f"✗ {detail}")
            return
        self.server = server
        self.set_status(detail)
        # Стежимо за файлами з першої секунди, не чекаючи відповіді порту.
        self._start_watcher()
        try:
            self.run_btn.configure(text="◼ Зупинити сайт", bg=theme.BG_ACTIVE)
        except tk.TclError:
            pass

        # Потік лише кладе результат у чергу: tkinter не можна чіпати з нього.
        self._ready_queue: "queue.Queue[tuple[bool, str]]" = queue.Queue()

        def wait() -> None:
            ready, note = web_server.wait_for_port(server.port, timeout=45)
            self._ready_queue.put((ready, note))

        threading.Thread(target=wait, daemon=True).start()
        self._poll_ready()

    def _poll_ready(self) -> None:
        """Чекати готовності сервера в головному потоці."""
        ready_queue = getattr(self, "_ready_queue", None)
        if ready_queue is None:
            return
        try:
            ready, note = ready_queue.get_nowait()
        except queue.Empty:
            try:
                (self.after(200, self._poll_ready) if self._timer_alive() else None)
            except tk.TclError:
                pass
            return
        self._after_ready(ready, note)


    def _timer_alive(self) -> bool:
        """Чи можна ще планувати ``after`` (віджет існує й вікно живе)."""
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001 - віджет уже знищено
            return False

    def _after_ready(self, ready: bool, note: str) -> None:
        if not ready:
            self.set_status(f"✗ {note}")
            if self.server is not None:
                tail = self.server.tail(12)
                if tail.strip():
                    self.set_status(f"✗ {note}\n{tail[-300:]}")
            return
        url = self.server.url if self.server is not None else ""
        try:
            self.url_label.configure(text=url)
        except tk.TclError:
            pass
        self.set_status(note)
        self.view.set_address(url)
        self.view.show(url)
        self._start_watcher()

    def stop_all(self) -> None:
        """Зупинити сервер і браузер."""
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.view.stop()
        self._stop_watcher()
        try:
            self.run_btn.configure(text="▶ Запустити сайт", bg=theme.ACCENT)
            self.url_label.configure(text="—")
        except tk.TclError:
            pass
        self.set_status("Зупинено.")

    def reload_page(self) -> None:
        self.view.reload()

    def open_url(self, url: str) -> bool:
        """Показати у вбудованому браузері будь-яку адресу."""
        target = browser_panel.normalise_url(url)
        if not target:
            return False
        try:
            self.url_label.configure(text=target)
        except tk.TclError:
            pass
        self.set_status(f"Відкриваю: {target}")
        return self.view.open_url(target)

    # ── живе оновлення ─────────────────────────────────────────────────────
    def _start_watcher(self) -> None:
        self._stop_watcher()
        self._snapshot = self._take_snapshot()
        self._tick()

    def _stop_watcher(self) -> None:
        if self._watcher_after is not None:
            try:
                self.after_cancel(self._watcher_after)
            except (tk.TclError, ValueError):
                pass
            self._watcher_after = None

    def _take_snapshot(self) -> dict[str, float]:
        """Час зміни файлів проєкту (лише ті, що впливають на сайт)."""
        root = self.root_provider() if self.root_provider else None
        if not root:
            return {}
        snapshot: dict[str, float] = {}
        skip = {"node_modules", ".venv", "__pycache__", ".git", "dist", "build",
                ".mypy_cache", ".pytest_cache"}
        try:
            for path in Path(root).rglob("*"):
                if not path.is_file():
                    continue
                if any(part in skip for part in path.parts):
                    continue
                if path.suffix.lower() not in {".html", ".htm", ".css", ".js", ".jsx",
                                               ".ts", ".tsx", ".json", ".svg", ".py",
                                               ".php", ".rb", ".go", ".rs", ".vue",
                                               ".svelte", ".md"}:
                    continue
                try:
                    snapshot[str(path)] = path.stat().st_mtime
                except OSError:
                    continue
                if len(snapshot) > 3000:
                    break
        except OSError:
            return {}
        return snapshot

    def _tick(self) -> None:
        """Перевірити зміни файлів і оновити сторінку РОЗУМНО.

        Раніше на будь-яку зміну йшло повне перезавантаження сторінки: на
        правку CSS сторінка перемальовувалась цілком, губилися прокрутка,
        введений текст і стан JS. Тепер кожен файл обробляється своїм
        способом (див. :mod:`hmr`): CSS — підміна без перезавантаження,
        HTML — точкове оновлення, JS — перезапуск зі збереженням стану.
        """
        if self.server is None or not self.server.running:
            self._watcher_after = None
            return
        current = self._take_snapshot()
        changed = [path for path, stamp in current.items()
                   if self._snapshot.get(path) != stamp]
        if changed:
            self._snapshot = current
            names = ", ".join(Path(path).name for path in changed[:3])
            if len(changed) > 3:
                names += f" і ще {len(changed) - 3}"
            self._refresh_changed(changed, names)
        try:
            self._watcher_after = (self.after(700, self._tick) if self._timer_alive() else None)
        except tk.TclError:
            self._watcher_after = None

    def _hmr_session(self):
        """Жива CDP-сесія для HMR (``None``, якщо сторінки ще немає).

        Провайдер підключає вікно — панель не має знати, звідки береться
        сесія, і не має створювати її сама.
        """
        provider = getattr(self, "hmr_session_provider", None)
        if provider is None:
            return None
        try:
            session = provider()
        except Exception:  # noqa: BLE001 - HMR не має ламати прев'ю
            LOG.debug("CDP-сесія для HMR недоступна", exc_info=True)
            return None
        if session is None or not getattr(session, "connected", False):
            return None
        return session

    def _refresh_changed(self, changed: list[str], names: str) -> None:
        """Оновити сторінку з урахуванням типів змінених файлів."""
        session = self._hmr_session()
        if session is None:
            # CDP недоступний — звичайне перезавантаження, як раніше.
            self.set_status(f"Змінено: {names} — оновлюю сторінку…")
            self.view.schedule_reload()
            return
        results = []
        # Стилі — найчастіше; обробляємо їх ПЕРШИМИ (дешево й без reload).
        ordered = sorted(changed, key=lambda path: (
            0 if Path(path).suffix.lower() in hmr.STYLE_SUFFIXES else 1, path))
        for path in ordered[:6]:
            try:
                result = hmr.update_for_file(session, Path(path))
            except Exception:  # noqa: BLE001 - HMR не має ламати прев'ю
                LOG.debug("HMR для %s впав", path, exc_info=True)
                continue
            results.append(result)
            if result.reloaded:
                break          # сторінку вже перезавантажено — далі не треба
        if not results:
            self.set_status(f"Змінено: {names}")
            return
        primary = next((item for item in results if item.mode == "css"), None)
        primary = primary or next((item for item in results if item.ok), results[-1])
        self.set_status(f"Змінено: {names} — {hmr.describe(primary)}")

    def on_file_saved(self) -> None:
        """Викликається після збереження файлу в IDE — оновити розумно."""
        if self.server is None or not self.server.running:
            return
        path = None
        try:
            provider = getattr(self, "saved_path_provider", None)
            path = provider() if provider is not None else None
        except Exception:  # noqa: BLE001 - провайдер не має ламати прев'ю
            path = None
        session = self._hmr_session()
        if path is not None and session is not None:
            try:
                result = hmr.update_for_file(session, Path(path))
            except Exception:  # noqa: BLE001
                result = None
            if result is not None and result.ok:
                self.set_status(f"Збережено {Path(path).name} — {hmr.describe(result)}")
                return
        self.view.schedule_reload(200)

    def on_close(self) -> None:
        self.stop_all()


__all__ = ["PreviewPanel"]
