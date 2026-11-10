"""Інтернет для локального агента: пошук, читання сторінок, документація.

Проблема, яку це вирішує. В IDE агент **не мав доступу до інтернету**:
``search_web`` і ``fetch_url`` існували лише в MCP-сервері (``server.py``),
тобто працювали виключно з підключеним MCP. Без MCP на питання «яка ціна
SOL сьогодні» модель або вигадувала відповідь, або чесно відмовлялась.

Тепер інтернет — вбудована можливість IDE, яка працює завжди й не потребує
жодних налаштувань:

* :func:`search` — агрегований пошук: Wikipedia, DuckDuckGo (миттєві
  відповіді + сторінки), погода (Open-Meteo), курси валют (Frankfurter),
  криптовалюти (CoinGecko);
* :func:`fetch` — завантажити й прочитати довільну сторінку як текст;
* :func:`fetch_json` — отримати JSON з API (для роботи з сервісами);
* :func:`http_request` — довільний запит (POST/PUT/тощо) для тестування API
  користувацького проєкту.

Залежностей немає — лише стандартна бібліотека. Модуль не тягне tkinter і
не робить запитів під час імпорту.
"""

from __future__ import annotations

import html as html_module
import json
import logging
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

LOG = logging.getLogger("blackchpok.internet")

#: Заголовок, під яким IDE представляється сайтам.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0 Safari/537.36 BlackChpokIDE/2.0")

#: Скільки чекати на відповідь (секунди).
DEFAULT_TIMEOUT = 25

#: Максимум символів, які повертаємо моделі (решта — у файл).
DEFAULT_LIMIT = 12_000


class InternetError(RuntimeError):
    """Помилка мережі зі зрозумілим поясненням."""


@dataclass
class Source:
    """Одне джерело інформації."""

    title: str
    url: str = ""
    text: str = ""


@dataclass
class SearchResult:
    """Результат пошуку: кілька джерел + зібраний текст."""

    query: str
    sources: list[Source] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.sources)

    def as_text(self, limit: int = DEFAULT_LIMIT) -> str:
        """Текст для моделі: джерела з посиланнями й коротким змістом."""
        if not self.sources:
            lines = [f"Нічого не знайдено за запитом «{self.query}»."]
            if self.errors:
                lines.append("Причини:")
                lines.extend(f"• {item}" for item in self.errors[:4])
            lines.append(
                "Порада: спробуй коротший запит англійською "
                "або конкретне посилання через fetch_url.")
            return "\n".join(lines)
        blocks = [f"Результати з інтернету для «{self.query}»:"]
        for index, source in enumerate(self.sources, start=1):
            head = f"{index}. {source.title}"
            if source.url:
                head += f"\n   {source.url}"
            blocks.append(head + ("\n   " + source.text.replace("\n", " ")
                                  if source.text else ""))
        blocks.append(
            "\nДжерела вказані посиланнями — посилайся на них у відповіді. "
            "Якщо потрібен повний текст, виклич fetch_url із цим посиланням.")
        return _clip("\n\n".join(blocks), limit)


# ─────────────────────────────────────────────────────────────────────────────
# Низький рівень
# ─────────────────────────────────────────────────────────────────────────────

def _clip(text: str, limit: int = DEFAULT_LIMIT) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit] + f"\n… (обрізано; повний текст — через fetch_url)"


def _open(request: "urllib.request.Request", timeout: int):
    """Відкрити запит, м'яко обходячи проблеми із сертифікатами.

    На Windows без свіжих кореневих сертифікатів або за корпоративного
    проксі стандартна перевірка падає з ``CERTIFICATE_VERIFY_FAILED``.
    Для читання публічної сторінки це не критично, тож робимо один повтор
    без перевірки — і пишемо про це в журнал.
    """
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        insecure = (isinstance(reason, ssl.SSLError)
                    or "CERTIFICATE" in str(reason).upper()
                    or "SSL" in str(reason).upper())
        if not insecure:
            raise InternetError(_network_hint(reason)) from exc
        LOG.info("Сертифікат не пройшов — повторюю без перевірки: %s", reason)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return urllib.request.urlopen(request, timeout=timeout, context=context)


def _network_hint(reason: Any) -> str:
    """Зрозуміле пояснення мережевої помилки (без технічного сміття)."""
    text = str(reason or "").lower()
    if "getaddrinfo" in text or "name or service" in text or "11001" in text:
        return ("Не вдалось знайти адресу — схоже, немає інтернету "
                "або сайт недоступний. Перевір з'єднання.")
    if "timed out" in text or "timeout" in text:
        return "Сайт не відповів вчасно (таймаут). Спробуй ще раз або іншу адресу."
    if "refused" in text or "10061" in text:
        return "З'єднання відхилено — адреса не слухає порт."
    if "403" in text:
        return "Сайт заборонив доступ (403). Спробуй інше джерело."
    return f"Помилка мережі: {reason}"


def http_get(url: str, *, timeout: int = DEFAULT_TIMEOUT,
             limit: int = 500_000) -> tuple[str, int]:
    """GET-запит. Повертає (тіло, HTTP-код)."""
    if not str(url or "").startswith(("http://", "https://")):
        raise InternetError(f"Адреса має починатись із http:// або https://: {url}")
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json,*/*",
        "Accept-Language": "uk,en;q=0.9",
    })
    try:
        with _open(request, timeout) as response:
            body = response.read(limit)
            charset = response.headers.get_content_charset() or "utf-8"
            return body.decode(charset, errors="replace"), int(response.status)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(400).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            detail = ""
        raise InternetError(
            f"HTTP {exc.code} від {url}"
            + (f": {_strip_html(detail)[:200]}" if detail else "")) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise InternetError(f"Таймаут {timeout} с: {url}") from exc


def http_json(url: str, *, timeout: int = DEFAULT_TIMEOUT) -> Any:
    """Отримати JSON з API."""
    body, _code = http_get(url, timeout=timeout, limit=2_000_000)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise InternetError(
            f"Відповідь не JSON: {body[:200]}") from exc


def http_request(url: str, *, method: str = "GET",
                 body: Optional[str | dict] = None,
                 headers: Optional[dict[str, str]] = None,
                 timeout: int = DEFAULT_TIMEOUT) -> str:
    """Довільний HTTP-запит (для тестування API користувацького проєкту).

    Повертає текст: код відповіді, заголовки й тіло. Саме цим агент
    перевіряє, що створений ним бекенд справді відповідає.
    """
    verb = (method or "GET").strip().upper()
    payload: Optional[bytes] = None
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if isinstance(body, dict):
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    elif isinstance(body, str) and body:
        payload = body.encode("utf-8")
        request_headers.setdefault("Content-Type", "text/plain; charset=utf-8")
    for name, value in (headers or {}).items():
        request_headers[str(name)] = str(value)
    request = urllib.request.Request(url, data=payload, method=verb,
                                     headers=request_headers)
    try:
        with _open(request, timeout) as response:
            raw = response.read(400_000).decode("utf-8", errors="replace")
            code = int(response.status)
            reason = getattr(response, "reason", "")
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read(400_000).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        code, reason = int(exc.code), str(exc.reason or "")
    return (f"{verb} {url}\nHTTP {code} {reason}\n\n"
            + _clip(_looks_like_json(raw) and _pretty_json(raw) or raw, 8000)).strip()


def _looks_like_json(text: str) -> bool:
    body = (text or "").strip()
    return bool(body) and body[0] in "[{"


def _pretty_json(text: str) -> str:
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return text


# ─────────────────────────────────────────────────────────────────────────────
# Читання сторінок
# ─────────────────────────────────────────────────────────────────────────────

def _strip_html(raw: str) -> str:
    """HTML → читабельний текст (без скриптів, стилів і розмітки)."""
    text = re.sub(r"(?is)<(script|style|noscript|svg|iframe).*?>.*?</\1>", " ", raw)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    # Блокові теги → переноси, щоб абзаци не злипались.
    text = re.sub(r"(?i)</?(p|div|br|li|tr|h[1-6]|section|article|header|footer)\b[^>]*>",
                  "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _page_title(raw: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    if not match:
        return ""
    return html_module.unescape(re.sub(r"\s+", " ", match.group(1))).strip()[:160]


def fetch(url: str, *, timeout: int = DEFAULT_TIMEOUT,
          limit: int = DEFAULT_LIMIT) -> str:
    """Завантажити сторінку й повернути її як текст."""
    body, code = http_get(url, timeout=timeout)
    if not body.strip():
        return f"Сторінка {url} порожня (HTTP {code})."
    tree = _strip_html(body)
    title = _page_title(body)
    head = f"{title}\n{url}\n\n" if title else f"{url}\n\n"
    if not tree:
        return f"{head}(сторінка без читабельного тексту; HTTP {code})"
    return head + _clip(tree, limit)


# ─────────────────────────────────────────────────────────────────────────────
# Пошук
# ─────────────────────────────────────────────────────────────────────────────

#: Ознаки того, що запит — про погоду.
_WEATHER_WORDS = ("погод", "weather", "температур", "прогноз", "forecast")

#: Ознаки валютного запиту.
_CURRENCY_WORDS = ("курс", "долар", "євро", "валют", "usd", "eur", "грив", "uah")

#: Ознаки крипто-запиту.
_CRYPTO_WORDS = ("бітко", "bitcoin", "btc", "етере", "ethereum", "eth",
                 "крипт", "crypto", "solana", "sol", "toncoin", "cardano",
                 "dogecoin", "ripple", "xrp", "bnb")

#: Відомі криптовалюти: (слова-ознаки, id у CoinGecko, назва).
#:
#: Порядок важливий: «solana» перевіряється РАНІШЕ за «sol», інакше довша
#: назва перехоплюється коротшим збігом.
_CRYPTO_IDS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("бітко", "bitcoin", "btc"), "bitcoin", "Bitcoin"),
    (("етере", "ethereum"), "ethereum", "Ethereum"),
    (("solana",), "solana", "Solana"),
    (("toncoin",), "the-open-network", "Toncoin"),
    (("doge", "доге"), "dogecoin", "Dogecoin"),
    (("cardano",), "cardano", "Cardano"),
    (("ripple", "xrp"), "ripple", "XRP"),
    (("binancecoin",), "binancecoin", "BNB"),
)


def _has_word(query: str, word: str) -> bool:
    """Чи є слово в запиті ЯК ОКРЕМЕ слово (а не частина іншого).

    Просте ``word in query`` для «sol» давало хибні збіги: «sol» входить у
    «solution», «console», «absolute». Через це звичайний текст міг
    вважатись крипто-запитом.
    """
    if not word:
        return False
    # Кирилиця й латиниця — окремі класи: «\w» у Python Unicode-режимі
    # змішує їх, і межа слова визначалась неправильно.
    pattern = r"(?<![A-Za-zА-Яа-яІіЇїЄєҐґ'’\-])" + re.escape(word) + \
              r"(?![A-Za-zА-Яа-яІіЇїЄєҐґ'’\-])"
    return re.search(pattern, query, flags=re.IGNORECASE) is not None


def _place_name(query: str) -> str:
    """Витягти назву міста з фрази про погоду."""
    match = re.search(
        r"(?:погод[ауи]?|weather)\s+(?:в|у|на|in)\s+([\w'’\-]{2,40})",
        query, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _wiki(query: str) -> Optional[Source]:
    """Короткий зміст із Вікіпедії (українською, далі англійською).

    ВАЖЛИВО: Вікіпедія шукає за будь-яким словом і охоче віддає
    нерелевантне (на запит «ціна SOL сьогодні» вона повернула статтю про
    GPT-6). Тому беремо лише те, що справді стосується запиту: заголовок
    або текст має містити хоч одне змістовне слово запиту.
    """
    words = _meaningful_words(query)
    if not words:
        return None
    tried: list[str] = []
    for lang in ("uk", "en"):
        try:
            search_url = (
                f"https://{lang}.wikipedia.org/w/api.php?"
                + urllib.parse.urlencode({
                    "action": "query", "list": "search", "srsearch": query,
                    "utf8": "1", "format": "json", "srlimit": "3",
                }))
            found = http_json(search_url, timeout=15)
            hits = ((found.get("query") or {}).get("search") or [])
            for hit in hits[:3]:
                title = str(hit.get("title") or "")
                if not title:
                    continue
                tried.append(title)
                # Релевантність перевіряємо ЗА НАЗВОЮ статті, а не за
                # фрагментом: Вікіпедія на «ціна SOL сьогодні» віддавала
                # статтю «GPT-6», бо в її тексті теж є слово «сьогодні».
                if not _title_matches(title, words):
                    LOG.debug("Вікіпедія: «%s» не стосується запиту", title)
                    continue
                summary = http_json(
                    f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
                    + urllib.parse.quote(title.replace(" ", "_")), timeout=15)
                extract = str(summary.get("extract") or "").strip()
                page = ((summary.get("content_urls") or {}).get("desktop") or {}).get("page") or ""
                if extract:
                    return Source(f"Вікіпедія ({lang}): {title}", page, extract[:900])
        except (InternetError, KeyError, TypeError):
            continue
    if tried:
        LOG.debug("Вікіпедія: жодна стаття не відповідає запиту (%s)", tried[:3])
    return None


def _title_matches(title: str, words: list[str]) -> bool:
    """Чи стосується назва статті запиту.

    Враховуємо основу слова: «солана» має збігтись із «Solana», а «sol» —
    із «Solana». Порівнюємо перші 4 символи, щоб не залежати від відмінків
    і транслітерації.
    """
    clean = (title or "").lower()
    for word in words:
        stem = word[:4]
        if len(stem) >= 3 and stem in clean:
            return True
    return False


#: Слова, які не несуть змісту (для перевірки релевантності).
_STOP_WORDS = frozenset({
    "яка", "який", "яке", "які", "що", "це", "як", "чи", "де", "коли",
    "сьогодні", "зараз", "будь", "ласка", "мені", "треба", "хочу",
    "ціна", "курс", "скільки", "коштує", "знайди", "покажи", "скажи",
    "the", "what", "is", "how", "much", "price", "today", "now", "a", "an",
    "please", "find", "show", "tell", "me",
})


def _meaningful_words(query: str) -> list[str]:
    """Змістовні слова запиту (без питань і службових слів)."""
    words = re.findall(r"[\w'’\-]{2,}", (query or "").lower())
    return [word for word in words if word not in _STOP_WORDS][:6]


def _ddg_instant(query: str) -> Optional[Source]:
    """Миттєва відповідь DuckDuckGo (факти, визначення)."""
    try:
        data = http_json("https://api.duckduckgo.com/?" + urllib.parse.urlencode({
            "q": query, "format": "json", "no_html": "1", "skip_disambig": "1",
        }), timeout=15)
    except InternetError:
        return None
    text = str(data.get("AbstractText") or data.get("Answer") or "").strip()
    if not text:
        return None
    heading = str(data.get("Heading") or "DuckDuckGo").strip()
    return Source(f"DuckDuckGo: {heading}", str(data.get("AbstractURL") or ""), text[:600])


def _ddg_pages(query: str, *, limit: int = 5) -> list[Source]:
    """Результати пошуку DuckDuckGo (HTML-версія — без ключа й без JS)."""
    try:
        raw, _code = http_get(
            "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query),
            timeout=20)
    except InternetError:
        return []
    links = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        raw, flags=re.IGNORECASE | re.DOTALL)
    if not links:
        links = re.findall(
            r'<a[^>]*href="([^"]+)"[^>]*class="result__a"[^>]*>(.*?)</a>',
            raw, flags=re.IGNORECASE | re.DOTALL)
    snippets = re.findall(
        r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>',
        raw, flags=re.IGNORECASE | re.DOTALL)
    found: list[Source] = []
    for index, (href, title_html) in enumerate(links[:limit]):
        title = _strip_html(title_html)
        if not title:
            continue
        url = href
        parsed = urllib.parse.urlparse(href)
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [])
        if target:
            url = urllib.parse.unquote(target[0])
        snippet = _strip_html(snippets[index]) if index < len(snippets) else ""
        found.append(Source(title, url, snippet[:400]))
    return found


#: Міста у називному відмінку: геокодер Open-Meteo приймає ЛИШЕ таку форму.
#: «Києві» й «Львові» він не знаходить зовсім (перевірено), а простого
#: відрізання останньої літери не досить: «Києві» → «Києв», а треба «Київ».
_CITY_FORMS: dict[str, str] = {
    "києві": "Київ", "києва": "Київ", "київ": "Київ", "киев": "Київ",
    "львові": "Львів", "львова": "Львів", "львів": "Львів",
    "одесі": "Одеса", "одеси": "Одеса", "одеса": "Одеса",
    "харкові": "Харків", "харкова": "Харків", "харків": "Харків",
    "дніпрі": "Дніпро", "дніпра": "Дніпро", "дніпро": "Дніпро",
    "вінниці": "Вінниця", "вінниця": "Вінниця",
    "полтаві": "Полтава", "полтава": "Полтава",
    "чернівцях": "Чернівці", "чернівці": "Чернівці",
    "ужгороді": "Ужгород", "ужгород": "Ужгород",
    "запоріжжі": "Запоріжжя", "запоріжжя": "Запоріжжя",
    "миколаєві": "Миколаїв", "миколаїв": "Миколаїв",
    "сумах": "Суми", "суми": "Суми",
    "рівному": "Рівне", "рівне": "Рівне",
    "тернополі": "Тернопіль", "тернопіль": "Тернопіль",
    "івано-франківську": "Івано-Франківськ",
    "івано-франківськ": "Івано-Франківськ",
    "житомирі": "Житомир", "житомир": "Житомир",
    "черкасах": "Черкаси", "черкаси": "Черкаси",
    "херсоні": "Херсон", "херсон": "Херсон",
    "кропивницькому": "Кропивницький", "кропивницький": "Кропивницький",
    "chernivtsi": "Чернівці", "kyiv": "Київ", "kiev": "Київ",
    "lviv": "Львів", "odesa": "Одеса", "odessa": "Одеса",
    "kharkiv": "Харків", "dnipro": "Дніпро", "london": "London",
    "warsaw": "Warsaw", "berlin": "Berlin", "paris": "Paris",
}


def _city_query(place: str) -> str:
    """Привести назву міста до форми, яку приймає геокодер."""
    clean = (place or "").strip()
    if not clean:
        return ""
    return _CITY_FORMS.get(clean.lower(), clean)


def _weather(query: str) -> Optional[Source]:
    """Поточна погода через Open-Meteo (без ключа)."""
    if not any(word in query.lower() for word in _WEATHER_WORDS):
        return None
    place = _place_name(query) or "Київ"
    candidates = []
    normalised = _city_query(place)
    if normalised:
        candidates.append(normalised)
    if place not in candidates:
        candidates.append(place)
    city: Optional[dict] = None
    for candidate in candidates:
        try:
            geo = http_json(
                "https://geocoding-api.open-meteo.com/v1/search?"
                + urllib.parse.urlencode({"name": candidate, "count": "6",
                                          "language": "uk"}), timeout=15)
        except InternetError:
            continue
        results = [row for row in (geo.get("results") or [])
                   if isinstance(row, dict)]
        if not results:
            continue
        # Обираємо НАЙБІЛЬШЕ місто, а не перше-ліпше: на запит «погода в
        # Києві» першим приходило «Киево-Александровское» (село), а не
        # столиця. Сортуємо за населенням.
        results.sort(key=lambda row: int(row.get("population") or 0),
                     reverse=True)
        city = results[0]
        break
    if not city:
        return None
    try:
        forecast = http_json(
            "https://api.open-meteo.com/v1/forecast?"
            + urllib.parse.urlencode({
                "latitude": city["latitude"],
                "longitude": city["longitude"],
                "current": "temperature_2m,wind_speed_10m,weather_code",
                "timezone": "auto",
            }), timeout=15)
    except InternetError:
        return None
    current = forecast.get("current") or {}
    sky = {0: "ясно", 1: "переважно ясно", 2: "мінлива хмарність", 3: "хмарно",
           45: "туман", 48: "туман", 51: "мряка", 61: "дощ", 63: "дощ",
           71: "сніг", 73: "сніг", 80: "злива", 95: "гроза"}.get(
               int(current.get("weather_code") or -1), "змінна погода")
    name = city.get("name") or place
    country = city.get("country") or ""
    return Source(
        f"Погода: {name}, {country}".strip(", "),
        "https://open-meteo.com/",
        f"{current.get('temperature_2m')}°C, {sky}, "
        f"вітер {current.get('wind_speed_10m')} км/год.")


def _crypto_marker(query: str) -> Optional[tuple[str, str]]:
    """Знайти монету в запиті: (id, назва) або ``None``.

    Правила навмисно СУВОРІ, щоб не було хибних спрацювань:

    * короткі тикери (``sol``, ``eth``, ``btc``, ``ton``, ``xrp``, ``bnb``)
      зараховуються лише ЯК ОКРЕМЕ СЛОВО у верхньому регістрі або поруч зі
      словом «ціна/курс/скільки». Інакше «solution», «console», «Python»
      перетворювались на запит про криптовалюту;
    * повні назви (``solana``, ``bitcoin``…) — як підрядок, це безпечно;
    * мається на увазі ціна, якщо у фразі є ціна/курс/скільки/коштує.
    """
    low = query.lower()
    #: Чи це взагалі про гроші.
    about_price = any(word in low for word in
                      ("цін", "курс", "скільк", "кошту", "price", "cost",
                       "вартіст", "капітал"))
    #: Короткі тикери: лише окремим словом.
    short_tickers = {
        "sol": ("solana", "Solana"),
        "eth": ("ethereum", "Ethereum"),
        "btc": ("bitcoin", "Bitcoin"),
        "ton": ("the-open-network", "Toncoin"),
        "xrp": ("ripple", "XRP"),
        "bnb": ("binancecoin", "BNB"),
        "doge": ("dogecoin", "Dogecoin"),
    }
    #: Повні назви: підрядок безпечний.
    long_names = (
        (("solana",), "solana", "Solana"),
        (("бітко", "bitcoin"), "bitcoin", "Bitcoin"),
        (("етере", "ethereum"), "ethereum", "Ethereum"),
        (("toncoin",), "the-open-network", "Toncoin"),
        (("dogecoin", "доге"), "dogecoin", "Dogecoin"),
        (("cardano",), "cardano", "Cardano"),
        (("ripple",), "ripple", "XRP"),
        (("binancecoin",), "binancecoin", "BNB"),
    )
    # 1. Повні назви — найнадійніше.
    for words, identifier, name in long_names:
        if any(word in low for word in words):
            return identifier, name
    # 2. Короткі тикери — лише окремим словом І з контекстом ціни.
    for ticker, (identifier, name) in short_tickers.items():
        if not _has_word(low, ticker):
            continue
        if not about_price:
            continue
        # Тикер має бути в оригінальному запиті великими літерами
        # («SOL», «TON») — так його пишуть люди, і це знімає хибні збіги
        # зі звичайними словами на кшталт «sol» у «solution».
        upper = re.search(
            r"(?<![A-Za-zА-Яа-яІіЇїЄєҐґ'’\-])" + ticker.upper()
            + r"(?![A-Za-zА-Яа-яІіЇїЄєҐґ'’\-])", query)
        if upper:
            return identifier, name
    return None


def _crypto(query: str) -> Optional[Source]:
    """Курс криптовалюти в USD/UAH через CoinGecko (без ключа)."""
    found = _crypto_marker(query)
    if found is None:
        return None
    coin_id, label = found
    try:
        data = http_json(
            "https://api.coingecko.com/api/v3/simple/price?"
            + urllib.parse.urlencode({
                "ids": coin_id, "vs_currencies": "usd,uah",
                "include_24hr_change": "true",
                "include_last_updated_at": "true",
            }), timeout=20)
    except InternetError:
        return None
    row = (data or {}).get(coin_id) or {}
    if not row:
        return None
    usd = row.get("usd")
    uah = row.get("uah")
    change = row.get("usd_24h_change")
    parts = [f"1 {label} = {usd} USD" if usd is not None else f"{label}: ціна недоступна"]
    if uah is not None:
        parts.append(f"≈ {uah} UAH")
    if change is not None:
        parts.append(f"за 24 год: {float(change):+.2f}%")
    stamp = row.get("last_updated_at")
    if stamp:
        parts.append("оновлено " + time.strftime(
            "%d.%m.%Y %H:%M UTC", time.gmtime(float(stamp))))
    return Source(f"Ціна {label} (CoinGecko)",
                  f"https://www.coingecko.com/en/coins/{coin_id}",
                  ", ".join(parts))


def _currency(query: str) -> Optional[Source]:
    """Курс валют через Frankfurter (без ключа).

    Frankfurter не має гривні в базовому наборі, тож ``UAH`` приходив як
    ``None`` — і модель отримувала безглузде «1 USD = None UAH». Тепер
    запитуємо кілька валют і показуємо ЛИШЕ ті, що справді прийшли.
    """
    if not any(word in query.lower() for word in _CURRENCY_WORDS):
        return None
    try:
        data = http_json("https://api.frankfurter.app/latest?from=USD&to=EUR,PLN,GBP",
                         timeout=15)
    except InternetError:
        return None
    rates = {name: value for name, value in (data.get("rates") or {}).items()
             if value is not None}
    if not rates:
        return None
    parts = [f"1 USD = {value} {name}" for name, value in rates.items()]
    detail = ", ".join(parts)
    # Гривню беремо з іншого відкритого джерела — вона потрібна найчастіше.
    uah = _uah_rate()
    if uah is not None:
        detail = f"1 USD = {uah} UAH; " + detail
    return Source(f"Курс валют (Frankfurter, {data.get('date')})",
                  "https://www.frankfurter.app/", detail + ".")


def _uah_rate() -> Optional[float]:
    """Курс USD→UAH з відкритого API Національного банку."""
    try:
        data = http_json(
            "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
            "?valcode=USD&json", timeout=15)
    except InternetError:
        return None
    if isinstance(data, list) and data:
        try:
            return float(data[0].get("rate"))
        except (TypeError, ValueError, AttributeError):
            return None
    return None


def search(query: str, *, timeout: int = DEFAULT_TIMEOUT,
           include_pages: bool = True) -> SearchResult:
    """Пошук в інтернеті: агрегує кілька незалежних джерел.

    Порядок навмисний: спершу швидкі фактичні сервіси (ціна, погода,
    курс), потім енциклопедія, потім загальні сторінки. Так модель
    отримує найкорисніше першим.
    """
    clean = (query or "").strip()
    result = SearchResult(query=clean)
    if not clean:
        result.errors.append("порожній запит")
        return result

    # 1. Точні факти: криптовалюта, погода, курси.
    for probe in (_crypto, _weather, _currency):
        try:
            source = probe(clean)
        except Exception as exc:  # noqa: BLE001 - одне джерело не має валити пошук
            LOG.debug("Джерело %s впало", probe.__name__, exc_info=True)
            result.errors.append(f"{probe.__name__}: {type(exc).__name__}")
            continue
        if source is not None:
            result.sources.append(source)

    # 2. Енциклопедія.
    try:
        wiki = _wiki(clean)
    except Exception:  # noqa: BLE001
        wiki = None
        LOG.debug("Вікіпедія недоступна", exc_info=True)
    if wiki is not None:
        result.sources.append(wiki)

    # 3. Миттєва відповідь.
    try:
        instant = _ddg_instant(clean)
    except Exception:  # noqa: BLE001
        instant = None
    if instant is not None:
        result.sources.append(instant)

    # 4. Загальні сторінки (найдовше — тому останніми).
    if include_pages:
        try:
            for source in _ddg_pages(clean):
                result.sources.append(source)
        except Exception:  # noqa: BLE001
            LOG.debug("DuckDuckGo недоступний", exc_info=True)

    if not result.sources and not result.errors:
        result.errors.append("сервіси нічого не повернули")
    return result


def connectivity() -> tuple[bool, str]:
    """Швидка перевірка, чи є інтернет (для панелі стану)."""
    checks = (
        ("https://api.duckduckgo.com/?q=test&format=json", "DuckDuckGo"),
        ("https://www.wikipedia.org/", "Wikipedia"),
    )
    for url, label in checks:
        try:
            _body, code = http_get(url, timeout=8, limit=2000)
            if 200 <= code < 400:
                return True, f"Інтернет доступний ({label})"
        except InternetError as exc:
            last = str(exc)
            continue
    return False, (f"Немає доступу до інтернету. {last}"
                   if 'last' in dir() else "Немає доступу до інтернету.")


__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_TIMEOUT",
    "InternetError",
    "SearchResult",
    "Source",
    "USER_AGENT",
    "connectivity",
    "fetch",
    "http_get",
    "http_json",
    "http_request",
    "search",
]
