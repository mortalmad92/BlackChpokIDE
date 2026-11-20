"""Екран «Спершу вибери теку проєкту» замість порожнього чату.

Логіка: агент працює з файлами, тож без робочої теки кожен його крок
або провалюється, або (гірше) виконується в домашній теці користувача.
Тому до вибору проєкту в колонці діалогу замість чату показується цей
екран із двома діями: вибрати теку або створити нову.

Екран навмисно самодостатній: він не знає ні про сховище чатів, ні про
агента — лише кличе передані колбеки.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import theme, widgets


class ProjectGate(tk.Frame):
    """Заглушка замість чату, поки не вибрано теку проєкту."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        *,
        on_pick: Optional[Callable[[], None]] = None,
        on_create: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG, bd=0, highlightthickness=0)
        self.fonts = fonts
        self.on_pick = on_pick
        self.on_create = on_create
        self._build()

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        card = widgets.Card(self, bg=theme.BG_CARD, border=theme.BORDER)
        card.grid(row=1, column=0, padx=theme.SPACE_3XL, pady=theme.SPACE_XL)
        self.card = card
        body = card.inner
        body.columnconfigure(0, weight=1)

        self.icon = tk.Label(body, text="🗂", bg=theme.BG_CARD, fg=theme.ACCENT,
                             font=theme.font(26))
        self.icon.grid(row=0, column=0, pady=(theme.SPACE_XL, theme.SPACE_MD))

        self.title = tk.Label(body, text="Спершу вибери теку проєкту",
                              bg=theme.BG_CARD, fg=theme.FG_BRIGHT,
                              font=self.fonts.ui_h1)
        self.title.grid(row=1, column=0, padx=theme.SPACE_2XL)

        self.note = tk.Label(
            body,
            text=("Агент працює з файлами твого проєкту: читає їх, править і "
                  "запускає перевірки. Без робочої теки він не має де працювати, "
                  "тому чат відкриється після вибору папки."),
            bg=theme.BG_CARD, fg=theme.FG_DIM, font=self.fonts.ui_small,
            justify="center", wraplength=460,
        )
        self.note.grid(row=2, column=0, padx=theme.SPACE_2XL,
                       pady=(theme.SPACE_SM, theme.SPACE_LG))

        buttons = tk.Frame(body, bg=theme.BG_CARD)
        buttons.grid(row=3, column=0, pady=(0, theme.SPACE_XL))

        #: Кнопка «Працювати тут» — створюється ПЕРШОЮ, але показується лише
        #: тоді, коли попередній проєкт справді існує. Саме вона має бути
        #: головною дією екрана: користувач просив, щоб застосунок
        #: автоматично продовжував роботу в останньому проєкті й не питав
        #: теку щоразу.
        self.use_btn = widgets.Chip(buttons, "✓  Продовжити тут",
                                    self._use_current, font=theme.font(10))
        widgets.Tip(self.use_btn,
                    "Продовжити з уже вибраною текою, не шукаючи її знову")

        self.pick_btn = widgets.Chip(buttons, "🗂  Інша папка…",
                                     self._pick, font=theme.font(10))
        widgets.Tip(self.pick_btn, "Відкрити теку, з якою працюватиме агент")

        # ── «Створити нову» — ЦЕ ІНША ДІЯ, НІЖ «Вибрати папку» ────────────
        # Раніше обидві кнопки відкривали той самий ``askdirectory``, і
        # користувач слушно питав: «вибери папку і створити папку виконує
        # одну й ту саму дію». Тепер «створити» справді створює: спершу
        # питає МІСЦЕ (батьківську теку), потім ІМ'Я нової папки — і лише
        # тоді створює її на диску й відкриває.
        self.create_btn = widgets.Chip(buttons, "＋  Створити нову",
                                       self._create, font=theme.font(10))
        widgets.Tip(self.create_btn,
                    "Спитає місце на диску й ім'я — і створить теку проєкту")

        self.hint = tk.Label(body, text="", bg=theme.BG_CARD, fg=theme.FG_FAINT,
                             font=theme.font(8), justify="center", wraplength=460)
        self.hint.grid(row=4, column=0, padx=theme.SPACE_2XL,
                       pady=(0, theme.SPACE_LG))

        # ── поточна тека й кнопка «працювати тут» ──────────────────────────
        # Екран мусить відповідати на питання «з чим я працюю», а не лише
        # просити вибрати. Інакше користувач щоразу шукає папку заново,
        # навіть коли вона вже вибрана.
        self.current = tk.Label(body, text="", bg=theme.BG_CARD, fg=theme.FG,
                                font=self.fonts.ui_small, justify="center",
                                wraplength=460)
        self.current.grid(row=5, column=0, padx=theme.SPACE_2XL)
        # Кнопка показується лише коли тека справді є.
        self._current_path = ""
        self._on_use_current: Optional[Callable[[], None]] = None
        #: Порядок кнопок, поки «працювати тут» недоступна: вибір → створення.
        self._repack_without_use()

    # ── дії ────────────────────────────────────────────────────────────────
    def _pick(self) -> None:
        if self.on_pick is not None:
            self.on_pick()

    def _create(self) -> None:
        if self.on_create is not None:
            self.on_create()

    def _use_current(self) -> None:
        if self._on_use_current is not None:
            self._on_use_current()

    # ── стан ───────────────────────────────────────────────────────────────
    def set_hint(self, text: str) -> None:
        """Показати пояснення під кнопками (напр. чому теку не прийнято)."""
        try:
            self.hint.configure(text=text)
        except tk.TclError:
            pass

    def set_current(self, path: str, *, on_use: Optional[Callable[[], None]] = None) -> None:
        """Показати поточну теку й дозволити продовжити з нею.

        ``on_use`` викликається кнопкою «Продовжити тут». Якщо шлях
        порожній — кнопка ховається, бо продовжувати нема з чим.
        """
        clean = str(path or "").strip()
        self._current_path = clean
        self._on_use_current = on_use
        try:
            if clean:
                self.current.configure(text=f"Минулого разу: {clean}")
                self._repack_with_use()
            else:
                self.current.configure(text="")
                self._repack_without_use()
        except tk.TclError:
            pass

    def _repack_without_use(self) -> None:
        """Кнопки без «Продовжити тут»: вибір іншої теки → створити нову."""
        self.use_btn.pack_forget()
        self.pick_btn.pack_forget()
        self.create_btn.pack_forget()
        self.pick_btn.pack(side="left", padx=(0, theme.SPACE_MD))
        self.create_btn.pack(side="left")

    def _repack_with_use(self) -> None:
        """«Продовжити тут» — ГОЛОВНА дія: стоїть першою й виділена.

        Решта — другорядні: людина, яка вже працювала з проєктом, має
        продовжити одним натисканням, без провідника.
        """
        self.use_btn.pack_forget()
        self.pick_btn.pack_forget()
        self.create_btn.pack_forget()
        self.use_btn.pack(side="left", padx=(0, theme.SPACE_MD))
        self.pick_btn.pack(side="left", padx=(0, theme.SPACE_MD))
        self.create_btn.pack(side="left")



__all__ = ["ProjectGate"]
