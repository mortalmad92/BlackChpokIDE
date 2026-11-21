"""Нескінченний чат, свобода дій і самонавчання — перевірка ВЛАСТИВОСТЕЙ.

Тести не питають «код виконався», а перевіряють те, що обіцяно людині:

* довгий чат не втрачає початку: витіснене згортається в хроніку й
  повертається в промпт наступного запиту;
* хроніка не з'їдає вікно моделі — вона підкоряється бюджету;
* рівень свободи дій справді додає кроків, але НЕ змінює дозволів і не
  рятує режим «Чат» від ліміту в один крок;
* уроки виводяться лише з ПІДТВЕРДЖЕНИХ фактів ходу, а не з будь-чого;
* збій мережі уроком не стає (він лікується повтором, а не правилом);
* приватний режим не пише ні хроніки, ні уроків.

Запуск: ``python -m unittest tests.test_long_chat_and_learning -v``
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import agent, autonomy, longchat, selflearning  # noqa: E402
from blackchpok_ide.agent_tools import ToolRegistry  # noqa: E402
from blackchpok_ide.chat_store import Chat, ChatStore  # noqa: E402
from blackchpok_ide.config import AgentSettings, LLMSettings  # noqa: E402
from blackchpok_ide.pcmm import Neuromesh  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Хроніка довгого чату
# ─────────────────────────────────────────────────────────────────────────────

class TestConversationDigest(unittest.TestCase):
    """Витіснене з вікна не зникає — воно стає хронікою."""

    def test_evicted_turn_is_kept(self) -> None:
        digest = longchat.ConversationDigest()
        digest.absorb([
            {"role": "user", "content": "Портал має бути на 8081"},
            {"role": "assistant", "content": "Зробив: порт 8081 у config.py"},
        ])
        self.assertEqual(len(digest.entries), 2)
        rendered = digest.render(window_tokens=16384)
        self.assertIn("8081", rendered)
        self.assertIn("Хроніка", rendered)

    def test_tool_output_is_not_dumped_whole(self) -> None:
        """Сирий дамп файлу в хроніку не йде — він уже в RAG."""
        digest = longchat.ConversationDigest()
        huge = "# calc.py (900 рядків)\n" + "    x = 1\n" * 900
        digest.absorb([{"role": "tool", "name": "read_file", "content": huge}])
        self.assertEqual(len(digest.entries), 1)
        text = digest.entries[0].text
        self.assertLessEqual(len(text), longchat.TOOL_CLIP + 40)
        self.assertIn("read_file", text)

    def test_repeated_identical_line_is_not_duplicated(self) -> None:
        digest = longchat.ConversationDigest()
        for _ in range(5):
            digest.absorb([{"role": "assistant", "content": "Готово."}])
        self.assertEqual(len(digest.entries), 1,
                         "той самий рядок поспіль не має дублюватись")

    def test_service_prompts_do_not_enter_digest(self) -> None:
        """Службові підказки агенту — не зміст розмови."""
        digest = longchat.ConversationDigest()
        digest.absorb([
            {"role": "user",
             "content": "Ти не дав ні тексту, ні виклику інструмента. Виконай…"},
            {"role": "assistant",
             "content": "Твої файли збережено на диску. Продовжуй роботу…"},
        ])
        self.assertTrue(digest.empty,
                        f"службові рядки потрапили в хроніку: "
                        f"{[e.text for e in digest.entries]}")

    def test_digest_respects_window_budget(self) -> None:
        """Хроніка не займає більше своєї частки вікна."""
        digest = longchat.ConversationDigest()
        for index in range(60):
            digest.absorb([{"role": "user",
                            "content": f"крок {index}: " + "пояснення " * 30}])
        small = digest.render(window_tokens=2048)
        large = digest.render(window_tokens=32768)
        self.assertLess(len(small), len(large),
                        "менше вікно має давати коротшу хроніку")
        # 12% від 2048 ≈ 246 токенів — це кілька рядків, не вся розмова.
        self.assertLess(small.count("• "), 20)

    def test_digest_is_capped_entry_wise(self) -> None:
        digest = longchat.ConversationDigest()
        for index in range(longchat.MAX_ENTRIES + 40):
            digest.absorb([{"role": "user", "content": f"повідомлення {index}"}])
        self.assertLessEqual(len(digest.entries), longchat.MAX_ENTRIES)
        self.assertGreater(digest.trimmed, 0,
                           "витиснуті рядки мають бути пораховані")

    def test_missing_older_turns_are_honestly_reported(self) -> None:
        """Якщо рядків більше, ніж влізло — блок каже, де шукати решту."""
        digest = longchat.ConversationDigest()
        for index in range(50):
            digest.absorb([{"role": "user",
                            "content": f"важливий крок номер {index}"}])
        rendered = digest.render(window_tokens=1024)
        self.assertIn("пам'яті", rendered.lower())

    def test_roundtrip_through_dict(self) -> None:
        digest = longchat.ConversationDigest()
        digest.absorb([{"role": "user", "content": "ціль проєкту — блог"}])
        restored = longchat.ConversationDigest.from_dict(digest.to_dict())
        self.assertEqual(len(restored.entries), 1)
        self.assertIn("блог", restored.entries[0].text)

    def test_garbage_input_is_tolerated(self) -> None:
        for junk in (None, "рядок", 42, [], {"entries": "не список"}):
            with self.subTest(junk=junk):
                digest = longchat.ConversationDigest.from_dict(junk)
                self.assertTrue(digest.empty)

    def test_memory_text_is_bounded(self) -> None:
        digest = longchat.ConversationDigest()
        for index in range(40):
            digest.absorb([{"role": "assistant",
                            "content": f"висновок {index} " + "деталі " * 40}])
        text = digest.memory_text()
        self.assertLessEqual(len(text), 1500)
        self.assertTrue(text.startswith("Хроніка розмови"))


class TestDigestReachesThePrompt(unittest.TestCase):
    """Хроніка мусить дійти до САМОГО запиту, а не лише лежати в пам'яті."""

    def _runner(self) -> "agent.AgentRunner":
        folder = Path(tempfile.mkdtemp(prefix="bchp-dg-"))
        registry = ToolRegistry(folder)
        settings = AgentSettings()
        return agent.AgentRunner(registry, LLMSettings(), settings, folder)

    def test_digest_block_lands_in_system_message(self) -> None:
        runner = self._runner()
        digest = longchat.ConversationDigest()
        digest.absorb([{"role": "user", "content": "пароль не змінювати ніколи"}])
        runner.attach_digest(digest)
        runner.session.context_limit = 16384
        block = runner._render_digest()
        self.assertIn("пароль", block)
        system = runner.session.system_message()["content"]
        self.assertIn("пароль", system,
                      "хроніка не потрапила в системний промпт")

    def test_evicted_block_goes_into_digest(self) -> None:
        runner = self._runner()
        runner.digest = longchat.ConversationDigest()
        runner._archive_evicted_context([
            {"role": "user", "content": "Портал на 8081, не на 8080"},
            {"role": "assistant", "content": "Записав порт 8081 у config.py"},
        ])
        self.assertEqual(len(runner.digest.entries), 2)

    def test_private_mode_keeps_nothing(self) -> None:
        """«Не зберігай» забороняє і хроніку, і пам'ять."""
        runner = self._runner()
        runner.digest = longchat.ConversationDigest()
        runner.state.private = True
        runner._archive_evicted_context([
            {"role": "user", "content": "таємний пароль 1234"}])
        self.assertTrue(runner.digest.empty,
                        "приватний режим не має писати хроніку")

    def test_rag_archive_is_called_with_text(self) -> None:
        runner = self._runner()
        seen: list[str] = []
        runner.rag_archive = lambda text, **kwargs: seen.append(text) or True
        runner._archive_evicted_context([
            {"role": "user", "content": "Потрібен портал на 8081"},
            {"role": "tool", "name": "read_file",
             "content": "# config.py\nPORT = 8080\n"},
        ])
        self.assertTrue(seen, "RAG-архів не викликано")
        self.assertIn("8081", seen[0])
        self.assertIn("read_file", seen[0])

    def test_rag_failure_does_not_break_the_turn(self) -> None:
        runner = self._runner()
        runner.digest = longchat.ConversationDigest()

        def boom(*_args, **_kwargs):
            raise RuntimeError("RAG зламався")

        runner.rag_archive = boom
        runner._archive_evicted_context([
            {"role": "user", "content": "важливе повідомлення про порт"}])
        self.assertEqual(len(runner.digest.entries), 1,
                         "збій RAG не має скасовувати хроніку")


class TestChatStoreDigest(unittest.TestCase):
    """Хроніка переживає перезапуск разом із чатом."""

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.store = ChatStore(Path(self._folder.name) / "chats.json")

    def tearDown(self) -> None:
        self._folder.cleanup()

    def test_digest_survives_save_and_load(self) -> None:
        chat = self.store.create(title="Довга розмова")
        self.store.store_digest(chat.id, {
            "entries": [{"role": "user", "text": "портал на 8081", "at": 1.0}],
            "trimmed": 2,
        })
        loaded = self.store.load_digest(chat.id)
        self.assertEqual(loaded["entries"][0]["text"], "портал на 8081")

    def test_clearing_chat_clears_digest(self) -> None:
        chat = self.store.create(title="Т")
        self.store.store_digest(chat.id, {
            "entries": [{"role": "user", "text": "старе", "at": 1.0}]})
        self.store.clear_messages(chat.id)
        self.assertEqual(self.store.load_digest(chat.id), {},
                         "«очистити чат» має чистити й хроніку")

    def test_chat_roundtrip_keeps_digest(self) -> None:
        chat = Chat(title="Т")
        chat.digest = {"entries": [{"role": "user", "text": "x", "at": 1.0}],
                       "trimmed": 0, "absorbed_blocks": 1}
        restored = Chat.from_dict(chat.to_dict())
        self.assertEqual(restored.digest["entries"][0]["text"], "x")
        self.assertEqual(restored.digest["absorbed_blocks"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# Свобода дій
# ─────────────────────────────────────────────────────────────────────────────

class TestAutonomy(unittest.TestCase):
    """Рівень свободи додає кроків, але не розширює прав."""

    def test_levels_are_ordered_by_steps(self) -> None:
        steps = [autonomy.step_bonus(key) for key in autonomy.LEVELS]
        self.assertEqual(steps, sorted(steps),
                         f"рівні мають зростати за кроками: {steps}")

    def test_unknown_level_falls_back(self) -> None:
        self.assertEqual(autonomy.normalise("вигаданий"),
                         autonomy.DEFAULT_LEVEL)

    def test_aliases_work(self) -> None:
        self.assertEqual(autonomy.normalise("max"), autonomy.EXPLORER)
        self.assertEqual(autonomy.normalise("автономно"), autonomy.AUTONOMOUS)
        self.assertEqual(autonomy.normalise("safe"), autonomy.CAUTIOUS)

    def test_ask_first_only_for_careful_levels(self) -> None:
        self.assertTrue(autonomy.asks_before_assume(autonomy.CAUTIOUS))
        self.assertTrue(autonomy.asks_before_assume(autonomy.BALANCED))
        self.assertFalse(autonomy.asks_before_assume(autonomy.AUTONOMOUS))
        self.assertFalse(autonomy.asks_before_assume(autonomy.EXPLORER))

    def test_every_level_has_a_prompt(self) -> None:
        for key in autonomy.LEVELS:
            with self.subTest(level=key):
                self.assertTrue(autonomy.prompt_hint(key).strip())
                self.assertTrue(autonomy.label_for(key).strip())

    def test_labels_are_unique(self) -> None:
        labels = [label for _key, label in autonomy.labels()]
        self.assertEqual(len(labels), len(set(labels)))


class TestStepBudget(unittest.TestCase):
    """Бюджет кроків: рівень додає, дозволи не змінює, «Чат» не чіпає."""

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        folder = Path(self._folder.name)
        self.runner = agent.AgentRunner(
            ToolRegistry(folder), LLMSettings(), AgentSettings(max_steps=8), folder)
        self.settings = self.runner.agent_settings

    def tearDown(self) -> None:
        self._folder.cleanup()

    def test_balanced_adds_two_steps(self) -> None:
        self.runner.set_autonomy(autonomy.BALANCED)
        self.assertEqual(self.runner.step_budget, 10)

    def test_explorer_adds_sixteen_steps(self) -> None:
        self.runner.set_autonomy(autonomy.EXPLORER)
        self.assertEqual(self.runner.step_budget, 24)

    def test_cautious_keeps_base(self) -> None:
        self.runner.set_autonomy(autonomy.CAUTIOUS)
        self.assertEqual(self.runner.step_budget, 8)

    def test_base_setting_is_not_rewritten(self) -> None:
        """Рівень НЕ має переписувати те, що задав користувач."""
        self.runner.set_autonomy(autonomy.EXPLORER)
        self.assertEqual(self.settings.max_steps, 8,
                         "налаштування кроків не має змінюватись")

    def test_permissions_are_not_touched(self) -> None:
        """Свобода дій — не дозволи. Це головна вимога безпеки."""
        from blackchpok_ide import permissions

        before = self.runner.permission_mode
        self.runner.set_autonomy(autonomy.EXPLORER)
        self.assertEqual(self.runner.permission_mode, before)
        self.assertEqual(self.runner.permission_mode, permissions.WORKSPACE)

    def test_chat_mode_keeps_one_step(self) -> None:
        """Явно заданий режимом ліміт усе ще діє на бюджет."""
        self.runner.tools_enabled = False
        self.runner.max_steps_override = 1
        self.runner.set_autonomy(autonomy.EXPLORER)
        self.assertEqual(self.runner.step_budget, 1)

    def test_ceiling_does_not_cut_normal_limit(self) -> None:
        """Стеля не ріже звичайний ліміт: 35 + 16 = 51, а не 300."""
        self.runner.max_steps_override = 35
        self.runner.set_autonomy(autonomy.EXPLORER)
        self.assertEqual(self.runner.step_budget, 51)

    def test_autonomy_prompt_reaches_the_context(self) -> None:
        self.runner.set_autonomy(autonomy.EXPLORER)
        block = self.runner._context_block()
        self.assertIn("ДОСЛІДНИК", block,
                      "модель має знати свій рівень свободи")


# ─────────────────────────────────────────────────────────────────────────────
# Самонавчання
# ─────────────────────────────────────────────────────────────────────────────

class TestLessonExtraction(unittest.TestCase):
    """Уроки виводяться з ПІДТВЕРДЖЕНИХ фактів, а не з будь-чого."""

    def test_clean_turn_teaches_nothing(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("read_file", True, "файл прочитано")],
            changed_files=[], goal="подивитись файл", ok=True,
            steps=1, max_steps=10)
        self.assertEqual(selflearning.extract_lessons(facts), [],
                         "у чистому ході нема чого вчити")

    def test_flaky_network_error_is_not_a_lesson(self) -> None:
        """Таймаут лікується повтором, а не правилом."""
        facts = selflearning.TurnFacts(
            calls=[("search_web", False, "Timeout: connection timed out"),
                   ("search_web", True, "знайдено 3 результати")],
            goal="пошук погоди", ok=True, steps=2, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertEqual(lessons, [],
                         f"мережевий збій став уроком: {[l.content() for l in lessons]}")

    def test_recovered_failure_becomes_a_lesson(self) -> None:
        """Помилка, яку модель САМА виправила, — це навик, а не шум."""
        facts = selflearning.TurnFacts(
            calls=[("write_file", False, "Помилка: немає такої теки"),
                   ("write_file", True, "Записано index.html")],
            changed_files=["index.html"], goal="створити сайт", ok=True,
            steps=2, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertTrue(lessons, "виправлена помилка мала стати уроком")
        self.assertIn("write_file", lessons[0].content())

    def test_repeated_call_becomes_a_lesson(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("list_dir", True, "файли: a.py")] * 4,
            goal="показати файли", ok=True, steps=4, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertTrue(any("list_dir" in lesson.content() for lesson in lessons))

    def test_syntax_repair_becomes_a_lesson(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("write_file", True, "Записано calc.py")],
            changed_files=["calc.py"], syntax_repairs=1,
            goal="створити калькулятор", ok=True, steps=3, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertTrue(any("python_check" in lesson.content() for lesson in lessons))

    def test_exhausted_steps_becomes_a_lesson(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("write_file", True, "Записано a.html")],
            changed_files=["a.html"], goal="зробити сайт", ok=False,
            steps=10, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertTrue(any("кроків" in lesson.content() for lesson in lessons))

    def test_lessons_are_limited(self) -> None:
        """За один хід — не більше WRITE_LIMIT уроків: решта вже шум."""
        facts = selflearning.TurnFacts(
            calls=[("a", False, "помилка"), ("a", True, "ок"),
                   ("b", False, "помилка"), ("b", True, "ок"),
                   ("c", True, "x"), ("c", True, "x"), ("c", True, "x"),
                   ("write_file", True, "Записано f.py")],
            changed_files=["f.py"] * 5, syntax_repairs=2,
            asked_permission=True, goal="зробити все", ok=False,
            steps=10, max_steps=10)
        lessons = selflearning.extract_lessons(facts)
        self.assertLessEqual(len(lessons), selflearning.WRITE_LIMIT)


class TestSelfLearningWithMemory(unittest.TestCase):
    """Уроки живуть у справжній пам'яті й повертаються нагадуванням."""

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.memory = Neuromesh(Path(self._folder.name) / "memory.db")
        from blackchpok_ide.memory_bridge import MemoryBridge

        self.bridge = MemoryBridge(self.memory)
        self.learning = selflearning.SelfLearning(self.bridge)

    def tearDown(self) -> None:
        self.memory.close()
        self._folder.cleanup()

    def test_lesson_is_stored_and_found(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("list_dir", True, "файли: a.py")] * 4,
            goal="показати список файлів проєкту", ok=True,
            steps=4, max_steps=10)
        saved = self.learning.learn_turn(facts)
        self.assertTrue(saved, "урок не збережено")
        found = self.memory.search("показати список файлів проєкту", limit=5,
                                   kinds=[selflearning.LESSON_KIND])
        self.assertGreater(found["count"], 0, "урок не знаходиться пошуком")
        stored = found["hits"][0]["memory"]
        self.assertEqual(stored["kind"], selflearning.LESSON_KIND)

    def test_hints_return_advice_only(self) -> None:
        facts = selflearning.TurnFacts(
            calls=[("list_dir", True, "файли: a.py")] * 4,
            goal="показати список файлів проєкту", ok=True,
            steps=4, max_steps=10)
        self.learning.learn_turn(facts)
        hints = self.learning.hints("показати список файлів проєкту")
        self.assertTrue(hints, "нагадування не повернулось")
        self.assertNotIn("Урок (", hints[0],
                         "у промпт іде сама порада, а не службова обгортка")

    def test_disabled_learning_writes_nothing(self) -> None:
        learning = selflearning.SelfLearning(self.bridge, enabled=False)
        facts = selflearning.TurnFacts(
            calls=[("list_dir", True, "x")] * 5, goal="список файлів",
            ok=True, steps=5, max_steps=10)
        self.assertEqual(learning.learn_turn(facts), [])
        self.assertEqual(self.memory.search("список файлів", limit=3)["count"], 0)

    def test_memory_failure_does_not_raise(self) -> None:
        class Broken:
            def ready(self):
                return True

            def remember_fact(self, *_args, **_kwargs):
                raise RuntimeError("пам'ять зламалась")

        learning = selflearning.SelfLearning(Broken())
        facts = selflearning.TurnFacts(
            calls=[("list_dir", True, "x")] * 5, goal="список", ok=True,
            steps=5, max_steps=10)
        self.assertEqual(learning.learn_turn(facts), [])   # не кидає

    def test_portal_scenario_end_to_end(self) -> None:
        """Реальний сценарій: агент зациклився — наступного разу має нагадування."""
        facts = selflearning.TurnFacts(
            calls=[("search_web", True, "ті самі результати")] * 4,
            goal="написати сайт блогу зі списком статей", ok=False,
            steps=6, max_steps=8, intent_type="create")
        saved = self.learning.learn_turn(facts)
        self.assertTrue(saved)
        hints = self.learning.hints("написати сайт блогу зі списком статей")
        self.assertTrue(hints, "наступного разу агент нічого не згадав")


class TestAgentWiresLearningAndAutonomy(unittest.TestCase):
    """Раннер справді викликає нові шари — інакше вони мертві."""

    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        folder = Path(self._folder.name)
        self.runner = agent.AgentRunner(
            ToolRegistry(folder), LLMSettings(), AgentSettings(), folder)

    def tearDown(self) -> None:
        self._folder.cleanup()

    def test_learn_from_turn_uses_observations(self) -> None:
        from blackchpok_ide.tool_orchestrator import Observation

        seen: list[selflearning.TurnFacts] = []

        class Recorder:
            enabled = True

            def hints(self, *_args, **_kwargs):
                return []

            def learn_turn(self, facts):
                seen.append(facts)
                return []

        self.runner.learning = Recorder()
        self.runner._observations = [
            Observation(name="write_file", ok=True, output="Записано a.py",
                        error="", rejected=False, suspicious=()),
        ]
        self.runner._touched_files = ["a.py"]
        self.runner.state.goal = "створити файл"
        self.runner._learn_from_turn(ok=True)
        self.assertTrue(seen, "_learn_from_turn не передав факти")
        self.assertEqual(seen[0].goal, "створити файл")
        self.assertIn("a.py", seen[0].changed_files)

    def test_private_state_blocks_learning(self) -> None:
        class Exploding:
            enabled = True

            def learn_turn(self, _facts):
                raise AssertionError("приватний режим не має вчитись")

            def hints(self, *_args, **_kwargs):
                return []

        self.runner.learning = Exploding()
        self.runner.state.private = True
        self.runner._learn_from_turn(ok=True)     # не має кинути

    def test_autonomy_survives_mode_switch(self) -> None:
        """Свобода дій діє й після перемикання режиму.

        ── ОНОВЛЕНО 21.11.2026 ───────────────────────────────────────────
        Раніше тут перевірялось ``16`` і ``20``: базові 8 кроків плюс 8 від
        «Автономно», а «Код» додавав свої 12. Тепер ліміту немає взагалі
        (``max_steps = 0`` = без ліміту), тож обидва бюджети — безлімітні.
        Перевіряємо саме те, що лишилось важливим: перемикання режиму НЕ
        скасовує свободу дій і не повертає стелю.
        """
        from blackchpok_ide import modes

        self.runner.agent_settings.max_steps = 0
        self.runner.set_autonomy(autonomy.AUTONOMOUS)
        self.assertGreater(self.runner.step_budget, 10_000)
        modes.apply(self.runner.agent_settings, self.runner, modes.CODE)
        self.runner.set_autonomy(autonomy.AUTONOMOUS)
        self.assertGreater(self.runner.step_budget, 10_000,
                           "режим «Код» повернув ліміт кроків")


if __name__ == "__main__":
    unittest.main(verbosity=2)
