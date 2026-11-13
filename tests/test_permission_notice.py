"""Нотатка «Режим дозволів» з'являється РІВНО раз на справжню зміну.

Причина появи. На скріншоті користувача один і той самий рядок стояв
ДВІЧІ поспіль:

    · Режим дозволів: Запис у робочій області. Агент може створювати…
    · Режим дозволів: Запис у робочій області. Агент може створювати…

Причина: при старті режим виставлявся ДВІЧІ — спершу
``chat.set_permission_mode()``, потім ``set_agent_mode()`` — і КОЖЕН виклик
писав нотатку в транскрипт.

Тепер у ``set_permission_mode`` є ``notify``:
  • ``False`` — відновлення при старті, нотатки немає;
  • ``True`` — лише на справжню зміну дозволів;
  • ``"always"`` — зміна РЕЖИМУ (дозволи в «Чат» і «Код» можуть збігатися,
    але користувач мусить бачити підтвердження).

Заміряно: 0 рядків при старті, рівно 1 на кожну зміну режиму.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_HOME",
                      tempfile.mkdtemp(prefix="perm-notes-home-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"


class TestPermissionNotice(TestCase):
    """Один рядок на одну дію — і жодного при старті."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter.filedialog as fd
        import tkinter.messagebox as mb

        mb.askyesno = lambda *a, **k: True
        mb.showinfo = lambda *a, **k: None
        mb.showwarning = lambda *a, **k: None
        mb.showerror = lambda *a, **k: None
        fd.asksaveasfilename = lambda *a, **k: ""
        fd.askopenfilename = lambda *a, **k: ""
        fd.askdirectory = lambda *a, **k: ""

        from blackchpok_ide.config import Settings
        from blackchpok_ide.main_window import BlackChpokIDE

        settings = Settings.load()
        settings.workspace = str(ROOT)
        settings.first_run_done = True
        settings.engine.auto_start = False
        settings.agent.queue_auto_run = False
        cls.app = BlackChpokIDE(settings)
        for _ in range(60):
            cls.app.update()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.app.agent.cancel()
            cls.app.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _count(self) -> int:
        self.app.update()
        return self.app.chat.transcript.get().count("Режим дозволів")

    def test_no_duplicate_on_startup(self) -> None:
        """При старті нотатки НЕМАЄ — це відновлення, а не дія.

        Перевіряємо ОКРЕМЕ вікно: у спільному ``setUpClass`` попередні
        тести вже змінювали режим, і їхні нотатки лишились у транскрипті.
        Інакше тест залежав би від порядку запуску — а така залежність сама
        є дефектом тесту.
        """
        import tkinter.filedialog as fd
        import tkinter.messagebox as mb

        mb.askyesno = lambda *a, **k: True
        mb.showinfo = lambda *a, **k: None
        mb.showwarning = lambda *a, **k: None
        mb.showerror = lambda *a, **k: None
        fd.askdirectory = lambda *a, **k: ""

        from blackchpok_ide.config import Settings
        from blackchpok_ide.main_window import BlackChpokIDE

        settings = Settings.load()
        settings.workspace = str(ROOT)
        settings.first_run_done = True
        settings.engine.auto_start = False
        settings.agent.queue_auto_run = False
        fresh = BlackChpokIDE(settings)
        try:
            for _ in range(40):
                fresh.update()
            body = fresh.chat.transcript.get()
            self.assertEqual(body.count("Режим дозволів"), 0,
                             "при старті з'явився рядок «Режим дозволів»")
        finally:
            try:
                fresh.agent.cancel()
                fresh.destroy()
            except Exception:  # noqa: BLE001
                pass

    def test_one_notice_per_mode_change(self) -> None:
        """Кожна зміна режиму — рівно один рядок."""
        before = self._count()
        self.app.set_agent_mode("code")
        self.assertEqual(self._count(), before + 1,
                         "зміна режиму дала не рівно один рядок")

    def test_direct_permission_change_notifies_once(self) -> None:
        before = self._count()
        # інший режим дозволів, ніж поточний
        from blackchpok_ide import permissions

        target = ("read_only" if self.app.chat.permission_mode
                  != permissions.READ_ONLY else permissions.FULL)
        self.app.chat.set_permission_mode(target)
        self.assertEqual(self._count(), before + 1,
                         "пряма зміна дозволів дала не рівно один рядок")

    def test_same_mode_twice_does_not_duplicate(self) -> None:
        """Повторний виклик із ТИМ САМИМ режимом не плодить нотаток."""
        self.app.chat.set_permission_mode(self.app.chat.permission_mode)
        after_first = self._count()
        self.app.chat.set_permission_mode(self.app.chat.permission_mode)
        self.assertEqual(self._count(), after_first,
                         "повтор із тим самим режимом додав нотатку")


class TestStartupIsSilent(TestCase):
    """Відновлення при старті не має писати в чат."""

    def test_startup_silent(self) -> None:
        import tkinter.filedialog as fd
        import tkinter.messagebox as mb

        mb.askyesno = lambda *a, **k: True
        mb.showinfo = lambda *a, **k: None
        mb.showwarning = lambda *a, **k: None
        mb.showerror = lambda *a, **k: None
        fd.askdirectory = lambda *a, **k: ""

        from blackchpok_ide.config import Settings
        from blackchpok_ide.main_window import BlackChpokIDE

        settings = Settings.load()
        settings.workspace = str(ROOT)
        settings.first_run_done = True
        settings.engine.auto_start = False
        settings.agent.queue_auto_run = False
        app = BlackChpokIDE(settings)
        try:
            for _ in range(40):
                app.update()
            body = app.chat.transcript.get()
            self.assertEqual(body.count("Режим дозволів"), 0)
        finally:
            try:
                app.agent.cancel()
                app.destroy()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    main()
