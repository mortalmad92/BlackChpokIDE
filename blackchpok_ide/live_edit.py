"""Жива правка у відкритому редакторі: стара версія червона, нова — зелена.

Модуль працює з віджетом :class:`editor.CodeEditor` і показує правку агента
ПОКИ модель її ще пише. Це той «інлайн-діф», що є в Cursor і Windsurf:

* старі рядки лишаються на місці з червоним тлом (їх НЕ видаляємо);
* нові рядки дописуються нижче із зеленим тлом, по кілька символів за тік;
* угорі блоку з'являються дві кнопки — «Прийняти» і «Відхилити».

Чому не видаляємо старе одразу. Якщо замінити рядки відразу, людина
втрачає можливість порівняти й не бачить, що саме було. Тому спершу
показуємо обидві версії, а видалення робить «Прийняти».

Чому одна група undo. Під час стріму текст вставляється десятками
дрібних шматків. Без об'єднання ``Ctrl+Z`` скасовував би по одному
символу. Тому на час правки вимикаємо ``autoseparators`` і ставимо
роздільники (``edit_separator``) лише на початку й у кінці — уся правка
агента стає ОДНІЄЮ дією скасування.
"""

from __future__ import annotations

import logging
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import stream_apply, theme, widgets

LOG = logging.getLogger("blackchpok.stream_apply.ui")

#: Скільки мілісекунд між порціями вставки. 28 мс — це ~35 кадрів за
#: секунду: око бачить плавний набір, а головний потік не зайнятий.
TICK_MS = 28

#: Теги для підсвітки. Окремі від ``line_added`` (він показує зміни
#: відносно збереженого файлу назавжди) — ці живуть лише поки триває правка.
TAG_OLD = "agent_edit_old"
TAG_NEW = "agent_edit_new"

__all__ = ["LiveEdit", "TICK_MS"]


@dataclass
class LiveEdit:
    """Одна правка, яку зараз показує редактор.

    Об'єкт створює вікно на КОЖЕН блок SEARCH/REPLACE. Він сам стежить за
    таймером і за тим, щоб правка не «застрягла», якщо редактор закрили.
    """

    editor: "object"                      # editor.CodeEditor
    block: stream_apply.EditBlock
    #: Робоча тека — потрібна для читання поточного вмісту файлу.
    root: Optional[Path] = None
    on_done: Optional["object"] = None    # Callable[[LiveEdit, bool], None]
    on_status: Optional["object"] = None  # Callable[[str], None]
    #: Рядок, з якого починається показана правка (1-based, 0 — не знайдено).
    start_line: int = 0
    #: Скільки рядків займав старий фрагмент.
    old_lines: int = 0
    #: Чи правку вже застосовано або відхилено (тоді таймер мовчить).
    settled: bool = False
    #: Чи знайдено фрагмент у файлі. Ні — показуємо лише «+»-рядки.
    located: bool = False
    _stream: stream_apply.EditStream = field(default_factory=stream_apply.EditStream)
    _job: Optional[str] = None
    _insert_at: str = ""
    _inserted: int = 0
    _row: Optional["object"] = None
    #: Чи відкрита група скасування (див. :meth:`_close_group`).
    _group_open: bool = False
    #: Чи вже додано службовий ``\n`` у кінці нової версії.
    _newline_added: bool = False
    #: Куди вставляти нові рядки (позиція в редакторі одразу після старого).
    _anchor: str = ""
    #: Чи ця правка ЗАМІНЮЄ вміст файлу цілком (``write_file``).
    #:
    #: Для ``write_file`` моделі не треба вказувати старий фрагмент — вона
    #: переписує файл. Без цього прапорця новий вміст дописувався в кінець,
    #: і після «Прийняти» у файлі лишався ще й старий код.
    whole_file: bool = False

    # ── показ ──────────────────────────────────────────────────────────────
    def start(self) -> bool:
        """Почати показ: підсвітити старий фрагмент і підготувати вставку."""
        text = self._widget()
        if text is None:
            return False
        content = self.editor.get_text()  # type: ignore[attr-defined]
        begin, end, actual = stream_apply.locate(content, self.block.search)
        # ── write_file переписує файл ЦІЛКОМ ──────────────────────────────
        # Старого фрагмента тут немає й бути не може. Вважаємо «старим
        # вмістом» увесь файл: підсвічуємо його червоним, а новий текст
        # вставляємо ПІСЛЯ. «Прийняти» видалить старий вміст, і у файлі
        # лишиться рівно те, що написала модель.
        if self.whole_file:
            begin, end, actual = 0, len(content), content
        self.located = begin >= 0
        try:
            # ── ОДНА група скасування на всю правку ────────────────────────
            # Далі буде десятки дрібних ``insert``. Без цього ``Ctrl+Z``
            # скасовував би по одному шматку. ``autoseparators=False``
            # вимикає автоматичні межі, а два ``edit_separator`` окреслюють
            # правку агента як одну дію.
            text.edit_separator()
            text.configure(autoseparators=False)
            self._group_open = True
            if self.located:
                self.old_lines = max(1, len(content.splitlines())) if self.whole_file \
                    else len(actual.splitlines())
                old_begin = self._index_of(content, begin)
                # ── Межа старого фрагмента — ПОЧАТОК НАСТУПНОГО РЯДКА ──────
                # Кінець фрагмента майже завжди лежить усередині рядка.
                # Якщо підсвітити й видалити рівно його, після «Прийняти»
                # лишався б порожній рядок (``\\n`` від старого коду).
                # Тому беремо рядок ЦІЛКОМ, разом із його перевідом.
                old_end = self._line_after(content, end)
                self._anchor = old_end
                self.start_line = int(old_begin.split(".")[0])
                text.tag_add(TAG_OLD, old_begin, old_end)
                # Новий код іде на звільнене місце — одразу після старого.
                self._insert_at = old_end
            else:
                # Фрагмент не знайдено — правку все одно показуємо, але
                # внизу файлу й без червоного: підсвічувати чуже небезпечно.
                last = text.index("end-1c")
                self._anchor = last
                self.start_line = int(last.split(".")[0])
                self._insert_at = last
                self.on_status_text(
                    "фрагмент не знайдено у файлі — показую правку в кінці")
        except tk.TclError:
            return False
        self._stream.push(self.block.replace)
        self._tick()
        return True

    def _line_after(self, content: str, offset: int) -> str:
        """Індекс початку рядка, що йде ОДРАЗУ після зсуву ``offset``.

        Якщо фрагмент закінчився перевідом рядка, це вже початок наступного
        рядка. Інакше переходимо на наступний рядок і ставимо курсор на
        початок — новий код не має чіплятись до старого.
        """
        line = content[:offset].count("\n") + 1
        column = offset - (content.rfind("\n", 0, offset) + 1)
        if column == 0:
            # Фрагмент закінчився рівно на межі рядків.
            return f"{line}.0"
        return f"{line + 1}.0"

    def _close_group(self) -> None:
        """Закрити групу скасування: уся правка стала ОДНІЄЮ дією."""
        if not getattr(self, "_group_open", False):
            return
        self._group_open = False
        text = self._widget()
        if text is None:
            return
        try:
            text.edit_separator()
            text.configure(autoseparators=True)
        except tk.TclError:
            pass

    def _tick(self) -> None:
        """Порція вставки «зеленого» тексту (виклик із циклу подій)."""
        # Таймер спрацював — ідентифікатор більше не дійсний. Без цього
        # ``append`` бачив непорожній ``_job`` і не будив показ, тож
        # наступні шматки стріму лишались у буфері до кінця ходу.
        self._job = None
        if self.settled:
            return
        text = self._widget()
        if text is None:
            self.settled = True
            return
        piece = self._stream.take()
        if piece:
            try:
                self._insert_new(text, piece)
            except tk.TclError:
                self.settled = True
                return
        if self._stream.finished:
            # ── Новий код не має злипатись із наступним рядком ─────────────
            # Вставка йде ПЕРЕД старим рядком, що лишився нижче. Якщо
            # заміна не закінчується перевідом рядка, останній рядок заміни
            # злипся б із наступним рядком файлу.
            #
            # Робимо це ЛИШЕ для завершеного блоку: стрім віддає порції, і
            # на кожній паузі буфер порожній. Інакше ``\\n`` вставлявся б
            # посеред правки — саме так ``return`` розривався на ``ret`` і
            # ``urn`` у двох рядках.
            if self.block.complete:
                self._ensure_trailing_newline()
            # Усе віддано: лишаємо кнопки й чекаємо рішення людини.
            self._ensure_row()
            self._retitle()
            return
        try:
            self._job = text.after(TICK_MS, self._tick)
        except tk.TclError:
            self.settled = True

    def _insert_new(self, text, piece: str) -> None:
        """Дописати шматок нового коду зеленим, підсвічуючи лише нове."""
        begin = text.index(f"{self._insert_at}+{self._inserted}c")
        text.insert(begin, piece)
        end = text.index(f"{self._insert_at}+{self._inserted + len(piece)}c")
        text.tag_add(TAG_NEW, begin, end)
        self._inserted += len(piece)
        text.see(end)

    def _ensure_trailing_newline(self) -> None:
        """Дописати ``\\n`` у кінці нової версії, якщо його там немає."""
        if getattr(self, "_newline_added", False):
            return
        if not self.block.replace or self.block.replace.endswith("\n"):
            return
        text = self._widget()
        if text is None:
            return
        try:
            begin = text.index(f"{self._insert_at}+{self._inserted}c")
            text.insert(begin, "\n")
            end = text.index(f"{self._insert_at}+{self._inserted + 1}c")
            text.tag_add(TAG_NEW, begin, end)
            self._inserted += 1
            self._newline_added = True
        except tk.TclError:
            return

    def _widget(self):
        try:
            text = self.editor.text  # type: ignore[attr-defined]
            if text.winfo_exists():
                return text
        except (AttributeError, tk.TclError):
            return None
        return None

    def _index_of(self, content: str, offset: int) -> str:
        """Перевести зсув у символах на індекс Tk (``рядок.стовпець``)."""
        before = content[:offset]
        line = before.count("\n") + 1
        column = offset - (before.rfind("\n") + 1)
        return f"{line}.{column}"

    def on_status_text(self, text: str) -> None:
        if self.on_status is not None:
            try:
                self.on_status(text)      # type: ignore[operator]
            except Exception:             # noqa: BLE001 - статус не має валити правку
                LOG.debug("Статус живої правки не показано", exc_info=True)

    # ── дописування під час стріму ─────────────────────────────────────────
    def append(self, content: str, *, final: bool = False) -> None:
        """Дописати приріст коду, який прийшов наступним шматком.

        ``content`` — ЦІЛИЙ поточний текст від моделі (вона віддає
        накопичене, а не приріст), тому спершу відрізаємо те, що вже
        показано. Так дублювання неможливе, навіть якщо шматок прийшов
        двічі або перекрився.
        """
        if self.settled:
            return
        shown_already = self.block.replace
        if not content.startswith(shown_already):
            # Модель переписала початок (буває з ``edit_file``: спершу
            # ``old_string``, потім ``new_string``). Показувати різницю
            # накладкою небезпечно — починаємо блок заново.
            self._stream = stream_apply.EditStream()
            self.block.replace = content
            self._inserted = 0
            text = self._widget()
            if text is not None:
                try:
                    ranges = text.tag_ranges(TAG_NEW)
                    if len(ranges) >= 2:
                        for start, stop in reversed(
                                list(zip(ranges[::2], ranges[1::2]))):
                            text.delete(start, stop)
                except tk.TclError:
                    pass
            self._stream.push(content)
            self.block.complete = final
            self._tick()
            return
        delta = content[len(shown_already):]
        self.block.replace = content
        self.block.complete = final
        if delta:
            self._stream.push(delta)
            # Таймер міг уже спинитись (усе показано) — будимо його.
            if self._job is None:
                self._tick()

    def _retitle(self) -> None:
        """Оновити підпис кнопок: кількість рядків змінилась під час стріму."""
        row = self._row
        if row is None:
            return
        try:
            for child in row.winfo_children():
                if isinstance(child, tk.Label):
                    child.configure(text=self._caption())
                    break
        except tk.TclError:
            pass

    # ── рішення людини ─────────────────────────────────────────────────────
    def accept(self) -> None:
        """Прийняти: видалити старий фрагмент і лишити новий."""
        if self.settled:
            return
        text = self._widget()
        if text is not None:
            try:
                ranges = text.tag_ranges(TAG_OLD)
                if len(ranges) >= 2:
                    # Видаляємо від кінця до початку: інакше індекси зсуваються
                    # й видаляється не те, що підсвічено.
                    for start, stop in reversed(list(zip(ranges[::2], ranges[1::2]))):
                        text.delete(start, stop)
            except tk.TclError:
                pass
            self._clear_tags(text)
            self._close_group()
        self.settled = True
        self._drop_row()
        self._finish(True)

    def reject(self) -> None:
        """Відхилити: прибрати новий текст і зняти підсвітку зі старого."""
        if self.settled:
            return
        text = self._widget()
        if text is not None:
            try:
                ranges = text.tag_ranges(TAG_NEW)
                if len(ranges) >= 2:
                    for start, stop in reversed(list(zip(ranges[::2], ranges[1::2]))):
                        text.delete(start, stop)
            except tk.TclError:
                pass
            self._clear_tags(text)
            self._close_group()
        self.settled = True
        self._drop_row()
        self._finish(False)

    def cancel_timer(self) -> None:
        """Зупинити таймер (вікно закривається або почалась нова правка)."""
        self.settled = True
        self._close_group()
        job = self._job
        self._job = None
        if job is None:
            return
        text = self._widget()
        if text is None:
            return
        try:
            text.after_cancel(job)
        except (tk.TclError, ValueError):
            pass

    def _finish(self, accepted: bool) -> None:
        if self.on_done is not None:
            try:
                self.on_done(self, accepted)   # type: ignore[operator]
            except Exception:                  # noqa: BLE001
                LOG.debug("Колбек завершення правки впав", exc_info=True)

    @staticmethod
    def _clear_tags(text) -> None:
        for tag in (TAG_OLD, TAG_NEW):
            try:
                text.tag_remove(tag, "1.0", "end")
            except tk.TclError:
                pass

    # ── кнопки ─────────────────────────────────────────────────────────────
    def _ensure_row(self) -> None:
        """Показати кнопки «Прийняти / Відхилити».

        Кнопки живуть у ``editor`` (рамка редактора), а не в ``text``: у
        ``tk.Text`` не можна вставити віджети посеред тексту, тож вони
        з'являються смугою над полем вводу — там, де людина їх і шукає.
        """
        if self._row is not None or self.settled:
            return
        try:
            holder = self.editor                          # type: ignore[attr-defined]
            row = tk.Frame(holder, bg=theme.BG_ALT, bd=0, highlightthickness=0)
            label = tk.Label(
                row, text=self._caption(), bg=theme.BG_ALT,
                fg=theme.FG_DIM, font=("Segoe UI", 9), anchor="w")
            label.pack(side="left", padx=(8, 6), pady=3)
            # ``Chip`` фарбує себе сам (fg у нього — не параметр), тому
            # підпис і кнопки розрізняємо текстом, а не кольором.
            widgets.Chip(row, "✓ Прийняти", self.accept).pack(
                side="left", padx=(0, 4), pady=2)
            widgets.Chip(row, "✕ Відхилити", self.reject).pack(
                side="left", pady=2)
            # Місце в сітці редактора: рядок 0 — заголовок (якщо є),
            # решта — полотно з кодом. Ставимо найвищим рядком.
            row.grid(row=0, column=0, columnspan=3, sticky="ew")
            row.lift()
            self._row = row
        except (tk.TclError, AttributeError):
            LOG.debug("Кнопки правки не показано", exc_info=True)

    def _caption(self) -> str:
        if not self.located:
            return "нова правка (фрагмент не знайдено)"
        return (f"правка агента · рядок {self.start_line} · "
                f"−{self.old_lines} +{len(self.block.replace.splitlines())}")

    def _drop_row(self) -> None:
        row = self._row
        self._row = None
        if row is None:
            return
        try:
            row.destroy()
        except tk.TclError:
            pass

    # ── підсвітка ──────────────────────────────────────────────────────────
    @staticmethod
    def configure_tags(text) -> None:
        """Кольори діфа: ті самі, що в панелі «Зміни» й у чаті."""
        try:
            text.tag_configure(TAG_OLD, background=theme.DIFF_DEL_BG,
                               foreground=theme.DIFF_DEL_FG)
            text.tag_configure(TAG_NEW, background=theme.DIFF_ADD_BG,
                               foreground=theme.DIFF_ADD_FG)
            text.tag_raise(TAG_OLD)
            text.tag_raise(TAG_NEW)
        except tk.TclError:
            pass


def feed_block(
    editor,
    block: stream_apply.EditBlock,
    *,
    on_done=None,
    on_status=None,
    whole_file: bool = False,
) -> Optional[LiveEdit]:
    """Показати один блок правки в редакторі (зручна обгортка для вікна).

    ``whole_file=True`` — блок замінює вміст файлу цілком (так працює
    ``write_file``). Інакше шукається старий фрагмент ``block.search``.
    """
    if editor is None or not block.replace:
        return None
    text = getattr(editor, "text", None)
    if text is None:
        return None
    LiveEdit.configure_tags(text)
    live = LiveEdit(editor=editor, block=block, on_done=on_done,
                    on_status=on_status, whole_file=whole_file)
    if not live.start():
        return None
    return live
