"""Вставка з буфера працює за БУДЬ-ЯКОЇ розкладки клавіатури.

Реальна скарга (скріншот 124): «Не можу вставити ключ щоб підключити
хмарний агент, немає контекстного меню та через ctrl+v не можу!»

Корінь не в полі ключа, а в розкладці. Прив'язки Tk на кшталт
``<Control-v>`` звіряють СИМВОЛ клавіші в поточній розкладці. На
українській розкладці клавіша «V» дає «і» (U+0456), символ не дорівнює
``v`` — і віртуальна подія ``<<Paste>>`` не виникає взагалі. Перевірено
на живому вікні: натискання приходить із keysym ``??`` і фізичним кодом
86. Тому Ctrl+V не працював у ВСЬОМУ застосунку: ні в чаті, ні в
терміналі, ні в полях налаштувань.

Виправлення: дія вибирається за фізичним кодом клавіші (він однаковий у
будь-якій розкладці), а латинські символи лишаються вбудованій обробці
Tk — інакше на англійській розкладці текст вставився б двічі.

Запуск: python -m unittest tests.test_clipboard_layout -v
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import widgets  # noqa: E402

#: Стан модифікаторів Tk на Windows: 0x4 — Control, 0x8 — NumLock
#: (стоїть майже завжди й до буфера не стосується), 0x20000 — Alt.
CTRL = 0x0004
NUMLOCK = 0x0008
ALT = 0x20000

#: Фізичні коди клавіш (Windows virtual-key codes) — однакові в усіх
#: розкладках.
KEYCODE_A, KEYCODE_C, KEYCODE_V, KEYCODE_X, KEYCODE_Z = 65, 67, 86, 88, 90

#: Один корінь Tk на весь файл. На Windows створювати й знищувати ``tk.Tk()``
#: понад один раз небезпечно: процес падає з access violation під час
#: збирання сміття, і весь прогін обривається (перевірено: два класи з
#: власними коренями давали exit code -1073741819).
_ROOT = None
_ROOT_FAILED = False


def _shared_root():
    """Спільний прихований корінь Tk (або ``SkipTest``, якщо дисплея немає)."""
    global _ROOT, _ROOT_FAILED
    if _ROOT is not None:
        return _ROOT
    if _ROOT_FAILED:
        raise unittest.SkipTest("немає дисплея")
    try:
        _ROOT = tk.Tk()
        _ROOT.withdraw()
    except Exception as exc:                     # noqa: BLE001
        _ROOT_FAILED = True
        raise unittest.SkipTest(f"немає дисплея: {exc}") from exc
    return _ROOT


class _Event:
    """Мінімальна подоба події Tk: рівно те, що читає обробник."""

    def __init__(self, widget=None, keysym="??", keycode=0, state=0) -> None:
        self.widget = widget
        self.keysym = keysym
        self.keycode = keycode
        self.state = state


class TestUkrainianLayoutPaste(unittest.TestCase):
    """На українській розкладці Ctrl+V/A/C/X мають працювати."""

    def test_ukrainian_ctrl_v_pastes(self) -> None:
        """keysym «і» замість «v», але фізичний код той самий — вставляє."""
        action = widgets.clipboard_action_for(
            _Event(keysym="і", keycode=KEYCODE_V, state=CTRL | NUMLOCK))
        self.assertIs(action, widgets.clipboard_paste,
                      "Ctrl+V на українській розкладці не вставляє")

    def test_ukrainian_ctrl_a_selects_all(self) -> None:
        action = widgets.clipboard_action_for(
            _Event(keysym="ф", keycode=KEYCODE_A, state=CTRL | NUMLOCK))
        self.assertIs(action, widgets.clipboard_select_all)

    def test_ukrainian_ctrl_c_copies(self) -> None:
        action = widgets.clipboard_action_for(
            _Event(keysym="с", keycode=KEYCODE_C, state=CTRL | NUMLOCK))
        self.assertIs(action, widgets.clipboard_copy)

    def test_ukrainian_ctrl_x_cuts(self) -> None:
        action = widgets.clipboard_action_for(
            _Event(keysym="ч", keycode=KEYCODE_X, state=CTRL | NUMLOCK))
        self.assertIs(action, widgets.clipboard_cut)

    def test_numlock_does_not_disable_shortcut(self) -> None:
        """NumLock стоїть завжди — раніше він глушив всі комбінації.

        Перша версія виправлення відсіювала 0x8 як «Shift/Alt» і вставка
        не працювала навіть на українській розкладці: 0x8 — це NumLock.
        """
        action = widgets.clipboard_action_for(
            _Event(keysym="??", keycode=KEYCODE_V, state=CTRL | NUMLOCK))
        self.assertIsNotNone(action, "NumLock не має ламати Ctrl+V")


class TestEnglishLayoutIsNotDoubled(unittest.TestCase):
    """На англійській розкладці Tk обробляє сам — власна дія не потрібна."""

    def test_latin_keysym_yields_no_action(self) -> None:
        for keysym, keycode in (("v", KEYCODE_V), ("a", KEYCODE_A),
                                ("c", KEYCODE_C), ("x", KEYCODE_X)):
            with self.subTest(keysym=keysym):
                action = widgets.clipboard_action_for(
                    _Event(keysym=keysym, keycode=keycode, state=CTRL | NUMLOCK))
                self.assertIsNone(
                    action,
                    f"«{keysym}» обробляє Tk; власна дія вставила б двічі")

    def test_uppercase_latin_keysym_yields_no_action(self) -> None:
        action = widgets.clipboard_action_for(
            _Event(keysym="V", keycode=KEYCODE_V, state=CTRL | NUMLOCK))
        self.assertIsNone(action)


class TestNonShortcutKeysIgnored(unittest.TestCase):
    """Зайві комбінації не перетворюються на дії буфера."""

    def test_ctrl_alt_is_not_paste(self) -> None:
        """Ctrl+Alt+V — команда IDE, а не вставка."""
        action = widgets.clipboard_action_for(
            _Event(keysym="??", keycode=KEYCODE_V, state=CTRL | ALT | NUMLOCK))
        self.assertIsNone(action)

    def test_plain_key_is_not_paste(self) -> None:
        """«v» без Control — це просто літера."""
        self.assertIsNone(widgets.clipboard_action_for(
            _Event(keysym="??", keycode=KEYCODE_V, state=NUMLOCK)))

    def test_ctrl_z_is_not_clipboard(self) -> None:
        """Ctrl+Z лишається скасуванням."""
        self.assertIsNone(widgets.clipboard_action_for(
            _Event(keysym="я", keycode=KEYCODE_Z, state=CTRL | NUMLOCK)))

    def test_event_without_state_does_not_crash(self) -> None:
        self.assertIsNone(widgets.clipboard_action_for(_Event(state=None)))
        self.assertIsNone(widgets.clipboard_action_for(object()))


class TestReadonlyFields(unittest.TestCase):
    """Поле лише для читання копіює, але не приймає вставку."""

    def test_readonly_blocks_paste(self) -> None:
        action = widgets.clipboard_action_for(
            _Event(keysym="??", keycode=KEYCODE_V, state=CTRL | NUMLOCK),
            readonly=True)
        self.assertIsNone(action, "поле лише для читання не має приймати вставку")

    def test_readonly_allows_copy(self) -> None:
        action = widgets.clipboard_action_for(
            _Event(keysym="??", keycode=KEYCODE_C, state=CTRL | NUMLOCK),
            readonly=True)
        self.assertIs(action, widgets.clipboard_copy)


class TestRealWidgets(unittest.TestCase):
    """Перевірка на справжніх віджетах: подія «української» розкладки вставляє.

    Корінь Tk спільний для всього файлу — див. ``_shared_root``.
    """

    def _clipboard(self, text: str) -> None:
        root = _shared_root()
        try:
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
        except tk.TclError:
            raise unittest.SkipTest("буфер обміну недоступний")

    def test_ukrainian_event_pastes_into_entry(self) -> None:
        self._clipboard("sk-cloud-key-123")
        root = _shared_root()
        entry = tk.Entry(root)
        self.addCleanup(entry.destroy)
        self.assertTrue(widgets._clipboard_event_handler(  # noqa: SLF001
            _Event(widget=entry, keysym="і", keycode=KEYCODE_V,
                   state=CTRL | NUMLOCK)) == "break")
        self.assertEqual(entry.get(), "sk-cloud-key-123")

    def test_ukrainian_event_pastes_into_ttk_secret_entry(self) -> None:
        """Саме поле API-ключа: ttk.Entry із прихованим текстом."""
        self._clipboard("sk-deploy-key-456")
        root = _shared_root()
        entry = ttk.Entry(root, show="•")
        self.addCleanup(entry.destroy)
        widgets._clipboard_event_handler(  # noqa: SLF001
            _Event(widget=entry, keysym="і", keycode=KEYCODE_V,
                   state=CTRL | NUMLOCK))
        self.assertEqual(entry.get(), "sk-deploy-key-456")

    def test_ukrainian_event_pastes_into_text(self) -> None:
        self._clipboard("у чат")
        root = _shared_root()
        box = tk.Text(root)
        self.addCleanup(box.destroy)
        widgets._clipboard_event_handler(  # noqa: SLF001
            _Event(widget=box, keysym="і", keycode=KEYCODE_V,
                   state=CTRL | NUMLOCK))
        self.assertEqual(box.get("1.0", "end-1c"), "у чат")

    def test_latin_event_does_nothing_and_leaves_paste_to_tk(self) -> None:
        """На англійській розкладці обробник мовчить — інакше була б двійка."""
        self._clipboard("лише раз")
        root = _shared_root()
        entry = tk.Entry(root)
        self.addCleanup(entry.destroy)
        result = widgets._clipboard_event_handler(  # noqa: SLF001
            _Event(widget=entry, keysym="v", keycode=KEYCODE_V,
                   state=CTRL | NUMLOCK))
        self.assertIsNone(result)
        self.assertEqual(entry.get(), "", "обробник не мав вставляти текст")

    def test_non_text_widget_is_ignored(self) -> None:
        """Кнопка не є полем введення — вставка не має туди потрапляти."""
        root = _shared_root()
        button = ttk.Button(root, text="Зберегти")
        self.addCleanup(button.destroy)
        result = widgets._clipboard_event_handler(  # noqa: SLF001
            _Event(widget=button, keysym="і", keycode=KEYCODE_V,
                   state=CTRL | NUMLOCK))
        self.assertIsNone(result)


class TestFallbackInstallation(unittest.TestCase):
    """Глобальний фолбек ставиться й не глушить решту обробників."""

    def test_install_adds_control_keypress_binding(self) -> None:
        root = _shared_root()
        widgets.install_clipboard_fallback(root)
        root.update()
        self.assertTrue(root.bind_all("<Control-KeyPress>"),
                        "глобальний фолбек вставки не встановлено")

    def test_attach_edit_actions_adds_physical_key_binding(self) -> None:
        entry = ttk.Entry(_shared_root())
        self.addCleanup(entry.destroy)
        widgets.attach_edit_actions(entry)
        # Tk нормалізує назву: те, що ми прив'язали як ``<Control-KeyPress>``,
        # читається назад як ``<Control-Key>``.
        bindings = " ".join(item.lower() for item in entry.bind())
        self.assertIn("<control-key>", bindings,
                      "немає прив'язки за фізичним кодом клавіші")
        self.assertIn("button-3", bindings, "немає контекстного меню")

    def test_text_widget_detection(self) -> None:
        """Усі типи полів введення впізнаються (інакше вставки в них не буде)."""
        for cls in (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox,
                    ttk.Spinbox, tk.Spinbox):
            with self.subTest(kind=cls.__name__):
                self.assertTrue(any(issubclass(cls, base)
                                    for base in widgets.TEXT_WIDGETS),
                                f"{cls.__name__} не вважається полем введення")


if __name__ == "__main__":
    unittest.main(verbosity=2)
