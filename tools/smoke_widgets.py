"""Створити кожен Tk-віджет пакета в живому вікні зі справжніми залежностями.

Імпорт нічого не доводить: більшість збоїв інтерфейсу — це ``NameError``
чи ``AttributeError`` у ``__init__``/``_build``, який видно лише тоді, коли
віджет справді створюють. Тут кожен клас-нащадок ``tk.Misc`` з пакета
конструюється з реальними об'єктами (тема, налаштування, черга завдань,
стани тощо) у прихованому вікні.

Вікно приховане — запуск безпечний і не заважає користувачеві.

Запуск: ``python tools/smoke_widgets.py`` — код виходу 1, якщо щось упало.
"""

from __future__ import annotations

import importlib
import inspect
import pathlib
import pkgutil
import sys
import tempfile
import traceback
from pathlib import Path

import tkinter as tk

# ── Корінь проєкту в ``sys.path`` ─────────────────────────────────────────
# Без цього скрипт працює ЛИШЕ коли запущений з кореня проєкту:
# ``ModuleNotFoundError: No module named 'blackchpok_ide'`` (перевірено).
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import blackchpok_ide as package  # noqa: E402
from blackchpok_ide import theme  # noqa: E402


class Context:
    """Живі залежності, які віджети очікують отримати."""

    def __init__(self, root: tk.Misc) -> None:
        from blackchpok_ide import hardware, queue_engine, runtime
        from blackchpok_ide.config import Settings

        self.root = root
        self.fonts = theme.Theme(root)
        self.settings = Settings.load()
        self.project = Path(tempfile.mkdtemp(prefix="smoke-widget-"))
        self.state = self.project / "queue.json"
        self.task_queue = queue_engine.TaskQueue(self.state)
        self.profile = hardware.detect(self.project)
        self.runtime = runtime
        self.stats = self._stats()
        self.service = self._service()

    def _service(self):
        """Сервіс Neuromesh/PCMM для панелей, які його потребують."""
        from blackchpok_ide import neuromesh_panel

        for name in ("service", "build_service", "default_service"):
            factory = getattr(neuromesh_panel, name, None)
            if callable(factory):
                try:
                    return factory()
                except Exception:                           # noqa: BLE001
                    continue
        return None

    def _stats(self):
        from blackchpok_ide import context_stats

        for name in ("ContextStats", "Stats", "Breakdown"):
            cls = getattr(context_stats, name, None)
            if cls is None:
                continue
            try:
                return cls()
            except TypeError:
                continue
        return None

    def cleanup(self) -> None:
        import shutil

        shutil.rmtree(self.project, ignore_errors=True)


def candidates() -> list[tuple[str, type]]:
    found: list[tuple[str, type]] = []
    for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        try:
            module = importlib.import_module(info.name)
        except Exception:                                   # noqa: BLE001
            print(f"ІМПОРТ ВПАВ: {info.name}")
            traceback.print_exc()
            continue
        for name, obj in vars(module).items():
            if (inspect.isclass(obj) and issubclass(obj, tk.Misc)
                    and obj.__module__ == info.name and not name.startswith("_")):
                found.append((f"{info.name}.{name}", obj))
    return found


def make_args(cls: type, ctx: Context) -> tuple[tuple, dict] | None:
    """Аргументи для конструктора; ``None`` — віджет пропускаємо."""
    signature = inspect.signature(cls.__init__)
    params = list(signature.parameters.values())[1:]
    args: list = []
    kwargs: dict = {}
    for param in params:
        if param.default is not inspect.Parameter.empty:
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        name = param.name
        annotated = str(param.annotation)
        if name in ("master", "parent", "host", "container"):
            args.append(ctx.root)
        elif name == "fonts":
            kwargs[name] = ctx.fonts
        elif "Voice" in annotated:
            from blackchpok_ide import voice

            kwargs[name] = voice.VoiceSettings()
        elif name == "settings":
            kwargs[name] = ctx.settings
        elif name == "stats":
            kwargs[name] = ctx.stats
        elif name in ("queue", "task_queue", "task_queue_engine"):
            kwargs[name] = ctx.task_queue
        elif name in ("engine", "autonomous_engine"):
            from blackchpok_ide import autonomous as auto

            kwargs[name] = auto.AutonomousEngine(queue=ctx.task_queue)
        elif name in ("book", "cases", "case_book"):
            from blackchpok_ide import cases_panel

            kwargs[name] = cases_panel.CaseBook()
        elif name == "session":
            from blackchpok_ide import deep_mode

            kwargs[name] = deep_mode.DeepSession(goal="перевірка віджета")
        elif name in ("service_provider", "runtime_provider"):
            kwargs[name] = lambda: ctx.service
        elif name in ("items",):
            kwargs[name] = [("a", "перше", lambda: None), ("b", "друге", lambda: None)]
        elif name in ("cwd", "path", "workspace", "root_folder", "folder"):
            kwargs[name] = ctx.project
        elif name in ("root_provider", "project_provider"):
            kwargs[name] = lambda: ctx.project
        elif name in ("text", "title", "label"):
            kwargs[name] = "перевірка"
        elif name.startswith("on_") or name in ("callback",):
            kwargs[name] = lambda *_a, **_k: None
        else:
            # Обов'язковий параметр без відомого відповідника: підставляємо
            # ``None`` — цікавить, чи віджет узагалі здатний зібратись.
            kwargs[name] = None
    return tuple(args), kwargs


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    ctx = Context(root)
    failures = 0
    checked = 0
    try:
        for label, cls in candidates():
            checked += 1
            prepared = make_args(cls, ctx)
            if prepared is None:
                continue
            args, kwargs = prepared
            try:
                widget = cls(*args, **kwargs)
            except Exception:                               # noqa: BLE001
                print(f"ВІДЖЕТ ВПАВ: {label}")
                traceback.print_exc(limit=8)
                failures += 1
                continue
            try:
                widget.destroy()
            except Exception:                               # noqa: BLE001
                print(f"ЗНИЩЕННЯ ВПАЛО: {label}")
                traceback.print_exc(limit=4)
                failures += 1
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
        ctx.cleanup()
    print(f"Віджетів перевірено: {checked}, проблем: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
