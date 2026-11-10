"""Права колонка «Live Preview»: застосунок проєкту поруч із чатом.

Обгортає перевірений :class:`preview_panel.PreviewPanel` (сервер + вбудований
браузер + hot-reload watcher) у сучасну Cursor-подібну оболонку:

    ┌────────────────────────────┐
    │ ● Live Preview        ⟳ ■  │   ← статус + дії
    │ http://127.0.0.1:8000      │   ← адреса
    ├────────────────────────────┤
    │                            │
    │   вбудований браузер       │
    │                            │
    └────────────────────────────┘

Кнопки: «Запустити» (▶/◼), «Оновити» (⟳), «Зовнішньо» (↗), «Зупинити» (■).
Усі дії виконуються тим самим ``AppController``, яким користується агент,
тож кнопка і інструменти агента ніколи не сперечаються за стан.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import app_control, browser_panel, theme, widgets
from .preview_panel import PreviewPanel

LOG = __import__("logging").getLogger("blackchpok.livepreview")


class LivePreviewPanel(tk.Frame):
    """Живий прев'ю застосунку для правої колонки."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        root_provider: Callable[[], Optional[object]],
        *,
        on_status: Optional[Callable[[str], None]] = None,
        app: Optional[app_control.AppController] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self._root_provider = root_provider
        self.app = app
        self._timer_after: Optional[str] = None
        self.columnconfigure(0, weight=1)
        # Сітка: 0 — заголовок, 1 — рядок адреси, 2 — статус, 3 — сам браузер.
        # Раніше weight стояв на рядку 2 (це статус-підпис), і браузер із
        # рядком адреси з'їжджав униз панелі, лишаючи понад собою порожнечу.
        self.rowconfigure(3, weight=1)
        #: DOM-інспектор і консоль сторінки (див. ``_build_inspector``).
        self.inspector: Optional[tk.Frame] = None
        self.console_box: Optional[tk.Frame] = None
        self._element: dict = {}
        self._inspect_mode = False
        #: Колбеки, які підключає вікно: передати елемент агенту, прочитати
        #: точку сторінки, виконати дію (знімок/аудит/адаптивність).
        self.on_send_element: Optional[Callable[[dict, str], None]] = None
        self.on_inspect_at: Optional[Callable[[int, int], dict]] = None
        self.action_provider: Optional[Callable[[str], str]] = None
        self._build()
        self._tick_state()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        # ── заголовок
        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(10, 4))
        head.columnconfigure(1, weight=1)

        self.state_dot = tk.Label(head, text="●", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                  font=("Segoe UI", 9))
        self.state_dot.grid(row=0, column=0, padx=(0, 6))
        tk.Label(head, text="Live Preview", bg=theme.BG_ALT, fg=theme.FG,
                 font=("Segoe UI", 9, "bold"), anchor="w").grid(row=0, column=1, sticky="w")

        actions = tk.Frame(head, bg=theme.BG_ALT)
        actions.grid(row=0, column=2, sticky="e")
        self.run_btn = widgets.IconButton(actions, "▶", self._toggle, bg=theme.BG_ALT,
                                          fg=theme.STATUS_WORKING, font=("Segoe UI", 10),
                                          tooltip="Запустити / зупинити застосунок")
        self.run_btn.pack(side="left")
        self.reload_btn = widgets.IconButton(actions, "⟳", self._reload, bg=theme.BG_ALT,
                                             fg=theme.FG_DIM, font=("Segoe UI", 10),
                                             tooltip="Перезавантажити сторінку")
        self.reload_btn.pack(side="left")
        self.open_btn = widgets.IconButton(actions, "↗", self._open_external, bg=theme.BG_ALT,
                                           fg=theme.FG_DIM, font=("Segoe UI", 10),
                                           tooltip="Відкрити в системному браузері")
        self.open_btn.pack(side="left")
        # ── сторінка як дані: інспектор, консоль, знімок, перевірка
        self.inspect_btn = widgets.IconButton(
            actions, "◎", self.toggle_inspect, bg=theme.BG_ALT,
            fg=theme.FG_DIM, font=("Segoe UI", 10),
            tooltip="Інспектор елементів: натисни на елемент сайту й передай агенту")
        self.inspect_btn.pack(side="left")
        self.console_btn = widgets.IconButton(
            actions, "⚠", self.collect_console, bg=theme.BG_ALT,
            fg=theme.FG_DIM, font=("Segoe UI", 10),
            tooltip="Консоль сторінки: помилки JS, ресурсів і HTTP")
        self.console_btn.pack(side="left")
        self.shot_btn = widgets.IconButton(
            actions, "⊠", lambda: self.run_action("screenshot"), bg=theme.BG_ALT,
            fg=theme.FG_DIM, font=("Segoe UI", 10),
            tooltip="Знімок самої сторінки (не екрана) у PNG")
        self.shot_btn.pack(side="left")

        # ── адресний рядок
        url_host = tk.Frame(self, bg=theme.BG_CARD)
        url_host.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        url_host.columnconfigure(0, weight=1)
        self.url_label = tk.Label(url_host, text="—", bg=theme.BG_CARD, fg=theme.FG_DIM,
                                  font=("Segoe UI", 8), anchor="w")
        self.url_label.grid(row=0, column=0, sticky="ew", ipady=5, padx=(10, 6))

        # ── статус-стрічка
        self.status_label = tk.Label(self, text="Стек не визначено", bg=theme.BG_ALT,
                                     fg=theme.FG_FAINT, font=("Segoe UI", 8), anchor="w",
                                     justify="left")
        self.status_label.grid(row=2, column=0, sticky="ew", padx=(14, 10), pady=(0, 2))

        # ── сам прев'ю (сервер + вбудований браузер + hot reload)
        self.inner = PreviewPanel(
            self, self.fonts,
            self._root_provider,
            on_status=self._on_inner_status,
        )
        self.inner.grid(row=3, column=0, sticky="nsew", padx=(8, 8), pady=(2, 8))
        self._inner_status = ""
        # ── DOM-інспектор і консоль сторінки (через CDP) ───────────────────
        # Це те, чого бракувало: побачити, ЯКИЙ елемент вибрано, і що
        # каже консоль. Обидва блоки будуються після браузера й за
        # замовчуванням приховані, щоб не з'їдати місце.
        self._build_inspector()
        self._build_console()
        # Внутрішній тулбар ховаємо: усі дії вже є в шапці колонки, а стан
        # показує наш status_label. Віджети лишаються живими (grid_remove),
        # тож логіка PreviewPanel працює без змін.
        for widget in (getattr(self.inner, "run_btn", None),
                       getattr(self.inner, "stop_btn", None),
                       getattr(self.inner, "reload_btn", None),
                       getattr(self.inner, "live_btn", None),
                       getattr(self.inner, "open_btn", None),
                       getattr(self.inner, "kind_label", None),
                       getattr(self.inner, "url_label", None),
                       getattr(self.inner, "info_label", None)):
            if widget is None:
                continue
            try:
                widget.grid_remove()
            except tk.TclError:
                pass
        # Рядок адреси внутрішнього браузера ховаємо: тут адреса вже є
        # окремим полем, і дублювати її в тулбарі не потрібно.
        for name in ("address", "back_btn", "go_btn"):
            widget = getattr(self.inner.view, name, None)
            if widget is None:
                continue
            try:
                widget.grid_remove()
            except tk.TclError:
                pass

    # ── дії ────────────────────────────────────────────────────────────────
    def _controller(self) -> Optional[app_control.AppController]:
        controller = self.app
        if controller is None:
            controller = getattr(self.inner, "app", None)
        return controller

    def _toggle(self) -> None:
        controller = self._controller()
        if controller is None:
            self.inner.toggle_server()
            self._tick_state()
            return
        if controller.running:
            self._note(controller.stop())
        else:
            ok, detail = controller.start()
            self._note(detail if ok else f"✗ {detail}")
            if ok:
                self.inner.server = controller.server
                self.inner.recipe = controller.recipe
                url = controller.url
                if url:
                    try:
                        self.inner.url_label.configure(text=url)
                    except tk.TclError:
                        pass
                self.inner.view.show(url)
                self.inner._start_watcher()
        self._tick_state()

    def _reload(self) -> None:
        self.inner.reload_page()

    def _open_external(self) -> None:
        self.inner.view.open_external()

    def _on_inner_status(self, text: str) -> None:
        self._inner_status = text
        try:
            self.status_label.configure(text=text)
        except tk.TclError:
            pass
        self._tick_state()

    def _note(self, text: str) -> None:
        self._on_inner_status(text)

    # ── стан ───────────────────────────────────────────────────────────────
    def _tick_state(self) -> None:
        """Оновити крапку й адресу за реальним станом контролера."""
        self._timer_after = None
        controller = self._controller()
        running = bool(controller is not None and controller.running)
        try:
            self.state_dot.configure(fg=theme.STATUS_WORKING if running else theme.FG_FAINT)
        except tk.TclError:
            return
        try:
            if controller is not None and controller.url:
                self.url_label.configure(text=controller.url)
        except tk.TclError:
            return
        try:
            if self._timer_alive():
                self._timer_after = self.after(1500, self._tick_state)
        except tk.TclError:
            self._timer_after = None

    def _cancel_timer(self) -> None:
        """Скасувати відкладене оновлення стану.

        Без цього після закриття вікна Tk скаржиться ``invalid command
        name …_tick_state``, а таймер тримає об'єкт живим.
        """
        job = getattr(self, "_timer_after", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
            self._timer_after = None

    def destroy(self) -> None:  # noqa: D102 - просте перевизначення
        self._cancel_timer()
        super().destroy()

    def _timer_alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001 - віджет уже знищено
            return False

    # ── DOM-інспектор ──────────────────────────────────────────────────────
    def _build_inspector(self) -> None:
        """Блок інспектора: тег, селектор, розміри, стилі, кнопки дій."""
        box = tk.Frame(self, bg=theme.BG_ALT)
        box.grid(row=4, column=0, sticky="ew")
        box.grid_remove()
        self.inspector = box

        head = tk.Frame(box, bg=theme.BG_ALT)
        head.pack(fill="x", padx=(12, 8), pady=(4, 0))
        self.inspect_tag = tk.Label(head, text="ЕЛЕМЕНТ", bg=theme.BG_ALT,
                                    fg=theme.FG_BRIGHT,
                                    font=("Segoe UI", 9, "bold"), anchor="w")
        self.inspect_tag.pack(side="left")
        self.inspect_selector = tk.Label(head, text="", bg=theme.BG_ALT,
                                         fg=theme.ACCENT, font=self.fonts.mono_small,
                                         anchor="w")
        self.inspect_selector.pack(side="left", padx=(8, 0))

        self.inspect_meta = tk.Label(box, text="", bg=theme.BG_ALT, fg=theme.FG_DIM,
                                     font=("Segoe UI", 8), anchor="w", justify="left")
        self.inspect_meta.pack(fill="x", padx=(12, 8))
        self.inspect_styles = tk.Label(box, text="", bg=theme.BG_ALT,
                                       fg=theme.FG_FAINT, font=("Segoe UI", 8),
                                       anchor="w", justify="left")
        self.inspect_styles.pack(fill="x", padx=(12, 8))

        actions = tk.Frame(box, bg=theme.BG_ALT)
        actions.pack(fill="x", padx=(12, 8), pady=(3, 6))
        widgets.HoverLabel(
            actions, text="→ Передати агенту", command=self._send_element,
            bg=theme.ACCENT, fg=theme.ON_ACCENT, hover_bg=theme.ACCENT_SOFT,
            hover_fg=theme.ON_ACCENT, font=("Segoe UI", 8, "bold"),
            padx=8, pady=2).pack(side="left")
        widgets.HoverLabel(
            actions, text="Копіювати селектор", command=self._copy_selector,
            bg=theme.BG_CARD, fg=theme.FG_DIM, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=("Segoe UI", 8),
            padx=8, pady=2).pack(side="left", padx=(6, 0))
        widgets.HoverLabel(
            actions, text="Закрити", command=self.hide_inspector,
            bg=theme.BG_ALT, fg=theme.FG_FAINT, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_DIM, font=("Segoe UI", 8),
            padx=8, pady=2).pack(side="left", padx=(6, 0))
        self.inspect_status = tk.Label(actions, text="", bg=theme.BG_ALT,
                                       fg=theme.FG_FAINT, font=("Segoe UI", 8),
                                       anchor="e")
        self.inspect_status.pack(side="right")

    def toggle_inspect(self) -> None:
        """Увімкнути/вимкнути інспектор елементів."""
        self._inspect_mode = not self._inspect_mode
        self._paint_inspect_button()
        if self._inspect_mode:
            self.show_inspector()
            self._note("Інспектор: натисни на елемент сайту.")
        else:
            self._note("Інспектор вимкнено.")

    def _paint_inspect_button(self) -> None:
        button = getattr(self, "inspect_btn", None)
        if button is None:
            return
        try:
            if self._inspect_mode:
                button.configure(bg=theme.ACCENT_SOFT, fg=theme.FG_BRIGHT,
                                 text="◎ Інспектор · увімк.")
            else:
                button.configure(bg=theme.BG_ALT, fg=theme.FG_DIM,
                                 text="◎ Інспектор")
        except tk.TclError:
            pass

    def show_inspector(self) -> None:
        if self.inspector is not None:
            try:
                self.inspector.grid()
            except tk.TclError:
                pass

    def hide_inspector(self) -> None:
        self._inspect_mode = False
        self._paint_inspect_button()
        if self.inspector is not None:
            try:
                self.inspector.grid_remove()
            except tk.TclError:
                pass

    def show_element(self, info: dict) -> None:
        """Показати елемент, прочитаний через CDP."""
        self._element = dict(info or {})
        if self.inspector is None:
            return
        if not self._element:
            try:
                self.inspect_status.configure(text="елемент не знайдено")
            except tk.TclError:
                pass
            return
        self.show_inspector()
        tag = self._element.get("tag") or "?"
        ident = f"#{self._element['id']}" if self._element.get("id") else ""
        classes = self._element.get("classes") or []
        class_text = "." + ".".join(str(name) for name in classes) if classes else ""
        rect = self._element.get("rect") or {}
        text = str(self._element.get("text") or "")
        styles = self._element.get("styles") or {}
        keys = ("display", "position", "color", "backgroundColor", "fontSize",
                "fontWeight", "margin", "padding", "borderRadius", "gap")
        shown = [f"{key}={styles[key]}" for key in keys if styles.get(key)]
        try:
            self.inspect_tag.configure(text=f"<{tag}{ident}{class_text}>")
            self.inspect_selector.configure(text=str(self._element.get("selector") or ""))
            meta = (f"{rect.get('width', '?')}×{rect.get('height', '?')} px · "
                    f"позиція ({rect.get('x', '?')}, {rect.get('y', '?')})")
            if text:
                meta += f"\nТекст: {text[:120]}"
            self.inspect_meta.configure(text=meta)
            self.inspect_styles.configure(
                text="Стилі: " + "; ".join(shown[:8]) if shown else "")
            self.inspect_status.configure(text="")
        except tk.TclError:
            pass
        self._note(f"Вибрано: <{tag}{ident}{class_text}>")

    def _send_element(self) -> None:
        """Передати вибраний елемент у контекст агента."""
        if not self._element:
            try:
                self.inspect_status.configure(text="спершу вибери елемент")
            except tk.TclError:
                pass
            return
        if self.on_send_element is None:
            return
        try:
            self.on_send_element(self._element, "")
        except Exception:  # noqa: BLE001 - дія не має ламати панель
            LOG.debug("Передавання елемента впало", exc_info=True)
            return
        try:
            self.inspect_status.configure(text="передано агенту")
        except tk.TclError:
            pass

    def _copy_selector(self) -> None:
        selector = str(self._element.get("selector") or "")
        if not selector:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(selector)
            self.inspect_status.configure(text="селектор скопійовано")
        except tk.TclError:
            return

    def handle_page_click(self, x: int, y: int) -> bool:
        """Клік по сторінці в режимі інспектора. ``True`` — подію оброблено."""
        if not self._inspect_mode or self.on_inspect_at is None:
            return False
        try:
            info = self.on_inspect_at(int(x), int(y))
        except Exception:  # noqa: BLE001 - інспектор не має ламати браузер
            LOG.debug("Інспектор упав", exc_info=True)
            return False
        self.show_element(info or {})
        return True

    # ── консоль сторінки ───────────────────────────────────────────────────
    def _build_console(self) -> None:
        """Блок консолі: помилки JS, ресурсів і HTTP."""
        box = tk.Frame(self, bg=theme.BG_EDITOR)
        box.grid(row=5, column=0, sticky="ew")
        box.grid_remove()
        self.console_box = box

        head = tk.Frame(box, bg=theme.BG_EDITOR)
        head.pack(fill="x", padx=(10, 6), pady=(3, 0))
        tk.Label(head, text="КОНСОЛЬ СТОРІНКИ", bg=theme.BG_EDITOR,
                 fg=theme.FG_FAINT, font=("Segoe UI", 7, "bold")).pack(side="left")
        self.console_summary = tk.Label(head, text="", bg=theme.BG_EDITOR,
                                        fg=theme.FG_FAINT, font=("Segoe UI", 7))
        self.console_summary.pack(side="right")
        widgets.HoverLabel(
            head, text="×", command=self.hide_console, bg=theme.BG_EDITOR,
            fg=theme.FG_FAINT, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_DIM,
            font=("Segoe UI", 9), padx=6).pack(side="right", padx=(0, 4))

        self.console_text = tk.Text(
            box, height=7, wrap="none", bd=0, highlightthickness=0,
            background=theme.BG_EDITOR, foreground=theme.FG_DIM,
            font=self.fonts.mono_small, padx=10, pady=3,
            state="disabled", cursor="arrow",
        )
        self.console_text.pack(fill="x", pady=(1, 5))
        self.console_text.tag_configure("error", foreground=theme.ERROR)
        self.console_text.tag_configure("warning", foreground=theme.WARN)
        self.console_text.tag_configure("info", foreground=theme.FG_FAINT)

    def show_console(self) -> None:
        if self.console_box is not None:
            try:
                self.console_box.grid()
            except tk.TclError:
                pass

    def hide_console(self) -> None:
        if self.console_box is not None:
            try:
                self.console_box.grid_remove()
            except tk.TclError:
                pass

    def set_console(self, lines: list[str], errors: int = 0) -> None:
        """Показати рядки консолі сторінки."""
        widget = getattr(self, "console_text", None)
        if widget is None:
            return
        self.show_console()
        try:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            if not lines:
                widget.insert("end", "Помилок і повідомлень немає.", "info")
            else:
                for line in lines[-80:]:
                    tag = ("error" if line.startswith("[error") else
                           "warning" if line.startswith("[warning") else "info")
                    widget.insert("end", line + "\n", tag)
            widget.configure(state="disabled")
            self.console_summary.configure(
                text=(f"{errors} помилок" if errors else "помилок немає"),
                fg=theme.ERROR if errors else theme.FG_FAINT)
        except tk.TclError:
            pass

    def collect_console(self) -> None:
        """Прочитати консоль через підключений провайдер."""
        provider = getattr(self, "console_provider", None)
        if provider is None:
            self.set_console([], 0)
            return
        try:
            payload = provider()
        except Exception:  # noqa: BLE001 - консоль не має ламати панель
            LOG.debug("Консоль недоступна", exc_info=True)
            payload = None
        if not payload:
            self.set_console([], 0)
            return
        lines, errors = payload
        self.set_console(list(lines or []), int(errors or 0))

    def run_action(self, name: str) -> str:
        """Виконати дію над сторінкою: screenshot | audit | responsive."""
        provider = getattr(self, "action_provider", None)
        if provider is None:
            return "Браузер ще не запущено."
        try:
            result = provider(name)
        except Exception as exc:  # noqa: BLE001 - дія не має ламати панель
            return f"{type(exc).__name__}: {exc}"
        return str(result or "")

    # ── делегування (сумісність із кодом вікна) ────────────────────────────
    @property
    def url(self) -> str:
        """Адреса запущеного сайту (``""``, якщо сервер не піднято).

        Потрібна шапці й режиму Live Browser: вони показують сайт, який уже
        працює, замість повторного запуску ще одного сервера.
        """
        controller = self._controller()
        if controller is not None and controller.running and controller.url:
            return str(controller.url)
        label = ""
        try:
            label = str(self.url_label.cget("text") or "")
        except tk.TclError:
            label = ""
        return "" if label in ("", "—") else label

    @property
    def server(self):
        return self.inner.server

    def start_server(self) -> None:
        """Запустити застосунок (через контролер, як агент)."""
        self._toggle()

    def stop_all(self) -> None:
        controller = self._controller()
        if controller is not None and controller.running:
            controller.stop()
        self.inner.stop_all()
        self._tick_state()

    def reload_page(self) -> None:
        self.inner.reload_page()

    def open_url(self, url: str) -> bool:
        """Відкрити довільну адресу у вбудованому вікні цієї колонки.

        Так само працює і для локального сайту проєкту, і для сторінки з
        інтернету (документація, завантаження git). Показує саму колонку,
        щоб користувач одразу бачив результат.
        """
        target = browser_panel.normalise_url(url)
        if not target:
            return False
        self.inner.view.open_url(target)
        try:
            self.url_label.configure(text=target)
        except tk.TclError:
            pass
        self._note(f"Відкрито у вбудованому браузері: {target}")
        return True

    def show_address_bar(self) -> None:
        """Показати рядок адреси внутрішнього браузера (для вільного входу)."""
        for name in ("address", "back_btn", "go_btn"):
            widget = getattr(self.inner.view, name, None)
            if widget is None:
                continue
            try:
                widget.grid()
            except tk.TclError:
                pass

    def on_file_saved(self) -> None:
        self.inner.on_file_saved()

    def on_close(self) -> None:
        if self._timer_after is not None:
            try:
                self.after_cancel(self._timer_after)
            except (tk.TclError, ValueError):
                pass
            self._timer_after = None
        self.inner.on_close()


__all__ = ["LivePreviewPanel"]
