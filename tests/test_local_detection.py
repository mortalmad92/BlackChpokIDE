"""Регресії «локальний чи хмарний» (Етап 5, 10.11.2026).

До виправлення це поняття визначалось **сімома** незалежними способами:

1. ``llm_client._is_local_url`` — 4 маркери підрядком;
2. ``auto_setup._is_local_url`` — власний ``LOCAL_HOSTS`` із 7 хостів;
3. ``providers.LocalProvider.is_local`` — завжди ``True``;
4. ``providers.ModelEntry.is_local`` — ``kind == LOCAL``;
5. ``main_window._model_summary`` — інлайн-список + окрема перевірка ``native://``;
6. ``browser_panel.is_local_url`` — власний набір хостів;
7. ``config.LLMSettings.normalise`` — інлайн-перевірка схеми.

Через це та сама адреса в різних частинах інтерфейсу могла вважатись
локальною або хмарною по-різному. Тепер є одна функція.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide import (  # noqa: E402
    auto_setup, browser_panel, llm_client, provider_adapters,
)

LOCAL_URLS = (
    "http://127.0.0.1:8080/v1",
    "http://localhost:1234/v1",
    "http://0.0.0.0:8000",
    "http://[::1]:8080",
    "http://192.168.1.5:8080/v1",
    "http://10.0.0.7/v1",
    "native://blackchpok",
)

CLOUD_URLS = (
    "https://api.openai.com/v1",
    "https://api.anthropic.com/v1",
    "https://generativelanguage.googleapis.com/v1beta",
    "https://api.deepseek.com/v1",
)


class TestSingleImplementation(unittest.TestCase):
    """Одна функція — один результат."""

    def test_local_urls_detected(self) -> None:
        for url in LOCAL_URLS:
            self.assertTrue(provider_adapters.is_local_url(url),
                            f"{url} мусить бути локальною")

    def test_cloud_urls_detected(self) -> None:
        for url in CLOUD_URLS:
            self.assertFalse(provider_adapters.is_local_url(url),
                             f"{url} мусить бути хмарною")

    def test_empty_is_not_local(self) -> None:
        self.assertFalse(provider_adapters.is_local_url(""))

    def test_embedded_counts_as_local(self) -> None:
        self.assertTrue(provider_adapters.is_local_url("native://blackchpok"))

    def test_cloud_helper(self) -> None:
        self.assertTrue(provider_adapters.is_cloud_url("https://api.openai.com/v1"))
        self.assertFalse(provider_adapters.is_cloud_url("http://127.0.0.1:8080/v1"))
        self.assertFalse(provider_adapters.is_cloud_url(""),
                         "порожня адреса — це не хмара, це «не налаштовано»")


class TestCallersAgree(unittest.TestCase):
    """Колишні незалежні реалізації мусять давати той самий результат."""

    def test_llm_client_delegates(self) -> None:
        for url in LOCAL_URLS + CLOUD_URLS:
            self.assertEqual(llm_client._is_local_url(url),
                             provider_adapters.is_local_url(url),
                             f"розбіжність для {url}")

    def test_auto_setup_delegates(self) -> None:
        for url in LOCAL_URLS + CLOUD_URLS:
            self.assertEqual(auto_setup._is_local_url(url),
                             provider_adapters.is_local_url(url),
                             f"розбіжність для {url}")

    def test_browser_panel_agrees_except_file(self) -> None:
        for url in LOCAL_URLS + CLOUD_URLS:
            self.assertEqual(browser_panel.is_local_url(url),
                             provider_adapters.is_local_url(url),
                             f"розбіжність для {url}")

    def test_browser_panel_treats_file_as_local(self) -> None:
        """``file://`` — свідомий виняток: це файл на диску."""
        self.assertTrue(browser_panel.is_local_url("file:///C:/x.html"))
        self.assertFalse(provider_adapters.is_local_url("file:///C:/x.html"))


class TestParsingEdgeCases(unittest.TestCase):
    """Розбір адрес: порт, логін, шлях, схема."""

    def test_port_is_stripped(self) -> None:
        self.assertTrue(provider_adapters.is_local_url("http://localhost:9999"))

    def test_credentials_are_stripped(self) -> None:
        self.assertTrue(
            provider_adapters.is_local_url("http://user:pass@127.0.0.1:8080/v1"))

    def test_path_does_not_matter(self) -> None:
        self.assertTrue(
            provider_adapters.is_local_url("http://127.0.0.1:8080/v1/chat/completions"))

    def test_scheme_is_optional(self) -> None:
        self.assertTrue(provider_adapters.is_local_url("127.0.0.1:8080"))

    def test_public_ip_is_not_local(self) -> None:
        self.assertFalse(provider_adapters.is_local_url("http://8.8.8.8:8080"))

    def test_hostname_containing_localhost_is_not_local(self) -> None:
        """``notlocalhost.example.com`` не має вважатись локальним.

        Стара реалізація шукала ПІДРЯДОК, тому такий хост проходив.
        """
        self.assertFalse(
            provider_adapters.is_local_url("https://notlocalhost.example.com/v1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
