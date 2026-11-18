"""Хмарна модель віддає виклики СВОЇМ протоколом, і IDE мусить їх розуміти.

Заміряно живим прогоном (скріншот користувача + ``chats.json``): на
хмарній ``deepseek-ai/deepseek-v4.1-flash-1017`` модель на «Привіт»
відповіла не текстом і не ``tool_calls``, а своїм XML-протоколом::

    <|DSML| calls>
    <|DSML| invoke name="read_file">
    <|DSML| parameter name="path" string="true">calculator.py</|DSML| parameter>
    </|DSML| invoke>
    </|DSML| calls>

Наслідків було три, і всі виміряні:

1. **Виклик не виконувався.** ``extract_native_calls`` знав лише
   ``[TOOL_CALLS]`` (Mistral) і ``<tool_call>`` (Qwen); JSON-розбирач тут
   безсилий, бо аргументи не в JSON. Агент отримував ``tool_calls = []``.
2. **Протокол ішов у чат.** ``looks_like_raw_protocol`` не знав цього
   маркера, тож ``final_answer`` вважав службовий XML відповіддю.
3. **Стрім показував його по токенах.** Перевірявся лише ПОЧАТОК
   накопиченого: якщо модель спершу пише речення, протокол після нього
   вже не на початку — і весь XML ішов у чат.

Окремо зафіксовано роздільник: живий прогін дав ШИРОКУ вертикальну риску
(``U+FF5C``), а документація показує звичайну (``U+007C``). Обидві мусять
працювати, інакше виправлення ламається на іншому провайдері.

Запуск:  python -m unittest tests.test_cloud_dsml_protocol -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import llm_client, response_engine, tool_dialect  # noqa: E402
from blackchpok_ide.native.chatfmt import ToolCallParser  # noqa: E402

#: Широка вертикальна риска, яку модель віддала ЖИВИМ прогоном.
#:
#: Записано escape-послідовністю НАВМИСНО: якщо покласти цей символ у файл
#: буквально, редактор або форматер може непомітно замінити його на
#: звичайну ``|`` — і тест почне перевіряти не той байт, який приходить від
#: моделі. Саме так фікстур одного разу вже став ASCII і «проходив» даремно.
WIDE = "\uff5c"


def _body(sep: str) -> str:
    """Відповідь моделі з конкретним роздільником у тегах."""
    return (
        f"<{sep}DSML{sep} calls>\n"
        f'<{sep}DSML{sep} invoke name="read_file">\n'
        f'<{sep}DSML{sep} parameter name="path" string="true">calculator.py'
        f"</{sep}DSML{sep} parameter>\n"
        f"</{sep}DSML{sep} invoke>\n"
        f'<{sep}DSML{sep} invoke name="read_file">\n'
        f'<{sep}DSML{sep} parameter name="path" string="true">run.py'
        f"</{sep}DSML{sep} parameter>\n"
        f"</{sep}DSML{sep} invoke>\n"
        f'<{sep}DSML{sep} invoke name="list_dir">\n'
        f'<{sep}DSML{sep} parameter name="path" string="true">tests'
        f"</{sep}DSML{sep} parameter>\n"
        f"</{sep}DSML{sep} invoke>\n"
        f"</{sep}DSML{sep} calls>"
    )


#: Реальна відповідь моделі — саме з широкою рискою (``U+FF5C``).
LIVE_BODY = _body(WIDE)

#: Та сама відповідь зі звичайною рискою — так пише документація.
ASCII_BODY = _body("|")

#: Текст, що йде ПЕРЕД протоколом. Саме цей випадок протікав у чат.
PREFIXED_BODY = "Гляну файли.\n" + LIVE_BODY

NAMES = {"read_file", "list_dir", "run_command", "write_file", "edit_file"}


class TestDsmlParsing(unittest.TestCase):
    """Крок 1: виклик мусить ставати справжнім ``tool_calls``."""

    def test_live_answer_gives_three_calls(self) -> None:
        calls = tool_dialect.extract_native_calls(LIVE_BODY, NAMES)
        self.assertEqual([call["function"]["name"] for call in calls],
                         ["read_file", "read_file", "list_dir"])

    def test_arguments_are_openai_shaped(self) -> None:
        calls = tool_dialect.extract_native_calls(LIVE_BODY, NAMES)
        self.assertEqual(calls[0]["function"]["arguments"],
                         '{"path": "calculator.py"}')
        self.assertEqual(calls[2]["function"]["arguments"],
                         '{"path": "tests"}')
        self.assertEqual(calls[0]["type"], "function")

    def test_wide_and_ascii_separator_both_work(self) -> None:
        """Живий прогін дав ``U+FF5C``, документація — ``U+007C``."""
        wide = tool_dialect.extract_native_calls(LIVE_BODY, NAMES)
        ascii_calls = tool_dialect.extract_native_calls(ASCII_BODY, NAMES)
        self.assertEqual(len(wide), 3)
        self.assertEqual(len(ascii_calls), 3)
        self.assertEqual([c["function"]["name"] for c in wide],
                         [c["function"]["name"] for c in ascii_calls])

    def test_unknown_tool_is_rejected(self) -> None:
        body = ('<|DSML| invoke name="hack_planet">'
                '<|DSML| parameter name="x" string="true">1</|DSML| parameter>'
                "</|DSML| invoke>")
        self.assertEqual(tool_dialect.extract_native_calls(body, NAMES), [])

    def test_several_calls_in_one_answer(self) -> None:
        body = (
            '<|DSML| calls>'
            '<|DSML| invoke name="read_file">'
            '<|DSML| parameter name="path" string="true">a.py</|DSML| parameter>'
            "</|DSML| invoke>"
            '<|DSML| invoke name="list_dir">'
            '<|DSML| parameter name="path" string="true">.</|DSML| parameter>'
            "</|DSML| invoke>"
            "</|DSML| calls>"
        )
        calls = tool_dialect.extract_native_calls(body, NAMES)
        self.assertEqual([c["function"]["name"] for c in calls],
                         ["read_file", "list_dir"])

    def test_arguments_with_tags_and_braces_survive(self) -> None:
        """У ``write_file`` лежить цілий файл — його не можна обрізати."""
        body = (
            '<|DSML| invoke name="write_file">'
            '<|DSML| parameter name="path" string="true">a.html</|DSML| parameter>'
            '<|DSML| parameter name="content" string="true">'
            "<div class='x'>text</div> {color: red}</|DSML| parameter>"
            "</|DSML| invoke>"
        )
        calls = tool_dialect.extract_native_calls(body, NAMES)
        self.assertEqual(len(calls), 1)
        arguments = calls[0]["function"]["arguments"]
        self.assertIn("<div class='x'>text</div>", arguments)
        self.assertIn("{color: red}", arguments)

    def test_llm_client_recognises_it(self) -> None:
        """Той самий шлях, яким іде агент: ``extract_tool_calls``."""
        calls = llm_client.extract_tool_calls(LIVE_BODY, [], NAMES)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]["function"]["name"], "read_file")


class TestDsmlIsNotShown(unittest.TestCase):
    """Крок 2: користувач не має читати службовий XML замість відповіді."""

    def test_protocol_is_detected(self) -> None:
        self.assertTrue(response_engine.looks_like_raw_protocol(LIVE_BODY))

    def test_clean_for_chat_removes_it(self) -> None:
        self.assertEqual(response_engine.clean_for_chat(LIVE_BODY), "")

    def test_answer_before_protocol_survives(self) -> None:
        cleaned = response_engine.clean_for_chat(PREFIXED_BODY)
        self.assertIn("Гляну файли.", cleaned)
        self.assertNotIn("DSML", cleaned)

    def test_strip_keeps_normal_text(self) -> None:
        text = "Ось розмітка:\n<div class='x'>текст</div>"
        self.assertEqual(tool_dialect.strip_dsml(text), text)

    def test_truncated_call_is_removed_entirely(self) -> None:
        """Модель спинилась посеред аргументів — хвіст теж не показуємо."""
        body = ("Готово, файл створено.\n"
                '<|DSML| invoke name="read_file">\n'
                '<|DSML| parameter name="path" string="true">calc')
        cleaned = tool_dialect.strip_dsml(body)
        self.assertIn("файл створено", cleaned)
        self.assertNotIn("parameter", cleaned)

    def test_final_answer_does_not_leak_protocol(self) -> None:
        """``final_answer`` мусить віддати чесний текст, а не протокол."""
        answer = response_engine.final_answer(LIVE_BODY, [])
        self.assertNotIn("DSML", answer)
        self.assertTrue(answer.strip())


class TestDsmlStreaming(unittest.TestCase):
    """Крок 3: стрім не мусить показувати протокол навіть частинами."""

    def _visible(self, body: str, chunk: int) -> str:
        """Що побачив користувач при поданні тексту шматками по ``chunk``."""
        shown = 0
        pieces: list[str] = []
        accumulated = ""
        for index in range(0, len(body), chunk):
            accumulated += body[index:index + chunk]
            safe_end = llm_client._visible_end(accumulated, NAMES)
            if safe_end > shown:
                pieces.append(accumulated[shown:safe_end])
                shown = safe_end
        return "".join(pieces)

    def test_no_leak_on_any_chunk_boundary(self) -> None:
        """Маркер ``<|DSML|`` віддається по токенах — межа буває будь-яка."""
        for chunk in (1, 2, 3, 5, 7, 11):
            with self.subTest(chunk=chunk):
                visible = self._visible(PREFIXED_BODY, chunk)
                self.assertNotIn("DSML", visible)
                self.assertNotIn("invoke", visible)

    def test_prefix_before_protocol_is_kept(self) -> None:
        visible = self._visible(PREFIXED_BODY, 3)
        self.assertIn("Гляну файли.", visible)

    def test_plain_answer_is_not_cut(self) -> None:
        plain = "Готово. Я створив три файли й перевірив синтаксис."
        self.assertEqual(plain[:llm_client._visible_end(plain, NAMES)], plain)

    def test_html_answer_is_not_cut(self) -> None:
        html = "Ось розмітка:\n<div class='x'>текст</div>"
        self.assertEqual(html[:llm_client._visible_end(html, NAMES)], html)

    def test_parser_hides_protocol_and_keeps_calls(self) -> None:
        """Нативний рушій: ``ToolCallParser`` ховає виклик, але збирає його."""
        parser = ToolCallParser(known=NAMES)
        shown = "".join(parser.feed(ch) for ch in LIVE_BODY) + parser.finish()
        self.assertNotIn("DSML", shown)
        calls = parser.native_calls()
        self.assertEqual([c["function"]["name"] for c in calls],
                         ["read_file", "read_file", "list_dir"])

    def test_call_prefix_detector(self) -> None:
        for piece in ("<", "<|", "<|D", "<|DS", "<|DSM", "<|DSML", "<|DSML|"):
            with self.subTest(piece=piece):
                self.assertTrue(tool_dialect.is_call_prefix(piece))
        self.assertFalse(tool_dialect.is_call_prefix("Привіт"))
        self.assertFalse(tool_dialect.is_call_prefix("<div>x</div>"))


class TestPseudoTagProtocol(unittest.TestCase):
    """Текст протоколу замість виклику — окреме зауваження власника проєкту.

    Заміряно живим прогоном: модель двічі відповіла ``<run_command>echo ok
    </run_command>`` замість звичайної відповіді. Це не «нестабільність
    моделі»: IDE не розпізнавала такий виклик і показувала тег у чаті.
    """

    def test_tag_call_becomes_a_real_call(self) -> None:
        body = "<run_command>echo ok</run_command>"
        calls = tool_dialect.extract_native_calls(body, NAMES)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "run_command")
        self.assertEqual(calls[0]["function"]["arguments"],
                         '{"command": "echo ok"}')

    def test_self_closing_tag_keeps_its_attribute(self) -> None:
        calls = tool_dialect.extract_native_calls(
            '<read_file path="calc.py"/>', NAMES)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["arguments"],
                         '{"path": "calc.py"}')

    def test_tag_is_removed_from_chat(self) -> None:
        cleaned = response_engine.clean_for_chat(
            "Перевірю: <run_command>echo ok</run_command> і скажу.")
        self.assertNotIn("run_command", cleaned)
        self.assertIn("Перевірю:", cleaned)

    def test_pure_tag_call_leaves_no_answer(self) -> None:
        """Сам лише виклик — не відповідь; порожній текст, а не тег."""
        self.assertEqual(
            response_engine.clean_for_chat("<run_command>echo ok</run_command>"),
            "")

    def test_unknown_tag_is_not_a_call(self) -> None:
        self.assertEqual(
            tool_dialect.extract_native_calls("<run_command>ok</run_command>",
                                              {"read_file"}), [])

    def test_real_html_is_untouched(self) -> None:
        """Звичайний XML відповіді не можна плутати з викликом."""
        html = 'Ось код:\n```html\n<div class="x">текст</div>\n```'
        self.assertEqual(response_engine.clean_for_chat(html), html)
        self.assertEqual(tool_dialect.extract_native_calls(html, NAMES), [])

    def test_llm_client_recovers_it(self) -> None:
        calls = llm_client.extract_tool_calls(
            "<run_command>echo ok</run_command>", [], NAMES)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "run_command")


class TestNativeParserHidesProtocol(unittest.TestCase):
    """Стрім нативного рушія теж не мусить показувати службові теги.

    Заміряно покроковим прогоном (чанк 1 символ): користувач бачив у
    чаті ``<tool_call>``, ``</tool_call>`` і ``</|DSML| calls>`` окремими
    символами — виклик усередині ховали, а самі теги ні.
    """

    def _shown(self, body: str, chunk: int, known: set[str]) -> str:
        parser = ToolCallParser(known=known)
        pieces = [parser.feed(body[i:i + chunk])
                  for i in range(0, len(body), chunk)]
        pieces.append(parser.finish())
        return "".join(pieces)

    def test_qwen_tags_do_not_leak(self) -> None:
        body = '<tool_call>{"name": "list_dir", "arguments": {"path": "."}}</tool_call>'
        for chunk in (1, 2, 5, 100):
            with self.subTest(chunk=chunk):
                shown = self._shown(body, chunk, {"list_dir"})
                self.assertNotIn("tool_call", shown)

    def test_qwen_call_is_still_collected(self) -> None:
        body = '<tool_call>{"name": "list_dir", "arguments": {"path": "."}}</tool_call>'
        parser = ToolCallParser(known={"list_dir"})
        for index in range(0, len(body), 3):
            parser.feed(body[index:index + 3])
        parser.finish()
        self.assertEqual([call.name for call in parser.calls()], ["list_dir"])

    def test_dsml_does_not_leak_on_any_chunk(self) -> None:
        body = "Гляну.\n" + LIVE_BODY
        for chunk in (1, 2, 3, 7, 40):
            with self.subTest(chunk=chunk):
                shown = self._shown(body, chunk, NAMES)
                self.assertNotIn("DSML", shown)
                self.assertNotIn("invoke", shown)

    def test_dsml_call_is_still_collected(self) -> None:
        parser = ToolCallParser(known=NAMES)
        for index in range(0, len(LIVE_BODY), 3):
            parser.feed(LIVE_BODY[index:index + 3])
        parser.finish()
        self.assertEqual([c["function"]["name"] for c in parser.native_calls()],
                         ["read_file", "read_file", "list_dir"])

    def test_plain_json_in_answer_is_kept(self) -> None:
        """Звичайний JSON відповіді — це ВМІСТ, його не можна ховати."""
        parser = ToolCallParser(known={"list_dir"}, dialect=None)
        body = 'Ось приклад: {"a": 1}. Готово.'
        shown = "".join(parser.feed(ch) for ch in body) + parser.finish()
        self.assertIn('"a"', shown)
        self.assertIn("Готово", shown)


class TestAllProvidersFilterTheProtocol(unittest.TestCase):
    """Захист мусить бути в КОЖНОМУ стрімі, а не лише в OpenAI-сумісному.

    Заміряно в коді: ``_stream_anthropic`` і ``_stream_gemini`` віддавали
    кожен шматок тексту в чат одразу, без жодної фільтрації. Тобто
    «виправлено» стосувалося половини провайдерів, а Gemini з його
    мільйонним вікном — цілком робочий шлях.
    """

    def _guard_shown(self, piece_size: int) -> str:
        shown: list[str] = []
        guard = llm_client._StreamGuard(shown.append, NAMES)
        for index in range(0, len(PREFIXED_BODY), piece_size):
            guard.feed(PREFIXED_BODY[index:index + piece_size])
        guard.flush(final=True)     # виклик не розпізнано — віддаємо хвіст
        return "".join(shown)

    def test_guard_hides_protocol_for_any_chunk_size(self) -> None:
        for size in (1, 2, 3, 7, 40, 500):
            with self.subTest(size=size):
                shown = self._guard_shown(size)
                self.assertNotIn("DSML", shown)
                self.assertNotIn("invoke", shown)

    def test_guard_keeps_the_human_prefix(self) -> None:
        shown = self._guard_shown(3)
        self.assertIn("Гляну файли.", shown)

    def test_guard_holds_back_when_call_recognised(self) -> None:
        """Якщо виклик розпізнано — притриманий хвіст показувати НЕ можна."""
        shown: list[str] = []
        guard = llm_client._StreamGuard(shown.append, NAMES)
        guard.feed("Гляну. " + LIVE_BODY)
        guard.flush(final=False)
        rendered = "".join(shown)
        self.assertNotIn("DSML", rendered)
        self.assertIn("Гляну.", rendered)

    def test_guard_without_callback_does_not_crash(self) -> None:
        guard = llm_client._StreamGuard(None, NAMES)
        guard.feed(LIVE_BODY)
        guard.flush(final=True)
        self.assertEqual(guard.text, LIVE_BODY)

    def test_every_stream_path_uses_the_guard(self) -> None:
        """Структурна перевірка: захист підключено в кожній стрім-гілці."""
        import inspect

        for method in ("_stream_anthropic", "_stream_gemini"):
            with self.subTest(method=method):
                source = inspect.getsource(getattr(llm_client.LLMClient, method))
                self.assertIn("_StreamGuard", source,
                              f"{method} не фільтрує службовий протокол")

    def test_non_stream_paths_strip_protocol(self) -> None:
        """``_chat_anthropic``/``_chat_gemini`` теж віддають content у чат."""
        import inspect

        for method in ("_chat_anthropic", "_chat_gemini"):
            with self.subTest(method=method):
                source = inspect.getsource(getattr(llm_client.LLMClient, method))
                self.assertTrue(
                    "extract_tool_calls" in source or "strip_" in source,
                    f"{method} не обробляє текстовий виклик")


class TestAnthropicAndGeminiStreams(unittest.TestCase):
    """Справжні SSE-сервери у форматі кожного провайдера.

    Структурна перевірка («у коді є ``_StreamGuard``») нічого не доводить:
    вона пройшла б і тоді, коли фільтр підключений, але не викликається.
    Тут піднімаємо справжній HTTP-сервер і дивимось, що РЕАЛЬНО отримав
    користувач через ``on_text``, і що лежить у ``result.content``.
    """

    def _stream(self, handler, style: str) -> tuple[str, str]:
        import threading
        from http.server import ThreadingHTTPServer

        from blackchpok_ide import provider_adapters

        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_address[1]
            client = llm_client.LLMClient(f"http://127.0.0.1:{port}/v1",
                                          api_key="test", model="test",
                                          timeout=30)
            # Стиль визначається за ДОМЕНОМ, тож підставляємо адаптер явно:
            # інакше тест тихо перевіряв би OpenAI-шлях під назвою
            # «Anthropic» (саме це й сталося з першою версією цього тесту).
            base = provider_adapters.for_url(
                "https://api.anthropic.com/v1" if style == "anthropic"
                else "https://generativelanguage.googleapis.com/v1beta")
            client.adapter = type(base)(
                style=base.style, chat_path=base.chat_path,
                models_path=base.models_path, version=base.version,
                extra_headers=base.extra_headers)
            shown: list[str] = []
            result = client.chat_stream(
                [{"role": "user", "content": "покажи файли"}],
                tools=[{"type": "function",
                        "function": {"name": "list_dir", "description": "",
                                     "parameters": {"type": "object",
                                                    "properties": {}}}}],
                on_text=shown.append, known_tools={"list_dir"})
            return "".join(shown), (result.content or "")
        finally:
            server.shutdown()
            server.server_close()

    def _pieces(self) -> list[str]:
        """Текст, порізаний так, як його віддає справжній SSE."""
        return ["Гляну", " файли", ".\n",
                *[LIVE_BODY[i:i + 4] for i in range(0, len(LIVE_BODY), 4)]]

    @staticmethod
    def _stubs():
        """Стаби SSE — з підтримкою ОБОХ способів запуску тестів.

        ``python -m unittest tests.test_x`` імпортує файл як частину пакета,
        а ``python -m unittest discover -s tests`` — як окремий модуль.
        Відносний імпорт працює лише в першому випадку, тому пробуємо обидва:
        інакше половина запусків падала б з ``ImportError``.
        """
        try:
            from . import tests_dsml_stubs as stubs
        except ImportError:
            import tests_dsml_stubs as stubs
        return stubs

    def test_anthropic_stream_is_clean(self) -> None:
        stubs = self._stubs()
        shown, content = self._stream(stubs.anthropic_handler(self._pieces()),
                                      "anthropic")
        self.assertIn("Гляну", shown)
        self.assertNotIn("DSML", shown)
        self.assertNotIn("DSML", content)

    def test_gemini_stream_is_clean(self) -> None:
        stubs = self._stubs()
        shown, content = self._stream(stubs.gemini_handler(self._pieces()),
                                      "gemini")
        self.assertIn("Гляну", shown)
        self.assertNotIn("DSML", shown)
        self.assertNotIn("DSML", content)


class TestFixtureMatchesLiveData(unittest.TestCase):
    """Фікстур мусить бути тим самим байтом, що прийшов від моделі.

    Навіщо окремий тест. Під час написання цих тестів фікстур випадково
    став ASCII-версією (``U+007C``) замість широкої (``U+FF5C``), і всі
    перевірки «проходили», не торкаючись того байта, що реально приходить
    від DeepSeek. Тут звіряємо фікстур із справжньою відповіддю.

    Файл історії може бути відсутній (інша машина, чиста інсталяція) —
    тоді тест пропускається, а не вигадує даних.
    """

    CHATS = Path(
        r"C:\Users\Admin\AppData\Roaming\BlackChpokIDE\chats.json")

    def _live_answer(self) -> str:
        if not self.CHATS.exists():
            self.skipTest("історії чатів немає на цій машині")
        import json

        try:
            data = json.loads(self.CHATS.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.skipTest(f"історію чатів не прочитано: {exc}")
        for chat in data.get("chats") or ():
            for message in chat.get("context") or ():
                text = str(message.get("content") or "")
                if "DSML" in text and "invoke" in text:
                    return text
        self.skipTest("у історії немає відповіді з протоколом DSML")

    def test_fixture_uses_wide_pipe_like_the_model(self) -> None:
        live = self._live_answer()
        self.assertIn(WIDE, live,
                      "жива відповідь мусить містити широку риску U+FF5C")
        self.assertEqual(LIVE_BODY, live,
                         "фікстур розійшовся зі справжньою відповіддю моделі")

    def test_live_answer_yields_three_calls(self) -> None:
        live = self._live_answer()
        calls = tool_dialect.extract_native_calls(live, NAMES)
        self.assertEqual([c["function"]["name"] for c in calls],
                         ["read_file", "read_file", "list_dir"])


if __name__ == "__main__":
    unittest.main()
