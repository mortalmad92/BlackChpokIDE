"""Тести картки глибокого аналізу ``deep_view`` (у справжньому вікні Tk).

``deep_view`` був єдиним модулем без тестів, і саме тому його «тихі»
обробники ``except tk.TclError: pass`` ніхто не перевіряв. Кожен такий
обробник — місце, де віджет уже знищено, а фоновий потік агента ще
дописує в картку. Тому перевіряємо дві речі:

1. **видиму поведінку** — що саме бачить людина (тексти, кружечки, стани,
   згортання, переноси рядків);
2. **тишу при знищених віджетах** — жоден виклик не має кидати виняток,
   навіть якщо віджет уже зник (це і є сенс тих обробників).

Запуск: python -m unittest tests.test_deep_view -v
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class GuiCase(unittest.TestCase):
    """Спільна основа: одне приховане вікно й набір шрифтів."""

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
        except Exception:  # noqa: BLE001 - закриття не має валити тест
            pass

    def setUp(self) -> None:
        import tkinter as tk

        self.host = tk.Frame(self.root)
        self.host.pack(fill="both", expand=True)

    def tearDown(self) -> None:
        try:
            self.host.destroy()
        except Exception:  # noqa: BLE001
            pass

    def pump(self) -> None:
        self.root.update()

    # ── фабрики ────────────────────────────────────────────────────────────
    def session(self, goal: str = "Зробити екран налаштувань"):
        from blackchpok_ide import deep_mode

        return deep_mode.DeepSession(goal=goal)

    def card(self, *, wrap_width: int = 520, session=None):
        from blackchpok_ide import deep_view

        card = deep_view.DeepCard(
            self.host, self.fonts, session or self.session(), wrap_width=wrap_width)
        card.pack(fill="x")
        self.pump()
        return card

    def group(self, title: str = "Читання файлів"):
        from blackchpok_ide import deep_view

        group = deep_view._ThoughtGroup(self.host, title)
        group.pack(fill="x")
        self.pump()
        return group


def _text(widget) -> str:
    return str(widget.cget("text"))


class TestThoughtGroup(GuiCase):
    """Згортаний блок кроків: заголовок, лічильник, стрілка, рядки."""

    def test_builds_with_title_and_collapsed(self) -> None:
        group = self.group("Читання файлів")
        self.assertEqual(_text(group.title_label), "Читання файлів")
        self.assertFalse(group.expanded)
        self.assertEqual(_text(group.arrow), "▸")
        self.assertEqual(group.row_count, 0)
        self.assertEqual(_text(group.state_label), "міркую…")

    def test_toggle_expands_and_collapses(self) -> None:
        group = self.group()
        group.toggle()
        self.assertTrue(group.expanded)
        self.assertEqual(_text(group.arrow), "▾")
        self.assertTrue(group.body.winfo_manager())
        group.toggle()
        self.assertFalse(group.expanded)
        self.assertEqual(_text(group.arrow), "▸")
        self.assertFalse(group.body.winfo_manager())

    def test_set_expanded_is_idempotent(self) -> None:
        group = self.group()
        group.set_expanded(True)
        group.set_expanded(True)
        self.assertTrue(group.expanded)
        self.assertEqual(_text(group.arrow), "▾")

    def test_header_click_is_bound(self) -> None:
        """Клік по заголовку має розгортати блок."""
        group = self.group()
        for widget in (group.head, group.arrow, group.title_label, group.count_label):
            self.assertTrue(str(widget.bind("<Button-1>")).strip(), widget)

    def test_count_label_singular_and_plural(self) -> None:
        group = self.group()
        group.add_row("read_file main.py")
        self.assertEqual(_text(group.count_label), "1 крок")
        group.add_row("read_file server.py")
        self.assertEqual(_text(group.count_label), "2 кроків")
        self.assertEqual(group.row_count, 2)

    def test_row_marks_and_colours(self) -> None:
        from blackchpok_ide import theme

        group = self.group()
        group.add_row("нейтральний")
        group.add_row("успіх", ok=True)
        group.add_row("провал", ok=False)
        texts = [_text(row) for row in group._rows]
        self.assertEqual(texts, ["· нейтральний", "✓ успіх", "✗ провал"])
        self.assertEqual(group._rows[0].cget("fg"), theme.FG_FAINT)
        self.assertEqual(group._rows[1].cget("fg"), theme.SUCCESS)
        self.assertEqual(group._rows[2].cget("fg"), theme.ERROR)

    def test_finish_marks_state(self) -> None:
        from blackchpok_ide import theme

        group = self.group()
        group.finish(ok=True)
        self.assertEqual(_text(group.state_label), "✓")
        self.assertEqual(group.state_label.cget("fg"), theme.SUCCESS)
        group.finish(ok=False)
        self.assertEqual(_text(group.state_label), "✗")
        self.assertEqual(group.state_label.cget("fg"), theme.ERROR)

    def test_set_title(self) -> None:
        group = self.group("Стара")
        group.set_title("Читання файлів, пошук коду")
        self.assertEqual(_text(group.title_label), "Читання файлів, пошук коду")

    def test_apply_wrap_sets_rows(self) -> None:
        group = self.group()
        group.add_row("довгий рядок з текстом")
        group.apply_wrap(300)
        self.assertEqual(int(float(group._rows[0].cget("wraplength"))), 300)

    def test_apply_wrap_never_shrinks_below_readable(self) -> None:
        """Дуже вузький чат не має робити рядки по одному символу."""
        group = self.group()
        group.add_row("текст")
        group.apply_wrap(10)
        self.assertEqual(int(float(group._rows[0].cget("wraplength"))), 160)

    # ── тихі обробники знищених віджетів ──────────────────────────────────
    def test_destroyed_parts_do_not_raise(self) -> None:
        group = self.group()
        group.add_row("рядок")
        group.body.destroy()
        group.title_label.destroy()
        group.count_label.destroy()
        group.state_label.destroy()
        group.arrow.destroy()
        # Усі методи мають тихо промовчати, а не кинути TclError.
        group.set_expanded(True)
        group.set_expanded(False)
        group.set_title("нове")
        group.add_row("ще рядок")
        group.finish(ok=False)
        group._paint_count()
        group.apply_wrap(280)
        self.assertTrue(group.expanded is False)
        self.assertEqual(group.row_count, 2)

    def test_apply_wrap_skips_destroyed_row(self) -> None:
        group = self.group()
        group.add_row("перший")
        group.add_row("другий")
        group._rows[0].destroy()
        group.apply_wrap(320)  # має пропустити знищений рядок
        self.assertEqual(int(float(group._rows[1].cget("wraplength"))), 320)


class TestDeepCardBuild(GuiCase):
    """Заголовок, таймер, панель задач і блок цілі з'являються одразу."""

    def test_header_and_goal(self) -> None:
        import tkinter as tk

        from blackchpok_ide import pulse

        card = self.card()
        self.assertEqual(_text(card.title_label), "Глибоке розмислення")
        self.assertEqual(_text(card.timer_label), "0с")
        self.assertIsInstance(card.dot, tk.Canvas)
        self.assertEqual(card.dot.state, pulse.PulseDot.RUNNING)
        self.assertIn("Поточна ціль", _text(card.goal_label))
        self.assertIn("Зробити екран", _text(card.goal_label))

    def test_goal_placeholder_when_empty(self) -> None:
        card = self.card(session=self.session(goal=""))
        self.assertIn("Поточна ціль", _text(card.goal_label))
        self.assertNotIn("None", _text(card.goal_label))

    def test_tasks_panel_starts_empty(self) -> None:
        card = self.card()
        self.assertEqual(_text(card.tasks_count), "задач немає")
        self.assertEqual(_text(card.tasks_arrow), "▾")
        self.assertEqual(card.tasks_list.winfo_children(), [])

    def test_wrap_width_has_floor(self) -> None:
        card = self.card(wrap_width=10)
        self.assertEqual(card._wrap, 240)

    def test_wrap_width_rounds_to_int(self) -> None:
        card = self.card(wrap_width=377.9)
        self.assertEqual(card._wrap, 377)


class TestNarration(GuiCase):
    """Проміжні думки агента — окремі абзаци стрічки."""

    def test_narration_adds_label_and_counts(self) -> None:
        card = self.card()
        card.add_narration("  Розберуся,   що зараз відкриває браузер. ")
        labels = [c for c in card.thoughts.winfo_children()
                  if _text(c) == "Розберуся, що зараз відкриває браузер."]
        self.assertEqual(len(labels), 1, "текст має бути стиснутий до одного рядка")
        self.assertEqual(card.session.narrations, 1)

    def test_blank_narration_is_ignored(self) -> None:
        card = self.card()
        for text in ("", "   ", "\n\t"):
            card.add_narration(text)
        self.assertEqual(card.session.narrations, 0)
        self.assertEqual(card.thoughts.winfo_children(), [])

    def test_narration_closes_open_group(self) -> None:
        from blackchpok_ide import theme

        card = self.card()
        card.add_tool("read_file", "main.py")
        group = card._group
        card.add_narration("Тепер зрозуміло.")
        self.assertIsNone(card._group)
        self.assertEqual(_text(group.state_label), "✓")
        self.assertEqual(group.state_label.cget("fg"), theme.SUCCESS)


class TestToolGrouping(GuiCase):
    """Групування кроків: читання й пошук — один етап, зміни й команди — інші."""

    def _groups(self, card):
        from blackchpok_ide.deep_view import _ThoughtGroup

        return [c for c in card.thoughts.winfo_children()
                if isinstance(c, _ThoughtGroup)]

    def test_first_tool_creates_group(self) -> None:
        card = self.card()
        card.add_tool("read_file", "main.py")
        groups = self._groups(card)
        self.assertEqual(len(groups), 1)
        self.assertEqual(_text(groups[0].title_label), "Читання файлів")
        self.assertEqual(groups[0].row_count, 1)
        self.assertEqual(_text(groups[0]._rows[0]), "· read_file main.py")

    def test_read_and_search_share_group(self) -> None:
        card = self.card()
        card.add_tool("read_file", "main.py")
        card.add_tool("search_text", "deep_view")
        groups = self._groups(card)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].row_count, 2)
        self.assertEqual(_text(groups[0].title_label),
                         "Читання файлів, Пошук коду")

    def test_run_command_starts_new_group(self) -> None:
        card = self.card()
        card.add_tool("read_file", "main.py")
        first = card._group
        card.add_tool("run_command", "pytest")
        groups = self._groups(card)
        self.assertEqual(len(groups), 2)
        self.assertIsNot(card._group, first)
        self.assertEqual(_text(groups[1].title_label), "Виконання команд")
        # Попередня група закрита галочкою.
        self.assertEqual(_text(first.state_label), "✓")

    def test_same_category_continues_group(self) -> None:
        card = self.card()
        card.add_tool("write_file", "a.py")
        card.add_tool("edit_file", "b.py")
        groups = self._groups(card)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].row_count, 2)

    def test_unknown_tool_is_other_and_separate(self) -> None:
        card = self.card()
        card.add_tool("read_file", "main.py")
        card.add_tool("mystery_tool")
        groups = self._groups(card)
        self.assertEqual(len(groups), 2)
        self.assertEqual(_text(groups[1].title_label), "Інструменти")

    def test_router_prefix_is_stripped(self) -> None:
        card = self.card()
        card.add_tool("read_file", "main.py")
        card.add_tool("router:search_text", "todo")
        groups = self._groups(card)
        self.assertEqual(len(groups), 1)
        self.assertEqual(_text(groups[0].title_label),
                         "Читання файлів, Пошук коду")

    def test_tool_without_target_has_no_trailing_space(self) -> None:
        card = self.card()
        card.add_tool("list_dir")
        self.assertEqual(_text(card._group._rows[0]), "· list_dir")

    def test_finish_tool_marks_last_row(self) -> None:
        card = self.card()
        card.add_tool("read_file", "main.py")
        card.finish_tool(ok=True)
        self.assertEqual(_text(card._group._rows[-1]), "✓ готово")
        card.finish_tool(ok=False)
        self.assertEqual(_text(card._group._rows[-1]), "✗ помилка")

    def test_finish_tool_without_group_is_noop(self) -> None:
        card = self.card()
        card.finish_tool()  # не має кидати
        self.assertIsNone(card._group)


class TestTasks(GuiCase):
    """Панель «Діла»: побудова, оновлення на місці, згортання."""

    def test_set_tasks_builds_rows(self) -> None:
        card = self.card()
        card.set_tasks(["Перший крок", "Другий крок", "Третій крок"])
        self.assertEqual(len(card._task_rows), 3)
        self.assertEqual(len(card.session.tasks), 3)
        self.assertEqual(_text(card.tasks_count), "3 в очікуванні")
        self.assertEqual(_text(card._task_rows[0]["mark"]), "○")

    def test_set_tasks_replaces_previous(self) -> None:
        card = self.card()
        card.set_tasks(["один", "два", "три"])
        card.set_tasks(["єдиний"])
        self.assertEqual(len(card._task_rows), 1)
        self.assertEqual(len(card.tasks_list.winfo_children()), 1)

    def test_set_tasks_empty(self) -> None:
        card = self.card()
        card.set_tasks([])
        self.assertEqual(_text(card.tasks_count), "задач немає")
        self.assertEqual(card.session.tasks, [])
        self.assertEqual(card.tasks_list.winfo_children(), [])

    def test_paint_task_running(self) -> None:
        from blackchpok_ide import deep_mode, theme

        card = self.card()
        card.set_tasks(["Перший крок", "Другий крок"])
        card.session.mark(0, deep_mode.STATE_RUNNING)
        card.paint_task(0)
        row = card._task_rows[0]
        self.assertEqual(_text(row["mark"]), "◐")
        self.assertEqual(row["mark"].cget("fg"), theme.ACCENT)
        self.assertEqual(row["text"].cget("fg"), theme.FG)
        self.assertEqual(_text(card.tasks_count), "1 у процесі · 1 в очікуванні")

    def test_paint_task_done_and_failed(self) -> None:
        from blackchpok_ide import deep_mode, theme

        card = self.card()
        card.set_tasks(["перший", "другий", "третій"])
        card.session.mark(0, deep_mode.STATE_DONE)
        card.session.mark(1, deep_mode.STATE_FAILED)
        card.paint_task(0)
        card.paint_task(1)
        self.assertEqual(_text(card._task_rows[0]["mark"]), "●")
        self.assertEqual(card._task_rows[0]["mark"].cget("fg"), theme.SUCCESS)
        self.assertEqual(card._task_rows[0]["text"].cget("fg"), theme.FG_FAINT)
        self.assertEqual(_text(card._task_rows[1]["mark"]), "✗")
        self.assertEqual(card._task_rows[1]["mark"].cget("fg"), theme.ERROR)

    def test_paint_pending_stays_dim(self) -> None:
        from blackchpok_ide import theme

        card = self.card()
        card.set_tasks(["перший"])
        card.paint_task(0)
        self.assertEqual(card._task_rows[0]["mark"].cget("fg"), theme.FG_FAINT)
        self.assertEqual(card._task_rows[0]["text"].cget("fg"), theme.FG_DIM)

    def test_paint_unknown_index_is_noop(self) -> None:
        card = self.card()
        card.set_tasks(["перший"])
        card.paint_task(99)   # тихо, без винятку
        card.paint_task(-1)
        self.assertEqual(_text(card.tasks_count), "1 в очікуванні")

    def test_toggle_tasks_hides_and_shows(self) -> None:
        card = self.card()
        card.set_tasks(["перший"])
        self.assertTrue(card.tasks_list.winfo_manager())
        card.toggle_tasks()
        self.assertFalse(card.tasks_list.winfo_manager())
        self.assertEqual(_text(card.tasks_arrow), "▸")
        card.toggle_tasks()
        self.assertTrue(card.tasks_list.winfo_manager())
        self.assertEqual(_text(card.tasks_arrow), "▾")

    def test_tasks_header_click_is_bound(self) -> None:
        card = self.card()
        self.assertTrue(str(card.tasks_arrow.bind("<Button-1>")).strip())

    # ── тихі обробники ────────────────────────────────────────────────────
    def test_destroyed_count_label_does_not_raise(self) -> None:
        card = self.card()
        card.set_tasks(["перший"])
        card.tasks_count.destroy()
        card.paint_task(0)  # _paint_tasks_count має промовчати

    def test_destroyed_task_labels_do_not_raise(self) -> None:
        card = self.card()
        card.set_tasks(["перший", "другий"])
        card._task_rows[0]["mark"].destroy()
        card._task_rows[0]["text"].destroy()
        card.paint_task(0)

    def test_destroyed_arrow_does_not_raise(self) -> None:
        card = self.card()
        card.set_tasks(["перший"])
        card.tasks_arrow.destroy()
        card.toggle_tasks()
        self.assertFalse(card._expanded_tasks)


class TestGoal(GuiCase):
    """Блок «Поточна ціль»."""

    def test_set_goal_updates_label(self) -> None:
        card = self.card()
        card.set_goal("  Змінити   заголовок вікна  ")
        self.assertEqual(card._goal_text, "Змінити заголовок вікна")
        self.assertIn("Змінити заголовок вікна", _text(card.goal_label))

    def test_long_goal_is_shortened(self) -> None:
        card = self.card()
        card.set_goal("слово " * 200)
        text = _text(card.goal_label)
        self.assertIn("…", text)
        self.assertLess(len(text), 260)

    def test_empty_goal(self) -> None:
        card = self.card()
        card.set_goal("")
        self.assertEqual(card._goal_text, "")
        self.assertIn("Поточна ціль", _text(card.goal_label))

    def test_destroyed_goal_label_does_not_raise(self) -> None:
        card = self.card()
        card.goal_label.destroy()
        card.set_goal("нова ціль")
        self.assertEqual(card._goal_text, "нова ціль")


class TestTimer(GuiCase):
    """Таймер «7м 0с»: цокає, поки сесія жива, і застигає на завершенні."""

    def test_timer_is_scheduled_at_start(self) -> None:
        card = self.card()
        self.assertIsNotNone(card._timer_job)

    def test_timer_shows_elapsed_text(self) -> None:
        card = self.card()
        card.session.started_at = time.time() - 125
        card._paint_timer()
        self.assertEqual(_text(card.timer_label), "2м 5с")

    def test_stop_timers_cancels_job(self) -> None:
        card = self.card()
        card.stop_timers()
        self.assertIsNone(card._timer_job)

    def test_finish_stops_timer(self) -> None:
        card = self.card()
        card.finish(ok=True)
        self.assertIsNone(card._timer_job)
        card._start_timer()          # повторний старт не має дублювати job
        self.assertIsNone(card._timer_job)

    def test_stop_timer_is_idempotent(self) -> None:
        card = self.card()
        card.stop_timers()
        card.stop_timers()
        self.assertIsNone(card._timer_job)

    def test_destroyed_timer_label_does_not_raise(self) -> None:
        card = self.card()
        card.timer_label.destroy()
        card._paint_timer()
        card.session.started_at = time.time() - 5
        card._tick()


class TestFinish(GuiCase):
    """Завершення сеансу: підсумок, крапка, задачі."""

    def test_finish_marks_success(self) -> None:
        from blackchpok_ide import pulse, theme

        card = self.card()
        card.set_tasks(["перший", "другий"])
        card.finish(ok=True)
        self.assertEqual(card.dot.state, pulse.PulseDot.DONE)
        self.assertEqual(card.timer_label.cget("fg"), theme.FG_FAINT)
        self.assertEqual(_text(card.title_label), "Аналіз завершен")
        self.assertTrue(card.session.done)
        self.assertEqual(_text(card.tasks_count), "2 готово")

    def test_finish_marks_failure(self) -> None:
        from blackchpok_ide import deep_mode, pulse, theme

        card = self.card()
        card.set_tasks(["перший", "другий"])
        card.session.mark(0, deep_mode.STATE_RUNNING)
        card.paint_task(0)
        card.finish(ok=False)
        self.assertEqual(card.dot.state, pulse.PulseDot.FAILED)
        self.assertEqual(card.timer_label.cget("fg"), theme.ERROR)
        self.assertEqual(_text(card.title_label), "Аналіз завершен")
        self.assertEqual(_text(card._task_rows[0]["mark"]), "✗")
        self.assertEqual(card.session.error, "виконання зупинено")

    def test_finish_closes_open_group(self) -> None:
        card = self.card()
        card.add_tool("read_file", "main.py")
        group = card._group
        card.finish()
        self.assertIsNone(card._group)
        self.assertEqual(_text(group.state_label), "✓")

    def test_finish_without_tasks(self) -> None:
        card = self.card()
        card.finish()  # порожній сеанс не має ламати підсумок
        self.assertEqual(_text(card.tasks_count), "задач немає")

    def test_finish_twice_is_safe(self) -> None:
        card = self.card()
        card.set_tasks(["перший"])
        card.finish(ok=True)
        card.finish(ok=True)
        self.assertEqual(_text(card.tasks_count), "1 готово")

    def test_destroyed_parts_do_not_raise(self) -> None:
        card = self.card()
        card.set_tasks(["перший"])
        card.title_label.destroy()
        card.timer_label.destroy()
        card.finish(ok=False)  # тихо


class TestApplyWrap(GuiCase):
    """Зміна ширини чату: переноси оновлюються в усіх частинах картки."""

    def test_updates_narration_rows_and_goal(self) -> None:
        card = self.card()
        card.add_narration("Довга думка агента про проєкт")
        card.set_tasks(["довга задача з текстом"])
        card.apply_wrap(400)
        self.assertEqual(card._wrap, 400)
        narration = card.thoughts.winfo_children()[0]
        self.assertEqual(int(float(narration.cget("wraplength"))), 380)
        self.assertEqual(
            int(float(card.goal_label.cget("wraplength"))), 340)
        self.assertEqual(
            int(float(card._task_rows[0]["text"].cget("wraplength"))), 350)

    def test_updates_group_rows(self) -> None:
        card = self.card()
        card.add_tool("read_file", "main.py")
        group = card._group
        card.apply_wrap(420)
        self.assertEqual(int(float(group._rows[0].cget("wraplength"))), 370)

    def test_floor_is_kept(self) -> None:
        card = self.card()
        card.apply_wrap(10)
        self.assertEqual(card._wrap, 240)

    def test_destroyed_rows_do_not_raise(self) -> None:
        card = self.card()
        card.set_tasks(["перший"])
        card._task_rows[0]["text"].destroy()
        card.add_narration("думка")
        card.thoughts.winfo_children()[0].destroy()
        card.apply_wrap(360)  # порожній список дітей — тихо
        self.assertEqual(card._wrap, 360)


class TestIntegrationWithDeepMode(GuiCase):
    """Картка має узгоджуватись із станом сесії ``deep_mode``."""

    def test_full_session_flow(self) -> None:
        from blackchpok_ide import deep_mode

        session = deep_mode.DeepSession(goal="Переробити браузер")
        card = self.card(session=session)
        card.add_narration("Спершу вивчу проєкт.")
        card.add_tool("read_file", "browser_panel.py")
        card.finish_tool()
        card.add_tool("search_text", "open_url")
        card.add_tool("run_command", "pytest")
        plan = ["Вивчити open_url", "Переписати реєстр", "Запустити тести"]
        card.set_tasks(plan)
        self.assertEqual(session.phase, deep_mode.PHASE_PLAN)
        first = session.start_work()
        self.assertIsNotNone(first)
        card.paint_task(first.index)
        self.assertEqual(_text(card.tasks_count), "1 у процесі · 2 в очікуванні")
        session.mark(first.index, deep_mode.STATE_DONE)
        card.paint_task(first.index)
        card.finish(ok=True)
        self.assertTrue(session.done)
        self.assertEqual(_text(card.tasks_count), "3 готово")

    def test_plan_shown_flag(self) -> None:
        session = self.session()
        card = self.card(session=session)
        self.assertFalse(session.plan_shown)
        card.set_tasks(["крок"])
        self.assertTrue(session.plan_shown)


class TestTimersDoNotOutliveWidgets(unittest.TestCase):
    """Таймери мають зніматись при знищенні віджета.

    Регресія, знайдена цими тестами: ``DeepCard`` ставив ``after(500, _tick)``
    і нічого не робив на ``<Destroy>``. Коли стрічку чату очищали (або
    закривали вікно) без ``stop_timers()``, у Tcl лишався запланований
    виклик, чия команда вже зникла, і Tk друкував у stderr
    «invalid command name ..._tick». Те саме стосувалось спільного тікера
    ``pulse``.
    """

    def setUp(self) -> None:
        import tkinter as tk

        from blackchpok_ide import theme

        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as exc:  # pragma: no cover - без дисплея
            raise unittest.SkipTest(f"tkinter недоступний: {exc}") from exc
        self.fonts = theme.Theme(self.root)

    def tearDown(self) -> None:
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def test_card_timer_cancels_on_destroy(self) -> None:
        import tkinter as tk

        from blackchpok_ide import deep_mode, deep_view

        host = tk.Frame(self.root)
        host.pack()
        card = deep_view.DeepCard(
            host, self.fonts, deep_mode.DeepSession(goal="x"))
        card.pack()
        self.root.update()
        self.assertIsNotNone(card._timer_job, "таймер має бути запланований")
        host.destroy()
        self.assertIsNone(card._timer_job, "таймер має знятись разом із віджетом")

    def test_finished_card_leaves_no_job(self) -> None:
        import tkinter as tk

        from blackchpok_ide import deep_mode, deep_view, pulse

        host = tk.Frame(self.root)
        host.pack()
        card = deep_view.DeepCard(
            host, self.fonts, deep_mode.DeepSession(goal="x"))
        card.pack()
        self.root.update()
        card.finish(ok=True)
        # Власний таймер картки знято...
        self.assertIsNone(card._timer_job)
        # ...і крапка більше не просить кадрів у спільного тікера. Тікер
        # вікна лишається живим (він спільний), але без підписників він
        # сам зупиняється після наступного кадру.
        self.assertEqual(card.dot.state, pulse.PulseDot.DONE)
        ticker = pulse._TICKERS.get(str(self.root))
        if ticker is not None:
            self.assertNotIn(card.dot._on_frame, ticker._subscribers)
        host.destroy()

    def test_ticker_is_forgotten_when_window_dies(self) -> None:
        import tkinter as tk

        from blackchpok_ide import deep_mode, deep_view, pulse

        extra = tk.Toplevel(self.root)
        extra.withdraw()
        host = tk.Frame(extra)
        host.pack()
        card = deep_view.DeepCard(
            host, self.fonts, deep_mode.DeepSession(goal="x"))
        card.pack()
        self.root.update()
        key = str(extra)
        self.assertIn(key, pulse._TICKERS)
        extra.destroy()
        self.root.update()
        self.assertNotIn(key, pulse._TICKERS,
                         "тікер знищеного вікна має зникнути з обліку")


if __name__ == "__main__":
    unittest.main(verbosity=2)
