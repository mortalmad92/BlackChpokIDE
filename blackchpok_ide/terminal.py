"""Вбудований термінал: постійна сесія оболонки, історія, швидкі команди.

Панель лише малює те, що приходить від ``shell_session.ShellSession``:
сам процес живе, доки живе панель, тому ``cd``, змінені змінні середовища й
віртуальні оточення зберігаються між командами так само, як у справжньому
терміналі IDE.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from . import shell_session, theme, widgets


def _short_path(path: Path, limit: int = 64) -> str:
    text = str(path)
    if len(text) <= limit:
        return text
    return "…" + text[-(limit - 1):]


class TerminalPanel(tk.Frame):
    """Панель терміналу внизу вікна."""

    def __init__(self, master: tk.Misc, fonts: theme.Theme, cwd: Path) -> None:
        super().__init__(master, bg=theme.BG, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.cwd = Path(cwd)
        self.on_status: Optional[Callable[[str], None]] = None
        self.on_output: Optional[Callable[[str], None]] = None
        self._history: list[str] = []
        self._history_pos = 0
        self._pending_line = ""
        self._session: Optional[shell_session.ShellSession] = None
        self._fallback = False
        self._ui_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._drain_after: Optional[str] = None
        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")
        self._drain()

    # ── UI ─────────────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        bar = tk.Frame(self, bg=theme.BG)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=(12, 8), pady=(8, 4))
        bar.columnconfigure(1, weight=1)

        self.title = tk.Label(bar, text="ТЕРМІНАЛ", bg=theme.BG, fg=theme.FG_FAINT,
                              font=("Segoe UI", 8, "bold"))
        self.title.grid(row=0, column=0, sticky="w")

        self.cwd_label = tk.Label(bar, text=_short_path(self.cwd), bg=theme.BG, fg=theme.FG_DIM,
                                  font=("Segoe UI", 8))
        self.cwd_label.grid(row=0, column=1, sticky="w", padx=(10, 8))

        quick = tk.Frame(bar, bg=theme.BG)
        quick.grid(row=0, column=2, sticky="e")
        for text, command in (
            ("Тести", f'"{sys.executable}" -m unittest discover -s tests -v'),
            ("Git", "git status --short --branch"),
            ("Компіляція", f'"{sys.executable}" -m compileall -q .'),
        ):
            widgets.Chip(quick, text, lambda c=command: self.run(c), font=("Segoe UI", 8)).pack(
                side="left", padx=(0, 4))
        widgets.IconButton(quick, "⌫", self.clear, bg=theme.BG, fg=theme.FG_FAINT,
                           font=("Segoe UI", 9), tooltip="Очистити (Ctrl+L)").pack(side="left", padx=(4, 0))
        widgets.IconButton(quick, "⟳", self.restart, bg=theme.BG, fg=theme.FG_FAINT,
                           font=("Segoe UI", 9), tooltip="Перезапустити сесію").pack(side="left")

        self.output = tk.Text(
            self, height=8, wrap="none", border=0, highlightthickness=0,
            background=theme.BG_EDITOR, foreground=theme.FG, insertbackground=theme.FG_BRIGHT,
            font=self.fonts.mono_small, padx=12, pady=8, state="disabled",
            selectbackground=theme.SELECTION,
        )
        self.output.grid(row=2, column=0, sticky="nsew", padx=(10, 0), pady=(0, 0))
        self.output.tag_configure("cmd", foreground=theme.SUCCESS)
        self.output.tag_configure("err", foreground=theme.ERROR)
        self.output.tag_configure("info", foreground=theme.FG_FAINT)
        self.output.tag_configure("out", foreground=theme.FG)
        self.output.tag_configure("exit_ok", foreground=theme.FG_FAINT)
        self.output.tag_configure("exit_err", foreground=theme.ERROR)

        scroll = tk.Scrollbar(self, orient="vertical", command=self.output.yview)
        scroll.grid(row=2, column=1, sticky="ns", padx=(0, 6), pady=(0, 0))
        self.output.configure(yscrollcommand=scroll.set)

        entry_row = tk.Frame(self, bg=theme.BG)
        entry_row.grid(row=3, column=0, columnspan=2, sticky="ew", padx=(10, 8), pady=(6, 8))
        entry_row.columnconfigure(1, weight=1)

        self.prompt = tk.Label(entry_row, text="›", bg=theme.BG, fg=theme.ACCENT,
                               font=self.fonts.mono_bold)
        self.prompt.grid(row=0, column=0, padx=(2, 6))

        self.entry = tk.Entry(
            entry_row, bg=theme.BG_INPUT, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
            relief="flat", font=self.fonts.mono_small, bd=0, highlightthickness=1,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT_SOFT,
        )
        self.entry.grid(row=0, column=1, sticky="ew", ipady=5, padx=(0, 6))
        self.entry.bind("<Return>", lambda _e: self._submit())
        self.entry.bind("<Up>", self._history_up)
        self.entry.bind("<Down>", self._history_down)
        self.entry.bind("<Control-l>", lambda _e: (self.clear(), "break")[1])
        self.entry.bind("<Control-c>", lambda _e: (self.interrupt(), "break")[1])

        widgets.IconButton(entry_row, "■", self.interrupt, bg=theme.BG, fg=theme.ERROR,
                           font=("Segoe UI", 9), tooltip="Перервати команду (Ctrl+C)").grid(
            row=0, column=2)

        self._write("BlackChpok IDE · термінал готовий.\n", "info")
        self.after(120, self.start)

    # ── сесія ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._session is not None and self._session.running:
            return
        try:
            session = shell_session.ShellSession(
                self.cwd,
                on_output=self._on_shell_output,
                on_exit=self._on_shell_exit,
            )
        except Exception as exc:  # noqa: BLE001 - термінал не має ламати вікно
            self._write(f"[термінал недоступний: {exc}]\n", "err")
            return
        if session.start():
            self._session = session
            self._fallback = False
            shell_name = Path(shell_session.available_shell() or "sh").name
            self._write(f"[сесія {shell_name} · {self.cwd}]\n", "info")
        else:
            self._session = None
            self._fallback = True
            self._write("[не вдалось підняти постійну сесію — команди виконуються окремо]\n", "err")

    def restart(self) -> None:
        if self._session is not None:
            self._session.stop()
            self._session = None
        self._write("\n[перезапуск сесії]\n", "info")
        self.start()

    @property
    def session(self) -> Optional[shell_session.ShellSession]:
        return self._session

    def _on_shell_output(self, chunk: str) -> None:
        """Викликається з потоку читця.

        Торкатись віджетів і навіть ``after()`` з чужого потоку небезпечно,
        тому лише складаємо текст у чергу, а малює головний цикл у ``_drain``.
        """
        self._ui_queue.put(("out", chunk))

    def _on_shell_exit(self, code: int) -> None:
        self._ui_queue.put(("exit", code))

    def _drain(self) -> None:
        """Виконати накопичені оновлення (лише головний потік)."""
        try:
            for _ in range(200):
                try:
                    kind, payload = self._ui_queue.get_nowait()
                except queue.Empty:
                    break
                if kind == "out":
                    self._append(str(payload))
                elif kind == "exit":
                    self._write(f"\n[сесія завершилась, код {payload}]\n", "err")
                elif kind == "done":
                    code, output = payload
                    self._apply_finish(int(code), str(output))
        except tk.TclError:
            pass
        try:
            self._drain_after = (self.after(60, self._drain) if self._timer_alive() else None)
        except tk.TclError:
            self._drain_after = None

    # ── API ────────────────────────────────────────────────────────────────
    def set_cwd(self, folder: Path) -> None:
        self.cwd = Path(folder)
        try:
            self.cwd_label.configure(text=_short_path(self.cwd))
        except tk.TclError:
            pass
        if self._session is not None and self._session.running:
            self._session.set_cwd(self.cwd)

    def clear(self) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    def _append(self, text: str) -> None:
        if not text:
            return
        tag = "out"
        if text.startswith("[") and "]" in text[:80]:
            tag = "info"
        self.output.configure(state="normal")
        self.output.insert("end", text, tag)
        self.output.see("end")
        self.output.configure(state="disabled")
        if self.on_output:
            self.on_output(text)

    def _write(self, text: str, tag: str = "") -> None:
        self.output.configure(state="normal")
        self.output.insert("end", text, tag)
        self.output.see("end")
        self.output.configure(state="disabled")

    def write_text(self, text: str, tag: str = "") -> None:
        """Показати ТЕКСТ у терміналі (публічний метод для звітів).

        Навіщо окремий метод. Самодіагностика кликала ``write_text``, якого
        не існувало — виняток ловився й звіт ішов у лог, а користувач бачив
        порожній термінал. Тепер звіт справді видно там, де на нього
        чекають.

        Дописує рядок цілком: без переводу рядка в кінці ``print``-подібні
        виклики склеювали б рядки звіту в один.
        """
        body = str(text or "")
        if not body:
            return
        if not body.endswith("\n"):
            body += "\n"
        for line in body.splitlines(keepends=True):
            try:
                self._write(line, tag)
            except tk.TclError:
                return
        try:
            self.output.see("end")
        except tk.TclError:
            pass

    def _submit(self) -> None:
        command = self.entry.get().strip()
        if not command:
            return
        self.entry.delete(0, "end")
        self._history.append(command)
        self._history_pos = len(self._history)
        self.run(command)

    def run(self, command: str) -> None:
        command = (command or "").strip()
        if not command:
            return
        self._write(f"\n{_short_path(self.cwd, 40)} › {command}\n", "cmd")
        if self.on_status:
            self.on_status(f"Термінал: {command}")
        session = self._session
        if session is None or not session.running:
            self.start()
            session = self._session
        if session is not None and session.running:
            def worker() -> None:
                code, _output = session.run(command)
                # Рядки вже прийшли через on_output. Повторно їх не друкуємо:
                # інакше кожна команда з'являлась у вікні двічі.
                self._ui_queue.put(("done", (code, "")))

            threading.Thread(target=worker, daemon=True).start()
            return
        # Запасний шлях: одноразовий процес, якщо постійну сесію підняти не вдалось.
        def once() -> None:
            code, output = shell_session.run_once(command, self.cwd)
            self._ui_queue.put(("done", (code, output)))

        threading.Thread(target=once, daemon=True).start()

    def _apply_finish(self, code: int, output: str) -> None:
        if output:
            self._append(output if output.endswith("\n") else output + "\n")
        if code not in (0, None):
            self._write(f"[код завершення: {code}]\n", "exit_err")
        else:
            self._write("[код завершення: 0]\n", "exit_ok")
        session = self._session
        if session is not None:
            try:
                self._sync_cwd_label(session.cwd)
            except Exception:  # noqa: BLE001
                pass

    def _sync_cwd_label(self, folder: Path) -> None:
        """Оновити підпис теки, не надсилаючи зайвий ``cd`` в оболонку."""
        self.cwd = Path(folder)
        try:
            self.cwd_label.configure(text=_short_path(self.cwd))
        except tk.TclError:
            pass


    def _timer_alive(self) -> bool:
        """Чи можна ще планувати ``after`` (віджет існує й вікно живе)."""
        try:
            return bool(self.winfo_exists())
        except Exception:  # noqa: BLE001 - віджет уже знищено
            return False

    def interrupt(self) -> None:
        if self._session is not None and self._session.running:
            self._session.interrupt()
            self._write("[перервано]\n", "err")
        else:
            self._write("[сесія не запущена]\n", "err")

    def stop(self) -> None:
        """Зупинити процес (використовується при закритті вікна)."""
        job = getattr(self, "_drain_after", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
            self._drain_after = None
        if self._session is not None:
            try:
                self._session.stop()
            finally:
                self._session = None

    def _on_destroy(self, event=None) -> None:
        """Зняти таймер при знищенні панелі.

        Без цього запланований ``after(60, self._drain)`` лишається в Tcl,
        його команда зникає разом із віджетом — і Tk друкує «invalid
        command name ..._drain», а закриття вікна падає з «application has
        been destroyed».
        """
        if event is not None and getattr(event, "widget", self) is not self:
            return
        self.stop()

    # ── історія ────────────────────────────────────────────────────────────
    def _history_up(self, _event=None) -> str:
        if not self._history:
            return "break"
        if self._history_pos == len(self._history):
            self._pending_line = self.entry.get()
        self._history_pos = max(0, self._history_pos - 1)
        self.entry.delete(0, "end")
        self.entry.insert(0, self._history[self._history_pos])
        return "break"

    def _history_down(self, _event=None) -> str:
        if not self._history:
            return "break"
        self._history_pos = min(len(self._history), self._history_pos + 1)
        self.entry.delete(0, "end")
        if self._history_pos < len(self._history):
            self.entry.insert(0, self._history[self._history_pos])
        else:
            self.entry.insert(0, self._pending_line)
        return "break"
