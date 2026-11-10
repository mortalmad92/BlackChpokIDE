"""Скриншот хабу моделей (перевірка вигляду панелі).

Запуск: python tests/screenshot_hub.py [шлях.png]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def main() -> int:
    from blackchpok_ide import model_hub as hub
    from blackchpok_ide.config import Settings, setup_logging

    setup_logging()
    settings = Settings.load()
    settings.workspace = str(ROOT)
    settings.ui.chat_visible = False
    settings.ui.bottom_visible = True
    settings.ui.bottom_height = 380

    from blackchpok_ide.main_window import BlackChpokIDE

    app = BlackChpokIDE(settings)
    app.geometry("1500x950+40+20")
    pump(app, 0.6)
    app.show_bottom("hub")
    app.model_hub.start()
    pump(app, 1.2)

    # Наповнюємо результати демонстраційними даними, щоб кадр був показовим.
    demo = [
        hub.ModelHit(source="huggingface", model_id="Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
                     name="Qwen2.5-Coder-7B-Instruct-GGUF",
                     filename="qwen2.5-coder-7b-instruct-q4_k_m.gguf",
                     size_bytes=int(4.36 * 2**30), downloads=351061),
        hub.ModelHit(source="huggingface", model_id="Qwen/Qwen2.5-Coder-14B-Instruct-GGUF",
                     name="Qwen2.5-Coder-14B-Instruct-GGUF",
                     filename="qwen2.5-coder-14b-instruct-q4_k_m.gguf",
                     size_bytes=int(8.37 * 2**30), downloads=186887),
        hub.ModelHit(source="huggingface", model_id="Qwen/Qwen3-4B-GGUF",
                     name="Qwen3-4B-GGUF", filename="Qwen3-4B-Q4_K_M.gguf",
                     size_bytes=int(2.33 * 2**30), downloads=94000),
        hub.ModelHit(source="github", model_id="ggml-org/llama.cpp", name="ggml-org/llama.cpp",
                     description="LLM inference in C/C++", downloads=133466),
        hub.ModelHit(source="civitai", model_id="122359", name="Detail Tweaker XL",
                     filename="add-detail-xl.safetensors", size_bytes=int(0.21 * 2**30),
                     kind="lora", base_model="SDXL 1.0", likes=43807),
    ]
    for hit in demo:
        app.model_hub._add_hit(hit)
    if app.model_hub.hits:
        app.model_hub.results.selection_set("0")
        app.model_hub._on_select()
    app.model_hub.progress.configure(value=43)
    app.model_hub.status.configure(
        text=" 43.0%  ·  1.87 з 4.36 ГБ  ·  38.4 МБ/с  ·  лишилось ~1 хв 5 с")
    pump(app, 0.8)

    def shoot() -> None:
        try:
            from PIL import ImageGrab

            x = app.winfo_rootx()
            y = app.winfo_rooty()
            w = app.winfo_width()
            h = app.winfo_height()
            menu = app.nametowidget(app.cget("menu")) if app.cget("menu") else None
            menu_h = menu.winfo_height() if menu is not None else 0
            if menu_h <= 1:
                menu_h = 24
            image = ImageGrab.grab(bbox=(x, y - menu_h, x + w, y + h))
            target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".buildtmp" / "hub.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target)
            print(f"saved {target} {image.size}")
        except Exception as exc:  # noqa: BLE001
            print("screenshot failed:", exc)
        finally:
            app.model_hub.on_close()
            app.destroy()

    app.after(600, lambda: (app.lift(), app.focus_force(), app.attributes("-topmost", True)))
    app.after(2200, shoot)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
