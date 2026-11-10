"""Тести провайдера Deploy (deploy.com): адреси, моделі, регіони, запити.

Запуск:  python tests/test_deploy.py
"""

from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import cloud_agents, effort  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402
from blackchpok_ide.llm_client import LLMClient  # noqa: E402

failures = 0
checked = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures, checked
    checked += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


# ─────────────────────────────────────────────────────────────────────────────
# Пресет і адреси
# ─────────────────────────────────────────────────────────────────────────────

def test_preset() -> None:
    provider = cloud_agents.get("deploy")
    check("пресет Deploy є", provider is not None)
    if provider is None:
        return
    check("підпис", "Deploy" in provider.label, provider.label)
    check("типова адреса — api.deploy.com",
          provider.base_url == "https://api.deploy.com/api/v1", provider.base_url)
    check("сторінка ключа — portal.deploy.com",
          "portal.deploy.com" in provider.key_url, provider.key_url)
    check("є документація", "docs.deploy.com" in provider.docs_url, provider.docs_url)
    check("вікно 1 млн токенів", provider.context == 1_000_000, str(provider.context))
    check("reasoning позначено", provider.reasoning)

    models = provider.models
    check("модель DeepSeek V4.1 Flash",
          any("deepseek-v4.1-flash" in m for m in models), str(models))
    check("модель GLM 5.3 Flash",
          any("glm-5.3-flash" in m for m in models), str(models))

    labels = dict(cloud_agents.provider_labels())
    check("Deploy у списку провайдерів", "deploy" in labels, ",".join(labels))


def test_urls() -> None:
    check("нормалізація додає /api/v1",
          cloud_agents.normalise_base_url("api.deploy.com")
          == "https://api.deploy.com/api/v1",
          cloud_agents.normalise_base_url("api.deploy.com"))
    check("наявний /api/v1 не дублюється",
          cloud_agents.normalise_base_url("https://api.deploy.com/api/v1")
          == "https://api.deploy.com/api/v1")
    check("зайвий /v1 виправляється",
          cloud_agents.normalise_base_url("https://api.deploy.com/v1")
          == "https://api.deploy.com/api/v1",
          cloud_agents.normalise_base_url("https://api.deploy.com/v1"))
    check("SF-адреса зберігається",
          cloud_agents.normalise_base_url("https://api-sf1.deploy.com/api/v1")
          == "https://api-sf1.deploy.com/api/v1")

    # Не плутаємо Deploy з іншими провайдерами
    check("deepseek не стає deploy",
          cloud_agents.normalise_base_url("https://api.deepseek.com")
          == "https://api.deepseek.com/v1",
          cloud_agents.normalise_base_url("https://api.deepseek.com"))


def test_detect() -> None:
    for url in ("https://api.deploy.com/api/v1",
                "https://api-cdn.deploy.com/api/v1",
                "https://api-sf1.deploy.com/api/v1",
                "https://api-va1-cdn.deploy.com/api/v1"):
        found = cloud_agents.detect(url)
        check(f"detect {url}", found is not None and found.key == "deploy",
              found.key if found else "None")

    other = cloud_agents.detect("https://api.openai.com/v1")
    check("detect OpenAI не Deploy", other is not None and other.key == "openai",
          other.key if other else "None")

    check("is_deploy розпізнає", cloud_agents.is_deploy("https://api.deploy.com/api/v1"))
    check("is_deploy відхиляє чуже", not cloud_agents.is_deploy("https://api.openai.com"))


def test_regions() -> None:
    endpoints = cloud_agents.deploy_endpoints()
    check("є 6 регіонів", len(endpoints) == 6, str(len(endpoints)))
    urls = [url for _label, url in endpoints]
    check("усі належать deploy.com",
          all("deploy.com" in url for url in urls), str(urls))
    check("перший — найближчий", endpoints[0][1] == "https://api.deploy.com/api/v1",
          endpoints[0][1])
    check("є CDN-варіант",
          any("api-cdn" in url for _label, url in endpoints))
    check("є SF і VA",
          any("api-sf1" in url for _label, url in endpoints)
          and any("api-va1" in url for _label, url in endpoints))


def test_efforts() -> None:
    levels = cloud_agents.deploy_efforts()
    check("чотири рівні Deploy", levels == ["none", "low", "high", "max"], str(levels))

    # Наші рівні мають покривати значення Deploy
    for key in ("none", "low", "high", "max"):
        payload = effort.payload_for(key)
        check(f"рівень «{key}» передається",
              payload.get("reasoning_effort") == key, str(payload))

    check("«Без міркувань» вимикає thinking",
          effort.payload_for("none").get("reasoning_effort") == "none")
    check("«Максимум» має найбільший бюджет",
          effort.get("max").budget_tokens > effort.get("high").budget_tokens,
          f"{effort.get('max').budget_tokens} > {effort.get('high').budget_tokens}")


def test_settings_roundtrip() -> None:
    settings = Settings()
    settings.cloud.provider = "deploy"
    settings.cloud.api_key = "test-key-123"
    settings.cloud.base_url = "https://api-va1.deploy.com/api/v1"
    settings.cloud.model = "deepseek-ai/deepseek-v4.1-flash-1017"

    restored = Settings.from_dict(settings.to_dict())
    check("провайдер зберігається", restored.cloud.provider == "deploy")
    check("адреса зберігається",
          restored.cloud.base_url == "https://api-va1.deploy.com/api/v1")
    check("модель ��берігається",
          restored.cloud.model == "deepseek-ai/deepseek-v4.1-flash-1017")
    check("хмара вважається налаштованою", restored.cloud.enabled)


# ─────────────────────────────────────────────────────────────────────────────
# Реальний запит: сервер, що відтворює формат Deploy
# ─────────────────────────────────────────────────────────────────────────────

class _DeployStub(BaseHTTPRequestHandler):
    """Відтворює відповідь Deploy із documentation (reasoning_content)."""

    protocol_version = "HTTP/1.1"
    seen: dict = {}

    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        payload = {"object": "list", "data": [
            {"id": "deepseek-ai/deepseek-v4.1-flash-1017", "object": "model",
             "owned_by": "deploy"},
            {"id": "zai-org/glm-5.3-flash", "object": "model", "owned_by": "deploy"},
        ]}
        self._send(payload)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        _DeployStub.seen = {
            "path": self.path,
            "model": body.get("model"),
            "reasoning_effort": body.get("reasoning_effort"),
            "tools": len(body.get("tools") or []),
        }
        payload = {
            "id": "bf7eb425-c8ee-11f1-bc46-67542ee84316",
            "object": "chat.completion",
            "created": 1792106317,
            "model": body.get("model"),
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "Відповідь українською.",
                    "reasoning_content": "Спершу подумаю про це завдання…",
                },
            }],
            "usage": {"prompt_tokens": 25, "completion_tokens": 12, "total_tokens": 37,
                      "prompt_tokens_details": {"cached_tokens": 10}},
        }
        self._send(payload)

    def _send(self, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_live_request() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DeployStub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}/api/v1"
    try:
        client = LLMClient(base, "deepseek-ai/deepseek-v4.1-flash-1017", "test-key",
                           timeout=10, reasoning_effort="high")
        models = client.list_models()
        check("список моделей віддається", len(models) == 2, str(models))

        result = client.chat(
            [{"role": "user", "content": "поясни TCP і UDP"}],
            tools=[{"type": "function",
                    "function": {"name": "read_file", "description": "читати",
                                 "parameters": {"type": "object", "properties": {}}}}],
        )
        check("відповідь отримано", result.content.startswith("Відповідь"),
              result.content[:40])
        check("reasoning_content зчитано",
              "подумаю" in result.reasoning, result.reasoning[:40])

        seen = _DeployStub.seen
        check("запит пішов на /chat/completions",
              seen.get("path", "").endswith("/chat/completions"), seen.get("path", ""))
        check("модель передано", seen.get("model") == "deepseek-ai/deepseek-v4.1-flash-1017",
              str(seen.get("model")))
        check("reasoning_effort передано", seen.get("reasoning_effort") == "high",
              str(seen.get("reasoning_effort")))
        check("інструменти передано", seen.get("tools") == 1, str(seen.get("tools")))
    finally:
        server.shutdown()


def test_real_endpoint() -> None:
    """Справжній api.deploy.com: перевіряємо, що ендпоінт живий і віддає моделі."""
    result = cloud_agents.probe("test-invalid-key", "https://api.deploy.com/api/v1",
                                timeout=12)
    # Навіть із недійсним ключем /models може відповісти — головне, що сервіс живий.
    if result.ok:
        check("справжній Deploy віддає моделі", len(result.models) >= 2,
              str(result.models))
    else:
        check("справжній Deploy відповідає", "немає з'єднання" not in result.detail.lower(),
              result.detail[:120])


def main() -> int:
    test_preset()
    test_urls()
    test_detect()
    test_regions()
    test_efforts()
    test_settings_roundtrip()
    test_live_request()
    test_real_endpoint()
    print()
    print(f"Перевірено тверджень: {checked}")
    print("Deploy:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_deploy.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
