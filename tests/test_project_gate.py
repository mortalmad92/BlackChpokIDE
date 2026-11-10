"""Тека проєкту — обов'язкова умова для будь-якого запуску агента.

Регресія, яку ці тести фіксують: екран «Спершу вибери теку проєкту» існував,
але перевірка стояла лише в «Новий чат» і «Відкрити чат». До агента ж
ведуть ще кілька входів — стартовий екран, голос, скіл, черга задач,
кнопка надіслати в композері, ``send_to_agent`` з меню, — і кожен із них
створював чат із ``workspace = C:\\Users\\<ім'я>``. Перший же ``read_file``
або ``write_file`` тоді працював у домашній теці користувача.

Тому перевірка тепер стоїть у ЄДИНОМУ шлюзі — ``ChatPanel._send`` — а
оболонка підключає туди ``has_project``. Ці тести перевіряють і сам шлюз,
і те, що кожен із входів справді поводиться як належить.

Запуск: python -m unittest tests.test_project_gate -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestHasProject(unittest.TestCase):
    """``has_project()`` має розрізняти «не вибрано» від «вибрано домашню»."""

    @classmethod
    def setUpClass(cls) -> None:
        from blackchpok_ide import main_window

        cls.cls = main_window.BlackChpokIDE

    def _probe(self, workspace: str, *, chosen: bool):
        """Мінімальний носій методу ``has_project`` (без вікна)."""
        from types import SimpleNamespace

        stub = SimpleNamespace(
            settings=SimpleNamespace(workspace=workspace, project_chosen=chosen)
        )
        return self.cls.has_project(stub)

    def test_empty_workspace_is_no_project(self) -> None:
        self.assertFalse(self._probe("", chosen=False))
        self.assertFalse(self._probe("   ", chosen=False))

    def test_missing_folder_is_no_project(self) -> None:
        missing = str(Path(tempfile.gettempdir()) / "blackchpok_absent_xyz" / "nope")
        self.assertFalse(self._probe(missing, chosen=True))

    def test_home_without_explicit_choice_is_no_project(self) -> None:
        """Домашня тека типово підставляється — це стан «нічого не вибрано»."""
        self.assertFalse(self._probe(str(Path.home()), chosen=False))

    def test_home_with_explicit_choice_is_project(self) -> None:
        """Але свідомий вибір домашньої теки має працювати.

        Інакше кнопка «Вибрати папку» на вибір домашньої теки не робила б
        нічого видимого: екран лишався б на місці назавжди.
        """
        self.assertTrue(self._probe(str(Path.home()), chosen=True))

    def test_ordinary_folder_is_project(self) -> None:
        folder = tempfile.mkdtemp()
        try:
            self.assertTrue(self._probe(folder, chosen=False))
        finally:
            Path(folder).rmdir()


class TestSettingsRemembersChoice(unittest.TestCase):
    """Вибір теки має запам'ятовуватись, зокрема для домашньої."""

    def test_remember_workspace_sets_flag(self) -> None:
        from blackchpok_ide.config import Settings

        settings = Settings(workspace=str(Path.home()))
        self.assertFalse(settings.project_chosen)
        settings.remember_workspace(str(Path.home()))
        self.assertTrue(settings.project_chosen,
                        "свідомий вибір має відрізнятись від «не вибрано»")

    def test_flag_survives_roundtrip(self) -> None:
        from blackchpok_ide.config import Settings

        settings = Settings(workspace=r"C:\p", project_chosen=True)
        restored = Settings.from_dict(settings.to_dict())
        self.assertTrue(restored.project_chosen)

    def test_old_config_without_flag_is_false(self) -> None:
        """Старі конфіги не мають поля — читаємось як «не вибрано»."""
        from blackchpok_ide.config import Settings

        restored = Settings.from_dict({"workspace": r"C:\p"})
        self.assertFalse(restored.project_chosen)


class TestSendGate(unittest.TestCase):
    """Шлюз ``_project_ok`` у панелі чату."""

    def setUp(self) -> None:
        from blackchpok_ide import chat_panel

        self.module = chat_panel

        class _Stub:
            project_ready = None
            on_need_project = None
            notes: list = []
            text_set = ""

            def _note(self, text, *, kind="info"):
                self.notes.append((kind, text))

            def set_text(self, text):
                self.text_set = text

        self.stub = _Stub()
        self.stub._project_ok = chat_panel.ChatPanel._project_ok.__get__(self.stub)

    def test_without_hook_everything_passes(self) -> None:
        """Панель без підключеного колбека не блокує роботу (тести, скріншоти)."""
        self.assertTrue(self.stub._project_ok("привіт"))

    def test_ready_project_passes(self) -> None:
        self.stub.project_ready = lambda: True
        self.assertTrue(self.stub._project_ok("привіт"))
        self.assertEqual(self.stub.notes, [])

    def test_missing_project_blocks(self) -> None:
        self.stub.project_ready = lambda: False
        self.assertFalse(self.stub._project_ok("привіт"))

    def test_blocking_shows_gate_and_explains(self) -> None:
        shown: list[bool] = []
        self.stub.project_ready = lambda: False
        self.stub.on_need_project = lambda: shown.append(True)
        self.assertFalse(self.stub._project_ok("привіт"))
        self.assertTrue(shown, "екран вибору теки має з'явитись")
        self.assertTrue(self.stub.notes, "користувач має бачити причину")
        self.assertEqual(self.stub.notes[0][0], "error")

    def test_request_text_is_not_lost(self) -> None:
        """Запит повертається в поле — після вибору теки досить натиснути Enter."""
        self.stub.project_ready = lambda: False
        self.assertFalse(self.stub._project_ok("довгий запит про браузер"))
        self.assertEqual(self.stub.text_set, "довгий запит про браузер")

    def test_empty_text_does_not_clear_composer(self) -> None:
        self.stub.project_ready = lambda: False
        self.stub._project_ok("")
        self.assertEqual(self.stub.text_set, "")

    def test_broken_hook_does_not_block(self) -> None:
        """Зламана перевірка не має відрізати користувача від агента."""
        from blackchpok_ide import safe

        before = safe.failure_count()

        def boom():
            raise RuntimeError("зламано")

        self.stub.project_ready = boom
        self.assertTrue(self.stub._project_ok("привіт"))
        self.assertGreater(safe.failure_count(), before,
                           "прихований збій має потрапити в реєстр")

    def test_gate_connected_in_main_window(self) -> None:
        """Оболонка справді підключає шлюз — інакше він мовчить."""
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._build_centre)
        self.assertIn("project_ready", source)
        self.assertIn("on_need_project", source)


class TestAllEntryPointsUseGate(unittest.TestCase):
    """Кожен вхід до агента має пройти через ``_send`` (а не повз нього)."""

    @staticmethod
    def _calls_in(source: str) -> set[str]:
        import ast
        import textwrap

        tree = ast.parse(textwrap.dedent(source))
        names: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
        return names

    def _source(self, name: str) -> str:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        return inspect.getsource(getattr(BlackChpokIDE, name))

    def test_send_to_agent_uses_send(self) -> None:
        self.assertIn("_send", self._calls_in(self._source("send_to_agent")))

    def test_voice_query_uses_send(self) -> None:
        self.assertIn("_send", self._calls_in(self._source("_on_voice_query")))

    def test_skill_uses_send(self) -> None:
        self.assertIn("_send", self._calls_in(self._source("_use_skill")))

    def test_queue_uses_send(self) -> None:
        """Черга доходить до ``_send`` — через виконавець кроків.

        Виконання кроку тепер іде через :class:`task_executor.QueueExecutor`:
        ``run_next_task`` кличе виконавець, той — ``on_run_step``, а це
        ``_run_plan_step``, який віддає запит у ``chat._send``. Шлюз
        теки проєкту лишається обов'язковим на цьому шляху.
        """
        senders = self._calls_in(self._source("_run_plan_step"))
        self.assertIn("_send", senders,
                      "крок черги має йти тим самим шляхом, що й чат")
        self.assertIn("_send", self._calls_in(self._source("_split_task_to_queue"))
                      | senders)

    def test_welcome_checks_project_before_hiding(self) -> None:
        """Стартовий екран не має зникати, поки теки немає."""
        import ast
        import textwrap

        tree = ast.parse(textwrap.dedent(self._source("_start_from_welcome")))
        order: dict[str, int] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            order.setdefault(name, node.lineno)
        self.assertIn("has_project", order)
        self.assertIn("_hide_welcome", order)
        self.assertLess(order["has_project"], order["_hide_welcome"],
                        "спершу перевірка теки, потім приховування екрана")

    def test_queue_checks_project_before_mark_running(self) -> None:
        """Інакше відмова шлюзу лишила б задачу «в роботі» назавжди.

        Перевіряємо порядок СПРАВЖНІХ викликів через ``ast``: у тексті
        функції є коментар зі словом ``mark_running``, і пошук підрядком
        ловив би коментар замість коду.

        Статус «в роботі» тепер ставить виконавець
        (``executor.start`` / ``start_next`` → ``TaskQueue.mark_running``).
        Тому перевіряємо, що перевірка теки стоїть ДО будь-якого запуску
        кроку.
        """
        import ast
        import textwrap

        tree = ast.parse(textwrap.dedent(self._source("run_next_task")))
        order: dict[str, int] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            # Перший виклик кожного імені — саме він визначає порядок.
            order.setdefault(name, node.lineno)
        self.assertIn("has_project", order, "черга має перевіряти теку проєкту")
        starters = [name for name in ("start", "start_next") if name in order]
        self.assertTrue(starters,
                        "черга має запускати крок через виконавець")
        for starter in starters:
            self.assertLess(order["has_project"], order[starter],
                            "перевірка теки має стояти до запуску кроку")

    def test_executor_marks_running_only_after_start(self) -> None:
        """Виконавець позначає крок «в роботі» лише коли справді стартує."""
        import inspect
        import textwrap

        from blackchpok_ide.task_executor import QueueExecutor

        source = textwrap.dedent(inspect.getsource(QueueExecutor.start))
        self.assertIn("mark_running", source)
        self.assertIn("is_ready", source,
                      "крок із невиконаними залежностями не має запускатись")

    def test_queue_pump_requires_project(self) -> None:
        """Насос не має смикати gate щосекунди."""
        self.assertIn("has_project", self._calls_in(self._source("_queue_pump")))


class TestGateClassifiedAsTested(unittest.TestCase):
    """``_project_ok`` має бути видимим у панелі чату."""

    def test_method_exists(self) -> None:
        from blackchpok_ide.chat_panel import ChatPanel

        self.assertTrue(hasattr(ChatPanel, "_project_ok"))

    def test_send_calls_it(self) -> None:
        import inspect
        import textwrap

        from blackchpok_ide.chat_panel import ChatPanel

        source = textwrap.dedent(inspect.getsource(ChatPanel._send))
        self.assertIn("_project_ok", source,
                      "шлюз має стояти саме в _send — там проходять усі входи")


class TestPanelsDoNotScanHome(unittest.TestCase):
    """Панелі не мають показувати вміст домашньої теки.

    Регресія зі скріншота: екран вибору теки вже був, а права колонка
    показувала ``AppData``, ``NTUSER.DAT`` та інші службові файли — бо
    «Зміни», панель контексту й провідник брали ``settings.workspace``
    напряму. Виглядало так, ніби агент уже працює в домі.
    """

    @staticmethod
    def _source(name: str) -> str:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        return inspect.getsource(getattr(BlackChpokIDE, name))

    @staticmethod
    def _stub(workspace: str, *, chosen: bool):
        """Носій ``settings`` + справжні ``has_project``/``_project_root``."""
        from types import SimpleNamespace

        from blackchpok_ide.main_window import BlackChpokIDE

        class _Host:
            settings = SimpleNamespace(workspace=workspace, project_chosen=chosen)

        _Host.has_project = BlackChpokIDE.has_project
        _Host._project_root = BlackChpokIDE._project_root
        return _Host()

    def test_project_root_returns_none_without_project(self) -> None:
        host = self._stub(str(Path.home()), chosen=False)
        self.assertFalse(host.has_project())
        self.assertIsNone(host._project_root())

    def test_project_root_returns_folder_with_project(self) -> None:
        folder = tempfile.mkdtemp()
        try:
            host = self._stub(folder, chosen=True)
            self.assertTrue(host.has_project())
            self.assertEqual(host._project_root(), Path(folder))
        finally:
            Path(folder).rmdir()

    def test_panels_take_root_from_one_place(self) -> None:
        """``lambda: Path(self.settings.workspace)`` більше не передається панелям."""
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(encoding="utf-8")
        self.assertNotIn("lambda: Path(self.settings.workspace)", source,
                         "панелі мають брати теку через _project_root")

    def test_changes_panel_uses_project_root(self) -> None:
        self.assertIn("_project_root", self._source("_build_centre"))

    def test_context_panel_uses_project_root(self) -> None:
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(encoding="utf-8")
        start = source.index("context_panel.ContextPanel(")
        block = source[start:start + 320]
        self.assertIn("_project_root", block,
                      "панель контексту не має читати домашню теку")

    def test_statusbar_shows_no_home_path(self) -> None:
        source = self._source("_build_status")
        self.assertIn("has_project", source,
                      "статусбар не має показувати шлях дому як проєкт")

    def test_file_tree_starts_empty_without_project(self) -> None:
        source = self._source("_build_centre")
        self.assertIn("has_project", source,
                      "провідник не має сканувати домашню теку")

    def test_startup_labels_project_as_not_chosen(self) -> None:
        source = self._source("_startup")
        self.assertIn("has_project", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
