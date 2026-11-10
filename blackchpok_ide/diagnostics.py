"""Самодіагностика IDE: чому модель не працює — однією відповіддю.

Навіщо окремий модуль. Користувач бачив «Локальна модель зараз
недоступна» і не міг зрозуміти причину. У реальному лозі рушій працював на
порті **8081** (бо 8080 тримав Steam), а клієнт слал запити на **8080** —
тобто модель ПРАЦЮВАЛА, а програма цього не бачила.

Діагностика перевіряє ланцюг по порядку й показує, на якій ланці обрив:

1. **рушій** — чи встановлено llama-server;
2. **модель** — чи вибрано GGUF і чи існує файл;
3. **порт** — чи слухає хтось налаштований порт і ЧИ ЦЕ НАШ сервер
   (Steam на 8080 теж «слухає», але відповідає 404);
4. **живі порти** — які порти рушіїв ми записали під час запуску;
5. **ключ** — чи збігається API-ключ клієнта з ключем сервера;
6. **відповідь** — реальний запит до моделі (найважливіше: «працює» без
   відповіді на запит — це не «працює»).

Модуль не залежить від tkinter: результат — це список рядків, який
інтерфейс показує як є, а користувач може скопіювати.
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

LOG = logging.getLogger("blackchpok.diagnostics")

PASS = "OK"
WARN = "УВАГА"
FAIL = "ЗБІЙ"
SKIP = "—"


@dataclass
class Check:
    """Один крок діагностики."""

    name: str
    status: str = SKIP
    detail: str = ""
    #: Що зробити, якщо крок не пройдено.
    fix: str = ""

    @property
    def ok(self) -> bool:
        return self.status == PASS

    @property
    def failed(self) -> bool:
        return self.status == FAIL

    def line(self) -> str:
        mark = {PASS: "✓", WARN: "!", FAIL: "✗"}.get(self.status, "·")
        text = f"{mark} {self.status:<5} {self.name}"
        if self.detail:
            text += f" — {self.detail}"
        return text


@dataclass
class Report:
    """Підсумок самодіагностики."""

    checks: list[Check] = field(default_factory=list)
    #: Готова адреса, яку знайшла діагностика (порожня — не знайдено).
    working_url: str = ""
    #: Головний висновок людською мовою.
    verdict: str = ""
    #: Хвіст логу рушія (останні рядки) — найкорисніше для відладки.
    engine_log: str = ""

    @property
    def failures(self) -> list[Check]:
        return [item for item in self.checks if item.failed]

    @property
    def ok(self) -> bool:
        return not self.failures

    def text(self) -> str:
        lines = ["САМОДІАГНОСТИКА BLACKCHPOK IDE", ""]
        lines.extend(item.line() for item in self.checks)
        if self.engine_log:
            lines += ["", "ЛОГ РУШІЯ (останні рядки):", self.engine_log]
        if self.verdict:
            lines += ["", "ВИСНОВОК:", self.verdict]
        failed = self.failures
        if failed:
            lines += ["", "ЩО ЗРОБИТИ:"]
            for item in failed:
                if item.fix:
                    lines.append(f"  • {item.name}: {item.fix}")
        return "\n".join(lines)


def _port_in(url: str) -> int:
    import re

    match = re.search(r":(\d{2,5})(?:/|$)", str(url or ""))
    return int(match.group(1)) if match else 0


def _who_listens(port: int) -> str:
    """Ім'я процесу, який слухає порт (Windows) — щоб побачити «це Steam».

    Без цього «порт зайнятий» нічого не пояснює: користувач не знає, що
    8080 тримає стороння програма.
    """
    if not port:
        return ""
    try:
        import subprocess

        completed = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    pid = ""
    for line in (completed.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local, state, owning = parts[1], parts[3], parts[4]
        if state.upper() != "LISTENING":
            continue
        if local.rsplit(":", 1)[-1] == str(port):
            pid = owning
            break
    if not pid:
        return ""
    try:
        import subprocess

        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        first = (result.stdout or "").strip().splitlines()
        if first:
            name = first[0].split(",")[0].strip('"')
            return f"{name} (pid {pid})"
    except (OSError, subprocess.SubprocessError):
        pass
    return f"pid {pid}"


def run(*, settings: Any, engine_log_tail: Callable[[int], str] | None = None,
        probe_inference: bool = True,
        timeout: float = 3.0) -> Report:
    """Виконати повну перевірку й повернути звіт.

    ``settings`` — живі налаштування IDE (:class:`config.Settings`).
    ``engine_log_tail`` — функція, що повертає хвіст логу рушія.
    ``probe_inference`` — чи робити РЕАЛЬНИЙ запит до моделі (повільніше,
    але саме він доводить, що модель відповідає).
    """
    from . import runtime

    report = Report()
    llm = getattr(settings, "llm", None)
    engine = getattr(settings, "engine", None)
    configured = str(getattr(llm, "base_url", "") or "")
    model = str(getattr(llm, "model", "") or "")
    api_key = str(getattr(llm, "api_key", "") or "")
    port = _port_in(configured)

    # 1. Рушій ──────────────────────────────────────────────────────────────
    try:
        installed = runtime.engine_installed()
    except Exception as exc:  # noqa: BLE001
        installed = False
        report.checks.append(Check("Рушій llama.cpp", FAIL,
                                   f"перевірка не вдалась: {exc}",
                                   "перевстанови рушій у «Хабі моделей»"))
    else:
        version = ""
        try:
            version = runtime.engine_version()
        except Exception:  # noqa: BLE001
            version = ""
        report.checks.append(Check(
            "Рушій llama.cpp",
            PASS if installed else FAIL,
            f"встановлено{(' ' + version) if version else ''}" if installed
            else "не встановлено",
            "" if installed else "відкрий «Хаб моделей» → «Встановити рушій»"))

    # 2. Модель ─────────────────────────────────────────────────────────────
    model_path = str(getattr(engine, "model_path", "") or "")
    path_ok = bool(model_path) and Path(model_path).exists()
    report.checks.append(Check(
        "Файл моделі",
        PASS if path_ok else FAIL,
        (f"{Path(model_path).name} "
         f"({Path(model_path).stat().st_size / 2**30:.1f} ГБ)") if path_ok
        else (f"немає файлу: {model_path}" if model_path else "модель не вибрано"),
        "" if path_ok else "вибери модель у «Хабі моделей»"))

    # 3. Налаштований порт ──────────────────────────────────────────────────
    busy = False
    try:
        busy = runtime.port_is_busy(port) if port else False
    except Exception:  # noqa: BLE001
        busy = False
    responds = False
    if configured:
        try:
            responds = runtime.server_responds(configured, api_key=api_key)
        except Exception:  # noqa: BLE001
            responds = False
    if responds:
        report.checks.append(Check("Адреса з налаштувань", PASS, configured))
    elif busy:
        owner = _who_listens(port)
        report.checks.append(Check(
            "Адреса з налаштувань", FAIL,
            f"{configured} — порт слухає {owner or 'інша програма'}, "
            f"але це не наш рушій",
            "натисни «Знайти робочий порт» — IDE перемкнеться сама"))
    else:
        report.checks.append(Check(
            "Адреса з налаштувань", FAIL,
            f"{configured or '(порожньо)'} — ніхто не слухає",
            "запусти модель: «Хаб моделей» → «Запустити»"))

    # 4. Живі рушії ─────────────────────────────────────────────────────────
    lives: list[dict[str, Any]] = []
    try:
        lives = runtime.live_server_ports()
    except Exception:  # noqa: BLE001
        lives = []
    if lives:
        described = ", ".join(f"{item['port']} (pid {item['pid']})" for item in lives)
        report.checks.append(Check("Живі рушії", PASS, described))
    else:
        # ── Простій: найчастіша причина «модель не працює» ───────────────
        # Модель вивантажується через простій (це правильно — інакше
        # відеокарта зайнята 24/7). Але раніше вона не піднімалась назад, і
        # після 5 хв паузи КОЖЕН запит падав. Користувач бачив «модель не
        # стартує», хоч вона стартувала. Тепер це видно з діагностики.
        idle_off = not bool(getattr(engine, "unload_when_idle", True))
        detail = ("жодного записаного процесу рушія"
                  if idle_off else
                  "рушій не запущено (можливо, вивантажено через простій — "
                  "підніметься на наступний запит)")
        report.checks.append(Check("Живі рушії", WARN, detail,
                                   "надішли будь-який запит — модель має "
                                   "піднятися сама"))

    # 5. Пошук робочої адреси ───────────────────────────────────────────────
    found = ""
    try:
        found = runtime.discover_server_url(configured, api_key=api_key)
    except Exception:  # noqa: BLE001
        found = ""
    if found:
        same = found.rstrip("/") == configured.rstrip("/")
        report.checks.append(Check(
            "Робочий порт",
            PASS if same else WARN,
            f"{found}" + ("" if same else f" (у налаштуваннях {configured})"),
            "" if same else "натисни «Виправити адресу» — IDE перемкнеться"))
        report.working_url = found
    else:
        report.checks.append(Check(
            "Робочий порт", FAIL, "жоден локальний порт не відповідає",
            "запусти модель; якщо вона вже запущена — подивись лог рушія нижче"))

    # 6. Реальний запит ─────────────────────────────────────────────────────
    if probe_inference and found and model:
        answered, detail = _probe_model(found, model, api_key, timeout=timeout)
        report.checks.append(Check(
            "Відповідь моделі",
            PASS if answered else FAIL,
            detail,
            "" if answered else "перевір лог рушія: можливо, модель не "
                                "завантажилась або контекст завеликий"))
    else:
        report.checks.append(Check(
            "Відповідь моделі", SKIP,
            "пропущено (немає робочої адреси або моделі)"))

    # 7. Лог рушія ──────────────────────────────────────────────────────────
    if engine_log_tail is not None:
        try:
            report.engine_log = engine_log_tail(25)
        except Exception:  # noqa: BLE001
            report.engine_log = ""
    if not report.engine_log:
        try:
            log_path = runtime.runtime_dir() / "server.log"
            if log_path.exists():
                raw = log_path.read_text(encoding="utf-8", errors="replace")
                report.engine_log = "\n".join(raw.splitlines()[-25:])
        except OSError:
            report.engine_log = ""

    report.verdict = _verdict(report, configured, found, model)
    return report


def _probe_model(base_url: str, model: str, api_key: str, *,
                 timeout: float = 3.0) -> tuple[bool, str]:
    """Зробити РЕАЛЬНИЙ запит до моделі й повернути (відповіла, деталь)."""
    import json
    import urllib.error
    import urllib.request

    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Скажи одне слово: тест"}],
        "max_tokens": 8, "temperature": 0.0,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        request = urllib.request.Request(f"{url}/chat/completions",
                                         data=payload, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
        choice = (data.get("choices") or [{}])[0]
        text = str((choice.get("message") or {}).get("content") or "").strip()
        return True, f"«{text[:40]}»"
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return False, ("HTTP 401 — невірний API-ключ. Сервер працює, "
                           "але не приймає ключ клієнта")
        if exc.code == 404:
            return False, ("HTTP 404 — за цією адресою немає /chat/completions "
                           "(ймовірно, це інший сервіс на тому ж порту)")
        return False, f"HTTP {exc.code} {exc.reason}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"запит не пройшов: {exc}"


def _verdict(report: Report, configured: str, found: str, model: str) -> str:
    """Головний висновок людською мовою."""
    failed = {item.name for item in report.failures}
    if not failed:
        if found and found.rstrip("/") != configured.rstrip("/"):
            return (f"Модель працює, але адреса в налаштуваннях застаріла. "
                    f"Робоча: {found}. Натисни «Виправити адресу».")
        return f"Модель «{model}» працює й відповідає на запити."
    if "Рушій llama.cpp" in failed:
        return "Рушій llama.cpp не встановлено — модель запустити неможливо."
    if "Файл моделі" in failed:
        return "Файл моделі відсутній — вибери іншу модель у «Хабі моделей»."
    if "Робочий порт" in failed and "Адреса з налаштувань" in failed:
        return ("Жоден локальний порт не відповідає: рушій не запущено або "
                "він упав під час завантаження. Найчастіше модель просто "
                "вивантажена через простій — надішли будь-який запит, і вона "
                "підніметься сама. Інакше дивись лог рушія нижче.")
    if "Відповідь моделі" in failed:
        return ("Сервер відповідає, але модель не дала відповіді. "
                "Найчастіше це ключ API або завеликий контекст.")
    if found and found.rstrip("/") != configured.rstrip("/"):
        return (f"Адреса з налаштувань неправильна ({configured}), "
                f"але робочий сервер є: {found}. Натисни «Виправити адресу».")
    return "Є проблеми — дивись список вище."


__all__ = ["Check", "FAIL", "PASS", "Report", "SKIP", "WARN", "run"]
