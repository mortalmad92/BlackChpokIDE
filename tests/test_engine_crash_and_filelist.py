"""Регресії на аварію рушія й розпізнавання переліку файлів.

Обидва дефекти знайдені запуском (див. ``docs/CRASH_AND_FILELIST_FIX.md``):

1. **Аварія всього процесу** (``GGML_ASSERT(seq_id …)``, код 0xC0000409):
   ``NativeEngine.unload()`` звільняв контекст, не дочекавшись поточного
   ``llama_decode`` у потоці агента — різні замки (``engine._lock`` проти
   ``context._lock``).
2. **``list_dir`` не визнавався переліком**: прихований ``.gitignore`` і
   службові рядки-підсумки опускали критерій нижче порогу, тому відповідь
   ставала код-блоком на 12 рядків без назв файлів.

Тести не завантажують модель (це коштує секунди й VRAM): вони перевіряють
саме логіку, яка ламалась.
"""

from __future__ import annotations

import inspect
import threading
import time
import unittest

from blackchpok_ide import response_engine
from blackchpok_ide.native import engine as engine_module


class TestUnloadWaitsForDecode(unittest.TestCase):
    """``unload`` мусить дочекатись завершення декодування."""

    def test_unload_takes_context_lock(self) -> None:
        """Регресія на причину: контекст звільняється під ``context._lock``.

        Перевіряємо ДЖЕРЕЛО, а не поведінку: справжня гонка вимагає
        завантаженої моделі й реального ``llama_decode``, а її наслідок —
        аварія процесу, яку не можна зловити в unittest.
        """
        source = inspect.getsource(engine_module.NativeEngine.unload)
        self.assertIn("context._lock", source,
                      "unload має брати замок контексту, інакше звільняє "
                      "пам'ять під час декодування")
        self.assertIn("cancel", source,
                      "unload має спершу попросити генерацію зупинитись")

    def test_unload_cancels_then_frees(self) -> None:
        """Порядок саме такий: cancel → free (інакше чекали б повний хід)."""
        source = inspect.getsource(engine_module.NativeEngine.unload)
        cancel_at = source.find("cancel")
        free_at = source.find("context.free()")
        self.assertGreater(cancel_at, -1)
        self.assertGreater(free_at, -1)
        self.assertLess(cancel_at, free_at,
                        "скасування мусить бути ДО звільнення пам'яті")

    def test_lock_order_is_engine_then_context(self) -> None:
        """Порядок блокувань узгоджений: ``engine._lock`` → ``context._lock``.

        Зворотний порядок дав би взаємне блокування (deadlock). Перевіряємо
        саме виконуваний код, а не згадку в docstring: рядок
        ``with self._lock:`` мусить стояти ПЕРЕД ``with lock:`` (замок
        контексту береться всередині).
        """
        source = inspect.getsource(engine_module.NativeEngine.unload)
        engine_at = source.find("with self._lock:")
        context_at = max(source.find("with lock:"),
                         source.find("with context._lock:"))
        self.assertGreater(engine_at, -1, "немає замка рушія")
        self.assertGreater(context_at, -1, "немає замка контексту")
        self.assertLess(engine_at, context_at,
                        "замок контексту береться ПІСЛЯ замка рушія")

    def test_unload_is_safe_when_nothing_loaded(self) -> None:
        """Без завантаженої моделі ``unload`` не падає й повертає False."""
        fake = engine_module.NativeEngine.__new__(engine_module.NativeEngine)
        fake._lock = threading.RLock()
        fake.model = None
        fake.context = None
        fake._formatter = None
        fake._stats = {"unloads": 0}
        self.assertFalse(fake.unload())


class TestFileListRecognition(unittest.TestCase):
    """``list_dir`` у корені проєкту мусить ставати переліком, не код-блоком."""

    #: Реальний вивід ``list_dir('.')`` на цьому проєкті (скорочено).
    REAL_OUTPUT = (
        ". — 35 записів (файлів 16, тек 19)\n"
        "Підсумок за типами: .bat: 6, .py: 6, .spec: 1, .toml: 1\n"
        ".agents/\n"
        ".buildtmp/\n"
        ".github/\n"
        ".venv/\n"
        "__pycache__/\n"
        "assets/\n"
        "blackchpok_ide/\n"
        "docs/\n"
        "tests/\n"
        "tools/\n"
        ".gitignore  (757 B)\n"
        "agent_tools.py  (70,468 B)\n"
        "main.py  (12,326 B)\n"
    )

    def test_hidden_file_is_recognised(self) -> None:
        """``.gitignore`` — файл, хоч і не має основи до крапки."""
        self.assertTrue(response_engine._file_like(".gitignore  (757 B)"),
                        "приховані файли мусять визнаватись файлами")

    def test_metadata_line_is_recognised(self) -> None:
        """Службові рядки ``list_dir`` не вважаються елементами переліку."""
        self.assertTrue(
            response_engine._is_metadata_line(". — 35 записів (файлів 16, тек 19)"))
        self.assertTrue(response_engine._is_metadata_line(
            "Підсумок за типами: .bat: 6, .py: 6"))
        self.assertFalse(response_engine._is_metadata_line("main.py  (12,326 B)"))

    def test_real_listing_is_a_file_list(self) -> None:
        self.assertTrue(response_engine.looks_like_file_list(self.REAL_OUTPUT))

    def test_answer_contains_file_names(self) -> None:
        """Головне: у ВІДПОВІДІ видно назви файлів, а не лише теки."""
        from blackchpok_ide.tool_orchestrator import Observation

        draft = response_engine.answer_from_observations(
            [Observation(name="list_dir", ok=True,
                         output=self.REAL_OUTPUT, error="")])
        text = draft.text
        self.assertIn("blackchpok_ide", text)
        self.assertIn("main.py", text)
        self.assertNotIn("… (усього", text,
                         "перелік не має обрізатись як код-блок")

    def test_summary_is_not_a_bullet(self) -> None:
        """Службовий підсумок — у підзаголовку, а не пунктом списку."""
        from blackchpok_ide.tool_orchestrator import Observation

        text = response_engine.answer_from_observations(
            [Observation(name="list_dir", ok=True,
                         output=self.REAL_OUTPUT, error="")]).text
        for line in text.splitlines():
            if line.startswith("- "):
                self.assertNotIn("записів", line,
                                 "рядок-підсумок не ма�� бути пунктом списку")

    def test_plain_text_is_not_a_file_list(self) -> None:
        """Звичайний текст не можна приймати за перелік файлів."""
        body = ("Функція читає файл і повертає його вміст. "
                "Вона перевіряє шлях і не виходить за межі теки.")
        self.assertFalse(response_engine.looks_like_file_list(body))

    def test_single_file_is_not_a_list(self) -> None:
        self.assertFalse(response_engine.looks_like_file_list("main.py  (12,326 B)"))


class TestSingleSourceOfTruth(unittest.TestCase):
    """Правило «це перелік файлів» має бути в ОДНОМУ місці."""

    def test_agent_delegates_to_response_engine(self) -> None:
        """Регресія: у ``agent.py`` була друга копія правила, і вони розійшлися."""
        from blackchpok_ide.agent import AgentRunner

        source = inspect.getsource(AgentRunner._looks_like_file_list)
        self.assertIn("response_engine.looks_like_file_list", source,
                      "агент має делегувати в response_engine, а не дублювати")


if __name__ == "__main__":
    unittest.main(verbosity=2)
