"""Віджет голосового керування: кнопка мікрофона й стан запису.

Малює кнопку **🎙** у рядку композера. Натискання запускає запис у
фоновому потоці, потім розпізнає мовлення й віддає текст назовні.

**Потокова безпека.** tkinter не можна викликати з робочого потоку:
``after()`` реєструє команду в інтерпретаторі Tk, і поза головним циклом
це падає з ``RuntimeError: main thread is not in main loop`` (а в Release
збірці просто вбиває застосунок). Тому фоновий потік лише кладе
результат у чергу, а головний потік забирає його своїм таймером — так
само, як це зроблено в панелі інструментів і в чаті.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from typing import Callable, Optional

from . import theme, voice, widgets


class VoiceButton(tk.Frame):
    """Кнопка мікрофона зі станом і таймером."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        settings: voice.VoiceSettings,
        on_text: Optional[Callable[[voice.SpeechResult], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        bg: str = theme.BG_INPUT,
    ) -> None:
        super().__init__(master, bg=bg, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.voice_settings = settings
        self.on_text = on_text
        self.on_status = on_status
        self._bg = bg
        self._busy = False
        self._thread: Optional[threading.Thread] = None
        self._elapsed = 0.0
        self._blink = 0
        self._after: Optional[str] = None
        #: Результати з фонового потоку → головний потік.
        self._results: "queue.Queue[voice.SpeechResult]" = queue.Queue()
        self._pump_job: Optional[str] = None
        self._build()
        # Кнопка живе в композері й знищується разом із чатом. Без зняття
        # таймерів заплановані ``after`` лишаються в Tcl: Tk друкує
        # «invalid command name ..._pump», а закриття вікна падає з
        # «application has been destroyed».
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._update_engine_state()
        self._start_pump()

    def _on_destroy(self, event=None) -> None:
        if event is not None and getattr(event, "widget", self) is not self:
            return
        self.stop()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.button = tk.Label(self, text="🎙", bg=self._bg, fg=theme.FG_DIM,
                               font=("Segoe UI", 11), padx=6, cursor="hand2")
        self.button.pack(side="left")
        self.button.bind("<Button-1>", lambda _e: self.toggle())
        widgets.Tip(self.button, "Голосове керування — натисни й говори")

    def _update_engine_state(self) -> None:
        """Показати, чи взагалі доступне розпізнавання."""
        engine = voice.best_engine(self.voice_settings.whisper_dir)
        if not engine:
            self.button.configure(fg=theme.FG_FAINT)
            widgets.Tip(self.button, "Розпізнавання недоступне: перевір мікрофон")
            return
        name = "whisper.cpp" if engine == "whisper" else "рушій Windows"
        widgets.Tip(self.button, f"Голосове керування ({name}) — натисни й говори")

    # ── запис ──────────────────────────────────────────────────────────────
    def toggle(self) -> None:
        if self._busy:
            return
        engine = voice.best_engine(self.voice_settings.whisper_dir)
        if not engine:
            self._notify("Розпізнавання мовлення недоступне на цій системі.")
            return
        self.start()

    def start(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._elapsed = 0.0
        self.button.configure(text="■", fg=theme.ERROR)
        self._notify("Слухаю… говори зараз")
        self._tick()

        settings = self.voice_settings
        thread = threading.Thread(target=self._work, args=(settings,), daemon=True)
        self._thread = thread
        thread.start()

    def _work(self, settings: voice.VoiceSettings) -> None:
        """Фоновий потік: запис і розпізнавання. Tk тут не чіпаємо."""
        try:
            result = voice.listen(settings, on_tick=self._on_tick)
        except Exception as exc:  # noqa: BLE001 - інтерфейс не має падати
            result = voice.SpeechResult(False, detail=f"{type(exc).__name__}: {exc}")
        # Лише черга — жодних викликів tkinter із цього потоку.
        self._results.put(result)

    # ── місток «потік → інтерфейс» ─────────────────────────────────────────
    def _start_pump(self) -> None:
        """Запустити таймер головного потоку, що забирає результати."""
        self._pump_job = None
        self._schedule_pump()

    def _schedule_pump(self) -> None:
        if not self._timer_alive():
            self._pump_job = None
            return
        try:
            self._pump_job = self.after(80, self._pump)
        except tk.TclError:
            self._pump_job = None

    def _pump(self) -> None:
        """Головний потік: забрати готовий результат і показати його."""
        self._pump_job = None
        while True:
            try:
                result = self._results.get_nowait()
            except queue.Empty:
                break
            self._finish(result)
        self._schedule_pump()

    def _on_tick(self, elapsed: float) -> None:
        """Зворотний виклик із потоку запису — лише число."""
        self._elapsed = elapsed

    def _tick(self) -> None:
        """Оновити напис на кнопці (головний потік)."""
        if not self._busy:
            return
        seconds = int(self._elapsed)
        dots = "." * (self._blink % 4)
        try:
            self.button.configure(text=f"●{seconds}{dots}" if seconds else "●")
        except tk.TclError:
            return
        self._blink += 1
        self._after = (self.after(200, self._tick) if self._timer_alive() else None)

    def _finish(self, result: voice.SpeechResult) -> None:
        self._busy = False
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except (tk.TclError, ValueError):
                pass
            self._after = None
        try:
            self.button.configure(text="🎙", fg=theme.FG_DIM)
        except tk.TclError:
            pass
        if result.ok and result.text.strip():
            self._notify(f"Розпізнано: {voice.short_text(result.text, 70)}")
        else:
            self._notify(result.detail or "Нічого не розпізнано.")
        if self.on_text is not None:
            try:
                self.on_text(result)
            except Exception:  # noqa: BLE001
                pass


    def _timer_alive(self) -> bool:
        """Чи можна ще планувати ``after`` (віджет існує й вікно живе)."""
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001 - віджет уже знищено
            return False

    def _notify(self, text: str) -> None:
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:  # noqa: BLE001
                pass

    @property
    def busy(self) -> bool:
        return self._busy

    def stop(self) -> None:
        self._busy = False
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except (tk.TclError, ValueError):
                pass
            self._after = None
        if self._pump_job is not None:
            try:
                self.after_cancel(self._pump_job)
            except (tk.TclError, ValueError):
                pass
            self._pump_job = None


__all__ = ["VoiceButton"]
