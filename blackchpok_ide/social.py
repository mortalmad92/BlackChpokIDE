"""Соціальні мережі: налаштування API в програмі й реальна публікація.

Раніше ключі бралися лише зі змінних середовища (`MCP_X_ACCESS_TOKEN` тощо),
тож у звичайного користувача публікація не працювала. Тепер їх можна вписати
в **Налаштування → Соцмережі**, а модуль знає, як для кожної мережі:

* взяти ключ із налаштувань (або зі змінної середовища як запасний варіант);
* сформувати запит;
* опублікувати й повернути зрозумілий результат.

Модуль не тягне tkinter; мережеві запити — лише у функції ``publish``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Network:
    """Опис соцмережі: які поля потрібні й куди постити."""

    key: str
    label: str
    fields: tuple[tuple[str, str, str], ...]   # (поле, підпис, підказка)
    limit: int = 0                             # ліміт символів (0 = без)
    how: str = ""                              # як отримати ключ
    secret_fields: tuple[str, ...] = ("token",)


NETWORKS: tuple[Network, ...] = (
    Network(
        key="telegram",
        label="Telegram",
        fields=(
            ("token", "Токен бота", "Від @BotFather → /newbot → токен"),
            ("chat", "Chat ID", "Ваш id або @назва_каналу"),
        ),
        limit=4096,
        how="Напиши @BotFather у Telegram, створи бота й скопіюй токен. "
            "Chat ID можна взяти в @userinfobot.",
        secret_fields=("token",),
    ),
    Network(
        key="x",
        label="X (Twitter)",
        fields=(
            ("token", "Токен доступу", "OAuth 2.0 user token із правом tweet.write"),
        ),
        limit=280,
        how="developer.twitter.com → App → Keys and tokens → OAuth 2.0 "
            "User context (потрібен дозвіл write).",
        secret_fields=("token",),
    ),
    Network(
        key="facebook",
        label="Facebook (сторінка)",
        fields=(
            ("page", "Page ID", "Ідентифікатор сторінки"),
            ("token", "Токен сторінки", "Page Access Token"),
        ),
        limit=63_206,
        how="developers.facebook.com → Graph API Explorer → вибери сторінку "
            "й скопіюй Page Access Token.",
        secret_fields=("token",),
    ),
    Network(
        key="mastodon",
        label="Mastodon",
        fields=(
            ("base", "Адреса сервера", "Напр. https://mastodon.social"),
            ("token", "Токен доступу", "Preferences → Development → New application"),
        ),
        limit=500,
        how="У Mastodon: Preferences → Development → New application, "
            "права write:statuses.",
        secret_fields=("token",),
    ),
    Network(
        key="discord",
        label="Discord (вебхук)",
        fields=(
            ("webhook", "URL вебхука", "Канал → Інтеграції → Вебхуки"),
        ),
        limit=2000,
        how="Канал → Налаштування → Інтеграції → Вебхуки → Скопіювати URL.",
        secret_fields=("webhook",),
    ),
)

_BY_KEY: dict[str, Network] = {network.key: network for network in NETWORKS}

#: Змінні середовища як запасний варіант (сумісність зі старим MCP-сервером).
ENV_MAP: dict[str, dict[str, str]] = {
    "x": {"token": "MCP_X_ACCESS_TOKEN"},
    "facebook": {"page": "MCP_FACEBOOK_PAGE_ID", "token": "MCP_FACEBOOK_PAGE_TOKEN"},
    "telegram": {"token": "MCP_TELEGRAM_BOT_TOKEN", "chat": "MCP_TELEGRAM_CHAT_ID"},
    "mastodon": {"base": "MCP_MASTODON_BASE_URL", "token": "MCP_MASTODON_TOKEN"},
    "discord": {"webhook": "MCP_DISCORD_WEBHOOK"},
}


def get(key: str) -> Optional[Network]:
    return _BY_KEY.get((key or "").strip().lower())


def network_labels() -> list[tuple[str, str]]:
    return [(network.key, network.label) for network in NETWORKS]


def detect(text: str) -> list[str]:
    """Які мережі згадані у фразі."""
    low = (text or "").lower()
    found: list[str] = []
    markers = {
        "telegram": ("telegram", "телеграм", "телеґрам", "телега"),
        "x": ("twitter", "твіт", "твит", " x ", "у x", "в x"),
        "facebook": ("facebook", "фейсбук", "фесбук"),
        "mastodon": ("mastodon", "мастодон"),
        "discord": ("discord", "діскорд", "дискорд"),
    }
    for key, words in markers.items():
        if any(word in low for word in words):
            found.append(key)
    return found


def limit_for(key: str) -> int:
    network = get(key)
    return network.limit if network else 0


def values_from_settings(settings: Any, key: str) -> dict[str, str]:
    """Дістати збережені значення (спершу налаштування, потім середовище)."""
    network = get(key)
    if network is None:
        return {}
    stored = {}
    social = getattr(settings, "social", None)
    if social is not None:
        accounts = getattr(social, "accounts", {}) or {}
        entry = accounts.get(key) or {}
        if isinstance(entry, dict):
            stored = {name: str(value) for name, value in entry.items() if value}
    env_names = ENV_MAP.get(key, {})
    for field_name in [name for name, _label, _hint in network.fields]:
        if not stored.get(field_name) and env_names.get(field_name):
            value = os.environ.get(env_names[field_name], "").strip()
            if value:
                stored[field_name] = value
    return stored


def missing_fields(settings: Any, key: str) -> list[str]:
    """Яких полів бракує для публікації."""
    network = get(key)
    if network is None:
        return []
    values = values_from_settings(settings, key)
    return [label for name, label, _hint in network.fields if not values.get(name)]


def is_configured(settings: Any, key: str) -> bool:
    return not missing_fields(settings, key)


def configured_networks(settings: Any) -> list[str]:
    """Перелік мереж, готових до публікації."""
    return [network.key for network in NETWORKS if is_configured(settings, network.key)]


def setup_hint(settings: Any, key: str) -> str:
    """Що саме сказати користувачу, якщо мережа не налаштована."""
    network = get(key)
    if network is None:
        return f"Невідома мережа «{key}»."
    missing = missing_fields(settings, key)
    if not missing:
        return f"{network.label} готова до публікації."
    return (f"{network.label}: не заповнено {', '.join(missing)}. "
            f"Відкрий Налаштування → Соцмережі. {network.how}")


# ─────────────────────────────────────────────────────────────────────────────
# Публікація
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PublishResult:
    """Результат публікації в одну мережу."""

    network: str
    ok: bool
    detail: str = ""
    url: str = ""
    status: int = 0

    @property
    def label(self) -> str:
        network = get(self.network)
        return network.label if network else self.network


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str],
               timeout: float = 30.0) -> tuple[bool, int, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json; charset=utf-8")
    request.add_header("User-Agent", "BlackChpokIDE/1.2")
    for name, value in headers.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4000).decode("utf-8", errors="replace")
            return True, response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read(1200).decode("utf-8", errors="replace")
        return False, exc.code, body
    except urllib.error.URLError as exc:
        return False, 0, f"немає з'єднання: {exc.reason}"
    except (TimeoutError, OSError) as exc:
        return False, 0, f"помилка мережі: {exc}"


def publish(network_key: str, text: str, settings: Any, *,
            dry_run: bool = False) -> PublishResult:
    """Опублікувати текст у мережу. Ніколи не кидає винятків."""
    network = get(network_key)
    if network is None:
        return PublishResult(network_key, False, f"Невідома мережа «{network_key}».")
    body = (text or "").strip()
    if not body:
        return PublishResult(network_key, False, "Порожній текст поста.")
    if network.limit and len(body) > network.limit:
        body = body[: network.limit - 1].rstrip() + "…"
    values = values_from_settings(settings, network_key)
    missing = [label for name, label, _hint in network.fields if not values.get(name)]
    if missing:
        return PublishResult(network_key, False,
                             f"Не заповнено: {', '.join(missing)}. "
                             f"Налаштування → Соцмережі.")
    if dry_run:
        return PublishResult(network_key, True,
                             f"Чернетка ({len(body)} симв.) — публікацію вимкнено.")

    if network_key == "telegram":
        url = f"https://api.telegram.org/bot{values['token']}/sendMessage"
        ok, status, resp = _post_json(url, {"chat_id": values["chat"], "text": body}, {})
        link = ""
        if ok:
            try:
                data = json.loads(resp)
                chat = data.get("result", {}).get("chat", {})
                username = chat.get("username") or ""
                message_id = data.get("result", {}).get("message_id")
                if username:
                    link = f"https://t.me/{username}/{message_id}"
            except (json.JSONDecodeError, AttributeError):
                link = ""
        return PublishResult(network_key, ok, _clean(resp), link, status)

    if network_key == "x":
        ok, status, resp = _post_json(
            "https://api.twitter.com/2/tweets", {"text": body},
            {"Authorization": f"Bearer {values['token']}"})
        link = ""
        if ok:
            try:
                tweet_id = json.loads(resp).get("data", {}).get("id", "")
                link = f"https://x.com/i/status/{tweet_id}" if tweet_id else ""
            except (json.JSONDecodeError, AttributeError):
                link = ""
        return PublishResult(network_key, ok, _clean(resp), link, status)

    if network_key == "facebook":
        page = urllib.parse.quote(values["page"])
        url = f"https://graph.facebook.com/v21.0/{page}/feed"
        ok, status, resp = _post_json(
            url, {"message": body, "access_token": values["token"]}, {})
        return PublishResult(network_key, ok, _clean(resp), "", status)

    if network_key == "mastodon":
        base = values["base"].rstrip("/")
        ok, status, resp = _post_json(
            f"{base}/api/v1/statuses", {"status": body, "visibility": "public"},
            {"Authorization": f"Bearer {values['token']}"})
        link = ""
        if ok:
            try:
                link = json.loads(resp).get("url", "")
            except (json.JSONDecodeError, AttributeError):
                link = ""
        return PublishResult(network_key, ok, _clean(resp), link, status)

    if network_key == "discord":
        ok, status, resp = _post_json(values["webhook"], {"content": body}, {})
        return PublishResult(network_key, ok, _clean(resp or "надіслано"), "", status)

    return PublishResult(network_key, False, "Публікація для цієї мережі не реалізована.")


def _clean(raw: str) -> str:
    """Скоротити відповідь сервісу до читабельного вигляду."""
    text = (raw or "").strip().replace("\n", " ")
    if len(text) > 300:
        text = text[:300] + "…"
    return text


def publish_many(network_keys: list[str], text: str, settings: Any,
                 *, dry_run: bool = False) -> list[PublishResult]:
    """Опублікувати в кілька мереж поспіль."""
    seen: set[str] = set()
    results: list[PublishResult] = []
    for key in network_keys:
        if key in seen:
            continue
        seen.add(key)
        results.append(publish(key, text, settings, dry_run=dry_run))
    return results


def summary_text(results: list[PublishResult]) -> str:
    """Підсумок для чату."""
    if not results:
        return "Немає мереж для публікації."
    lines: list[str] = []
    for result in results:
        if result.ok:
            line = f"✓ {result.label}: опубліковано"
            if result.url:
                line += f" — {result.url}"
            lines.append(line)
        else:
            lines.append(f"✗ {result.label}: {result.detail}")
    return "\n".join(lines)


def tool_schemas() -> list[dict[str, Any]]:
    """Схема інструмента для моделі — щоб агент умів постити з розмови."""
    return [
        {
            "type": "function",
            "function": {
                "name": "publish_social",
                "description": (
                    "Опублікувати пост у соціальній мережі. Використовуй, коли "
                    "користувач просить опублікувати/викласти/запостити текст. "
                    "Мережі: telegram, x, facebook, mastodon, discord."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Текст поста"},
                        "network": {
                            "type": "string",
                            "description": "Мережа: telegram, x, facebook, mastodon, discord",
                        },
                    },
                    "required": ["text"],
                },
            },
        },
    ]


def catalogue_text(settings: Any) -> str:
    """Що доступно для публікації — для системного промпта."""
    ready = configured_networks(settings)
    if not ready:
        return ("Публікація в соцмережі недоступна: у Налаштуваннях → Соцмережі "
                "не заповнено жодного акаунта.")
    labels = [label_for(key) for key in ready]
    return "Готові до публікації: " + ", ".join(labels)


def label_for(key: str) -> str:
    network = get(key)
    return network.label if network else (key or "—")


__all__ = [
    "ENV_MAP",
    "NETWORKS",
    "Network",
    "PublishResult",
    "catalogue_text",
    "configured_networks",
    "detect",
    "get",
    "is_configured",
    "label_for",
    "limit_for",
    "missing_fields",
    "network_labels",
    "publish",
    "publish_many",
    "setup_hint",
    "summary_text",
    "tool_schemas",
    "values_from_settings",
]
