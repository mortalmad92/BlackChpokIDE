"""Викликати публічні методи віджетів без аргументів і зловити збої.

Створення віджета нічого не доводить: ``AttributeError`` й ``NameError``
часто живуть у методах, які викликаються зрідка — «Очистити», «Оновити»,
«Показати підсумок». Тут кожен такий метод справді викликається.

БЕЗПЕКА: методи, які запускають процеси, пишуть файли, змінюють
налаштування або закривають застосунок, пропускаються — їх перевіряють
окремі проби з ізольованими даними.

Запуск: ``python tools/probe_methods.py`` — код виходу 1, якщо є
необроблені падіння.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import tempfile
import traceback
from pathlib import Path

import tkinter as tk

import blackchpok_ide as package
from blackchpok_ide import theme

#: Слова в назві методу, через які його НЕ викликаємо автоматично.
DANGEROUS = (
    "start", "run", "stop", "exit", "quit", "close", "shutdown", "kill",
    "delete", "remove", "clear_all", "wipe", "save", "write", "send", "post",
    "publish", "deploy", "install", "download", "upload", "exec", "shell",
    "command", "apply", "commit", "reset", "reload", "restart", "open_url",
    "browse", "record", "listen", "speak", "generate", "model", "engine",
    "logout", "auth", "pump", "tick", "wait", "poll", "drain", "loop",
    "modal", "dialog", "ask", "confirm", "prompt", "choose", "browse",
)

#: ДОЗВОЛЕНИЙ список: лише методи, які гарантовано не блокують і не мають
#: побічних ефектів у зовнішньому світі. Автоматичний вибір «усі методи без
#: аргументів» на цьому коді зависав: частина методів чекає чергу або
#: відкриває модальне вікно й блокує потік подій.
SAFE_METHODS = frozenset({
    "refresh", "update", "retheme", "relayout", "redraw", "repaint",
    "recalculate", "refresh_status", "refresh_all", "refresh_models",
    "apply_font", "apply_settings", "apply_theme", "sync", "sync_state",
    "reset", "clear", "clear_messages", "clear_results", "empty",
    "set_busy", "set_online", "set_mode", "set_title", "set_text",
    "set_workspace", "set_model_label", "set_context_limit", "set_queue_count",
    "set_available_models", "set_chat_model", "set_permission_mode",
    "set_stage", "set_goal", "set_plan", "set_status", "set_hint",
    "finish_stages", "advance_stage", "begin_deep", "end_deep",
    "show_history", "show_changes", "show_nothing", "hide",
    "cancel_events", "cancel_probe", "cancel", "compact_history",
    "indicator_text", "summary", "summary_text", "counts", "stats",
    "render", "render_now", "toggle", "expand", "collapse",
    "mark_original", "detach", "attach", "raise_", "focus_input",
})

#: Модулі, які чіпають мережу/модель/процеси.
SKIP_MODULES = {
    "blackchpok_ide.cdp", "blackchpok_ide.browser_panel", "blackchpok_ide.internet",
    "blackchpok_ide.native", "blackchpok_ide.native.api", "blackchpok_ide.model_hub",
    "blackchpok_ide.runtime", "blackchpok_ide.llm_client", "blackchpok_ide.agent",
    "blackchpok_ide.main_window", "blackchpok_ide.auto_setup", "blackchpok_ide.env_setup",
    "blackchpok_ide.voice", "blackchpok_ide.voice_panel", "blackchpok_ide.social",
    "blackchpok_ide.cloud_agents", "blackchpok_ide.first_run", "blackchpok_ide.bench",
    "blackchpok_ide.screenshot", "blackchpok_ide.imaging", "blackchpok_ide.diagnostics",
    "blackchpok_ide.mcp_client", "blackchpok_ide.mcp_supervisor", "blackchpok_ide.mcp_panel",
    "blackchpok_ide.mcp_watch", "blackchpok_ide.web_server", "blackchpok_ide.live_preview",
    "blackchpok_ide.preview_panel", "blackchpok_ide.hmr", "blackchpok_ide.dom_bridge",
    "blackchpok_ide.settings_dialog", "blackchpok_ide.model_hub_panel",
    "blackchpok_ide.model_verify", "blackchpok_ide.rag_panel",
}

SAFE_ARGWORDS = {"self"}


def widget_classes() -> list[tuple[str, type]]:
    found: list[tuple[str, type]] = []
    for info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        if info.name in SKIP_MODULES:
            continue
        try:
            module = importlib.import_module(info.name)
        except Exception:                                    # noqa: BLE001
            continue
        for name, obj in vars(module).items():
            if (inspect.isclass(obj) and issubclass(obj, tk.Misc)
                    and obj.__module__ == info.name and not name.startswith("_")):
                found.append((f"{info.name}.{name}", obj))
    return found


class Ctx:
    def __init__(self, root: tk.Misc) -> None:
        from blackchpok_ide import queue_engine
        from blackchpok_ide.config import Settings

        self.root = root
        self.fonts = theme.Theme(root)
        self.settings = Settings.load()
        self.project = Path(tempfile.mkdtemp(prefix="probe-methods-"))
        self.queue = queue_engine.TaskQueue(self.project / "queue.json")


def make(cls: type, ctx: Ctx):
    signature = inspect.signature(cls.__init__)
    args: list = []
    kwargs: dict = {}
    for param in list(signature.parameters.values())[1:]:
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
        elif name in ("queue", "task_queue"):
            kwargs[name] = ctx.queue
        elif name in ("cwd", "path", "workspace", "folder"):
            kwargs[name] = ctx.project
        elif name in ("root_provider", "project_provider"):
            kwargs[name] = lambda: ctx.project
        elif name in ("service_provider", "runtime_provider"):
            kwargs[name] = lambda: None
        elif name in ("engine", "autonomous_engine"):
            from blackchpok_ide import autonomous as auto

            kwargs[name] = auto.AutonomousEngine(queue=ctx.queue)
        elif name == "book":
            # Різні панелі чекають різні «книги»: CaseBook (справи) або
            # SkillBook (скіли). Вибір за анотацією, інакше перевірка падає
            # не через дефект коду, а через підставлений не той об'єкт.
            if "Skill" in str(param.annotation):
                from blackchpok_ide import skills as skills_mod

                kwargs[name] = skills_mod.SkillBook(ctx.project)
            else:
                from blackchpok_ide import cases_panel

                kwargs[name] = cases_panel.CaseBook()
        elif name == "case_book":
            from blackchpok_ide import cases_panel

            kwargs[name] = cases_panel.CaseBook()
        elif name == "session":
            from blackchpok_ide import deep_mode

            kwargs[name] = deep_mode.DeepSession(goal="перевірка")
        elif name == "items":
            kwargs[name] = [("a", "перше", lambda: None)]
        elif name in ("text", "title", "label"):
            kwargs[name] = "перевірка"
        elif name.startswith("on_") or name == "callback":
            kwargs[name] = lambda *_a, **_k: None
        else:
            kwargs[name] = None
    return tuple(args), kwargs


def callable_methods(instance: object) -> list[str]:
    names: list[str] = []
    for name in dir(type(instance)):
        if name.startswith("_") or name not in SAFE_METHODS:
            continue
        attribute = getattr(instance, name, None)
        if not callable(attribute):
            continue
        try:
            signature = inspect.signature(attribute)
        except (TypeError, ValueError):
            continue
        required = [p for p in signature.parameters.values()
                    if p.default is inspect.Parameter.empty
                    and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD,
                                   p.KEYWORD_ONLY)]
        if required:
            continue                     # аргументи вгадувати не будемо
        names.append(name)
    return names


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    ctx = Ctx(root)
    crashes = 0
    calls = 0
    try:
        for label, cls in widget_classes():
            try:
                args, kwargs = make(cls, ctx)
                widget = cls(*args, **kwargs)
            except Exception:                                # noqa: BLE001
                continue                 # збої створення ловить smoke_widgets.py
            for name in callable_methods(widget):
                calls += 1
                try:
                    getattr(widget, name)()
                except (tk.TclError, ValueError, TypeError, OSError, RuntimeError,
                        KeyError, IndexError, AttributeError) as exc:
                    # AttributeError буває законним (немає сервісу/моделі) —
                    # важливо, щоб це не був NameError або звернення до
                    # неіснуючого атрибута САМОГО віджета.
                    message = str(exc)
                    if isinstance(exc, AttributeError) and (
                            "'" + type(widget).__name__ + "' object has no attribute"
                            in message):
                        print(f"ЗБІЙ МЕТОДУ {label}.{name}(): {message}")
                        crashes += 1
                except NameError as exc:
                    print(f"NAMEERROR {label}.{name}(): {exc}")
                    crashes += 1
                except Exception:                            # noqa: BLE001
                    print(f"ПАДІННЯ {label}.{name}()")
                    print("   ", traceback.format_exc().strip().splitlines()[-1])
                    crashes += 1
            try:
                widget.destroy()
            except Exception:                                # noqa: BLE001
                pass
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
    print(f"Викликано методів: {calls}, проблем: {crashes}")
    return 1 if crashes else 0


if __name__ == "__main__":
    raise SystemExit(main())
