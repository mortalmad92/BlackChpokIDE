"""Вбудований рушій не має порту — про це мусить знати КОЖНА перевірка.

Дефект, який бачив користувач на скріншоті: модель завантажена у власний
рушій (``engine.loaded is True``, ``context_actual`` 32768, GPU-шарів 48),
а шапка показує «● МОДЕЛЬ ОФЛАЙН», у чаті червона крапка, а діагностика
радить «запусти модель» і «жоден локальний порт не відповідає».

Причина одна на всі симптоми: ``server_responds("native://blackchpok")``
робить HTTP-запит на адресу БЕЗ ПОРТУ й завжди повертає ``False``.
``LLMClient.list_models()`` теж не годиться як «жива модель»: для
вбудованого рушія він повертає СПИСОК ФАЙЛІВ на диску.

Ці тести фіксують правильні відповіді на трьох рівнях:
* :mod:`blackchpok_ide.runtime` — ``model_answers`` / ``embedded_model_loaded``;
* :mod:`blackchpok_ide.providers` — проба провайдера й вид адреси;
* :mod:`blackchpok_ide.diagnostics` — звіт самодіагностики.

Модель НЕ завантажується: підмінюємо стан рушія, бо питання тут — кому
вірити, а не чи вміє llama.cpp рахувати.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import diagnostics, providers, runtime  # noqa: E402

NATIVE = "native://blackchpok"


class _FakeEngine:
    """Мінімальний рушій: цікавлять лише ``loaded`` і ``available``."""

    def __init__(self, loaded: bool, available: bool = True) -> None:
        self.loaded = loaded
        self.available = available


class _FakeRuntime:
    def __init__(self, loaded: bool, available: bool = True) -> None:
        self.engine = _FakeEngine(loaded, available)


class TestEmbeddedAddressRecognition(unittest.TestCase):
    def test_all_embedded_schemes_recognised(self) -> None:
        for url in (NATIVE, "inproc://engine", "blackchpok://local", NATIVE.upper()):
            self.assertTrue(runtime.embedded_url(url), url)

    def test_http_addresses_are_not_embedded(self) -> None:
        for url in ("http://127.0.0.1:8080/v1", "https://api.openai.com/v1", "", None):
            self.assertFalse(runtime.embedded_url(url or ""), url)

    def test_server_responds_is_still_false_for_embedded(self) -> None:
        """Це не дефект, а факт: у ``native://`` немає HTTP.

        Тест фіксує межу між двома функціями. Якщо колись ``server_responds``
        почне повертати ``True`` для ``native://``, це означатиме, що вона
        знову змішує два різні питання.
        """
        self.assertFalse(runtime.server_responds(NATIVE, api_key="local",
                                                 timeout=0.3, level=0))

    def test_server_responds_never_raises_on_bad_host(self) -> None:
        """Функція обіцяє ``bool`` — і мусить його повертати.

        ЗАМІРЯНО: ``server_responds("native://blackchpok", level=0)`` кидала
        ``socket.gaierror: [Errno 11001] getaddrinfo failed``, бо ім'я
        ``blackchpok`` не резолвиться. Виняток летів у виклик, і кожне місце
        мусило мати власний ``try/except`` — а де забули, там падав
        інтерфейс.
        """
        for url in (NATIVE, "http://no-such-host.invalid:1/v1",
                    "http://[bad", "ftp://x"):
            for level in (0, 1, 2):
                with self.subTest(url=url, level=level):
                    answer = runtime.server_responds(url, api_key="k",
                                                     timeout=0.2, level=level)
                    self.assertIsInstance(answer, bool)


class TestModelAnswersForEmbedded(unittest.TestCase):
    """``model_answers`` — те, чим має користуватись інтерфейс."""

    def test_loaded_model_is_online(self) -> None:
        fake = _FakeRuntime(loaded=True)
        with mock.patch("blackchpok_ide.native.bridge.runtime", return_value=fake):
            self.assertTrue(runtime.model_answers(NATIVE))
            self.assertTrue(runtime.embedded_model_loaded())

    def test_unloaded_model_is_offline(self) -> None:
        """Рушій є, модель не в пам'яті — це ЧЕСНО офлайн, а не «онлайн»."""
        fake = _FakeRuntime(loaded=False)
        with mock.patch("blackchpok_ide.native.bridge.runtime", return_value=fake):
            self.assertFalse(runtime.model_answers(NATIVE))
            self.assertFalse(runtime.embedded_model_loaded())

    def test_broken_engine_does_not_raise(self) -> None:
        """Статус у шапці не має падати через відсутній рушій."""
        with mock.patch("blackchpok_ide.native.bridge.runtime",
                        side_effect=RuntimeError("рушія немає")):
            self.assertFalse(runtime.model_answers(NATIVE))

    def test_http_address_goes_through_network_path(self) -> None:
        """Для HTTP ``model_answers`` делегує в ``server_responds``."""
        with mock.patch.object(runtime, "server_responds",
                               return_value=True) as spy:
            self.assertTrue(runtime.model_answers("http://127.0.0.1:8080/v1"))
        spy.assert_called_once()
        with mock.patch.object(runtime, "embedded_model_loaded") as never:
            runtime.model_answers("http://127.0.0.1:8080/v1")
        never.assert_not_called()


class TestProvidersKnowEmbedded(unittest.TestCase):
    def test_embedded_url_is_local(self) -> None:
        self.assertEqual(providers._kind_of(NATIVE), providers.LOCAL)

    def test_probe_reports_loaded_model(self) -> None:
        fake = _FakeRuntime(loaded=True)
        with mock.patch("blackchpok_ide.native.bridge.runtime", return_value=fake):
            probe = providers.ProviderProbe([("current", NATIVE, providers.LOCAL)])
            probe.start()
            for thread in probe._threads:
                thread.join(timeout=10)
            outcomes = probe.drain()
        self.assertEqual(len(outcomes), 1, "проба мусить дати рівно один результат")
        self.assertTrue(outcomes[0].ok)
        self.assertEqual(outcomes[0].base_url, NATIVE)

    def test_probe_reports_unloaded_model_honestly(self) -> None:
        fake = _FakeRuntime(loaded=False)
        with mock.patch("blackchpok_ide.native.bridge.runtime", return_value=fake):
            probe = providers.ProviderProbe([("current", NATIVE, providers.LOCAL)])
            probe.start()
            for thread in probe._threads:
                thread.join(timeout=10)
            outcomes = probe.drain()
        self.assertFalse(outcomes[0].ok)
        self.assertIn("не завантажена", outcomes[0].detail)


class TestDiagnosticsUnderstandsEmbedded(unittest.TestCase):
    """Діагностика не має радити «запусти модель», коли вона вже працює."""

    def _settings(self):
        from blackchpok_ide.config import Settings

        settings = Settings()
        settings.llm.base_url = NATIVE
        settings.llm.model = "qwen-test"
        return settings

    def test_working_embedded_engine_passes_address_checks(self) -> None:
        fake = _FakeRuntime(loaded=True)
        with mock.patch("blackchpok_ide.native.bridge.runtime", return_value=fake):
            report = diagnostics.run(settings=self._settings(),
                                     probe_inference=False)
        names = {item.name: item for item in report.checks}
        self.assertTrue(names["Адреса з налаштувань"].ok,
                        names["Адреса з налаштувань"].detail)
        self.assertTrue(names["Робочий порт"].ok, names["Робочий порт"].detail)
        self.assertIn("вбудований", names["Робочий порт"].detail)

    def test_no_port_scan_for_embedded(self) -> None:
        """Пошук по 8 портах для ``native://`` — це час намарно."""
        fake = _FakeRuntime(loaded=True)
        with mock.patch("blackchpok_ide.native.bridge.runtime", return_value=fake):
            with mock.patch.object(runtime, "discover_server_url",
                                   side_effect=AssertionError("скан портів!")):
                report = diagnostics.run(settings=self._settings(),
                                         probe_inference=False)
        self.assertTrue(report.checks)

    def test_unloaded_embedded_engine_still_has_working_address(self) -> None:
        """Адреса ``native://blackchpok`` правильна й без моделі в пам'яті.

        ЗАМІРЯНО: у живому звіті було «✗ Адреса з налаштувань — ніхто не
        слухає» і «✗ Робочий порт — модель не завантажена» — і поруч
        «✓ Відповідь моделі — «Тест»». Звіт суперечив сам собі.
        """
        fake = _FakeRuntime(loaded=False, available=True)
        with mock.patch("blackchpok_ide.native.bridge.runtime", return_value=fake):
            report = diagnostics.run(settings=self._settings(),
                                     probe_inference=False)
        names = {item.name: item for item in report.checks}
        self.assertTrue(names["Адреса з налаштувань"].ok,
                        names["Адреса з налаштувань"].detail)
        self.assertTrue(names["Робочий порт"].ok,
                        names["Робочий порт"].detail)
        # Але чесно кажемо, що модель ще не в пам'яті.
        self.assertIn("перший запит",
                      names["Адреса з налаштувань"].detail
                      + names["Робочий порт"].detail)

    def test_missing_engine_fails_with_actionable_hint(self) -> None:
        fake = _FakeRuntime(loaded=False, available=False)
        with mock.patch("blackchpok_ide.native.bridge.runtime", return_value=fake):
            report = diagnostics.run(settings=self._settings(),
                                     probe_inference=False)
        names = {item.name: item for item in report.checks}
        self.assertFalse(names["Адреса з налаштувань"].ok)
        self.assertFalse(names["Робочий порт"].ok)
        self.assertIn("не встановлено", names["Робочий порт"].detail)
        self.assertIn("Встановити рушій", names["Робочий порт"].fix)

    def test_verdict_does_not_mention_ports_for_embedded(self) -> None:
        """Порада «шукай робочий порт» для вбудованого рушія — неправда."""
        fake = _FakeRuntime(loaded=True)
        with mock.patch("blackchpok_ide.native.bridge.runtime", return_value=fake):
            report = diagnostics.run(settings=self._settings(),
                                     probe_inference=False)
        self.assertNotIn("порт", report.verdict.lower())

    def test_no_server_log_for_embedded(self) -> None:
        """``server.log`` пише llama-server, якого тут не запускали."""
        fake = _FakeRuntime(loaded=True)
        with mock.patch("blackchpok_ide.native.bridge.runtime", return_value=fake):
            report = diagnostics.run(settings=self._settings(),
                                     probe_inference=False,
                                     engine_log_tail=lambda n: "model loaded")
        self.assertEqual(report.engine_log, "")


class TestMainWindowPathsAreFixed(unittest.TestCase):
    """Перевірка самих місць, де дефект проявлявся в інтерфейсі."""

    def test_header_state_uses_model_answers(self) -> None:
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(
            encoding="utf-8")
        # ``_confirm_model_online`` мусить питати ``model_answers``.
        start = source.index("def _confirm_model_online")
        block = source[start:start + 2000]
        self.assertIn("runtime.model_answers", block)

    def test_reconcile_skips_embedded(self) -> None:
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(
            encoding="utf-8")
        start = source.index("def _reconcile_server_url")
        block = source[start:start + 2000]
        self.assertIn("runtime.embedded_url", block)

    def test_agent_skips_network_probe_for_embedded(self) -> None:
        source = (ROOT / "blackchpok_ide" / "agent.py").read_text(
            encoding="utf-8")
        start = source.index("def _resolved_base_url")
        block = source[start:start + 1500]
        self.assertIn("runtime.embedded_url", block)


if __name__ == "__main__":
    unittest.main()
