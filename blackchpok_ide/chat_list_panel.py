"""Бічна панель сесій: чати й агенти в одному списку.

    ┌──────────────────────────────┐
    │  ⌕ Пошук…                    │
    │  СЕСІЇ ТА АГЕНТИ         12  │
    │  ┌────────────────────────┐  │
    │  │ ● Назва сесії      5 хв│  │   ← статус агента + час
    │  │ │   останнє повідомлен…  ⊟ × │   ← архівувати / закрити
    │  └────────────────────────┘  │
    │  ○ Інша сесія     щойно      │
    │  …                           │
    │  [Активні]  [Архів]          │
    └──────────────────────────────┘

«Чати» й «Агенти» — це одна сутність: кожна розмова і є сесія агента, тож
список один. Кожна сесія — м'яка картка: світле тло, статус (Working /
Completed / Queued), час і прев'ю останнього повідомлення. Поки агент
працює — крапка пульсує. Біля кожного рядка живуть дві іконки: «архівувати»
й «закрити» (вони з'являються під курсором, щоб не захаращувати список).
Усі інші дії (закріпити, експорт, дублювати) — у контекстному меню.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable, Optional

from . import pulse, theme, widgets
from .chat_store import (
    STATUS_DONE,
    STATUS_IDLE,
    STATUS_QUEUED,
    STATUS_WORKING,
)

LOG = logging.getLogger("blackchpok.chats")

#: Людські підписи статусів.
STATUS_LABELS = {
    STATUS_WORKING: "Working",
    STATUS_DONE: "Completed",
    STATUS_QUEUED: "Queued",
    STATUS_IDLE: "",
}

#: Скільки символів назви лишаємо, коли рядок вузький.
COMPACT_TITLE_CHARS = 26

#: Панель, вужча за це, не показує правий блок «час · статус» окремою
#: колонкою — інакше назва чату обрізається до кількох символів.
NARROW_PANEL_WIDTH = 320


class _SessionRow(tk.Frame):
    """Картка однієї сесії агента з іконками архівування й закриття."""

    def __init__(
        self,
        master: tk.Misc,
        chat,
        *,
        active: bool,
        fonts: theme.Theme,
        on_open: Callable[[], None],
        on_menu: Callable[[object, object], None],
        on_archive: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
        compact: bool = False,
        narrow: bool = False,
    ) -> None:
        bg = theme.BG_ACTIVE if active else theme.BG_CARD
        super().__init__(master, bg=bg, bd=0, highlightthickness=0, cursor="hand2")
        self.chat = chat
        self._bg = bg
        self._active = active
        self._compact = compact
        self._narrow = narrow
        self._on_archive = on_archive
        self._on_close = on_close
        self.columnconfigure(1, weight=1)

        # ── колонка 0: статус-індикатор агента
        self.dot = pulse.PulseDot(self, size=11, bg=bg, state=self._dot_state(chat.status))
        self.dot.grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=(9, 8))

        # ── колонка 1: назва + прев'ю
        title = chat.title or "Новий агент"
        if chat.pinned:
            title = "★ " + title
        limit = COMPACT_TITLE_CHARS if compact else 60
        if len(title) > limit:
            title = title[: limit - 1] + "…"
        self.title_label = tk.Label(
            self, text=title, bg=bg,
            fg=theme.FG_BRIGHT if active else theme.FG,
            font=("Segoe UI", 9, "bold" if active else "normal"),
            anchor="w", justify="left",
        )
        self.title_label.grid(row=0, column=1, sticky="ew", padx=(0, 4), pady=(8, 0))

        preview = (chat.preview(72) or "Порожня сесія")
        if compact:
            preview = (chat.preview(40) or "Порожня сесія")
        self.preview_label = tk.Label(
            self, text=preview, bg=bg, fg=theme.FG_FAINT,
            font=("Segoe UI", 8), anchor="w", justify="left",
        )
        self.preview_label.grid(row=1, column=1, sticky="ew", padx=(0, 4), pady=(1, 8))

        # ── колонка 2: час + статус праворуч (лише коли є місце)
        status_text = STATUS_LABELS.get(chat.status, "")
        time_text = chat.age_text
        if status_text and status_text != STATUS_LABELS.get(STATUS_IDLE):
            caption = f"{time_text} · {status_text}" if time_text not in ("щойно",) else status_text
        else:
            caption = time_text
        # У вузькій колонці правий блок з'їдає назву: тоді час переїздить
        # у другий рядок, а назва отримує всю ширину. Без цього рядок
        # виглядав як «Поясни т 2 хв · Completed» — обрізана назва.
        show_meta = not narrow
        self.meta_label = tk.Label(
            self, text=caption, bg=bg, fg=theme.FG_FAINT,
            font=("Segoe UI", 7), anchor="e", justify="right",
        )
        if show_meta:
            self.meta_label.grid(row=0, column=2, sticky="e", padx=(0, 6), pady=(9, 0))

        self.status_label = tk.Label(
            self, text="", bg=bg, fg=theme.FG_FAINT,
            font=("Segoe UI", 7), anchor="e",
        )
        if status_text:
            colour = {
                STATUS_WORKING: theme.STATUS_WORKING,
                STATUS_DONE: theme.FG_FAINT,
                STATUS_QUEUED: theme.STATUS_QUEUED,
            }.get(chat.status, theme.FG_FAINT)
            self.status_label.configure(text="● " + status_text, fg=colour)
        if show_meta:
            self.status_label.grid(row=1, column=2, sticky="e", padx=(0, 6), pady=(1, 8))
        elif status_text:
            # Вузько: статус і час стають частиною другого рядка.
            extra = " · ".join(part for part in (time_text, status_text) if part)
            self.preview_label.configure(text=f"{extra} · {preview}")

        # ── колонка 3: іконки дій (архівувати · закрити)
        self.actions_host = tk.Frame(self, bg=bg, bd=0, highlightthickness=0)
        self.actions_host.grid(row=0, column=3, rowspan=2, sticky="e", padx=(0, 6))
        self.archive_btn = self._make_icon(
            "⊟", "Архівувати сесію" if not chat.archived else "Повернути з архіву",
            self._archive)
        self.archive_btn.pack(side="left", padx=(0, 1))
        # В архіві «×» видаляє остаточно — підказка має це казати, інакше
        # кнопка виглядає як «закрити», а насправді стирає розмову.
        self.close_btn = self._make_icon(
            "×", "Видалити назавжди" if chat.archived else "Закрити чат",
            self._close)
        self.close_btn.pack(side="left")

        for widget in (self, self.title_label, self.preview_label, self.meta_label):
            widget.bind("<Button-1>", lambda _e: on_open())
            widget.bind("<Button-3>", lambda e: on_menu(chat, e))
            widget.bind("<Enter>", self._hover_on)
            widget.bind("<Leave>", self._hover_off)
        self.dot.bind("<Button-1>", lambda _e: on_open())
        self.dot.bind("<Button-3>", lambda e: on_menu(chat, e))
        self.status_label.bind("<Button-1>", lambda _e: on_open())
        self.status_label.bind("<Button-3>", lambda e: on_menu(chat, e))
        self._hover_on()

    def _make_icon(self, text: str, tip: str, command) -> tk.Label:
        """Іконка дії в рядку сесії (досить велика, щоб у неї влучити)."""
        label = tk.Label(self.actions_host, text=text, bg=self._bg, fg=theme.FG_FAINT,
                         font=("Segoe UI", 12), padx=4, pady=1, cursor="hand2",
                         bd=0, highlightthickness=0)
        label.bind("<Button-1>", lambda _e: self._run(command))
        label.bind("<Enter>", lambda _e: self._icon_hover(label, True))
        label.bind("<Leave>", lambda _e: self._icon_hover(label, False))
        label.bind("<Button-3>", lambda _e: "break")
        try:
            widgets.Tip(label, tip)
        except Exception:  # noqa: BLE001 - підказка не обов'язкова
            pass
        return label

    @staticmethod
    def _run(command) -> None:
        if command is None:
            return
        try:
            command()
        except Exception:  # noqa: BLE001 - дія рядка не має валити список
            LOG.debug("Дія рядка сесії впала", exc_info=True)

    def _icon_hover(self, label: tk.Label, entering: bool) -> None:
        try:
            label.configure(fg=theme.FG_BRIGHT if entering else theme.FG_FAINT)
        except tk.TclError:
            pass

    def _archive(self) -> None:
        self._run(self._on_archive)

    def _close(self) -> None:
        self._run(self._on_close)

    # ── вигляд ─────────────────────────────────────────────────────────────
    @staticmethod
    def _dot_state(status: str) -> str:
        if status == STATUS_WORKING:
            return pulse.PulseDot.RUNNING
        if status == STATUS_DONE:
            return pulse.PulseDot.DONE
        return pulse.PulseDot.IDLE

    def _hover_on(self, _event=None) -> None:
        if self._active:
            return
        self._recolor(theme.BG_HOVER)

    def _hover_off(self, _event=None) -> None:
        if self._active:
            return
        self._recolor(theme.BG_CARD)

    def _recolor(self, bg: str) -> None:
        """Перефарбувати рядок і всі його підписи (колір береться з теми)."""
        self._bg = bg
        try:
            self.configure(bg=bg)
            for widget in (self.title_label, self.preview_label,
                           self.meta_label, self.status_label, self.dot,
                           self.actions_host, self.archive_btn, self.close_btn):
                widget.configure(bg=bg)
        except tk.TclError:
            pass

    def refresh_status(self) -> None:
        """Оновити статус-крапку й підпис (без перестворення рядка).

        Підпис теж перемальовується: раніше оновлювалась лише крапка, і
        завершена сесія назавжди лишалась із текстом «Working» у списку.
        """
        state = self._dot_state(self.chat.status)
        try:
            self.dot.set_state(state)
            if self.chat.status == STATUS_QUEUED:
                self.dot.set_colour(theme.STATUS_QUEUED)
            elif self.chat.status == STATUS_IDLE:
                self.dot.set_colour(theme.FG_FAINT)
        except tk.TclError:
            pass
        status_text = STATUS_LABELS.get(self.chat.status, "")
        try:
            if status_text:
                colour = {
                    STATUS_WORKING: theme.STATUS_WORKING,
                    STATUS_DONE: theme.FG_FAINT,
                    STATUS_QUEUED: theme.STATUS_QUEUED,
                }.get(self.chat.status, theme.FG_FAINT)
                self.status_label.configure(text="● " + status_text, fg=colour)
            else:
                self.status_label.configure(text="")
            # Час у першому рядку теж міняється після завершення роботи.
            time_text = self.chat.age_text
            if status_text and time_text not in ("щойно", ""):
                self.meta_label.configure(text=f"{time_text} · {status_text}")
            elif status_text:
                self.meta_label.configure(text=status_text)
            else:
                self.meta_label.configure(text=time_text)
        except tk.TclError:
            pass


class ChatListPanel(tk.Frame):
    """Список сесій (чати = агенти) із керуванням."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        store=None,
        on_open: Optional[Callable[[str], None]] = None,
        on_new: Optional[Callable[[], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_close_chat: Optional[Callable[[str], bool]] = None,
        on_cleared: Optional[Callable[[int], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.store = store
        self.on_open = on_open
        self.on_new = on_new
        self.on_status = on_status
        #: Скільки чатів видалено кнопкою «🗑» — оболонка скидає стан.
        self.on_cleared = on_cleared
        #: Закриття чату з рядка. Оболонка сама вирішує, що це означає
        #: (прибрати зі списку / закрити сесію агента), і повертає True,
        #: якщо чат справді закрито.
        self.on_close_chat = on_close_chat
        self.show_archived = False
        self.query = ""
        self.compact = False
        self._active_id = ""
        self._rows: dict[str, _SessionRow] = {}
        #: Ширина, за якої малювався список (перемальовуємо при зміні).
        self._built_width = 0
        self._build()
        self.refresh()
        # Панель можна розтягнути — рядки мають перемалюватись під ширину.
        self.bind("<Configure>", self._on_resize, add="+")

    def _on_resize(self, event=None) -> None:
        width = int(getattr(event, "width", 0) or 0)
        if width <= 1:
            return
        # Поріг переходу «вузько / широко» — саме він змінює розкладку рядка.
        before = self._built_width >= NARROW_PANEL_WIDTH
        after = width >= NARROW_PANEL_WIDTH
        self._built_width = width
        if before != after:
            self.refresh()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        # Кнопка «New Agent» живе вгорі сайдбара (будує вікно) — тут лише
        # пошук, заголовок і список, щоб не дублювати головну дію.

        # ── пошук
        search_host = tk.Frame(self, bg=theme.BG_CARD)
        search_host.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 8))
        search_host.columnconfigure(1, weight=1)
        icon = tk.Label(search_host, text="⌕", bg=theme.BG_CARD, fg=theme.FG_FAINT,
                        font=("Segoe UI", 10))
        icon.grid(row=0, column=0, padx=(8, 2), pady=2)
        self.search_entry = tk.Entry(
            search_host, bg=theme.BG_CARD, fg=theme.FG, insertbackground=theme.FG_BRIGHT,
            relief="flat", font=("Segoe UI", 9), bd=0, highlightthickness=0,
        )
        self.search_entry.grid(row=0, column=1, sticky="ew", ipady=5, padx=(0, 6))
        self.search_entry.bind("<KeyRelease>", self._on_search)
        self.search_entry.bind("<Escape>", lambda _e: (self.search_entry.delete(0, "end"),
                                                       self._on_search(None)))
        self._search_placeholder = "Пошук…"
        self._show_search_placeholder(True)

        # ── заголовок секції: чати й агенти — це один список
        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=2, column=0, sticky="ew", padx=(16, 12), pady=(2, 4))
        head.columnconfigure(0, weight=1)
        self.section_label = tk.Label(head, text="ЧАТИ Й АГЕНТИ", bg=theme.BG_ALT,
                                      fg=theme.FG_FAINT, font=("Segoe UI", 7, "bold"),
                                      anchor="w")
        self.section_label.grid(row=0, column=0, sticky="w")
        widgets.Tip(self.section_label,
                    "Один список: кожна розмова — це сесія агента. "
                    "Іконки праворуч архівують або закривають чат.")
        self.count_label = tk.Label(head, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                    font=("Segoe UI", 7), anchor="e")
        self.count_label.grid(row=0, column=1, sticky="e")

        # ── список
        self.scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.scroll.grid(row=3, column=0, sticky="nsew", padx=(4, 4), pady=(0, 6))
        self.host = self.scroll.inner

        # ── перемикач архіву
        tabs_row = tk.Frame(self, bg=theme.BG_ALT)
        tabs_row.grid(row=4, column=0, sticky="ew", padx=(14, 10), pady=(0, 8))
        self.active_tab = widgets.HoverLabel(
            tabs_row, "Активні", lambda: self._set_archived(False),
            bg=theme.BG_ACTIVE, fg=theme.FG_BRIGHT,
            font=("Segoe UI", 8), padx=10, pady=3)
        self.active_tab.pack(side="left", padx=(0, 4))
        self.arch_tab = widgets.HoverLabel(
            tabs_row, "Архів", lambda: self._set_archived(True),
            bg=theme.BG_ALT, fg=theme.FG_FAINT,
            font=("Segoe UI", 8), padx=10, pady=3)
        self.arch_tab.pack(side="left")

        # ── видалити всі чати
        self.clear_btn = widgets.IconButton(
            tabs_row, "🗑", self._delete_all, bg=theme.BG_ALT, fg=theme.FG_FAINT,
            font=("Segoe UI", 9), tooltip="Видалити всі чати")
        self.clear_btn.pack(side="right")

    def _show_search_placeholder(self, on: bool) -> None:
        if on:
            self.search_entry.insert(0, self._search_placeholder)
            self.search_entry.configure(fg=theme.FG_FAINT)

    def _search_text(self) -> str:
        value = self.search_entry.get().strip()
        if value == self._search_placeholder:
            return ""
        return value

    # ── дії ────────────────────────────────────────────────────────────────
    def _notify(self, text: str) -> None:
        if self.on_status:
            self.on_status(text)

    def _new(self) -> None:
        if self.on_new:
            self.on_new()

    def _set_archived(self, archived: bool) -> None:
        self.show_archived = archived
        self.refresh()

    def _on_search(self, _event=None) -> None:
        self.query = self._search_text()
        self.refresh()

    # ── малювання ──────────────────────────────────────────────────────────
    def set_active(self, chat_id: str) -> None:
        """Підсвітити активну сесію без перечитування сховища."""
        self._active_id = chat_id or ""

    def refresh(self) -> None:
        for child in self.host.winfo_children():
            child.destroy()
        self._rows.clear()
        if self.store is None:
            self.count_label.configure(text="")
            return

        chats = self.store.search(self.query) if self.query else None
        if chats is None:
            chats = self.store.visible(archived=self.show_archived)
        else:
            chats = [c for c in chats if bool(c.archived) == self.show_archived]

        counts = self.store.counts()
        self.count_label.configure(text=f"{counts.get('усього', 0)}")
        self.active_tab.configure(bg=theme.BG_ALT if self.show_archived else theme.BG_ACTIVE,
                                  fg=theme.FG_FAINT if self.show_archived else theme.FG_BRIGHT)
        self.arch_tab.configure(bg=theme.BG_ACTIVE if self.show_archived else theme.BG_ALT,
                                fg=theme.FG_BRIGHT if self.show_archived else theme.FG_FAINT)

        if not chats:
            text = "Архів порожній" if self.show_archived else (
                "Нічого не знайдено" if self.query else "Чатів ще немає — створи перший.")
            tk.Label(self.host, text=text, bg=theme.BG_ALT, fg=theme.FG_FAINT,
                     font=("Segoe UI", 8), justify="left", anchor="w",
                     wraplength=max(160, self.winfo_width() - 32)).pack(
                anchor="w", fill="x", padx=14, pady=12)
            return

        for chat in chats:
            self._chat_row(chat)

    def set_compact(self, compact: bool) -> None:
        """Вузька колонка: коротші назви, менше службових підписів."""
        target = bool(compact)
        if target == self.compact:
            return
        self.compact = target
        self.refresh()

    def _chat_row(self, chat) -> None:
        store_active = getattr(self.store, "active_id", "")
        active = chat.id == (self._active_id or store_active)
        row = _SessionRow(
            self.host, chat, active=active, fonts=self.fonts,
            on_open=lambda c=chat: self.on_open and self.on_open(c.id),
            on_menu=lambda c, e: self._menu(c, e),
            on_archive=lambda c=chat: self._archive(c),
            on_close=lambda c=chat: self._close_chat(c),
            compact=self.compact,
            narrow=self._narrow(),
        )
        row.pack(fill="x")
        self._rows[chat.id] = row

    def _narrow(self) -> bool:
        """Чи вузька сама панель (а не вікно).

        Список сесій живе в бічній колонці сталої ширини, тож орієнтуватись
        на ширину вікна марно: на 1560 px панель усе одно 244 px, і
        правий блок «час · статус» з'їдав назву чату.
        """
        try:
            width = self.winfo_width()
        except tk.TclError:
            return False
        if width <= 1:
            return self.compact
        return width < NARROW_PANEL_WIDTH

    def _close_chat(self, chat) -> None:
        """Закрити чат з іконки «×» у рядку.

        Поведінка залежить від вкладки, у якій стоїть рядок:

        * **активні** — питаємо оболонку: чат може бути сесією агента, і
          «закрити» означає прибрати його зі списку (архівувати);
        * **архів** — «×» означає СПРАВЖНЄ видалення з підтвердженням.
          Раніше тут виконувався той самий шлях, що й для активних, тобто
          чат просто архівувався ЩЕ РАЗ — і з архіву не зникав ніколи.
          Саме на це скаржився користувач: «з архіву не видаляються чати».
        """
        if chat is None:
            return
        # ── Архів: «×» = видалити остаточно ───────────────────────────────
        if getattr(chat, "archived", False):
            self._delete(chat)
            return
        closed = False
        if self.on_close_chat is not None:
            try:
                closed = bool(self.on_close_chat(chat.id))
            except Exception:  # noqa: BLE001 - іконка не має валити список
                LOG.debug("on_close_chat упав", exc_info=True)
                closed = False
        if closed:
            self._notify(f"Чат закрито: {chat.title or 'Без назви'}")
            self.refresh()
            return
        # Запасний шлях: без оболонки закриття = архівування.
        self.store.archive(chat.id, True)
        self.refresh()
        self._notify(f"Чат прибрано зі списку: {chat.title or 'Без назви'}")

    def update_row_status(self, chat_id: str, status: str) -> None:
        """Живе оновлення статусу рядка (без повного refresh)."""
        row = self._rows.get(chat_id)
        if row is None:
            return
        row.chat.status = status
        row.refresh_status()

    def _menu(self, chat, event) -> None:
        items: list[tuple[str, Optional[Callable[[], None]]]] = [
            ("Відкрити", lambda: self.on_open and self.on_open(chat.id)),
            ("", None),
            ("Закріпити" if not chat.pinned else "Відкріпити",
             lambda: self._pin(chat)),
            ("Архівувати" if not chat.archived else "Повернути з архіву",
             lambda: self._archive(chat)),
            ("Дублювати", lambda: self._duplicate(chat)),
            ("Перейменувати…", lambda: self._rename(chat)),
            ("", None),
            ("Експорт у Markdown", lambda: self._export(chat)),
            ("", None),
            ("Видалити", lambda: self._delete(chat)),
        ]
        widgets.context_menu(self, items, event)

    def _pin(self, chat) -> None:
        self.store.pin(chat.id, not chat.pinned)
        self.refresh()

    def _archive(self, chat) -> None:
        self.store.archive(chat.id, not chat.archived)
        self.refresh()
        self._notify("Чат архівовано." if not chat.archived else "Чат повернуто з архіву.")

    def _duplicate(self, chat) -> None:
        copy = self.store.duplicate(chat.id)
        self.refresh()
        if copy:
            self._notify(f"Створено копію: {copy.title}")

    def _rename(self, chat) -> None:
        from tkinter import simpledialog

        name = simpledialog.askstring("Перейменувати сесію", "Нова назва:",
                                      initialvalue=chat.title, parent=self)
        if name:
            self.store.rename(chat.id, name)
            self.refresh()

    def _export(self, chat) -> None:
        from tkinter import filedialog

        text = self.store.export_markdown(chat.id)
        target = filedialog.asksaveasfilename(
            parent=self, title="Експорт сесії", defaultextension=".md",
            initialfile=f"{chat.title or 'chat'}.md",
            filetypes=[("Markdown", "*.md"), ("Усі файли", "*.*")],
        )
        if not target:
            return
        try:
            from pathlib import Path

            Path(target).write_text(text, encoding="utf-8")
            self._notify(f"Експортовано: {target}")
        except OSError as exc:
            self._notify(f"Не вдалось зберегти: {exc}")

    def _delete(self, chat) -> None:
        from tkinter import messagebox

        if not messagebox.askyesno(
            "Видалити сесію",
            f"Видалити «{chat.title or 'Без назви'}»?\n\nЦе незворотно.",
            parent=self,
        ):
            return
        self.store.delete(chat.id)
        self.refresh()
        self._notify("Сесію видалено.")

    def _delete_all(self) -> None:
        """Видалити всі чати (у вкладці архіву — лише архівні).

        Підтвердження обов'язкове: дія незворотна, і випадковий клік по
        іконці не має стирати всю історію роботи.
        """
        from tkinter import messagebox

        if self.store is None:
            return
        archived_only = self.show_archived
        total = len(self.store.chats)
        if archived_only:
            scoped = sum(1 for chat in self.store.chats if chat.archived)
            what = f"усі чати в архіві ({scoped})"
        else:
            scoped = total
            what = f"ВСІ чати ({total}), разом з архівом"
        if not scoped:
            self._notify("Немає чого видаляти.")
            return
        if not messagebox.askyesno(
            "Видалити всі чати",
            f"Видалити {what}?\n\nЦе незворотно: історія розмов зникне.",
            parent=self,
        ):
            return
        removed = self.store.delete_all(archived=archived_only)
        self.refresh()
        self._notify(f"Видалено чатів: {removed}.")
        if self.on_cleared is not None:
            try:
                self.on_cleared(removed)
            except Exception:  # noqa: BLE001 - оболонка не має ламати список
                LOG.debug("on_cleared упав", exc_info=True)


__all__ = ["ChatListPanel", "STATUS_LABELS"]
