"""Панель «Скіли»: перелік інструкцій агента з теки .agents/skills.

Скіл можна ввімкнути (його інструкція потрапить у системний промпт),
поставити як задачу в чергу або надіслати в чат одним натисканням.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from . import skills as skills_module, theme, widgets


class SkillsPanel(tk.Frame):
    """Список скілів робочої теки."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        book: skills_module.SkillBook,
        *,
        on_status: Optional[Callable[[str], None]] = None,
        on_use: Optional[Callable[[skills_module.Skill], None]] = None,
        on_queue: Optional[Callable[[skills_module.Skill], None]] = None,
        on_open_file: Optional[Callable[[Path], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.book = book
        self.on_status = on_status
        self.on_use = on_use
        self.on_queue = on_queue
        self.on_open_file = on_open_file
        self._build()
        # Відкладений перший refresh: читання теки скілів — це файловий
        # обхід, і в конструкторі він додає час до запуску вікна. Панель
        # усе одно не видно, поки користувач не перемкне розділ.
        self.after(0, self.refresh)

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=(10, 2))
        head.columnconfigure(1, weight=1)

        tk.Label(head, text="СКІЛИ АГЕНТА", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                 font=("Segoe UI", 8, "bold")).grid(row=0, column=0, sticky="w")
        self.count_label = tk.Label(head, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 8), anchor="e")
        self.count_label.grid(row=0, column=1, sticky="e")

        actions = tk.Frame(self, bg=theme.BG_ALT)
        actions.grid(row=1, column=0, sticky="ew", padx=(8, 4), pady=(2, 6))
        widgets.Chip(actions, "＋ Новий скіл", self.create, font=("Segoe UI", 8)).pack(
            side="left", padx=(0, 4))
        widgets.Chip(actions, "⟳ Оновити", self.reload, font=("Segoe UI", 8)).pack(side="left")

        self.scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=(8, 4), pady=(0, 6))
        self.list_host = self.scroll.inner

        self.hint = tk.Label(
            self, text="Скіл — це тека .agents/skills/<назва>/SKILL.md з інструкцією для агента.",
            bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 8), justify="left",
            wraplength=260,
        )
        self.hint.grid(row=3, column=0, sticky="ew", padx=(12, 8), pady=(0, 10))

    # ── дії ────────────────────────────────────────────────────────────────
    def reload(self) -> None:
        self.book.reload()
        self.refresh()
        self._notify(f"Скілів знайдено: {len(self.book.skills)}")

    def create(self) -> None:
        from tkinter import simpledialog

        name = simpledialog.askstring("Новий скіл", "Назва скіла (латиницею або українською):",
                                      parent=self)
        if not name:
            return
        description = simpledialog.askstring("Новий скіл", "Коли застосовувати (коротко):",
                                            parent=self) or ""
        try:
            path = skills_module.create_skill(self.book.root, name, description)
        except OSError as exc:
            self._notify(f"Не вдалось створити скіл: {exc}")
            return
        self.book.reload()
        self.refresh()
        self._notify(f"Створено скіл: {path.parent.name}")
        if self.on_open_file:
            self.on_open_file(path)

    def _toggle(self, skill: skills_module.Skill) -> None:
        enabled = self.book.toggle(skill.name)
        self.refresh()
        self._notify(f"Скіл «{skill.name}» {'увімкнено' if enabled else 'вимкнено'}.")

    def _notify(self, text: str) -> None:
        if self.on_status:
            self.on_status(text)

    def _skill_menu(self, skill: skills_module.Skill, event) -> None:
        items: list[tuple[str, Optional[Callable[[], None]]]] = [
            ("Надіслати в чат", lambda: self.on_use and self.on_use(skill)),
            ("Додати в чергу", lambda: self.on_queue and self.on_queue(skill)),
            ("", None),
            ("Увімкнути/вимкнути", lambda: self._toggle(skill)),
            ("Відкрити SKILL.md", lambda: self.on_open_file and skill.path and self.on_open_file(skill.path)),
            ("Відкрити теку", lambda: self._open_folder(skill)),
        ]
        widgets.context_menu(self, items, event)

    def _open_folder(self, skill: skills_module.Skill) -> None:
        if not skill.path:
            return
        import subprocess

        try:
            subprocess.Popen(["explorer", "/select,", str(skill.path)])
        except OSError as exc:
            self._notify(f"Не вдалось відкрити теку: {exc}")

    # ── малювання ──────────────────────────────────────────────────────────
    def refresh(self) -> None:
        for child in self.list_host.winfo_children():
            child.destroy()
        skills = self.book.skills
        active = len([s for s in skills if s.enabled])
        self.count_label.configure(text=f"{len(skills)} · увімкнено {active}")
        if not skills:
            tk.Label(self.list_host, text="Скілів не знайдено.", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                     font=("Segoe UI", 9)).pack(anchor="w", padx=6, pady=10)
            return
        for skill in skills:
            self._skill_card(skill)

    def _skill_card(self, skill: skills_module.Skill) -> None:
        card = tk.Frame(self.list_host, bg=theme.BG_CARD, bd=0, highlightthickness=1,
                        highlightbackground=theme.ACCENT_SOFT if skill.enabled else theme.BORDER)
        card.pack(fill="x", padx=2, pady=(0, 4))
        card.columnconfigure(1, weight=1)

        mark = tk.Label(card, text="✓" if skill.enabled else "○", bg=theme.BG_CARD,
                        fg=theme.SUCCESS if skill.enabled else theme.FG_FAINT,
                        font=("Segoe UI", 10), cursor="hand2")
        mark.grid(row=0, column=0, padx=(8, 6), pady=(6, 0), sticky="n")
        mark.bind("<Button-1>", lambda _e: self._toggle(skill))

        title = tk.Label(card, text=skill.name, bg=theme.BG_CARD,
                         fg=theme.FG_BRIGHT if skill.enabled else theme.FG,
                         font=("Segoe UI", 9, "bold"), anchor="w")
        title.grid(row=0, column=1, sticky="ew", pady=(6, 0))

        description = tk.Label(card, text=skill.preview(180), bg=theme.BG_CARD, fg=theme.FG_DIM,
                               font=("Segoe UI", 8), justify="left", anchor="w", wraplength=250)
        description.grid(row=1, column=1, sticky="ew", pady=(1, 2))

        buttons = tk.Frame(card, bg=theme.BG_CARD)
        buttons.grid(row=2, column=1, sticky="w", pady=(0, 6))
        widgets.Chip(buttons, "У чат", lambda: self.on_use and self.on_use(skill),
                     font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        widgets.Chip(buttons, "У чергу", lambda: self.on_queue and self.on_queue(skill),
                     font=("Segoe UI", 8)).pack(side="left")

        for widget in (card, title, description):
            widget.bind("<Button-3>", lambda e, s=skill: self._skill_menu(s, e))
            widget.bind("<Double-1>", lambda _e, s=skill: self.on_use and self.on_use(s))
