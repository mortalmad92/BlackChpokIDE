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
    def _on_ctrl_wheel_zoom(self, event) -> None:
        try:
            if not self.winfo_viewable():
                return
            x_root = getattr(event, "x_root", 0)
            if x_root >= self.winfo_rootx():
                delta = getattr(event, "delta", 0)
                if delta > 0:
                    self._change_zoom(0.1)
                elif delta < 0:
                    self._change_zoom(-0.1)
        except Exception:
            pass

    def _toggle_fullscreen_preview(self) -> None:
        try:
            host = getattr(self, "master", None)
            split = getattr(host, "master", None) if host is not None else None
            if host is None or split is None:
                return
            total_w = max(800, split.winfo_width())
            if not getattr(self, "_is_preview_max", False):
                self._saved_preview_w = max(360, host.winfo_width())
                self._is_preview_max = True
                self._resize_preview(int(total_w * 0.88) - self._saved_preview_w)
            else:
                self._is_preview_max = False
                target_w = getattr(self, "_saved_preview_w", 460)
                self._resize_preview(target_w - host.winfo_width())
        except Exception:
            pass

    def _close_preview_panel(self) -> None:
        try:
            top = self.winfo_toplevel()
            if hasattr(top, "toggle_preview"):
                top.toggle_preview(False)
        except Exception:
            pass

    def set_viewport_mode(self, mode: str = "desktop", target_w: int = 0) -> str:
        """?????????? ????? ????????? ????????: mobile (????????), tablet (???????), desktop (????'????)."""
        m = str(mode or "desktop").strip().lower()
        presets = {"mobile": 415, "phone": 415, "smartphone": 415, "tablet": 790, "desktop": 0, "pc": 0}
        if m not in presets:
            m = "desktop"
        width = target_w if target_w > 0 else presets[m]
        self._viewport_mode = "mobile" if m in ("mobile", "phone", "smartphone") else ("tablet" if m == "tablet" else "desktop")
        for k, b in getattr(self, "_vp_btns", {}).items():
            try:
                b.configure(fg="#38BDF8" if k == self._viewport_mode else theme.FG_DIM)
            except Exception:
                pass
        try:
            top = self.winfo_toplevel()
            pw = getattr(top, "_split", None) or getattr(top, "main_split", None)
            total_w = top.winfo_width()
            if width > 0 and total_w > width + 260:
                if pw is not None and hasattr(pw, "sashpos"):
                    panes = pw.panes()
                    if len(panes) >= 2:
                        pw.sashpos(len(panes) - 2, max(240, total_w - width))
            elif width == 0 and total_w > 900:
                if pw is not None and hasattr(pw, "sashpos"):
                    panes = pw.panes()
                    if len(panes) >= 2:
                        pw.sashpos(len(panes) - 2, int(total_w * 0.52))
            self.reload_page()
        except Exception:
            pass
        return f"????? ?????????: {self._viewport_mode}"

    def _resize_preview(self, delta: int) -> None:
        try:
            host = getattr(self, "master", None)
            split = getattr(host, "master", None) if host is not None else None
            if host is None or split is None:
                return
            cur_w = max(320, host.winfo_width())
            total_w = max(800, split.winfo_width())
            new_w = max(320, min(int(total_w * 0.72), cur_w + int(delta)))
            real_delta = new_w - cur_w
            if real_delta == 0:
                return
            host.configure(width=new_w)
            if hasattr(split, "sash_place") and hasattr(split, "panes"):
                panes = list(split.panes())
                n_sashes = len(panes) - 1
                for si in range(n_sashes):
                    sx, sy = split.sash_coord(si)
                    split.sash_place(si, max(180, sx - real_delta), sy)
        except Exception:
            pass

    def _change_zoom(self, step: float) -> None:
        try:
            z = round(max(0.6, min(2.2, getattr(self, "_page_zoom", 1.0) + step)), 2)
            self._page_zoom = z
            view = getattr(getattr(self, "inner", None), "view", None)
            if view is not None and hasattr(view, "ensure_cdp"):
                sess = view.ensure_cdp()
                if sess is not None:
                    sess.evaluate(f"document.documentElement.style.zoom = '{z}'; document.body.style.zoom = '{z}';")
            if hasattr(self, "status_label"):
                self.status_label.configure(text=f"\u041c\u0430\u0441\u0448\u0442\u0430\u0431 \u0441\u0442\u043e\u0440\u0456\u043d\u043a\u0438: {int(z * 100)}%")
        except Exception:
            pass

    def _translate_page_to_ukrainian(self) -> None:
        try:
            import urllib.parse as _up
            view = getattr(getattr(self, "inner", None), "view", None)
            cur_url = str(getattr(view, "url", "") or "").strip()
            if not cur_url or "translate.goog" in cur_url or "translate.google.com" in cur_url:
                return
            if view is not None and hasattr(view, "ensure_cdp"):
                try:
                    sess = view.ensure_cdp()
                    if sess is not None:
                        js_gt = (
                            "if(!document.getElementById('gt_ide_el')){"
                            "var d=document.createElement('div');d.id='gt_ide_el';d.style.cssText='position:fixed;top:6px;right:6px;z-index:999999;background:#fff;padding:4px;border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,.3)';"
                            "document.body.appendChild(d);"
                            "window.googleTranslateElementInit=function(){new google.translate.TranslateElement({pageLanguage:'auto',includedLanguages:'uk,en,pl,de',autoDisplay:true},'gt_ide_el');};"
                            "var s=document.createElement('script');s.src='https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit';document.body.appendChild(s);"
                            "}"
                        )
                        sess.evaluate(js_gt)
                except Exception:
                    pass
            tr_url = f"https://translate.google.com/translate?sl=auto&tl=uk&u={_up.quote(cur_url, safe='')}"
            top = self.winfo_toplevel()
            if hasattr(top, "open_url_in_browser"):
                top.open_url_in_browser(tr_url)
        except Exception:
            pass


    def _build(self) -> None:
        # ── заголовок
        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(10, 4))
        head.columnconfigure(1, weight=1)

        self.state_dot = tk.Label(head, text="●", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                  font=theme.font(9))
        self.state_dot.grid(row=0, column=0, padx=(0, 6))
        tk.Label(head, text="Live Preview", bg=theme.BG_ALT, fg=theme.FG,
                 font=theme.font(9, "bold"), anchor="w").grid(row=0, column=1, sticky="w")

        actions = tk.Frame(head, bg=theme.BG_ALT)
        actions.grid(row=0, column=2, sticky="e")
        self.run_btn = widgets.IconButton(actions, "▶", self._toggle, bg=theme.BG_ALT,
                                          fg=theme.STATUS_WORKING, font=theme.font(10),
                                          tooltip="Запустити / зупинити застосунок")
        self.run_btn.pack(side="left")
        self.reload_btn = widgets.IconButton(actions, "⟳", self._reload, bg=theme.BG_ALT,
                                             fg=theme.FG_DIM, font=theme.font(10),
                                             tooltip="Перезавантажити сторінку")
        self.reload_btn.pack(side="left")
        self.open_btn = widgets.IconButton(actions, "↗", self._open_external, bg=theme.BG_ALT,
                                           fg=theme.FG_DIM, font=theme.font(10),
                                           tooltip="Відкрити в системному браузері")
        self.open_btn.pack(side="left")
        # ── сторінка як дані: інспектор, консоль, знімок, перевірка
        self.inspect_btn = widgets.IconButton(
            actions, "◎", self.toggle_inspect, bg=theme.BG_ALT,
            fg=theme.FG_DIM, font=theme.font(10),
            tooltip="Інспектор елементів: натисни на елемент сайту й передай агенту")
        self.inspect_btn.pack(side="left")
        self.console_btn = widgets.IconButton(
            actions, "⚠", self.collect_console, bg=theme.BG_ALT,
            fg=theme.FG_DIM, font=theme.font(10),
            tooltip="Консоль сторінки: помилки JS, ресурсів і HTTP")
        self.console_btn.pack(side="left")
        self.shot_btn = widgets.IconButton(
            actions, "⊠", lambda: self.run_action("screenshot"), bg=theme.BG_ALT,
            fg=theme.FG_DIM, font=theme.font(10),
            tooltip="Знімок самої сторінки (не екрана) у PNG")
        self.shot_btn.pack(side="left")
        # ?????? ????????? ??????? ?????, ????????? (A-/A+) ?? ???????????? Google ?? ?????????? ????
        self._page_zoom = 1.0
        self._viewport_mode = "desktop"
        self._vp_btns = {}
        for vp_key, vp_icon, vp_w, vp_tip in (
            ("mobile", "\U0001f4f1 390", 415, "\u0420\u0435\u0436\u0438\u043c \u0441\u043c\u0430\u0440\u0442\u0444\u043e\u043d\u0430 (390\u00d7844)"),
            ("tablet", "\U0001f4df 768", 790, "\u0420\u0435\u0436\u0438\u043c \u043f\u043b\u0430\u043d\u0448\u0435\u0442\u0430 (768\u00d71024)"),
            ("desktop", "\U0001f5a5 PC", 0, "\u0420\u0435\u0436\u0438\u043c \u043a\u043e\u043c\u043f'\u044e\u0442\u0435\u0440\u0430 (\u0448\u0438\u0440\u043e\u043a\u0438\u0439 \u0435\u043a\u0440\u0430\u043d)"),
        ):
            vbtn = widgets.HoverLabel(
                actions, text=vp_icon, command=lambda m=vp_key, w=vp_w: self.set_viewport_mode(m, w),
                bg=theme.BG_ALT, fg=theme.FG_BRIGHT if vp_key == "desktop" else theme.FG_DIM,
                hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT, font=theme.font(8, "bold"), padx=5, pady=2)
            vbtn.pack(side="left", padx=(3, 0))
            widgets.Tip(vbtn, vp_tip)
            self._vp_btns[vp_key] = vbtn

        self.zoom_out_btn = widgets.HoverLabel(
            actions, text="A\u2212", command=lambda: self._change_zoom(-0.15),
            bg=theme.BG_ALT, fg=theme.FG_DIM, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT, font=theme.font(8, "bold"), padx=5, pady=2)
        self.zoom_out_btn.pack(side="left", padx=(4, 0))
        widgets.Tip(self.zoom_out_btn, "\u0417\u043c\u0435\u043d\u0448\u0438\u0442\u0438 \u0448\u0440\u0438\u0444\u0442 \u0456 \u043c\u0430\u0441\u0448\u0442\u0430\u0431")

        self.zoom_in_btn = widgets.HoverLabel(
            actions, text="A+", command=lambda: self._change_zoom(0.15),
            bg=theme.BG_ALT, fg=theme.FG_DIM, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT, font=theme.font(8, "bold"), padx=5, pady=2)
        self.zoom_in_btn.pack(side="left")
        widgets.Tip(self.zoom_in_btn, "\u0417\u0431\u0456\u043b\u044c\u0448\u0438\u0442\u0438 \u0448\u0440\u0438\u0444\u0442 \u0456 \u043c\u0430\u0441\u0448\u0442\u0430\u0431")

        self.translate_ua_btn = widgets.HoverLabel(
            actions, text="\U0001f310 UA", command=self._translate_page_to_ukrainian,
            bg=theme.BG_ALT, fg="#38BDF8", hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT, font=theme.font(8, "bold"), padx=6, pady=2)
        self.translate_ua_btn.pack(side="left", padx=(4, 0))
        self.fullscreen_btn = widgets.HoverLabel(
            actions, text="\u26f6", command=self._toggle_fullscreen_preview,
            bg=theme.BG_ALT, fg=theme.FG_DIM, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_BRIGHT, font=theme.font(9, "bold"), padx=5, pady=2)
        self.fullscreen_btn.pack(side="left", padx=(4, 0))
        widgets.Tip(self.fullscreen_btn, "\u041d\u0430 \u0432\u0435\u0441\u044c \u0435\u043a\u0440\u0430\u043d / \u041f\u043e\u0432\u0435\u0440\u043d\u0443\u0442\u0438 \u0440\u043e\u0437\u043c\u0456\u0440")

        self.close_preview_btn = widgets.HoverLabel(
            actions, text="\u2715", command=self._close_preview_panel,
            bg=theme.BG_ALT, fg="#F87171", hover_bg=theme.BG_HOVER, hover_fg="#FCA5A5", font=theme.font(9, "bold"), padx=5, pady=2)
        self.close_preview_btn.pack(side="left", padx=(4, 0))
        widgets.Tip(self.close_preview_btn, "\u0417\u0430\u043a\u0440\u0438\u0442\u0438 \u0432\u0431\u0443\u0434\u043e\u0432\u0430\u043d\u0438\u0439 \u0431\u0440\u0430\u0443\u0437\u0435\u0440")
        self.bind_all("<Control-MouseWheel>", self._on_ctrl_wheel_zoom, add="+")
        widgets.Tip(self.translate_ua_btn, "\u041f\u0435\u0440\u0435\u043a\u043b\u0430\u0441\u0442\u0438 \u0441\u0442\u043e\u0440\u0456\u043d\u043a\u0443 \u043d\u0430 \u0443\u043a\u0440\u0430\u0457\u043d\u0441\u044c\u043a\u0443 (Google Translate)")

        # ── адресний рядок
        url_host = tk.Frame(self, bg=theme.BG_CARD)
        url_host.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        url_host.columnconfigure(0, weight=1)
        self.url_label = tk.Label(url_host, text="—", bg=theme.BG_CARD, fg=theme.FG_DIM,
                                  font=theme.font(8), anchor="w")
        self.url_label.grid(row=0, column=0, sticky="ew", ipady=5, padx=(10, 6))

        # ── статус-стрічка
        self.status_label = tk.Label(self, text="Стек не визначено", bg=theme.BG_ALT,
                                     fg=theme.FG_FAINT, font=theme.font(8), anchor="w",
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

    def adopt_running(self) -> bool:
        """Підхопити сервер, який підняв ХТОСЬ ІНШИЙ (агент через ``app_start``).

        Навіщо це потрібно. ``AppController`` піднімає сервер сам, у своєму
        потоці: сторінка вже відповідає на адресі, але колонка прев'ю про це
        не знає — у неї порожній ``inner.server``. Через це не запускався
        watcher, і зміни, які агент вносив далі, НЕ з'являлись на сторінці,
        доки не натиснути ⟳ вручну. Користувач просив рівно протилежне:
        «коли вносить зміни, щоб там все оновлювалося в реальному часі».

        Повертає ``True``, якщо сторінку справді показано.
        """
        controller = self._controller()
        if controller is None or not controller.running:
            return False
        url = ""
        try:
            url = str(controller.url or "")
        except Exception:                            # noqa: BLE001
            url = ""
        if not url:
            return False
        # Стан сервера переносимо в панель: інакше ``_tick`` вважатиме, що
        # запускати нічого, і живих оновлень не буде.
        self.inner.server = getattr(controller, "server", None)
        self.inner.recipe = getattr(controller, "recipe", None)
        try:
            self.inner.url_label.configure(text=url)
        except tk.TclError:
            pass
        try:
            self.url_label.configure(text=url)
        except tk.TclError:
            pass
        # Сторінку відкриваємо ЛИШЕ якщо вона ще не ця: повторний ``show``
        # перезапускає Chromium, і кожне збереження файлу мигало б вікном.
        try:
            current = str(self.inner.view.url or "")
        except Exception:                            # noqa: BLE001
            current = ""
        if current.rstrip("/") != url.rstrip("/"):
            self.inner.view.set_address(url)
            self.inner.view.show(url)
        # Живий watcher — та сама «реальна година», що й у ``_toggle``.
        self.inner._start_watcher()       # noqa: SLF001 - публічного входу немає
        self._tick_state()
        return True

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
                                    font=theme.font(9, "bold"), anchor="w")
        self.inspect_tag.pack(side="left")
        self.inspect_selector = tk.Label(head, text="", bg=theme.BG_ALT,
                                         fg=theme.ACCENT, font=self.fonts.mono_small,
                                         anchor="w")
        self.inspect_selector.pack(side="left", padx=(8, 0))

        self.inspect_meta = tk.Label(box, text="", bg=theme.BG_ALT, fg=theme.FG_DIM,
                                     font=theme.font(8), anchor="w", justify="left")
        self.inspect_meta.pack(fill="x", padx=(12, 8))
        self.inspect_styles = tk.Label(box, text="", bg=theme.BG_ALT,
                                       fg=theme.FG_FAINT, font=theme.font(8),
                                       anchor="w", justify="left")
        self.inspect_styles.pack(fill="x", padx=(12, 8))

        actions = tk.Frame(box, bg=theme.BG_ALT)
        actions.pack(fill="x", padx=(12, 8), pady=(3, 6))
        widgets.HoverLabel(
            actions, text="→ Передати агенту", command=self._send_element,
            bg=theme.ACCENT, fg=theme.ON_ACCENT, hover_bg=theme.ACCENT_SOFT,
            hover_fg=theme.ON_ACCENT, font=theme.font(8, "bold"),
            padx=8, pady=2).pack(side="left")
        widgets.HoverLabel(
            actions, text="Копіювати селектор", command=self._copy_selector,
            bg=theme.BG_CARD, fg=theme.FG_DIM, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_BRIGHT, font=theme.font(8),
            padx=8, pady=2).pack(side="left", padx=(6, 0))
        widgets.HoverLabel(
            actions, text="Закрити", command=self.hide_inspector,
            bg=theme.BG_ALT, fg=theme.FG_FAINT, hover_bg=theme.BG_HOVER,
            hover_fg=theme.FG_DIM, font=theme.font(8),
            padx=8, pady=2).pack(side="left", padx=(6, 0))
        self.inspect_status = tk.Label(actions, text="", bg=theme.BG_ALT,
                                       fg=theme.FG_FAINT, font=theme.font(8),
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
                 fg=theme.FG_FAINT, font=theme.font(7, "bold")).pack(side="left")
        self.console_summary = tk.Label(head, text="", bg=theme.BG_EDITOR,
                                        fg=theme.FG_FAINT, font=theme.font(7))
        self.console_summary.pack(side="right")
        widgets.HoverLabel(
            head, text="×", command=self.hide_console, bg=theme.BG_EDITOR,
            fg=theme.FG_FAINT, hover_bg=theme.BG_HOVER, hover_fg=theme.FG_DIM,
            font=theme.font(9), padx=6).pack(side="right", padx=(0, 4))

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
        for name in ("address", "back_btn", "go_btn"):
            widget = getattr(self.inner.view, name, None)
            if widget is None:
                continue
            try:
                widget.grid()
            except tk.TclError:
                pass
        addr = getattr(self.inner.view, "address", None)
        if addr is not None and not getattr(addr, "_ctx_enhanced", False):
            addr._ctx_enhanced = True
            def _go_addr(_e=None):
                raw = str(addr.get() or "").strip()
                if not raw:
                    return "break"
                if " " in raw or ("." not in raw and not raw.startswith(("http://", "https://", "localhost"))):
                    import urllib.parse
                    raw = "https://google.com" + urllib.parse.quote_plus(raw)
                self.open_url(raw)
                return "break"
            def _paste_and_go():
                try:
                    txt = str(self.clipboard_get() or "").strip()
                    if txt:
                        addr.delete(0, "end")
                        addr.insert(0, txt)
                        _go_addr()
                except Exception:
                    pass
            def _paste_only():
                try:
                    txt = str(self.clipboard_get() or "")
                    if txt:
                        if addr.selection_present():
                            addr.delete("sel.first", "sel.last")
                        addr.insert("insert", txt)
                except Exception:
                    pass
            def _show_addr_ctx(ev):
                widgets.context_menu(self, [
                    ("\u23ce  \u0412\u0441\u0442\u0430\u0432\u0438\u0442\u0438 \u0442\u0430 \u043f\u0435\u0440\u0435\u0439\u0442\u0438", _paste_and_go),
                    ("\u2398  \u0412\u0441\u0442\u0430\u0432\u0438\u0442\u0438", _paste_only),
                    ("\u2397  \u041a\u043e\u043f\u0456\u044e\u0432\u0430\u0442\u0438", lambda: addr.event_generate("<<Copy>>")),
                    ("\u2702  \u0412\u0438\u0440\u0456\u0437\u0430\u0442\u0438", lambda: addr.event_generate("<<Cut>>")),
                    ("", None),
                    ("\u25a3  \u0412\u0438\u0434\u0456\u043b\u0438\u0442\u0438 \u0432\u0441\u0435", lambda: (addr.select_range(0, "end"), addr.icursor("end"))),
                ], ev)
                return "break"
            try:
                addr.bind("<Return>", _go_addr, add="+")
                addr.bind("<KP_Enter>", _go_addr, add="+")
                addr.bind("<Button-3>", _show_addr_ctx, add="+")
            except Exception:
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

