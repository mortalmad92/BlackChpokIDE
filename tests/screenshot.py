"""Зняти скриншот вікна IDE (для перевірки вигляду).

Запуск: python tests/screenshot.py [шлях.png]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _has_git() -> bool:
    import shutil

    return shutil.which("git") is not None


def main() -> int:
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.ui.chat_visible = True
    settings.ui.bottom_visible = True
    settings.ui.font_size = 13
    settings.llm.model = settings.llm.model or "qwen2.5-coder-14b-instruct"

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1500x920+40+30")
    app.open_path(ROOT / "main.py")
    app.update()
    app.show_bottom("terminal")
    # git може бути не встановлений — тоді в кадрі був би червоний текст помилки
    app.terminal.run("python -m compileall -q blackchpok_ide" if _has_git() else "python --version")
    if _has_git():
        app.terminal.run("git status --short --branch")
    app.outline.update_for(app.tabs.current())
    app.chat.new_chat()

    demo = "--demo-agent" in sys.argv
    if demo:
        import fake_llm

        server, port = fake_llm.start(0)
        app.settings.llm.base_url = f"http://127.0.0.1:{port}/v1"
        app.settings.llm.model = "fake-coder"
        app.agent.llm_settings = app.settings.llm
        app._on_model_changed()
        app.chat._send("Покажи, що є в проєкті")
    else:
        app.chat._write("\nВИ\n", "user_role")
        app.chat._write("Перевір проєкт і скажи, що робить server.py\n", "user_text")
        app.chat._write("\nАГЕНТ\n", "assistant_role")
        app.chat._write_markdown(
            "Прочитав структуру. Основні модулі:\n"
            "- `server.py` — MCP-сервер з єдиним інструментом master_agent_router\n"
            "- `agent_tools.py` — реалізація файлових дій і терміналу\n\n"
            "```python\ndef master_agent_router(intent='auto', request=''):\n    ...\n```\n"
        )
    app.update()

    def shoot() -> None:
        try:
            from PIL import ImageGrab

            x = app.winfo_rootx()
            y = app.winfo_rooty()
            w = app.winfo_width()
            h = app.winfo_height()
            # winfo_rooty() вказує на клієнтську область, тож рядок меню
            # лишається за кадром — додаємо його висоту вручну.
            menu = app.nametowidget(app.cget("menu")) if app.cget("menu") else None
            menu_h = menu.winfo_height() if menu is not None else 0
            if menu_h <= 1:
                menu_h = 24
            image = ImageGrab.grab(bbox=(x, y - menu_h, x + w, y + h))
            target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".buildtmp" / "ide.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target)
            print(f"saved {target} {image.size}")
        except Exception as exc:  # noqa: BLE001
            print("screenshot failed:", exc)
        finally:
            app.destroy()

    app.after(800, lambda: (app.lift(), app.focus_force(), app.attributes("-topmost", True)))
    app.after(2500, shoot)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
