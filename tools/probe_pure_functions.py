"""Прокинути чисті (без-GUI) функції пакета на граничних входах.

Ідея: узяти публічні функції модулів, які нічого не малюють, і викликати їх
з «поганими» аргументами того ж типу, що заявлено в анотації (``""``,
``None``, кирилиця, дуже довгий рядок). Справжній дефект — це НЕ
контрольований виняток, а необроблений ``AttributeError``/``NameError``/
``IndexError``/``KeyError``, який у застосунку виглядає як «нічого не
сталось».

Функції, які чекають об'єкт (``Path``, ``list``, моделі даних), не
смикаємо рядком: це була б перевірка не коду, а нашої фантазії.

Запуск: ``python tools/probe_pure_functions.py`` — код виходу 1, якщо є
неконтрольовані падіння.
"""

from __future__ import annotations

import importlib
import inspect
import pathlib
import pkgutil
import sys
import traceback

# ── Корінь проєкту в ``sys.path`` ─────────────────────────────────────────
# Без цього скрипт працює ЛИШЕ коли запущений з кореня проєкту:
# ``ModuleNotFoundError: No module named 'blackchpok_ide'`` (перевірено).
# Той самий пропуск був і в ``audit_exports.py``.
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import blackchpok_ide as package  # noqa: E402

#: Модулі, які чіпають GUI, мережу, модель або диск — їх перевіряють інші
#: інструменти (``smoke_widgets.py``, ``smoke_modules.py``).
SKIP = {
    "blackchpok_ide.main_window", "blackchpok_ide.theme", "blackchpok_ide.widgets",
    "blackchpok_ide.chat_panel", "blackchpok_ide.settings_dialog", "blackchpok_ide.cdp",
    "blackchpok_ide.internet", "blackchpok_ide.browser_panel", "blackchpok_ide.model_hub",
    "blackchpok_ide.runtime", "blackchpok_ide.llm_client", "blackchpok_ide.agent",
    "blackchpok_ide.hardware", "blackchpok_ide.native", "blackchpok_ide.voice",
    "blackchpok_ide.voice_panel", "blackchpok_ide.social", "blackchpok_ide.cloud_agents",
    "blackchpok_ide.first_run", "blackchpok_ide.bench", "blackchpok_ide.diagnostics",
    "blackchpok_ide.screenshot", "blackchpok_ide.imaging", "blackchpok_ide.auto_setup",
    "blackchpok_ide.env_setup", "blackchpok_ide.workspace", "blackchpok_ide.pcmm",
    # Ці модулі на першому ж виклику піднімають рушій або читають налаштування:
    # перевіряти їх «синтетичним рядком» недоречно й дорого (завантаження
    # моделі у VRAM під час аналізу).
    "blackchpok_ide.providers", "blackchpok_ide.hmr", "blackchpok_ide.model_verify",
    "blackchpok_ide.model_hub_panel", "blackchpok_ide.runtime_panel",
    "blackchpok_ide.native.engine", "blackchpok_ide.native.manager",
    "blackchpok_ide.native.api", "blackchpok_ide.native.bridge",
}

#: Тексти, на яких функції обробки рядків найчастіше ламаються.
SAMPLE_TEXTS = ("", "   ", "файл.py", "a" * 5000, "))((")

#: Анотації, які позначають «це текст», а не об'єкт.
TEXTY = {"str", "str | None", "Optional[str]", "Any", "_T", "object", ""}


def _text_params(signature: inspect.Signature) -> list[inspect.Parameter]:
    """Обов'язкові параметри, які справді чекають текст."""
    result: list[inspect.Parameter] = []
    for param in signature.parameters.values():
        if param.kind not in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD,
                              param.KEYWORD_ONLY):
            continue
        if param.default is not inspect.Parameter.empty:
            continue
        if str(param.annotation) not in TEXTY:
            return []            # тип не текстовий — перевірка була б хибною
        result.append(param)
    return result


def main() -> int:
    crashes = 0
    calls = 0
    for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        if info.name in SKIP or info.ispkg:
            continue
        try:
            module = importlib.import_module(info.name)
        except Exception:                                   # noqa: BLE001
            continue
        for name, func in vars(module).items():
            if name.startswith("_") or not inspect.isfunction(func):
                continue
            if func.__module__ != info.name:
                continue
            try:
                signature = inspect.signature(func)
            except (TypeError, ValueError):
                continue
            params = _text_params(signature)
            if not params or len(params) > 2:
                continue
            for sample in SAMPLE_TEXTS:
                args = {param.name: sample for param in params}
                calls += 1
                try:
                    func(**args)
                except (ValueError, TypeError, OSError, RuntimeError, LookupError,
                        UnicodeError, ZeroDivisionError, NotImplementedError):
                    continue     # контрольована відмова — це нормально
                except Exception as exc:                    # noqa: BLE001
                    print(f"НЕОБРОБЛЕНЕ ПАДІННЯ {info.name}.{name}({sample!r:.16})"
                          f" → {type(exc).__name__}: {exc}")
                    crashes += 1
                    break
    print(f"Викликів: {calls}, необроблених падінь: {crashes}")
    return 1 if crashes else 0


if __name__ == "__main__":
    raise SystemExit(main())
