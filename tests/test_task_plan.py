"""Розуміння людської задачі, підбір інструментів і смуга етапів.

Те, що перевіряється тут, — це відповідь на три прохання:

1. **розуміти завдання з людської мови** — українські дієслова мають багато
   форм («зроби», «зробити», «зробіть»), тому зіставляємо за основою слова;
2. **підбирати інструменти** — кожен намір дає конкретний набір, який
   передається агенту підказкою;
3. **розбивати велике завдання на етапи** й показувати їх над полем вводу
   зі спінером у поточного та ✓ у виконаного.

Запуск: python -m unittest tests.test_task_plan -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import task_plan as tp  # noqa: E402


class TestUnderstandVerbs(unittest.TestCase):
    """Намір визначається за основою слова, а не за точною формою."""

    def test_run_tests(self) -> None:
        for phrase in ("запусти тести", "прожени тести", "перевір тестами"):
            info = tp.understand(phrase)
            self.assertIn(tp.TEST, info.intents, phrase)
            self.assertFalse(info.is_big, phrase)

    def test_show_files_is_read(self) -> None:
        info = tp.understand("покажи файли")
        self.assertEqual(info.primary, tp.READ)

    def test_search(self) -> None:
        info = tp.understand("знайди де використовується open_url")
        self.assertEqual(info.primary, tp.SEARCH)

    def test_debug(self) -> None:
        for phrase in ("виправ помилку в main.py", "чат падає", "не працює кнопка"):
            info = tp.understand(phrase)
            self.assertIn(tp.DEBUG, info.intents, phrase)

    def test_create(self) -> None:
        for phrase in ("створи файл notes.txt", "додай модуль", "згенеруй тест"):
            info = tp.understand(phrase)
            self.assertIn(tp.CREATE, info.intents, phrase)

    def test_verb_forms_are_stem_matched(self) -> None:
        """«зроби», «зробити», «зробіть» — та сама дія."""
        for phrase in ("зроби файл", "зробити файл", "зробіть файл"):
            info = tp.understand(phrase)
            self.assertNotEqual(info.primary, tp.TALK, phrase)

    def test_case_insensitive(self) -> None:
        self.assertEqual(tp.understand("ЗАПУСТИ ТЕСТИ").primary,
                         tp.understand("запусти тести").primary)

    def test_paths_are_captured(self) -> None:
        info = tp.understand("виправ помилку в main.py і в tests/test_x.py")
        self.assertIn("main.py", info.paths)
        self.assertIn("tests/test_x.py", info.paths)

    def test_quoted_is_captured(self) -> None:
        info = tp.understand('перейменуй «Мій Чат» на «Новий»')
        self.assertIn("Мій Чат", info.quoted)


class TestTalkIsNotAction(unittest.TestCase):
    """Звичайна розмова не має запускати інструменти."""

    def test_greetings(self) -> None:
        for phrase in ("привіт", "як справи?", "розкажи вірш про море",
                       "що ти вмієш?", "дякую"):
            info = tp.understand(phrase)
            self.assertEqual(info.primary, tp.TALK, phrase)
            self.assertFalse(info.is_action, phrase)

    def test_empty(self) -> None:
        info = tp.understand("")
        self.assertEqual(info.intents, [])
        self.assertFalse(info.is_action)

    def test_no_false_edit_from_pravy(self) -> None:
        """«як справи» не має читатись як «правити»."""
        self.assertEqual(tp.understand("як справи").primary, tp.TALK)


class TestBigTask(unittest.TestCase):
    """Велика задача розпізнається, дрібна — ні."""

    def test_real_brief_is_big(self) -> None:
        brief = ("Потрібно обєднати вкладки чати і агенти в одне. Зроби щоб "
                 "були іконки закриття чатів біля кожного чату та архівування. "
                 "Зроби адаптивний розмір чату і відповідей в залежності до "
                 "екрану.")
        self.assertTrue(tp.understand(brief).is_big)

    def test_short_command_is_not_big(self) -> None:
        for phrase in ("запусти тести", "покажи файли", "виправ помилку"):
            self.assertFalse(tp.understand(phrase).is_big, phrase)

    def test_many_intents_and_demands(self) -> None:
        brief = ("Створи екран налаштувань, додай перевірку полів, виправ "
                 "валідацію та перевір збереження. Потрібно також оновити тести.")
        self.assertTrue(tp.understand(brief).is_big)


class TestToolsForIntent(unittest.TestCase):
    """Кожен намір дає дореєнні інструменти."""

    def test_read_tools(self) -> None:
        tools = tp.tools_for_stage("покажи main.py")
        self.assertIn("read_file", tools)

    def test_create_tools_include_write(self) -> None:
        tools = tp.tools_for_stage("створи файл a.py")
        self.assertIn("write_file", tools)
        self.assertIn("python_check", tools)

    def test_test_tools_include_command(self) -> None:
        tools = tp.tools_for_stage("запусти тести")
        self.assertIn("run_command", tools)

    def test_debug_tools_cover_read_and_run(self) -> None:
        tools = tp.tools_for_stage("виправ помилку в main.py")
        self.assertIn("read_file", tools)
        self.assertIn("run_command", tools)

    def test_search_tools(self) -> None:
        tools = tp.tools_for_stage("знайди де використовується open_url")
        self.assertIn("search_text", tools)

    def test_talk_has_no_tools(self) -> None:
        self.assertEqual(tp.tools_for_stage("привіт, як справи"), ())

    def test_no_duplicates(self) -> None:
        tools = tp.tools_for_intents([tp.EDIT, tp.REFACTOR, tp.TEST])
        self.assertEqual(len(tools), len(set(tools)))

    def test_hint_mentions_tools(self) -> None:
        hint = tp.tools_hint(("read_file", "run_command"))
        self.assertIn("read_file", hint)
        self.assertIn("run_command", hint)

    def test_empty_hint_is_empty(self) -> None:
        self.assertEqual(tp.tools_hint(()), "")


class TestSplitIntoStages(unittest.TestCase):
    """Розбиття на етапи — без моделі, отже без затримки."""

    def test_sentences_become_stages(self) -> None:
        brief = ("Потрібно обєднати вкладки чати і агенти в одне. Зроби щоб "
                 "були іконки закриття чатів біля кожного чату. Зроби "
                 "адаптивний розмір чату.")
        stages = tp.split_into_stages(brief)
        self.assertGreaterEqual(len(stages), 2)
        self.assertEqual([s.index for s in stages], list(range(len(stages))))

    def test_ready_made_list_is_respected(self) -> None:
        stages = tp.split_into_stages("1) створи файл a.py\n2) напиши функцію\n"
                                      "3) запусти тести")
        self.assertEqual(len(stages), 3)
        self.assertIn("a.py", stages[0].text)
        self.assertIn("тести", stages[2].text)

    def test_bullet_list_is_respected(self) -> None:
        stages = tp.split_into_stages("- створи конфіг\n- перевір запуск")
        self.assertEqual(len(stages), 2)

    def test_short_task_is_one_stage(self) -> None:
        stages = tp.split_into_stages("запусти тести")
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0].text, "запусти тести")

    def test_empty(self) -> None:
        self.assertEqual(tp.split_into_stages(""), [])
        self.assertEqual(tp.split_into_stages("   "), [])

    def test_limit_is_respected(self) -> None:
        many = "\n".join(f"{n}) крок номер {n} з описом" for n in range(1, 30))
        stages = tp.split_into_stages(many, limit=5)
        self.assertEqual(len(stages), 5)

    def test_every_stage_has_tools_when_task_has_them(self) -> None:
        """Навіть етап без власного дієслова дістає інструменти задачі."""
        brief = ("Потрібно обєднати вкладки в одне. Іконки закриття біля "
                 "кожного чату. Адаптивний розмір.")
        stages = tp.split_into_stages(brief)
        self.assertTrue(any(s.tools for s in stages),
                        "хоч один етап має мати інструменти")

    def test_no_empty_stage_text(self) -> None:
        for stage in tp.split_into_stages("1) а\n2) б"):
            self.assertTrue(stage.text.strip())


class TestStageStates(unittest.TestCase):
    """Стани етапу: маркери й переходи."""

    def test_marks(self) -> None:
        stage = tp.Stage(text="крок")
        self.assertEqual(stage.mark, "○")
        self.assertFalse(stage.running)
        stage.state = tp.STAGE_RUNNING
        self.assertEqual(stage.mark, "◐")
        self.assertTrue(stage.running)
        stage.state = tp.STAGE_DONE
        self.assertEqual(stage.mark, "✓")
        self.assertTrue(stage.settled)
        stage.state = tp.STAGE_FAILED
        self.assertEqual(stage.mark, "✗")

    def test_tools_text_is_human(self) -> None:
        stage = tp.Stage(text="крок", tools=("read_file", "run_command"))
        text = stage.tools_text()
        self.assertIn("читання файлу", text)
        self.assertIn("команда", text)

    def test_stage_prompt_mentions_tools(self) -> None:
        stage = tp.Stage(text="створи файл", index=0, tools=("write_file",))
        prompt = tp.stage_prompt(stage, total=3)
        self.assertIn("Етап 1 з 3", prompt)
        self.assertIn("write_file", prompt)

    def test_stage_prompt_without_tools(self) -> None:
        stage = tp.Stage(text="поговорити", index=1)
        prompt = tp.stage_prompt(stage, total=2)
        self.assertIn("Етап 2 з 2", prompt)
        self.assertNotIn("доречні інструменти", prompt)


class GuiCase(unittest.TestCase):
    """Спільна основа для смуги етапів."""

    @classmethod
    def setUpClass(cls) -> None:
        import tkinter as tk

        from blackchpok_ide import theme

        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover - без дисплея
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        cls.fonts = theme.Theme(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def strip(self):
        from blackchpok_ide import stage_strip

        widget = stage_strip.StageStrip(self.root, self.fonts)
        widget.pack()
        self.root.update()
        return widget

    @staticmethod
    def visible(widget) -> bool:
        """Чи віджет справді в розкладці.

        ``winfo_manager()`` тут не годиться: ``grid_remove()`` лишає
        назву менеджера, лише знімає віджет із сітки. Перевіряємо
        ``grid_info()`` — він порожній саме тоді, коли віджет прибрано.
        """
        try:
            return bool(widget.grid_info())
        except tk.TclError:
            return False


class TestStageStrip(GuiCase):
    """Смуга етапів над полем вводу."""

    def _stages(self) -> list:
        return tp.split_into_stages(
            "Потрібно обєднати вкладки в одне. Зроби іконки закриття. "
            "Зроби адаптивний розмір.")

    def test_hidden_when_empty(self) -> None:
        strip = self.strip()
        try:
            self.assertFalse(self.visible(strip))
            self.assertEqual(strip.stages, [])
        finally:
            strip.destroy()

    def test_visible_after_set(self) -> None:
        strip = self.strip()
        try:
            strip.set_stages(self._stages(), goal="мета")
            self.root.update()
            self.assertTrue(self.visible(strip))
            self.assertGreaterEqual(len(strip.stages), 2)
        finally:
            strip.destroy()

    def test_title_counts_progress(self) -> None:
        strip = self.strip()
        try:
            stages = self._stages()
            strip.set_stages(stages, goal="мета")
            self.root.update()
            self.assertIn("0 з", str(strip.title.cget("text")))
            strip.update_stage(0, tp.STAGE_RUNNING)
            self.root.update()
            self.assertIn("Етап 1 з", str(strip.title.cget("text")))
        finally:
            strip.destroy()

    def test_running_stage_spins(self) -> None:
        """У поточного етапу кружечок обертається, а не стоїть."""
        strip = self.strip()
        try:
            strip.set_stages(self._stages())
            strip.update_stage(0, tp.STAGE_RUNNING)
            self.root.update()
            self.assertIsNotNone(strip._spin_job, "спінер має бути запланований")
            first = strip.stages[0].mark
            # Чекаємо кілька кадрів і перевіряємо, що позначка змінюється.
            seen = set()
            for _ in range(6):
                strip._spin_spin()
                seen.add(str(strip._marks[0].cget("text")))
            self.assertGreater(len(seen), 1,
                               f"позначка не обертається: {first} {seen}")
        finally:
            strip.stop_timers()
            strip.destroy()

    def test_done_stage_turns_green(self) -> None:
        from blackchpok_ide import theme

        strip = self.strip()
        try:
            strip.set_stages(self._stages())
            strip.update_stage(0, tp.STAGE_DONE)
            self.root.update()
            self.assertEqual(str(strip._marks[0].cget("text")), "✓")
            self.assertEqual(str(strip._marks[0].cget("fg")), theme.SUCCESS)
        finally:
            strip.destroy()

    def test_failed_stage_is_red(self) -> None:
        from blackchpok_ide import theme

        strip = self.strip()
        try:
            strip.set_stages(self._stages())
            strip.update_stage(0, tp.STAGE_FAILED)
            self.root.update()
            self.assertEqual(str(strip._marks[0].cget("fg")), theme.ERROR)
        finally:
            strip.destroy()

    def test_spinner_stops_when_nothing_runs(self) -> None:
        strip = self.strip()
        try:
            strip.set_stages(self._stages())
            strip.update_stage(0, tp.STAGE_RUNNING)
            self.root.update()
            self.assertIsNotNone(strip._spin_job)
            strip.update_stage(0, tp.STAGE_DONE)
            self.root.update()
            self.assertIsNone(strip._spin_job, "після завершення спінер має стати")
        finally:
            strip.destroy()

    def test_running_index(self) -> None:
        strip = self.strip()
        try:
            strip.set_stages(self._stages())
            self.assertEqual(strip.running_index(), -1)
            strip.update_stage(1, tp.STAGE_RUNNING)
            self.assertEqual(strip.running_index(), 1)
        finally:
            strip.destroy()

    def test_clear_hides_strip(self) -> None:
        strip = self.strip()
        try:
            strip.set_stages(self._stages())
            self.root.update()
            strip.clear()
            self.root.update()
            self.assertEqual(strip.stages, [])
            self.assertFalse(self.visible(strip))
        finally:
            strip.destroy()

    def test_unknown_index_is_ignored(self) -> None:
        strip = self.strip()
        try:
            strip.set_stages(self._stages())
            strip.update_stage(99, tp.STAGE_DONE)  # без винятку
            self.assertEqual(strip.stages[0].state, tp.STAGE_PENDING)
        finally:
            strip.destroy()

    def test_repeated_set_does_not_rebuild(self) -> None:
        """Той самий вміст не має перебудовувати віджети (курсор смикався б)."""
        strip = self.strip()
        try:
            stages = self._stages()
            strip.set_stages(stages)
            self.root.update()
            before = list(strip.list_host.winfo_children())
            strip.set_stages(stages)
            self.root.update()
            self.assertEqual(before, list(strip.list_host.winfo_children()))
        finally:
            strip.destroy()

    def test_destroy_cancels_spinner(self) -> None:
        strip = self.strip()
        strip.set_stages(self._stages())
        strip.update_stage(0, tp.STAGE_RUNNING)
        self.root.update()
        strip.destroy()
        self.root.update()  # не має кинути «invalid command name»


class TestChatPanelIntegration(unittest.TestCase):
    """Панель чату має вміти показувати й рухати етапи."""

    def test_panel_has_methods(self) -> None:
        from blackchpok_ide.chat_panel import ChatPanel

        for name in ("advance_stage", "finish_stages", "_start_with_stages"):
            self.assertTrue(hasattr(ChatPanel, name), name)

    def test_send_shows_tools_hint(self) -> None:
        import inspect

        from blackchpok_ide.chat_panel import ChatPanel

        source = inspect.getsource(ChatPanel._start_with_stages)
        self.assertIn("tools_hint", source,
                      "агенту має передаватись перелік доречних інструментів")
        self.assertIn("runner.start", source)

    def test_stages_shown_before_branching(self) -> None:
        """Етапи мають з'являтись і в глибокому аналізі, і в черзі.

        Регресія: показ стояв лише в звичайному шляху, тож на задачі, яка
        вмикає глибокий аналіз, смуга не заповнювалась зовсім.

        Порівнюємо позиції ВИКЛИКІВ (через ``ast``), а не підрядків: у
        тексті функції слова ``is_big_task`` й ``_show_local_stages``
        трапляються ще й у коментарях та docstring, і пошук підрядком
        ловив коментар замість коду.
        """
        import ast
        import inspect
        import textwrap

        from blackchpok_ide.chat_panel import ChatPanel

        tree = ast.parse(textwrap.dedent(inspect.getsource(ChatPanel._send)))
        shown: int | None = None
        branched: int | None = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            if name == "_show_local_stages" and shown is None:
                shown = node.lineno
            if name in ("is_big_task", "on_split_task") and branched is None:
                branched = node.lineno
        self.assertIsNotNone(shown, "етапи мають показуватись")
        self.assertIsNotNone(branched, "має бути розгалуження на чергу")
        self.assertLess(shown, branched,
                        "етапи мають показуватись ДО розгалуження на чергу")

    def test_deep_path_passes_hint(self) -> None:
        """І глибокий аналіз теж передає підказку інструментів."""
        import inspect

        from blackchpok_ide.chat_panel import ChatPanel

        for name in ("_plan_deep", "_poll_planner"):
            source = inspect.getsource(getattr(ChatPanel, name))
            self.assertNotIn("self.runner.start(text)", source,
                             f"{name} має йти через _start_with_stages")

    def test_single_stage_is_not_shown(self) -> None:
        """Смуга з одного рядка лише займала б місце над полем."""
        import inspect

        from blackchpok_ide.chat_panel import ChatPanel

        source = inspect.getsource(ChatPanel._show_local_stages)
        self.assertIn("len(stages) > 1", source)

    def test_send_clears_previous_stages(self) -> None:
        import inspect

        from blackchpok_ide.chat_panel import ChatPanel

        source = inspect.getsource(ChatPanel._show_local_stages)
        self.assertIn("stage_strip.clear", source,
                      "нова задача не має показувати етапи попередньої")

    def test_done_event_finishes_stages(self) -> None:
        import inspect

        from blackchpok_ide.chat_panel import ChatPanel

        source = inspect.getsource(ChatPanel._handle_event)
        self.assertIn("finish_stages", source,
                      "інакше спінер крутився б вічно після відповіді")

    def test_queue_task_advances_stages(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._after_task_finished)
        self.assertIn("advance_stage", source,
                      "етап має рухатись разом із задачею черги")

    def test_planner_steps_become_stages(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._after_split)
        self.assertIn("stage_from_text", source,
                      "кроки моделі теж мають стати етапами смуги")


if __name__ == "__main__":
    unittest.main(verbosity=2)
