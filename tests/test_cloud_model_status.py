"""Хмарна модель не має виглядати «зламаною», коли вона працює.

Три дефекти, знайдені живим прогоном на Deploy (скріншот користувача:
«вказав ключ, а хмарна модель не працює» — великий статус у шапці
«● МОДЕЛЬ ОФЛАЙН», а в чаті «вікно 16 384»):

1. **Хмару не перевіряли, доки вона не поточна.** ``probe_targets``
   віддавав лише локальні пресети + ПОТОЧНУ адресу. Поки поточною був
   ``native://blackchpok``, хмари в списку не було, і селектор малював її
   запис із ``online=False``. Користувач бачив «недоступна» про робочий
   API — і саме цей запис потім ставав активним.

2. **Вибір моделі брав ``entry.online`` зі списку.** Запис знімали ДО
   вибору, тож у шапку потрапляв стан СТАРОЇ адреси. Тепер шапка показує
   «…» і перевіряє НОВУ адресу у фоні.

3. **Хмара працювала з локальним вікном контексту.** У хмари немає ні
   ``/props``, ні ``--ctx-size``: ліміт задає провайдер. Агент брав
   заявлене локальне 16384, ділив навпіл (захист від поділу на слоти,
   якого в хмарі немає) і працював із 8192 при провайдері на 1 000 000.

Запуск:  python -m unittest tests.test_cloud_model_status -v
"""

from __future__ import annotations

import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import agent as agent_module  # noqa: E402
from blackchpok_ide import agent_tools, providers  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402

NATIVE = "native://blackchpok"
DEPLOY_URL = "https://api.deploy.com/api/v1"
DEPLOY_MODEL = "deepseek-ai/deepseek-v4.1-flash-1017"


class _CloudApiStub(BaseHTTPRequestHandler):
    """Хмарний API, який, як і справжній, вимагає ключ на ``/models``."""

    protocol_version = "HTTP/1.1"
    seen_keys: list[str] = []

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        key = str(self.headers.get("Authorization") or "")
        _CloudApiStub.seen_keys.append(key)
        if not key.startswith("Bearer ") or len(key) <= len("Bearer "):
            self._send({"error": {"message": "Unauthorized"}}, status=401)
            return
        self._send({"object": "list", "data": [
            {"id": DEPLOY_MODEL, "object": "model", "owned_by": "deploy"},
        ]})

    def _send(self, payload: dict, *, status: int = 200) -> None:
        import json

        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _local_cloud_settings(url: str, key: str) -> Settings:
    """Налаштування з локальною моделлю поточною, а хмарою — налаштованою."""
    settings = Settings()
    settings.engine.native = True
    settings.engine.ctx_size = 16384
    settings.llm.base_url = NATIVE
    settings.llm.model = "qwen2.5-coder-14b-instruct-q4_k_m"
    settings.llm.api_key = "local"
    settings.cloud.provider = "custom"
    settings.cloud.base_url = url
    settings.cloud.model = DEPLOY_MODEL
    settings.cloud.api_key = key
    return settings


class TestCloudIsProbed(unittest.TestCase):
    """Дефект 1: стан хмари мусить бути відомий ДО її вибору."""

    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _CloudApiStub)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{port}/v1"
        _CloudApiStub.seen_keys = []

    def tearDown(self) -> None:
        self.server.shutdown()

    def test_cloud_url_in_probe_targets(self) -> None:
        settings = _local_cloud_settings(self.url, "secret-key")
        targets = providers.probe_targets(settings)
        urls = [url for _key, url, _kind, _api in targets]
        self.assertIn(self.url, urls,
                      "налаштована хмара мусить бути серед цілей перевірки")

    def test_cloud_target_carries_api_key(self) -> None:
        """Без ключа ``GET /models`` дає 401 — проба мусить його передати."""
        settings = _local_cloud_settings(self.url, "secret-key")
        cloud = [(key, url, kind, api) for key, url, kind, api
                 in providers.probe_targets(settings) if url == self.url]
        self.assertEqual(len(cloud), 1, str(cloud))
        _key, _url, kind, api = cloud[0]
        self.assertEqual(kind, providers.CLOUD, "адреса має бути хмарною")
        self.assertEqual(api, "secret-key", "ключ API загублено")

    def test_probe_uses_key_and_reports_online(self) -> None:
        settings = _local_cloud_settings(self.url, "secret-key")
        targets = [item for item in providers.probe_targets(settings)
                   if item[1] == self.url]
        probe = providers.ProviderProbe(targets, timeout=10)
        probe.start()
        for thread in probe._threads:
            thread.join(timeout=15)
        outcomes = [item for item in probe.drain() if item.base_url == self.url]
        self.assertEqual(len(outcomes), 1, "проба має дати рівно один результат")
        self.assertTrue(outcomes[0].ok,
                        f"робоча хмара позначена недоступною: {outcomes[0].detail}")
        self.assertIn(DEPLOY_MODEL, outcomes[0].models)
        sent = " ".join(_CloudApiStub.seen_keys)
        self.assertIn("secret-key", sent, "запит пішов без ключа API")

    def test_cloud_model_entry_is_online_in_catalogue(self) -> None:
        """Селектор мусить показати робочу хмару доступною → вибір не «зламаний»."""
        settings = _local_cloud_settings(self.url, "secret-key")
        probed = {"cloud": providers.ProbeOutcome(
            "cloud", True, "моделей: 1", [DEPLOY_MODEL], self.url)}
        entries = providers.catalogue(settings, probed=probed)
        cloud = [entry for entry in entries if entry.name == DEPLOY_MODEL]
        self.assertTrue(cloud, "хмарної моделі немає в каталозі")
        self.assertTrue(cloud[0].online,
                        "робоча хмара показана недоступною — саме це давало "
                        "«● МОДЕЛЬ ОФЛАЙН» одразу після вибору")

    def test_probe_without_key_says_so_honestly(self) -> None:
        """Порожній ключ — не «мовчазний 401», а чесна причина."""
        # Ціль без ключа: саме так виглядає хмара, яку ще не налаштували.
        targets = [("cloud", self.url, providers.CLOUD, "")]
        probe = providers.ProviderProbe(targets, timeout=10)
        probe.start()
        for thread in probe._threads:
            thread.join(timeout=15)
        outcomes = probe.drain()
        self.assertFalse(outcomes[0].ok)
        self.assertIn("ключа", outcomes[0].detail)


class TestCloudContextWindow(unittest.TestCase):
    """Дефект 3: вікно контексту хмари береться з каталогу провайдера."""

    def _runner(self, base_url: str, model: str) -> agent_module.AgentRunner:
        settings = Settings()
        settings.llm.base_url = base_url
        settings.llm.model = model
        settings.llm.api_key = "k"
        settings.engine.ctx_size = 16384
        return agent_module.AgentRunner(
            agent_tools.ToolRegistry(ROOT), settings.llm, settings.agent, ROOT)

    def test_deploy_window_is_one_million(self) -> None:
        self.assertEqual(agent_module._cloud_context_window(DEPLOY_URL), 1_000_000)

    def test_openai_window_from_catalogue(self) -> None:
        self.assertEqual(agent_module._cloud_context_window("https://api.openai.com/v1"),
                         128_000)

    def test_local_and_embedded_are_not_cloud(self) -> None:
        """Локальні адреси мають іти звичайним шляхом (рушій / ``/props``)."""
        self.assertEqual(agent_module._cloud_context_window(NATIVE), 0)
        self.assertEqual(
            agent_module._cloud_context_window("http://127.0.0.1:8080/v1"), 0)

    def test_agent_adopts_provider_window_not_local_half(self) -> None:
        """Було 8192 (половина локальних 16384) — стало вікно провайдера."""
        runner = self._runner(DEPLOY_URL, DEPLOY_MODEL)
        runner.set_requested_context(16384)
        budget = runner.probe_context_window()
        self.assertEqual(budget.window, 1_000_000,
                         f"агент узяв локальне вікно: {runner.context_state()}")
        self.assertEqual(runner.session.context_limit, 1_000_000)

    def test_embedded_path_still_uses_requested_window(self) -> None:
        """Вбудований рушій не змінився: заявлене число без ділення навпіл."""
        runner = self._runner(NATIVE, "qwen2.5-coder-14b-instruct-q4_k_m")
        runner.set_requested_context(16384)
        budget = runner.probe_context_window()
        self.assertEqual(budget.window, 16384,
                         "хмарна гілка не має втручатись у локальний рушій")


class TestContextPanelTitle(unittest.TestCase):
    """Підпис панелі не має суперечити рядку «модель: … · хмара deploy»."""

    def test_section_title_is_not_hardcoded_local(self) -> None:
        """Заголовок секції береться з коду, а не зі здогаду."""
        source = (ROOT / "blackchpok_ide" / "context_panel.py").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn('self._section(host, "АГЕНТ · МОДЕЛЬ", "agent")', source,
                      "секція агента мусить мати нейтральний заголовок: "
                      "«локальна модель» показувалась і для хмари")

    def test_window_shows_unknown_instead_of_offline_before_probe(self) -> None:
        """Поки перевірка не завершилась, стан має бути «…», а не «ОФЛАЙН»."""
        source = (ROOT / "blackchpok_ide" / "main_window.py").read_text(
            encoding="utf-8", errors="replace")
        self.assertIn("_verify_current_endpoint_async", source,
                      "вибір моделі мусить перевіряти НОВУ адресу")
        self.assertIn("set_model_status(None", source,
                      "невідомий стан має показуватись сірим «…», а не червоним")


if __name__ == "__main__":
    unittest.main(verbosity=2)
