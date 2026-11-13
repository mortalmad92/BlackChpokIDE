"""Регресії, знайдені живим прогоном у GUI: агент не виконує завдання.

Сценарій користувача (скріншот): «Напиши сайт у вигляді блогу і форуму … з
своїм API … Без використання PHP». Агент відповідав «Модель повернула
порожню відповідь» за 0 кроків, на диску нічого не з'являлось.

Тут зафіксовані ПРИЧИНИ, знайдені вимірюванням, — кожна окремим тестом:

1. Модель кличе інструмент у СВОЄМУ форматі (``[TOOL_CALLS]``), а розбирач
   знав лише JSON. Текст вирізався як службовий → порожня відповідь.
2. Опис інструментів подавали лише текстовим протоколом українською, хоч
   шаблон моделі очікує ``[AVAILABLE_TOOLS]``.
3. ``tool_calls`` і ``tool``-результати в історії не потрапляли в промпт
   (``llama_chat_apply_template`` їх не бачить): модель не знала, що дію
   вже виконано, і не мала де почати відповідь.
4. Перший же порожній хід завершував роботу діагностикою замість файлів.
5. Роутер перетворював ЗАВДАННЯ на пошук в інтернеті через слово «новини».
6. Код, покладений моделлю в чат блоками, не потрапляв у файли.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import agent as agent_module  # noqa: E402
from blackchpok_ide import llm_client, tool_dialect, tool_router  # noqa: E402

MISTRAL_TEMPLATE = (
    "{{ '[TOOL_CALLS]' + tool['function']['name'] }}"
    "{{ '[AVAILABLE_TOOLS]' }}"
)
QWEN_TEMPLATE = "<tools>{{ tools }}</tools><tool_call>"

#: Реальний виклик Ministral-3-14B, записаний живим прогоном.
MISTRAL_BODY = (
    '[TOOL_CALLS]write_file[ARGS]{"path": "app/main.py", "content": '
    '"from fastapi import FastAPI\\n\\napp = FastAPI()\\n"}'
)


class TestNativeDialectDetection(unittest.TestCase):
    """Діалект визначається з шаблону моделі, а не з назви файлу."""

    def test_mistral_template(self) -> None:
        dialect = tool_dialect.dialect_for_template(MISTRAL_TEMPLATE)
        self.assertEqual(dialect.kind, tool_dialect.MISTRAL)
        self.assertTrue(dialect.native)
        self.assertEqual(dialect.call_marker, "[TOOL_CALLS]")

    def test_qwen_template(self) -> None:
        dialect = tool_dialect.dialect_for_template(QWEN_TEMPLATE)
        self.assertEqual(dialect.kind, tool_dialect.QWEN)
        self.assertIn("<tool_call>", dialect.call_marker)

    def test_plain_template_has_no_native_format(self) -> None:
        dialect = tool_dialect.dialect_for_template("{{ m.content }}")
        self.assertEqual(dialect.kind, tool_dialect.TEXT)
        self.assertFalse(dialect.native)

    def test_real_ministral_template_is_recognised(self) -> None:
        """Справжній шаблон із GGUF мусить давати діалект Mistral."""
        path = (ROOT / "userdata" / "models"
                / "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf")
        if not path.exists():
            self.skipTest("моделі немає на диску")
        from blackchpok_ide.native.gguf import read_meta_cached

        template = read_meta_cached(path).get("tokenizer.chat_template") or ""
        dialect = tool_dialect.dialect_for_template(template)
        self.assertEqual(dialect.kind, tool_dialect.MISTRAL)


class TestMistralCallParsing(unittest.TestCase):
    """[TOOL_CALLS]…[ARGS]{json} — головна причина «порожньої відповіді»."""

    def test_llm_client_recognises_mistral_call(self) -> None:
        calls = llm_client.extract_tool_calls(
            MISTRAL_BODY, [], ["write_file", "list_dir"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "write_file")
        self.assertIn("app/main.py", calls[0]["function"]["arguments"])

    def test_content_with_braces_survives(self) -> None:
        """CSS/JS у вмісті файлу не має обрізати аргументи."""
        body = ('[TOOL_CALLS]write_file[ARGS]{"path": "a.css", "content": '
                '"body { color: red; }\\n@media { x: 1 }"}')
        calls = tool_dialect.extract_native_calls(body, {"write_file"})
        self.assertEqual(len(calls), 1)
        arguments = calls[0]["function"]["arguments"]
        self.assertIn("color: red", arguments)
        self.assertIn("@media", arguments)

    def test_several_calls_in_one_answer(self) -> None:
        body = (MISTRAL_BODY
                + ' і ще [TOOL_CALLS]list_dir[ARGS]{"path": "."}')
        calls = tool_dialect.extract_native_calls(
            body, {"write_file", "list_dir"})
        self.assertEqual([c["function"]["name"] for c in calls],
                         ["write_file", "list_dir"])

    def test_unknown_tool_is_rejected(self) -> None:
        calls = tool_dialect.extract_native_calls(
            '[TOOL_CALLS]hack_planet[ARGS]{}', {"write_file"})
        self.assertEqual(calls, [])

    def test_broken_json_is_ignored_not_crashing(self) -> None:
        calls = tool_dialect.extract_native_calls(
            '[TOOL_CALLS]write_file[ARGS]{"path": "a', {"write_file"})
        self.assertEqual(calls, [])

    def test_native_call_is_removed_from_visible_text(self) -> None:
        cleaned = llm_client.strip_tool_json(MISTRAL_BODY * 1)
        self.assertNotIn("[TOOL_CALLS]", cleaned)
        self.assertNotIn("app/main.py", cleaned)


class TestPromptUsesModelDialect(unittest.TestCase):
    """Модель має бачити СВІЙ формат, а не чужий текстовий протокол."""

    def test_mistral_tools_block(self) -> None:
        dialect = tool_dialect.dialect_for_template(MISTRAL_TEMPLATE)
        block = dialect.tools_block([
            {"type": "function", "function": {"name": "write_file"}}])
        self.assertTrue(block.startswith("[AVAILABLE_TOOLS]"))
        self.assertTrue(block.endswith("[/AVAILABLE_TOOLS]"))
        self.assertIn("write_file", block)

    def test_mistral_history_keeps_call_and_result_markers(self) -> None:
        """Раніше промпт 2-го кроку був ``… [/INST] A</s> T</s>``.

        Модель не бачила ні власного виклику, ні позначки, що це результат
        інструмента — і не мала де почати відповідь.
        """
        dialect = tool_dialect.dialect_for_template(MISTRAL_TEMPLATE)
        prompt = dialect.render_history([
            {"role": "system", "content": "Ти — агент."},
            {"role": "user", "content": "Створи index.html"},
            {"role": "assistant", "content": "План.",
             "tool_calls": [{"id": "c0", "type": "function",
                             "function": {"name": "write_file",
                                          "arguments": '{"path": "index.html"}'}}]},
            {"role": "tool", "tool_call_id": "c0", "name": "write_file",
             "content": "Записано index.html"},
        ])
        self.assertIn("[TOOL_CALLS]write_file[ARGS]", prompt)
        self.assertIn("[TOOL_RESULTS]Записано index.html[/TOOL_RESULTS]", prompt)
        self.assertIn("[INST] Створи index.html [/INST]", prompt)
        self.assertIn("[SYSTEM_PROMPT]", prompt)

    def test_qwen_history_keeps_tool_call_and_response(self) -> None:
        dialect = tool_dialect.dialect_for_template(QWEN_TEMPLATE)
        prompt = dialect.render_history([
            {"role": "system", "content": "S"},
            {"role": "user", "content": "U"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c0", "type": "function",
                             "function": {"name": "write_file",
                                          "arguments": '{"path": "a.py"}'}}]},
            {"role": "tool", "tool_call_id": "c0", "name": "write_file",
             "content": "Записано a.py"},
        ])
        self.assertIn("<tool_call>", prompt)
        self.assertIn("write_file", prompt)
        self.assertIn("<tool_response>", prompt)
        # Хід асистента відкрито: без нього модель продовжує попереднє.
        self.assertTrue(prompt.endswith("<|im_start|>assistant\n"))


class TestStreamParserDialect(unittest.TestCase):
    """Стрім не має показувати користувачу сирі ``[TOOL_CALLS]``."""

    def test_call_is_hidden_from_user(self) -> None:
        from blackchpok_ide.native.chatfmt import ToolCallParser

        dialect = tool_dialect.dialect_for_template(MISTRAL_TEMPLATE)
        parser = ToolCallParser(known={"write_file"}, dialect=dialect)
        shown = parser.feed(MISTRAL_BODY)
        self.assertEqual(shown, "")
        self.assertIn("[TOOL_CALLS]", parser.text)
        names = [call["function"]["name"] for call in parser.native_calls()]
        self.assertEqual(names, ["write_file"])

    def test_text_before_call_is_shown(self) -> None:
        from blackchpok_ide.native.chatfmt import ToolCallParser

        dialect = tool_dialect.dialect_for_template(MISTRAL_TEMPLATE)
        parser = ToolCallParser(known={"write_file"}, dialect=dialect)
        shown = parser.feed("Гаразд, створюю.\n" + MISTRAL_BODY)
        self.assertIn("Гаразд", shown)
        self.assertNotIn("[TOOL_CALLS]", shown)

    def test_token_by_token_does_not_hang(self) -> None:
        """Порізання по токенах не має зациклювати розбір."""
        from blackchpok_ide.native.chatfmt import ToolCallParser

        dialect = tool_dialect.dialect_for_template(MISTRAL_TEMPLATE)
        parser = ToolCallParser(known={"write_file"}, dialect=dialect)
        visible = "".join(parser.feed(piece)
                          for piece in MISTRAL_BODY)
        self.assertEqual(visible, "")
        self.assertEqual(
            [c["function"]["name"] for c in parser.native_calls()],
            ["write_file"])

    def test_plain_answer_still_shown(self) -> None:
        from blackchpok_ide.native.chatfmt import ToolCallParser

        dialect = tool_dialect.dialect_for_template(MISTRAL_TEMPLATE)
        parser = ToolCallParser(known={"write_file"}, dialect=dialect)
        body = "Готово: файл створено."
        self.assertEqual(parser.feed(body) + parser.finish(), body)


class TestRouterDoesNotStealBuildTask(unittest.TestCase):
    """Слово з опису речі не має перетворювати завдання на пошук."""

    BUILD = ("Напиши сайт у вигляді блогу і форуму де можна спілкуватися "
             "в коментарях, з своїм API для підключення агента який буде "
             "потім постити цікаві новини. Без використання PHP.")

    def test_build_request_gives_no_web_search(self) -> None:
        hints = tool_router.confident(self.BUILD)
        self.assertNotIn("search_web", [hint.tool for hint in hints],
                         "завдання «створи сайт» не має йти в інтернет")

    def test_site_with_news_is_build_request(self) -> None:
        self.assertEqual(tool_router.confident("створи сайт новин"), [])

    def test_real_news_question_still_searches(self) -> None:
        hints = tool_router.confident("які новини сьогодні?")
        self.assertEqual([hint.tool for hint in hints], ["search_web"])

    def test_price_question_still_searches(self) -> None:
        hints = tool_router.confident("скільки коштує біткоїн")
        self.assertEqual([hint.tool for hint in hints], ["search_web"])


class TestEmptyAnswerIsNotDeadEnd(unittest.TestCase):
    """Перший порожній хід не має завершувати роботу діагностикою."""

    def setUp(self) -> None:
        from blackchpok_ide import agent_tools, config

        self.settings = config.Settings()
        self.registry = agent_tools.ToolRegistry(ROOT)
        self.runner = agent_module.AgentRunner(
            self.registry, self.settings.llm, self.settings.agent, ROOT)

    def test_retry_budget_exists(self) -> None:
        self.assertGreaterEqual(agent_module.EMPTY_ANSWER_RETRIES, 1)
        self.assertEqual(self.runner._empty_turns, 0)

    def test_reason_is_human_and_actionable(self) -> None:
        text = self.runner._empty_answer_reason()
        self.assertIn("Що зробити", text)
        # Старе однореченнєве повідомлення нічого не пояснювало.
        self.assertNotEqual(text.strip(), "Модель повернула порожню відповідь.")


class TestCodeInChatBecomesFiles(unittest.TestCase):
    """Код, покладений моделлю в чат, має стати файлами на диску."""

    ANSWER = """Створимо файл app/main.py:

```python
from fastapi import FastAPI

app = FastAPI()
```

Тепер стилі:

```css static/style.css
body { color: #fff; }
```
"""

    def test_blocks_with_captions_are_extracted(self) -> None:
        blocks = agent_module.AgentRunner._code_blocks(self.ANSWER)
        paths = [path for path, _body in blocks]
        self.assertIn("app/main.py", paths)
        self.assertIn("static/style.css", paths)

    def test_block_without_name_is_skipped(self) -> None:
        text = '```python\nprint("hello world, no file name here")\n```'
        self.assertEqual(agent_module.AgentRunner._code_blocks(text), [])

    def test_unsafe_paths_rejected(self) -> None:
        for bad in ("../evil.py", "C:/Windows/x.py", "/etc/passwd",
                    "noext", "a/b/"):
            with self.subTest(path=bad):
                self.assertFalse(
                    agent_module.AgentRunner._safe_salvage_name(bad))

    def test_normal_paths_accepted(self) -> None:
        for good in ("app/main.py", "index.html", "static/style.css",
                     "data/posts.json"):
            with self.subTest(path=good):
                self.assertTrue(
                    agent_module.AgentRunner._safe_salvage_name(good))


class TestTruncatedStreamTail(unittest.TestCase):
    """Обірваний байт у кінці стріму не має ставати ``�`` у відповіді."""

    def test_partial_character_is_dropped_not_replaced(self) -> None:
        """Замірено: «… як моє щастя.** �» — останній знак був обривом.

        Кирилиця займає два байти, тож при обриві генерації (``finish_reason
        = length``) хвіст послідовності лишався неповним. ``errors="replace"``
        перетворював його на ``\ufffd``, і користувач бачив сміття в кінці
        кожної обірваної відповіді.
        """
        from blackchpok_ide.native.tokenizer import StreamingDecoder

        class FakeTokenizer:
            def _token_bytes(self, _token: int, *, skip_special: bool = True) -> bytes:
                return b""

        decoder = StreamingDecoder(FakeTokenizer())
        # «щастя» → половина байтів останнього символа «я» (0xD1 0x8F).
        decoder._pending.extend("щастя".encode("utf-8"))  # noqa: SLF001
        decoder._pending.extend(b"\xd1")                  # noqa: SLF001
        tail = decoder.flush()
        self.assertNotIn("\ufffd", tail)
        self.assertEqual(tail, "щастя")

    def test_stream_and_total_agree_on_truncated_text(self) -> None:
        from blackchpok_ide.native.tokenizer import StreamingDecoder

        class FakeTokenizer:
            def _token_bytes(self, _token: int, *, skip_special: bool = True) -> bytes:
                return b""

        text = "Привіт, це перевірка"
        raw = text.encode("utf-8") + b"\xe2\x82"     # половина «€»
        decoder = StreamingDecoder(FakeTokenizer())
        decoder._pending.extend(raw)                 # noqa: SLF001
        streamed = decoder.flush()
        self.assertEqual(streamed, text)


class TestBrokenCallNeverLeaksIntoChat(unittest.TestCase):
    """Обірваний виклик не має показуватись у чаті уривком."""

    def test_truncated_call_does_not_leak_args(self) -> None:
        """Замірено на скріншоті: у чаті висіло ``let[ARGS]``.

        Модель спинилась посеред аргументів (``finish_reason = length``), і
        службовий хвіст лишався в тексті відповіді.
        """
        from blackchpok_ide import response_engine

        for body in ('[TOOL_CALLS]let[ARGS]',
                     '[TOOL_CALLS]let[ARGS]{"code": "let x = 1',
                     '[TOOL_CALLS]write_file[ARGS]{"path": "a.py'):
            with self.subTest(body=body):
                cleaned = response_engine.clean_for_chat(body)
                self.assertNotIn("[ARGS]", cleaned)
                self.assertNotIn("[TOOL_CALLS]", cleaned)
                self.assertNotIn("let x", cleaned)

    def test_strip_native_calls_drops_truncated_call(self) -> None:
        self.assertEqual(
            tool_dialect.strip_native_calls(
                '[TOOL_CALLS]write_file[ARGS]{"path": "a.py'), "")
        self.assertEqual(
            tool_dialect.strip_native_calls('[TOOL_CALLS]let[ARGS]'), "")

    def test_answer_before_truncated_call_survives(self) -> None:
        body = ("Готово, файли створено.\n\n"
                '[TOOL_CALLS]write_file[ARGS]{"path": "a.py')
        cleaned = tool_dialect.strip_native_calls(body)
        self.assertIn("файли створено", cleaned)
        self.assertNotIn("[ARGS]", cleaned)

    def test_parser_finish_hides_truncated_call(self) -> None:
        from blackchpok_ide.native.chatfmt import ToolCallParser

        dialect = tool_dialect.dialect_for_template(MISTRAL_TEMPLATE)
        parser = ToolCallParser(known={"let", "write_file"}, dialect=dialect)
        shown = "".join(parser.feed(ch) for ch in '[TOOL_CALLS]let[ARGS]{"code": 1')
        shown += parser.finish()
        self.assertEqual(shown, "")
        self.assertNotIn("[ARGS]", shown)

    def test_protocol_detector_knows_mistral_markers(self) -> None:
        from blackchpok_ide import response_engine

        self.assertTrue(
            response_engine.looks_like_raw_protocol("[TOOL_CALLS]let[ARGS]{}"))


class TestSystemPromptMigration(unittest.TestCase):
    """Виправлення промпту мусить ДОХОДИТИ до користувача.

    ``settings.json`` зберігає ПОВНИЙ текст системного промпту. Через це
    будь-яке виправлення в ``DEFAULT_SYSTEM_PROMPT`` не діяло: у
    користувача лишалася копія від першого запуску. Заміряно на справжніх
    налаштуваннях — там був промпт, де мережа названа «ОБОВ'ЯЗКОВИМ
    ІНСТРУМЕНТОМ», і модель на «напиши сайт» ішла в ``search_web``.
    """

    OLD = (
        "Ти — Blackchpok AI, автономний програмний агент усередині IDE.\n\n"
        "Як працювати:\n"
        "1. ІНТЕРНЕТ — ОБОВ'ЯЗКОВИЙ ІНСТРУМЕНТ, А НЕ ОПЦІЯ.\n"
    )

    def test_stock_prompt_is_recognised(self) -> None:
        from blackchpok_ide import config

        self.assertTrue(config._is_stock_prompt(self.OLD))
        self.assertTrue(config._is_stock_prompt(config.DEFAULT_SYSTEM_PROMPT))
        self.assertTrue(config._is_stock_prompt(""))

    def test_custom_prompt_is_preserved(self) -> None:
        """Власний текст людини чіпати не можна."""
        from blackchpok_ide import config

        self.assertFalse(config._is_stock_prompt(
            "Ти — мій помічник для роботи з Django. Відповідай стисло."))
        self.assertFalse(config._is_stock_prompt(
            "Ти — BlackChpok AI. Але відповідай ВИКЛЮЧНО англійською."))

    def test_stale_prompt_is_replaced_on_load(self) -> None:
        from blackchpok_ide import config

        data = {"agent": {"system_prompt": self.OLD}}
        loaded = config.Settings.from_dict(data)
        self.assertEqual(loaded.agent.system_prompt.strip(),
                         config.DEFAULT_SYSTEM_PROMPT.strip())
        # Головне: нове правило справді є в завантаженому промпті.
        self.assertIn("СПЕРШУ ЗРОБИ ТЕ", loaded.agent.system_prompt)

    def test_custom_prompt_survives_load(self) -> None:
        from blackchpok_ide import config

        mine = "Ти — мій особистий асистент. Пиши лише українською."
        loaded = config.Settings.from_dict({"agent": {"system_prompt": mine}})
        self.assertEqual(loaded.agent.system_prompt, mine)

    def test_new_prompt_tells_model_to_build_before_searching(self) -> None:
        """Промпт має прямо казати: будуй, а не шукай."""
        from blackchpok_ide import config

        prompt = config.DEFAULT_SYSTEM_PROMPT
        self.assertIn("СПЕРШУ ЗРОБИ ТЕ", prompt)
        # Стара формула «обов'язковий» штовхала модель у пошук.
        self.assertNotIn("ІНТЕРНЕТ — ОБОВ'ЯЗКОВИЙ", prompt)
        self.assertNotIn("ІНТЕРНЕТ ОБОВ'ЯЗКОВИЙ", prompt)


class TestAgentKeepsWorking(unittest.TestCase):
    """Агент не має зупинятись на півдорозі й питати дозволу."""

    def setUp(self) -> None:
        from blackchpok_ide import agent_tools, config

        settings = config.Settings()
        self.runner = agent_module.AgentRunner(
            agent_tools.ToolRegistry(ROOT), settings.llm,
            settings.agent, ROOT)

    def test_asking_permission_is_recognised(self) -> None:
        """Замірено в GUI: «Наступні кроки: … Смакуй, як продовжити.»"""
        for text in ("Наступні кроки: створити маршрути API. Смакуй, як продовжити.",
                     "Хочеш, щоб я продовжив?",
                     "Скажи, як продовжити.",
                     "Let me know if you want me to continue."):
            with self.subTest(text=text):
                self.assertTrue(agent_module._asks_permission_or_next(text))

    def test_real_report_is_not_permission(self) -> None:
        for text in ("Готово: створено 5 файлів, сервер запускається.",
                     "Файли створено: app.py, style.css, app.js.",
                     "```python\nprint(1)\n```"):
            with self.subTest(text=text):
                self.assertFalse(agent_module._asks_permission_or_next(text))

    def test_web_search_is_not_a_build(self) -> None:
        """Мережеві інструменти не створюють файлів — це не робота."""
        self.assertIn("search_web", agent_module._WEB_LOOKUP_TOOLS)
        self.assertIn("fetch_url", agent_module._WEB_LOOKUP_TOOLS)

    def test_build_task_is_recognised(self) -> None:
        self.runner.session.add_user(
            "Напиши сайт у вигляді блогу і форуму з своїм API. Без PHP.")
        self.assertTrue(self.runner._asks_to_build())

    def test_price_question_is_not_a_build(self) -> None:
        self.runner.session.add_user("скільки коштує біткоїн")
        self.assertFalse(self.runner._asks_to_build())

    def test_flags_start_clean(self) -> None:
        self.assertFalse(self.runner._build_nudged)
        self.assertFalse(self.runner._continue_asked)


class TestUnfinishedCodeBlockIsSaved(unittest.TestCase):
    """Незакритий блок коду теж має потрапити у файл.

    Заміряно живим прогоном у вікні: модель спинилась посеред ``app.py``
    (обмеження довжини), і САМЕ головний файл проєкту не з'явився на диску,
    хоч закриті блоки вже були записані.
    """

    def test_unterminated_block_is_extracted(self) -> None:
        text = (
            "Створимо файл app.py:\n"
            "```python app.py\n"
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
        )
        blocks = agent_module.AgentRunner._code_blocks(text)
        self.assertEqual(len(blocks), 1)
        path, body = blocks[0]
        self.assertEqual(path, "app.py")
        self.assertIn("from flask import Flask", body)

    def test_closed_and_unterminated_both_extracted(self) -> None:
        text = (
            "```css static/style.css\n"
            "body { color: #fff; background: #111; }\n"
            "```\n\n"
            "Тепер сервер:\n"
            "```python app.py\n"
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
        )
        paths = [p for p, _b in agent_module.AgentRunner._code_blocks(text)]
        self.assertEqual(paths, ["static/style.css", "app.py"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
