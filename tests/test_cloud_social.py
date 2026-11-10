"""Тести хмарних агентів і публікації в соцмережі.

Мережеві виклики перевіряються на **справжньому локальному HTTP-сервері**,
який вдає API — жодних заглушок у коді самої програми.

Запуск:  python tests/test_cloud_social.py
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import cloud_agents, social  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402
from blackchpok_ide.llm_client import ChatResult, is_reasoning_model  # noqa: E402

failures = 0
checked = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures, checked
    checked += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


# ─────────────────────────────────────────────────────────────────────────────
# Хмарні провайдери
# ─────────────────────────────────────────────────────────────────────────────

def test_providers() -> None:
    check("є пресет DeepSeek", cloud_agents.get("deepseek") is not None)
    deepseek = cloud_agents.get("deepseek")
    check("DeepSeek має адресу API",
          deepseek is not None and "deepseek.com" in deepseek.base_url,
          deepseek.base_url if deepseek else "")
    check("DeepSeek має сторінку ключа",
          deepseek is not None and "platform.deepseek.com" in deepseek.key_url)
    check("у DeepSeek є reasoning-модель",
          deepseek is not None and any("reasoner" in m for m in deepseek.models))

    labels = dict(cloud_agents.provider_labels())
    for expected in ("deepseek", "openai", "gemini", "custom"):
        check(f"є провайдер {expected}", expected in labels, ",".join(labels))

    check("OpenRouter одним ключем до багатьох моделей",
          cloud_agents.get("openrouter") is not None)
    check("кастомний URL дозволено",
          (cloud_agents.get("custom") or object()) is not None)

    check("detect за адресою",
          cloud_agents.detect("https://api.deepseek.com/v1").key == "deepseek")
    check("detect чужого URL — None",
          cloud_agents.detect("http://127.0.0.1:1234/v1") is None)

    check("normalise додає /v1",
          cloud_agents.normalise_base_url("api.deepseek.com")
          == "https://api.deepseek.com/v1")
    check("normalise не дублює /v1",
          cloud_agents.normalise_base_url("https://api.openai.com/v1")
          == "https://api.openai.com/v1")
    check("openai-сумісний шлях Gemini зберігається",
          cloud_agents.normalise_base_url(
              "https://generativelanguage.googleapis.com/v1beta/openai")
          .endswith("/openai"))

    check("маска ключа не показує весь ключ",
          cloud_agents.mask_key("sk-abcdef123456") == "sk-a…3456",
          cloud_agents.mask_key("sk-abcdef123456"))
    check("порожній ключ — порожня маска", cloud_agents.mask_key("") == "")


def test_reasoning() -> None:
    check("deepseek-reasoner — reasoning", is_reasoning_model("deepseek-reasoner"))
    check("deepseek-chat — не reasoning", not is_reasoning_model("deepseek-chat"))
    check("o3-mini — reasoning", is_reasoning_model("o3-mini"))
    check("gpt-4o — не reasoning", not is_reasoning_model("gpt-4o"))
    check("порожня назва — не reasoning", not is_reasoning_model(""))

    result = ChatResult(content="відповідь", tool_calls=[], reasoning="міркування")
    check("ChatResult зберігає reasoning", result.reasoning == "міркування")
    check("reasoning не потрапляє у content", "міркування" not in result.content)


def test_cloud_settings() -> None:
    settings = Settings()
    check("хмара типово вимкнена", not settings.cloud.enabled)
    settings.cloud.api_key = "sk-test"
    settings.cloud.base_url = "https://api.deepseek.com/v1"
    check("з ключем і адресою — увімкнена", settings.cloud.enabled)
    settings.cloud.model = "deepseek-reasoner"

    data = settings.to_dict()
    restored = Settings.from_dict(data)
    check("хмарні налаштування зберігаються",
          restored.cloud.api_key == "sk-test"
          and restored.cloud.model == "deepseek-reasoner")
    check("модель розпізнається як reasoning",
          is_reasoning_model(restored.cloud.model))


# ─────────────────────────────────────────────────────────────────────────────
# Соцмережі
# ─────────────────────────────────────────────────────────────────────────────

def test_social_config() -> None:
    settings = Settings()
    check("є 5 мереж", len(social.NETWORKS) >= 5, str(len(social.NETWORKS)))
    keys = [network.key for network in social.NETWORKS]
    for expected in ("telegram", "x", "facebook", "mastodon"):
        check(f"є мережа {expected}", expected in keys)

    check("телеграм не налаштований", not social.is_configured(settings, "telegram"))
    missing = social.missing_fields(settings, "telegram")
    check("показано, чого бракує", len(missing) == 2, ", ".join(missing))

    settings.social.set_values("telegram", {"token": "1:a", "chat": "@c"})
    check("після заповнення — налаштований", social.is_configured(settings, "telegram"))
    check("мережа у списку готових", "telegram" in social.configured_networks(settings))

    check("detect однієї мережі", social.detect("опублікуй у телеграм") == ["telegram"])
    check("detect кількох мереж",
          set(social.detect("запости в twitter і facebook")) == {"x", "facebook"})
    check("detect без мережі", social.detect("просто текст") == [])

    check("ліміт X — 280", social.limit_for("x") == 280)
    check("ліміт Telegram — 4096", social.limit_for("telegram") == 4096)

    hint = social.setup_hint(settings, "x")
    check("підказка згадує налаштування", "Налаштування" in hint, hint[:70])


def test_social_publish_errors() -> None:
    settings = Settings()
    result = social.publish("telegram", "текст", settings)
    check("без ключів — відмова з поясненням", not result.ok and "Не заповнено" in result.detail,
          result.detail[:80])
    result2 = social.publish("telegram", "   ", settings)
    check("порожній текст відхилено", not result2.ok)
    result3 = social.publish("nonexistent", "текст", settings)
    check("невідома мережа — відмова", not result3.ok)


class _FakeTelegram(BaseHTTPRequestHandler):
    """Справжній HTTP-сервер, що вдає Telegram Bot API."""

    protocol_version = "HTTP/1.1"
    received: dict = {}

    def log_message(self, *_args) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        _FakeTelegram.received = {"path": self.path, "body": body}
        payload = {"ok": True, "result": {"message_id": 77,
                                          "chat": {"username": "mychannel"}}}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_social_publish_live() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeTelegram)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    settings = Settings()
    settings.social.set_values("telegram", {"token": "999:REAL", "chat": "@mychannel"})

    original = social._post_json

    def patched(url: str, payload: dict, headers: dict, timeout: float = 30.0):
        safe_url = url.replace("https://api.telegram.org", f"http://127.0.0.1:{port}")
        return original(safe_url, payload, headers, timeout)

    social._post_json = patched  # type: ignore[assignment]
    try:
        result = social.publish("telegram", "Привіт з IDE! Це справжня публікація.", settings)
        check("публікація успішна", result.ok, result.detail[:90])
        check("посилання на пост отримано", result.url == "https://t.me/mychannel/77",
              result.url)

        received = _FakeTelegram.received
        check("запит пішов на правильний шлях",
              "/bot999:REAL/sendMessage" in received.get("path", ""),
              received.get("path", ""))
        check("текст дійшов до сервера",
              received.get("body", {}).get("text", "").startswith("Привіт з IDE"),
              str(received.get("body", {}).get("text"))[:50])
        check("chat_id передано",
              received.get("body", {}).get("chat_id") == "@mychannel")

        # Обрізання довгого тексту під ліміт мережі
        long_text = "а" * 5000
        result2 = social.publish("telegram", long_text, settings)
        sent = str(_FakeTelegram.received.get("body", {}).get("text", ""))
        check("довгий текст обрізано до ліміту", result2.ok and len(sent) <= 4096,
              str(len(sent)))

        summary = social.summary_text([result])
        check("підсумок містить мережу й посилання",
              "Telegram" in summary and "t.me" in summary, summary[:80])
    finally:
        social._post_json = original  # type: ignore[assignment]
        server.shutdown()


def test_social_dry_run() -> None:
    settings = Settings()
    settings.social.set_values("discord", {"webhook": "https://example.invalid/hook"})
    result = social.publish("discord", "чернетка", settings, dry_run=True)
    check("чернетка без реального запиту", result.ok and "Чернетка" in result.detail,
          result.detail[:60])


def test_social_tool_schema() -> None:
    schemas = social.tool_schemas()
    check("є схема publish_social", len(schemas) == 1)
    function = schemas[0]["function"]
    check("назва інструмента", function["name"] == "publish_social")
    check("опис згадує мережі",
          all(name in function["description"] for name in ("telegram", "x")), "")
    check("параметри описані", "text" in function["parameters"]["properties"])


def test_catalogue() -> None:
    settings = Settings()
    text = social.catalogue_text(settings)
    check("без налаштувань — пояснення", "не заповнено" in text.lower(), text[:60])
    settings.social.set_values("telegram", {"token": "1:a", "chat": "@c"})
    text2 = social.catalogue_text(settings)
    check("з налаштуванням — перелік", "Telegram" in text2, text2[:60])


def main() -> int:
    test_providers()
    test_reasoning()
    test_cloud_settings()
    test_social_config()
    test_social_publish_errors()
    test_social_publish_live()
    test_social_dry_run()
    test_social_tool_schema()
    test_catalogue()
    print()
    print(f"Перевірено тверджень: {checked}")
    print("Хмара й соцмережі:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_cloud_social.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
