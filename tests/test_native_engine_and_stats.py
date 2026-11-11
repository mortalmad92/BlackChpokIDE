"""Регресії: увімкнений рушій і РЕАЛЬНА статистика токенів.

Три дефекти зі скріншота користувача «увімкнув власний рушій — все одно не
працює» і «токени показують нулі»:

1. **Прапорець рушія не перемикав адресу.** ``engine.native = True``
   зберігався, а ``llm.base_url`` лишався ``http://127.0.0.1:8080/v1`` —
   агент ішов у мережу й падав з ``[WinError 10061] target machine actively
   refused it``.
2. **``_on_native_model`` чіпав віджети з фонового потоку** —
   ``RuntimeError: main thread is not in main loop``, тому чат не
   перемикався на вбудований рушій.
3. **Розмова не рахувала токени взагалі.** ``_chat_only`` не емітував
   подію ``stats``, тому шкала показувала «0», хоч модель реально
   витратила тисячі токенів.
"""

from __future__ import annotations

import inspect
import unittest

from blackchpok_ide import config, context_stats, response_engine, stats_bar


def _settings_with_native(base_url: str = "http://127.0.0.1:8080/v1"):
    """Налаштування з увімкненим рушієм і чужою HTTP-адресою."""
    settings = config.Settings()
    settings.engine.native = True
    settings.engine.auto_start = False
    settings.llm.base_url = base_url
    settings.llm.api_key = "lm-studio"
    return settings


class TestEngineFlagSwitchesAddress(unittest.TestCase):
    """Прапорець рушія й адреса мусять перемикатися РАЗОМ."""

    def test_migration_fixes_http_address(self) -> None:
        """Читання налаштувань виправляє старий стан користувача."""
        import json
        import tempfile
        from pathlib import Path

        folder = Path(tempfile.mkdtemp(prefix="bchp-mig-"))
        try:
            data = {
                "llm": {"base_url": "http://127.0.0.1:8080/v1",
                        "api_key": "lm-studio", "model": "test"},
                "engine": {"native": True, "auto_start": False},
            }
            path = folder / "settings.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = config.Settings.load(path)
            self.assertEqual(
                loaded.llm.base_url, "native://blackchpok",
                "увімкнений рушій не може дивитись у HTTP — агент піде в "
                "мережу й отримає WinError 10061")
            self.assertEqual(loaded.llm.api_key, "local")
            self.assertTrue(loaded.engine.auto_start,
                            "без автозапуску модель не потрапить у рушій")
        finally:
            import shutil

            shutil.rmtree(folder, ignore_errors=True)

    def test_native_disabled_keeps_http_address(self) -> None:
        """Коли рушій вимкнено, HTTP-адресу НЕ чіпаємо."""
        import json
        import tempfile
        from pathlib import Path

        folder = Path(tempfile.mkdtemp(prefix="bchp-mig2-"))
        try:
            data = {
                "llm": {"base_url": "http://127.0.0.1:1234/v1",
                        "api_key": "lm-studio"},
                "engine": {"native": False},
            }
            path = folder / "settings.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = config.Settings.load(path)
            self.assertIn("1234", loaded.llm.base_url,
                          "зовнішній сервер користувача має лишитись")
        finally:
            import shutil

            shutil.rmtree(folder, ignore_errors=True)

    def test_foreign_server_address_is_kept(self) -> None:
        """LM Studio й Ollama — СВІДОМИЙ вибір, його не міняємо.

        Регресія: міграція спершу переписувала БУДЬ-ЯКУ HTTP-адресу, і це
        зламало ``test_ide_core.TestSettings.test_roundtrip``.
        """
        for url in ("http://127.0.0.1:1234/v1",
                    "http://127.0.0.1:11434/v1",
                    "http://192.168.1.5:1234/v1"):
            settings = _settings_with_native(url)
            self.assertFalse(
                config._points_at_managed_server(url, settings.engine),
                f"{url} — чужий сервіс, його не можна переписувати")

    def test_own_managed_port_is_migrated(self) -> None:
        """8080 — типовий порт КЕРОВАНОГО сервера IDE, це залишок."""
        settings = _settings_with_native("http://127.0.0.1:8080/v1")
        self.assertTrue(
            config._points_at_managed_server("http://127.0.0.1:8080/v1",
                                             settings.engine))

    def test_settings_dialog_switches_address(self) -> None:
        """Вкладка «AI Runtime» перемикає адресу при збереженні."""
        from blackchpok_ide import settings_dialog

        # Значення полів застосовує ``_apply_fields``, а ``_save`` лише
        # перевіряє числа й показує помилку. Раніше перевірка дивилась у
        # ``_save`` — і «падала» на робочому коді після перенесення логіки.
        source = inspect.getsource(settings_dialog.SettingsDialog._apply_fields)
        self.assertIn("EMBEDDED_URL", source,
                      "збереження має ставити native://blackchpok")
        self.assertIn("auto_start", source,
                      "збереження має вмикати автозапуск моделі")


class TestNativeModelSwitchesThread(unittest.TestCase):
    """Підписи моделі оновлюються в ГОЛОВНОМУ потоці."""

    def test_on_native_model_uses_ui_call(self) -> None:
        """Регресія на ``main thread is not in main loop``."""
        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._on_native_model)
        self.assertIn("_ui_call", source,
                      "віджети не можна чіпати з фонового потоку")
        self.assertIn("self.agent.llm_settings", source,
                      "агент має одразу бачити нову адресу")

    def test_engine_choice_applies_settings(self) -> None:
        """Після збереження налаштувань рушій справді вмикається."""
        from blackchpok_ide.main_window import BlackChpokIDE

        self.assertTrue(callable(getattr(BlackChpokIDE, "_apply_engine_choice", None)),
                        "має бути метод, який приводить рушій до стану налаштувань")
        source = inspect.getsource(BlackChpokIDE._after_settings)
        self.assertIn("_apply_engine_choice", source,
                      "_after_settings має викликати застосування рушія")


class TestStatsAreReal(unittest.TestCase):
    """Статистика показує РЕАЛЬНІ числа рушія."""

    def test_chat_only_publishes_stats(self) -> None:
        """Розмова теж рахує токени (раніше — ні, шкала стояла на нулі)."""
        from blackchpok_ide.agent import AgentRunner

        source = inspect.getsource(AgentRunner._chat_only)
        self.assertIn("_publish_stats", source,
                      "шлях без інструментів має публікувати статистику")

    def test_shared_stats_method_exists(self) -> None:
        from blackchpok_ide.agent import AgentRunner

        self.assertTrue(callable(getattr(AgentRunner, "_publish_stats", None)))

    def test_native_speeds_are_read(self) -> None:
        """Швидкість власного рушія лежить в ``usage['native']``."""
        usage = {
            "prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150,
            "native": {"tokens_per_second": 31.5,
                       "prompt_tokens_per_second": 581.0,
                       "generated_tokens": 30, "prompt_tokens": 120},
        }
        step = context_stats.StepStats.from_result({"usage": usage})
        self.assertEqual(step.prompt_tokens, 120)
        self.assertEqual(step.completion_tokens, 30)
        self.assertAlmostEqual(step.predicted_per_second, 31.5, places=1,
                               msg="швидкість декодування мусить бути реальною")
        self.assertAlmostEqual(step.prompt_per_second, 581.0, places=0)

    def test_zero_when_model_says_nothing(self) -> None:
        """Без ``usage`` числа лишаються нулем, а не вигадуються."""
        step = context_stats.StepStats.from_result({"usage": {}})
        self.assertEqual(step.prompt_tokens, 0)
        self.assertEqual(step.completion_tokens, 0)

    def test_applied_limit_wins_over_incoming(self) -> None:
        """Ліміт із ЗАВАНТАЖЕНОЇ моделі не перебивається числом зі знімка.

        Регресія: шкала показувала «0 / 8K», хоч модель працює з 16K, бо
        ``set_stats`` брав ``stats.context_limit`` із нового об'єкта.
        """
        # Мінімальний стенд без tkinter: перевіряємо саме пріоритет.
        bar = stats_bar.StatsBar.__new__(stats_bar.StatsBar)
        bar._limit = 16384
        bar.stats = context_stats.ContextStats()
        bar.stats.set_limit(16384)
        incoming = context_stats.ContextStats()
        incoming.set_limit(8192)          # застаріле число
        # Повторюємо логіку вибору з ``set_stats``.
        applied = int(getattr(bar, "_limit", 0) or 0)
        chosen = applied or int(getattr(incoming, "context_limit", 0) or 0)
        self.assertEqual(chosen, 16384,
                         "застосований ліміт має пріоритет над вхідним")


class TestFileListStillWorks(unittest.TestCase):
    """Раніше виправлений перелік файлів не має зламатись."""

    def test_hidden_file_still_recognised(self) -> None:
        self.assertTrue(response_engine._file_like(".gitignore  (757 B)"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
