"""Тести інтелектуальної черги: планувальник, виконавець, центр завдань.

Ці тести перевіряють ГОЛОВНУ вимогу: чергу формує локальна модель, а код
лише забезпечує структуру, збереження станів, порядок виконання й
перевірку результату.

Запуск: python -m unittest tests.test_task_queue_engine -v
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import queue_engine, task_executor, task_planner  # noqa: E402


def _folder() -> Path:
    path = Path(tempfile.mkdtemp(prefix="bctq-"))
    return path


class TestPlannerParsing(unittest.TestCase):
    """Модель повертає план — розбір має бути терпимим і безпечним."""

    def test_json_objects_with_dependencies(self) -> None:
        raw = json.dumps([
            {"title": "Аналіз структури проєкту та стеку",
             "detail": "Прочитати конфігурацію", "tools": ["list_dir"]},
            {"title": "Створити структуру бази даних", "depends_on": [1]},
            {"title": "Перевірити працездатність компонентів", "depends_on": [2]},
        ], ensure_ascii=False)
        steps = task_planner.parse_plan(raw)
        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0].title, "Аналіз структури проєкту та стеку")
        self.assertEqual(steps[0].tools, ["list_dir"])
        self.assertEqual(steps[1].depends_on, [1])
        self.assertEqual(steps[2].depends_on, [2])

    def test_markdown_fence_is_stripped(self) -> None:
        raw = '```json\n[{"title": "Створити файл app.py"}]\n```'
        steps = task_planner.parse_plan(raw)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].title, "Створити файл app.py")

    def test_numbered_and_bulleted_lists(self) -> None:
        self.assertEqual(
            [s.title for s in task_planner.parse_plan("1. Створити файл\n2. Додати тести")],
            ["Створити файл", "Додати тести"])
        self.assertEqual(
            [s.title for s in task_planner.parse_plan("- Створити файл\n- Додати тести")],
            ["Створити файл", "Додати тести"])

    def test_long_title_is_split_into_detail(self) -> None:
        """Крок не може бути абзацом: назва коротка, решта — в опис."""
        long_title = ("Це дуже довга назва кроку яка містить набагато більше "
                      "слів ніж треба і перетворюється на цілий абзац тексту")
        steps = task_planner.parse_plan(json.dumps([{"title": long_title}],
                                                   ensure_ascii=False))
        self.assertEqual(len(steps), 1)
        self.assertLessEqual(len(steps[0].title.split()), task_planner.MAX_TITLE_WORDS)
        self.assertTrue(steps[0].detail, "зайвий текст має стати описом")

    def test_duplicates_are_merged(self) -> None:
        raw = json.dumps([{"title": "Створити файл"},
                          {"title": "створити ФАЙЛ"},
                          {"title": "Додати тести"}], ensure_ascii=False)
        self.assertEqual(len(task_planner.parse_plan(raw)), 2)

    def test_semantic_duplicates_are_merged(self) -> None:
        """Той самий крок іншими словами — це дубль, а не два кроки.

        На живій моделі план містив і «Створити файл greeting.py», і
        «Створити greeting.py» — агент робив ту саму роботу двічі.
        """
        raw = json.dumps([
            {"title": "Створити файл greeting.py"},
            {"title": "Створити greeting.py"},
            {"title": "Додати функцію hello до greeting.py"},
        ], ensure_ascii=False)
        steps = task_planner.parse_plan(raw)
        self.assertEqual(len(steps), 2, [s.title for s in steps])
        self.assertIn("greeting.py", steps[0].title)

    def test_different_files_are_not_merged(self) -> None:
        """Однакова дія над різними файлами — це РІЗНІ кроки."""
        raw = json.dumps([
            {"title": "Створити файл a.py"},
            {"title": "Створити файл b.py"},
        ], ensure_ascii=False)
        self.assertEqual(len(task_planner.parse_plan(raw)), 2)

    def test_repeat_step_is_kept(self) -> None:
        """«Запустити тести повторно» — окремий крок, не дубль."""
        raw = json.dumps([
            {"title": "Запустити тести"},
            {"title": "Запустити тести повторно"},
        ], ensure_ascii=False)
        self.assertEqual(len(task_planner.parse_plan(raw)), 2)

    def test_self_reference_is_dropped(self) -> None:
        raw = json.dumps([{"title": "Перший крок", "depends_on": [1]},
                          {"title": "Другий крок"}], ensure_ascii=False)
        self.assertEqual(task_planner.parse_plan(raw)[0].depends_on, [])

    def test_dependency_cycle_is_broken(self) -> None:
        """Цикл у залежностях не має лишати кроки недосяжними."""
        raw = json.dumps([{"title": "A крок", "depends_on": [2]},
                          {"title": "B крок", "depends_on": [1]}], ensure_ascii=False)
        steps = task_planner.parse_plan(raw)
        self.assertEqual(len(steps), 2)
        # Хоча б один крок має бути доступним (без залежностей уперед).
        self.assertTrue(any(not step.depends_on for step in steps), steps)
        for step in steps:
            for dep in step.depends_on:
                self.assertLess(dep, len(steps), "залежність не може вказувати наперед")

    def test_garbage_gives_empty_plan(self) -> None:
        self.assertEqual(task_planner.parse_plan("не знаю, що відповісти"), [])
        self.assertEqual(task_planner.parse_plan(""), [])

    def test_topological_order(self) -> None:
        """Кроки переставляються так, щоб залежності йшли раніше.

        Список подано у ЗВОРОТНОМУ порядку (третій → другий → перший), а
        залежності описують справжній ланцюг перший→другий→третій.
        """
        raw = json.dumps([
            {"title": "Крок третій", "depends_on": [2]},
            {"title": "Крок другий", "depends_on": [3]},
            {"title": "Крок перший"},
        ], ensure_ascii=False)
        steps = task_planner.parse_plan(raw)
        self.assertEqual([step.title for step in steps],
                         ["Крок перший", "Крок другий", "Крок третій"])

    def test_step_prompt_keeps_focus(self) -> None:
        class _Task:
            text = "Створити БД"
            detail = "таблиця users"
            number = 2
            goal = "сайт"
            tools = ["write_file"]
            file_hint = ""

        prompt = task_planner.step_prompt(_Task(), total=9)
        self.assertIn("Крок 2 із 9", prompt)
        self.assertIn("таблиця users", prompt)
        self.assertIn("write_file", prompt)
        self.assertIn("ЛИШЕ цей крок", prompt)

    def test_step_prompt_mentions_target_file(self) -> None:
        """Файл кроку має потрапляти в запит.

        Регресія: ``file_hint`` (файл, який треба правити) не передавався,
        і агент шукав файл навмання — виправлення йшло не в той модуль.
        """
        class _Task:
            text = "Виправити помилку"
            detail = ""
            number = 3
            goal = ""
            tools = []
            file_hint = "app/core.py"

        prompt = task_planner.step_prompt(_Task(), total=5)
        self.assertIn("app/core.py", prompt)

    def test_plan_markdown_is_numbered(self) -> None:
        steps = [task_planner.PlanStep(title="Перший"), task_planner.PlanStep(title="Другий")]
        text = task_planner.plan_markdown("мета", steps)
        self.assertIn("01. Перший", text)
        self.assertIn("02. Другий", text)


class TestQueuePlan(unittest.TestCase):
    """Черга: нумерація, залежності, статуси, збереження."""

    def setUp(self) -> None:
        self.folder = _folder()
        self.queue = queue_engine.TaskQueue(self.folder / "queue.json")

    def tearDown(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_steps_are_numbered_from_one(self) -> None:
        self.queue.add("стороння задача")
        tasks = self.queue.add_steps(["перший", "другий", "третій"], chat_id="c1")
        self.assertEqual([t.number for t in tasks], [1, 2, 3])
        self.assertEqual([t.number for t in self.queue.plan_tasks(chat_id="c1")],
                         [1, 2, 3])

    def test_default_chain_dependency(self) -> None:
        tasks = self.queue.add_steps(["a", "b", "c"], chat_id="c1")
        self.assertEqual(tasks[0].depends_on, [])
        self.assertEqual(tasks[1].depends_on, [tasks[0].id])
        self.assertEqual(tasks[2].depends_on, [tasks[1].id])

    def test_independent_step_can_skip_chain(self) -> None:
        tasks = self.queue.add_steps(
            [{"text": "a"}, {"text": "b", "depends_on_previous": False}], chat_id="c1")
        self.assertEqual(tasks[1].depends_on, [])
        self.assertTrue(self.queue.is_ready(tasks[1]))

    def test_dependency_blocks_start(self) -> None:
        tasks = self.queue.add_steps(["a", "b"], chat_id="c1")
        self.assertFalse(self.queue.is_ready(tasks[1]))
        self.assertEqual(len(self.queue.blocked_by(tasks[1])), 1)
        self.queue.mark_running(tasks[0].id)
        self.queue.mark_done(tasks[0].id, "готово")
        self.assertTrue(self.queue.is_ready(tasks[1]))

    def test_next_pending_skips_blocked(self) -> None:
        tasks = self.queue.add_steps(["a", "b", "c"], chat_id="c1")
        self.assertEqual(self.queue.next_pending(chat_id="c1").id, tasks[0].id)
        self.queue.mark_running(tasks[0].id)
        self.queue.mark_done(tasks[0].id, "ок")
        self.assertEqual(self.queue.next_pending(chat_id="c1").id, tasks[1].id)

    def test_all_statuses_exist(self) -> None:
        for status in ("очікує", "аналіз", "виконується", "перевірка",
                       "готово", "помилка", "призупинено", "скасовано"):
            self.assertIn(status, queue_engine.STATUS_ORDER)
            self.assertIn(status, queue_engine.STATUS_MARKS)
            self.assertIn(status, queue_engine.STATUS_LABELS)

    def test_stage_transitions(self) -> None:
        task = self.queue.add_steps(["a"], chat_id="c1")[0]
        self.queue.mark_running(task.id)
        self.assertTrue(self.queue.set_stage(task.id, queue_engine.VERIFYING,
                                             step="перевіряю"))
        self.assertEqual(self.queue.get(task.id).status, queue_engine.VERIFYING)
        self.assertEqual(self.queue.get(task.id).current_step, "перевіряю")
        self.queue.mark_done(task.id, "ок")
        self.assertEqual(self.queue.get(task.id).status, queue_engine.DONE)

    def test_pause_and_resume(self) -> None:
        task = self.queue.add_steps(["a"], chat_id="c1")[0]
        self.queue.mark_running(task.id)
        self.queue.mark_paused(task.id, "зупинено")
        self.assertEqual(self.queue.get(task.id).status, queue_engine.PAUSED)
        self.assertTrue(self.queue.retry(task.id))
        self.assertEqual(self.queue.get(task.id).status, queue_engine.PENDING)

    def test_queue_survives_restart(self) -> None:
        tasks = self.queue.add_steps(
            [{"text": "перший"}, {"text": "другий", "depends_on": [1]}], chat_id="c1")
        self.queue.mark_running(tasks[0].id)
        restored = queue_engine.TaskQueue(self.folder / "queue.json")
        self.assertEqual(len(restored.tasks), 2)
        # Активний крок після перезапуску знову очікує, а не «висить».
        self.assertEqual(restored.get(tasks[0].id).status, queue_engine.PENDING)
        self.assertEqual(restored.get(tasks[1].id).depends_on, [tasks[0].id])
        self.assertEqual([t.number for t in restored.tasks], [1, 2])

    def test_progress_counters(self) -> None:
        tasks = self.queue.add_steps(["a", "b", "c"], chat_id="c1")
        self.queue.mark_running(tasks[0].id)
        self.queue.mark_done(tasks[0].id, "ок")
        self.queue.mark_failed(tasks[1].id, "збій")
        progress = self.queue.progress()
        self.assertEqual(progress["total"], 3)
        self.assertEqual(progress["done"], 1)
        self.assertEqual(progress["errors"], 1)
        self.assertAlmostEqual(self.queue.percent_done(), 100 / 3)

    def test_old_queue_file_still_loads(self) -> None:
        """Черга, збережена до появи нових полів, має читатись."""
        path = self.folder / "old.json"
        path.write_text(json.dumps({"tasks": [
            {"text": "стара задача", "status": "очікує"},
            {"text": "виконувалась", "status": "виконується"},
        ]}), encoding="utf-8")
        queue = queue_engine.TaskQueue(path)
        self.assertEqual(len(queue.tasks), 2)
        self.assertEqual(queue.tasks[1].status, queue_engine.PENDING)
        self.assertEqual(queue.tasks[0].number, 0)
        self.assertEqual(queue.tasks[0].history, [])

    def test_new_plan_does_not_mix_with_old(self) -> None:
        """Новий план замінює старий ПОВНІСТЮ, а не додається до нього.

        Регресія з живого прогону: завершені кроки попереднього плану
        лишались у черзі, і новий план показувався як «17 задач із
        дублями» замість своїх 6.
        """
        first = self.queue.add_steps(["старий крок 1", "старий крок 2"],
                                     chat_id="c1")
        for task in first:
            self.queue.mark_running(task.id)
            self.queue.mark_done(task.id, "ок")
        self.assertEqual(len(self.queue.tasks), 2)

        dropped = self.queue.drop_plan(chat_id="c1")
        self.assertEqual(dropped, 2, "завершені кроки старого плану мають піти")
        self.assertEqual(self.queue.tasks, [])

        fresh = self.queue.add_steps(["новий крок 1", "новий крок 2"],
                                     chat_id="c1")
        self.assertEqual(len(self.queue.tasks), 2, "нова черга без залишків")
        self.assertEqual([t.number for t in fresh], [1, 2])

    def test_drop_plan_keeps_active_step(self) -> None:
        """Активний крок не можна викидати — його виконує агент."""
        tasks = self.queue.add_steps(["перший", "другий"], chat_id="c1")
        self.queue.mark_running(tasks[0].id)
        dropped = self.queue.drop_plan(chat_id="c1")
        self.assertEqual(dropped, 1)
        self.assertEqual(self.queue.get(tasks[0].id).status, queue_engine.RUNNING)
        self.assertIsNone(self.queue.get(tasks[1].id))

    def test_drop_plan_does_not_touch_other_chat(self) -> None:
        self.queue.add_steps(["чужий крок"], chat_id="other")
        self.queue.add_steps(["свій крок"], chat_id="c1")
        self.assertEqual(self.queue.drop_plan(chat_id="c1"), 1)
        self.assertEqual(len(self.queue.tasks), 1)
        self.assertEqual(self.queue.tasks[0].chat_id, "other")

    def test_remove_for_chat_clears_plan(self) -> None:
        self.queue.add_steps(["a", "b"], chat_id="c1")
        self.assertEqual(self.queue.remove_for_chat("c1"), 2)
        self.assertEqual(self.queue.tasks, [])


class TestExecutor(unittest.TestCase):
    """Виконавець: реальні кроки, перевірка результату, ліміт спроб."""

    def setUp(self) -> None:
        self.folder = _folder()
        self.queue = queue_engine.TaskQueue(self.folder / "queue.json")
        self.ran: list[str] = []
        self.executor = task_executor.QueueExecutor(
            self.queue,
            validator=task_executor.TaskValidator(lambda: self.folder),
            on_run_step=lambda task, prompt: self.ran.append(task.text),
            chat_id_provider=lambda: "c1",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_start_sets_analyzing_then_running(self) -> None:
        task = self.queue.add_steps(["Створити файл"], chat_id="c1")[0]
        self.executor.start_next()
        self.assertEqual(self.queue.get(task.id).status, queue_engine.ANALYZING)
        self.executor.note_step("list_dir(.)")
        self.assertEqual(self.queue.get(task.id).status, queue_engine.RUNNING)
        self.assertTrue(self.executor.busy)

    def test_only_one_step_at_a_time(self) -> None:
        self.queue.add_steps(["a", "b"], chat_id="c1")
        self.executor.start_next()
        self.assertIsNone(self.executor.start_next())

    def test_empty_answer_is_not_success(self) -> None:
        """Порожня відповідь не зараховується (з вичерпаними спробами — збій)."""
        limited = task_executor.QueueExecutor(
            self.queue,
            validator=task_executor.TaskValidator(lambda: self.folder),
            on_run_step=lambda task, prompt: self.ran.append(task.text),
            chat_id_provider=lambda: "c1", max_attempts=1)
        task = self.queue.add_steps(["a"], chat_id="c1")[0]
        limited.start_next()
        limited.finish(ok=True, answer="")
        self.assertEqual(self.queue.get(task.id).status, queue_engine.FAILED)

    def test_real_file_confirms_step(self) -> None:
        task = self.queue.add_steps(["Створити app.py"], chat_id="c1")[0]
        (self.folder / "app.py").write_text("print(1)\n", encoding="utf-8")
        self.executor.start_next()
        self.executor.finish(ok=True, answer="Створив app.py", changed=["app.py"])
        done = self.queue.get(task.id)
        self.assertEqual(done.status, queue_engine.DONE)
        self.assertIn("app.py", done.files_changed)

    def test_imaginary_file_is_rejected(self) -> None:
        limited = task_executor.QueueExecutor(
            self.queue,
            validator=task_executor.TaskValidator(lambda: self.folder),
            on_run_step=lambda task, prompt: self.ran.append(task.text),
            chat_id_provider=lambda: "c1", max_attempts=1)
        task = self.queue.add_steps(["Створити test_app.py"], chat_id="c1")[0]
        limited.start_next()
        limited.finish(ok=True, answer="Створив test_app.py з тестами")
        failed = self.queue.get(task.id)
        self.assertEqual(failed.status, queue_engine.FAILED)
        self.assertIn("test_app.py", failed.error)

    def test_promise_without_action_is_retried_then_failed(self) -> None:
        """Обіцянка без дії: одна повторна спроба з підказкою, далі збій.

        Локальна модель іноді відповідає словами замість виклику
        інструмента. Даємо шанс виправитись, але не безкінечно.
        """
        limited = task_executor.QueueExecutor(
            self.queue,
            validator=task_executor.TaskValidator(lambda: self.folder),
            on_run_step=lambda task, prompt: self.ran.append(task.text),
            chat_id_provider=lambda: "c1", max_attempts=2)
        task = self.queue.add_steps(["a"], chat_id="c1")[0]
        self.executor = limited
        limited.start_next()
        limited.finish(ok=True, answer="Я зроблю це далі.")
        # Перша невдача → повтор із підказкою (крок знову активний)
        self.assertEqual(self.queue.get(task.id).status, queue_engine.RUNNING,
                         "має бути повторна спроба")
        limited.finish(ok=True, answer="Я зроблю це далі.")
        self.assertEqual(self.queue.get(task.id).status, queue_engine.FAILED,
                         "після вичерпання спроб — збій")

    def test_retry_hint_mentions_tools(self) -> None:
        """Підказка при повторі має прямо казати «виклич інструмент»."""
        import inspect

        from blackchpok_ide.task_executor import QueueExecutor

        source = inspect.getsource(QueueExecutor._retry_with_hint)
        self.assertIn("ВИКЛИКАЙ", source)
        self.assertIn("write_file", source)

    def test_dependency_wait_blocks_start(self) -> None:
        tasks = self.queue.add_steps(["a", "b"], chat_id="c1")
        # Наступним має бути перший крок, а не заблокований другий.
        started = self.executor.start_next()
        self.assertEqual(started.id, tasks[0].id)

    def test_attempt_limit_stops_loops(self) -> None:
        limited = task_executor.QueueExecutor(
            self.queue, on_run_step=lambda t, p: None, max_attempts=2)
        task = self.queue.add("крок")
        for _ in range(4):
            if self.queue.get(task.id).active:
                limited.finish(ok=False, error="збій")
            if limited.start(task) is None:
                break
            if self.queue.get(task.id).active:
                limited.finish(ok=False, error="збій")
        self.assertLessEqual(self.queue.get(task.id).attempts, 2)
        self.assertIsNone(limited.start(task))

    def test_stop_pauses_current_step(self) -> None:
        task = self.queue.add_steps(["a"], chat_id="c1")[0]
        self.executor.start_next()
        self.executor.stop()
        self.assertEqual(self.queue.get(task.id).status, queue_engine.PAUSED)

    def test_resume_returns_paused_to_queue(self) -> None:
        task = self.queue.add_steps(["a"], chat_id="c1")[0]
        self.executor.start_next()
        self.executor.stop()
        self.assertTrue(self.executor.resume())
        self.assertEqual(self.queue.get(task.id).status, queue_engine.PENDING)

    def test_report_lists_failures_and_files(self) -> None:
        tasks = self.queue.add_steps(["a", "b"], chat_id="c1")
        self.queue.mark_failed(tasks[0].id, "немає доступу")
        self.queue.mark_done(tasks[1].id, "ок")
        tasks[1].files_changed = ["app.py"]
        report = self.executor.report(chat_id="c1")
        self.assertIn("немає доступу", report)
        self.assertIn("app.py", report)

    def test_replan_replaces_only_pending(self) -> None:
        tasks = self.queue.add_steps(["a", "b"], chat_id="c1")
        self.queue.mark_running(tasks[0].id)
        self.queue.mark_done(tasks[0].id, "ок")
        created = self.queue.replace_plan(
            [{"text": "новий крок один"}, {"text": "новий крок два"}], chat_id="c1")
        titles = [t.text for t in self.queue.tasks]
        self.assertIn("a", titles, "виконаний крок має лишитись")
        self.assertNotIn("b", titles, "незавершений крок замінено")
        self.assertEqual(len(created), 2)
        self.assertEqual([t.number for t in self.queue.plan_tasks(chat_id="c1")],
                         [1, 2, 3])


class TestPlannerContext(unittest.TestCase):
    """Запит до моделі має нести реальний контекст проєкту."""

    def test_messages_include_context_and_tools(self) -> None:
        messages = task_planner.build_plan_messages(
            "зроби сайт", context="Мова/стек: Python", tool_names=["write_file"])
        self.assertEqual(len(messages), 2)
        body = messages[1]["content"]
        self.assertIn("Python", body)
        self.assertIn("write_file", body)
        self.assertIn("зроби сайт", body)

    def test_replan_uses_its_own_instruction(self) -> None:
        messages = task_planner.build_plan_messages(
            "далі", existing="01. крок [готово]", replan=True)
        self.assertIn("ПЕРЕПЛАНУВАННЯ", messages[0]["content"])
        self.assertIn("01. крок [готово]", messages[1]["content"])

    def test_plan_as_text_marks_status(self) -> None:
        class _T:
            number = 1
            title = "перший"
            status = "готово"
            text = "перший"

        text = task_planner.plan_as_text([_T()])
        self.assertIn("01. перший [готово]", text)

    def test_no_model_gives_clear_error(self) -> None:
        class _LLM:
            base_url = "http://127.0.0.1:1/v1"
            model = ""
            api_key = "local"

        result = task_planner.plan_with_model("завдання", _LLM())
        self.assertFalse(result.ok)
        self.assertIn("Модель не вибрана", result.error)
        self.assertEqual(result.steps, [])


class TestContextPlan(unittest.TestCase):
    """Параметри запуску моделі: більший контекст без втрати швидкості."""

    def _profile(self):
        from blackchpok_ide import hardware

        return hardware.HardwareProfile(
            os_name="Windows", arch="AMD64", cpu_name="test",
            cpu_cores=6, cpu_threads=12,
            ram_total_gb=64.0, ram_available_gb=60.0,
            gpus=[hardware.GpuInfo(name="test", vram_gb=12.0,
                                   vendor="nvidia", backend="cuda")],
            disk_free_gb=200.0, disk_total_gb=500.0,
        )

    def _choice(self):
        from blackchpok_ide import hardware

        for choice in hardware.MODEL_CATALOG:
            if "14b" in choice.filename.lower():
                return choice
        return hardware.MODEL_CATALOG[0]

    def test_bigger_context_is_never_downgraded(self) -> None:
        """Більший запит контексту не може дати МЕНШИЙ контекст."""
        from blackchpok_ide import hardware

        profile, choice = self._profile(), self._choice()
        previous = 0
        for target in (4096, 8192, 12288, 16384):
            plan = hardware.fit(profile, choice, target_ctx=target).plan
            self.assertLessEqual(plan.ctx_size, target,
                                 "не більше, ніж просили")
            self.assertGreaterEqual(plan.ctx_size, previous,
                                    f"запит {target} дав менший контекст")
            previous = plan.ctx_size
        self.assertGreaterEqual(previous, 12288,
                                "на 12 ГБ VRAM 14B має тягнути ≥12K")

    def test_32k_uses_kv_in_ram(self) -> None:
        """32K на 12 ГБ VRAM досяжний лише винесенням KV-кешу в RAM."""
        from blackchpok_ide import hardware

        plan = hardware.fit(self._profile(), self._choice(),
                            target_ctx=32768).plan
        self.assertEqual(plan.ctx_size, 32768)
        self.assertTrue(plan.kv_in_ram, "KV-кеш має жити в RAM")
        self.assertIn("--no-kv-offload", plan.args())
        self.assertIn("--cache-type-k", plan.args())

    def test_compressed_cache_is_used(self) -> None:
        """16K має вимагати стиснутого кешу, а не відмовлятись від контексту."""
        from blackchpok_ide import hardware

        plan = hardware.fit(self._profile(), self._choice(),
                            target_ctx=16384).plan
        self.assertEqual(plan.ctx_size, 16384)
        self.assertEqual(plan.cache_type, "q8_0")
        self.assertFalse(plan.kv_in_ram, "16K має влізти без RAM")

    def test_small_context_uses_compressed_cache(self) -> None:
        """Навіть малий контекст бере q8_0: заміряно, що він не повільніший.

        f16 при 8K: 32.2 ток/с, q8_0 при 8K: 31.6 ток/с — різниця в межах
        шуму, зате кеш удвічі менший і дає змогу підняти контекст.
        """
        from blackchpok_ide import hardware

        plan = hardware.fit(self._profile(), self._choice(),
                            target_ctx=8192).plan
        self.assertEqual(plan.ctx_size, 8192)
        self.assertEqual(plan.cache_type, "q8_0")
        self.assertFalse(plan.kv_in_ram, "8K має влізти без RAM")

    def test_auto_prefers_speed_over_max_context(self) -> None:
        """«Авто» має брати контекст, який влазить у VRAM, а не в RAM.

        Заміряно: KV у VRAM → 31.7 ток/с, KV у RAM → 20.7 ток/с (−35%).
        Тому 16K на повній швидкості краще за 32K на третину повільніше —
        користувач, якому справді треба 32K, попросить його явно.
        """
        from blackchpok_ide import hardware

        plan = hardware.fit(self._profile(), self._choice()).plan
        self.assertFalse(plan.kv_in_ram,
                         "авто не має обирати повільний режим із RAM")
        self.assertEqual(plan.ctx_size, 16384)

    def test_explicit_request_may_use_ram(self) -> None:
        """Явний запит великого контексту — привід перейти в RAM."""
        from blackchpok_ide import hardware

        plan = hardware.fit(self._profile(), self._choice(),
                            target_ctx=32768).plan
        self.assertEqual(plan.ctx_size, 32768)
        self.assertTrue(plan.kv_in_ram)
        self.assertIn("--no-kv-offload", plan.args())

    def test_cache_type_does_not_cost_speed(self) -> None:
        """Вибір кешу не має коштувати швидкості — це заміряний факт.

        Якщо хтось поверне f16 першим, контекст 16K перестане влазити в
        12 ГБ VRAM і рушій тихо деградує (заміряно: 31.7 → 14.1 ток/с).
        """
        from blackchpok_ide import hardware

        profile, choice = self._profile(), self._choice()
        plan = hardware.fit(profile, choice, target_ctx=16384).plan
        # 16K має влізти у VRAM, а не піти в RAM чи деградувати.
        self.assertEqual(plan.ctx_size, 16384)
        self.assertFalse(plan.kv_in_ram)
        used = (choice.approx_gb + hardware.kv_cache_gb(choice, 16384) / 2
                + hardware.RUNTIME_OVERHEAD_GB)
        self.assertLessEqual(used, profile.vram_budget_gb,
                             "16K зі стиснутим кешем має влазити у VRAM")
        # І бюджет дійсно врахований у плані.
        self.assertLessEqual(plan.vram_hint, profile.vram_budget_gb)

    def test_launch_args_carry_context(self) -> None:
        """Параметри запуску справді містять вибраний контекст."""
        from blackchpok_ide import hardware, runtime

        plan = hardware.fit(self._profile(), self._choice(),
                            target_ctx=32768).plan
        args = runtime.ServerConfig(model_path="m.gguf", plan=plan).command()
        self.assertIn("--ctx-size", args)
        self.assertEqual(args[args.index("--ctx-size") + 1], "32768")

    def test_kv_cache_grows_with_context(self) -> None:
        from blackchpok_ide import hardware

        choice = self._choice()
        small = hardware.kv_cache_gb(choice, 8192)
        big = hardware.kv_cache_gb(choice, 32768)
        self.assertGreater(big, small)
        self.assertAlmostEqual(big / small, 4.0, places=1)


class TestNoHang(unittest.TestCase):
    """Регресії на зависання, знайдені на живій моделі.

    Кожен випадок тут колись зупиняв чергу назавжди: інтерфейс показував
    «аналіз», а робота не йшла.
    """

    def setUp(self) -> None:
        self.folder = _folder()
        self.queue = queue_engine.TaskQueue(self.folder / "queue.json")

    def tearDown(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_plan_step_is_not_split_again(self) -> None:
        """Крок плану не може запускати НОВЕ планування.

        Регресія: крок містив загальну мету, текст перевищував поріг
        ``is_big_task``, і замість виконання починалось планування — рекурсія
        без жодної файлової дії.
        """
        import inspect

        from blackchpok_ide.chat_panel import ChatPanel

        source = inspect.getsource(ChatPanel._send)
        self.assertIn("plan_step", source)
        self.assertIn("not plan_step", source,
                      "розбиття має бути вимкнене для готового кроку")
        # Глибокий аналіз теж не має вмикатись усередині кроку.
        self.assertIn("False if plan_step", source)

    def test_run_step_reports_failure_to_start(self) -> None:
        """Якщо запит не пішов агенту, крок має повернутись у чергу.

        Регресія: ``_send`` мовчки відмовляв (агент зайнятий), а крок
        лишався в стані «аналіз» назавжди.
        """
        import inspect

        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.chat_panel import ChatPanel
        from blackchpok_ide.main_window import BlackChpokIDE

        self.assertIn("return False", inspect.getsource(AgentRunner.start))
        self.assertIn("return bool(self.runner.start", inspect.getsource(
            ChatPanel._start_with_stages))
        self.assertIn("started is False", inspect.getsource(
            task_executor.QueueExecutor.start))
        self.assertIn("return bool(started)", inspect.getsource(
            BlackChpokIDE._run_plan_step))

    def test_failure_cascades_to_dependents(self) -> None:
        """Після збою залежні кроки знімаються, а не висять «очікує»."""
        tasks = self.queue.add_steps(["a", "b", "c"], chat_id="c1")
        executor = task_executor.QueueExecutor(
            self.queue, on_run_step=lambda t, p: True, chat_id_provider=lambda: "c1")
        executor.start_next()
        executor.finish(ok=False, error="збій")
        self.assertEqual(self.queue.get(tasks[0].id).status, queue_engine.FAILED)
        self.assertEqual(self.queue.get(tasks[1].id).status, queue_engine.CANCELLED)
        self.assertEqual(self.queue.get(tasks[2].id).status, queue_engine.CANCELLED)
        self.assertEqual(self.queue.unresolved(chat_id="c1"), [])

    def test_unconfirmed_result_also_cascades(self) -> None:
        """Непідтверджений результат після вичерпання спроб знімає залежні."""
        tasks = self.queue.add_steps(["створити x.py", "наступний крок"],
                                     chat_id="c1")
        executor = task_executor.QueueExecutor(
            self.queue,
            validator=task_executor.TaskValidator(lambda: self.folder),
            on_run_step=lambda t, p: True, chat_id_provider=lambda: "c1",
            max_attempts=1)   # без повторів — одразу вичерпано
        executor.start_next()
        executor.finish(ok=True, answer="Створив x.py")   # файлу немає
        self.assertEqual(self.queue.get(tasks[0].id).status, queue_engine.FAILED)
        self.assertEqual(self.queue.get(tasks[1].id).status, queue_engine.CANCELLED)

    def test_stale_step_is_not_requeued_instantly(self) -> None:
        """Крок не можна вважати завислим одразу після старту.

        Регресія: перевірка спрацьовувала в проміжку між позначенням кроку
        й стартом потоку агента, і крок повертався в чергу прямо під час
        роботи.
        """
        from types import SimpleNamespace

        from blackchpok_ide.main_window import BlackChpokIDE

        self.assertGreaterEqual(BlackChpokIDE.STALE_STEP_SECONDS, 10.0)

        queue = self.queue
        task = queue.add("крок")
        queue.mark_running(task.id)
        window = SimpleNamespace(
            task_queue=queue,
            agent=SimpleNamespace(busy=False),
            _plan_step_active=False,
            executor=SimpleNamespace(busy=False),
            STALE_STEP_SECONDS=BlackChpokIDE.STALE_STEP_SECONDS,
            set_status=lambda _t: None,
            _update_queue_badge=lambda: None,
        )
        # Той самий вираз, що й у насосі: свіжий крок НЕ вважається завислим.
        import time

        started = float(queue.get(task.id).started_at or 0.0)
        stale = (time.time() - started) > window.STALE_STEP_SECONDS
        self.assertFalse(stale, "щойно запущений крок не є завислим")

    def test_each_plan_step_starts_with_fresh_context(self) -> None:
        """Кроки не мають бачити історію попередніх кроків.

        Інакше модель на кроці N+1 відповідала «вже зроблено» з пам'яті
        кроку N і не викликала інструментів.
        """
        import inspect

        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.chat_panel import ChatPanel

        self.assertIn("fresh", inspect.getsource(AgentRunner.start))
        self.assertIn("if fresh:", inspect.getsource(AgentRunner.start))
        self.assertIn("self.session.reset()", inspect.getsource(AgentRunner.start))
        self.assertIn("fresh=plan_step", inspect.getsource(ChatPanel._send))


if __name__ == "__main__":
    unittest.main(verbosity=2)
