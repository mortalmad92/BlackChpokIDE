"""Зображення в чаті: хмарний зір Deploy і МАЛІ ІКОНКИ прикріплень.

Фіксують два дефекти, на які скаржився користувач:

1. **«Поточна модель не читає зображення» для робочої моделі.** У чаті з
   ``deepseek-ai/deepseek-v4.1-flash-1017`` прикріпити скриншот було
   неможливо: назви не було в каталозі ``vision.VISION_MODELS``, і
   :func:`vision.model_sees_images` відповідав ``False``. У документації
   Deploy ця модель позначена як ``Input Modality: Text, Image``, тобто
   заборона була нашою вигадкою.

2. **Прикріплення показувалось лише рядком.** Смуга композера малювала
   «🖼 shot.png» без прев'ю: не було видно, ЩО прикріплено. Тепер там
   мала іконка (див. :mod:`thumbs`).

Запуск: python -m unittest tests.test_image_attachments -v
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_NO_SAVE", "1")

from blackchpok_ide import llm_client, thumbs, vision  # noqa: E402

#: Найменший справжній PNG (1×1, прозорий).
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class TestDeployModelsSeeImages(unittest.TestCase):
    """Deploy приймає зображення — і ми це знаємо, а не вигадуємо."""

    #: Моделі з документації Deploy (Models & Pricing, колонка Input Modality).
    MULTIMODAL = (
        "deepseek-ai/deepseek-v4.1-flash-1017",
        "zai-org/glm-5.3-flash",
    )

    def test_deploy_multimodal_models_have_vision(self) -> None:
        url = "https://api.deploy.com/api/v1"
        for model in self.MULTIMODAL:
            with self.subTest(model=model):
                self.assertTrue(
                    vision.model_sees_images(model, url, provider="deploy"),
                    f"{model}: Deploy заявляє Text, Image — зір мусить бути")

    def test_deploy_text_model_still_has_no_vision(self) -> None:
        """Правило не має стати «Deploy завжди бачить»."""
        self.assertFalse(
            vision.model_sees_images("zai-org/glm-4.5-air",
                                     "https://api.deploy.com/api/v1",
                                     provider="deploy"),
            "текстова модель не має отримувати картинки")

    def test_explanation_names_vision_not_refusal(self) -> None:
        """Підказка в чаті не має казати «модель не заявлена»."""
        detail = vision.describe("deepseek-ai/deepseek-v4.1-flash-1017",
                                 "https://api.deploy.com/api/v1",
                                 provider="deploy")
        self.assertNotIn("не заявлена", detail)
        self.assertIn("зір", detail)

    def test_cloud_catalogue_shows_vision_icon(self) -> None:
        """У списку моделей позначка 🖼 стоїть саме в мультимодальних."""
        from blackchpok_ide import providers

        icons = {entry.name: entry.caps for entry in providers.cloud_models()}
        for model in self.MULTIMODAL:
            with self.subTest(model=model):
                self.assertIn("🖼", icons.get(model, ()),
                              f"{model}: у списку моделей немає позначки зору")
        self.assertNotIn("🖼", icons.get("qwen-2.5-coder-32b", ()),
                         "текстова модель не має позначки зору")


class TestImageMime(unittest.TestCase):
    """MIME мусить відповідати СПРАВЖНЬОМУ формату файлу."""

    def test_suffixes_map_to_real_mime(self) -> None:
        expected = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".gif": "image/gif",
        }
        for suffix, mime in expected.items():
            with self.subTest(suffix=suffix):
                self.assertEqual(llm_client.image_mime(Path("shot" + suffix)), mime,
                                 f"{suffix} оголошено неправильним MIME")

    def test_message_uses_real_mime_for_webp(self) -> None:
        """WebP не має їхати як image/jpeg — сервер відхилив би запит."""
        folder = Path(tempfile.mkdtemp(prefix="bchp-mime-"))
        shot = folder / "shot.webp"
        shot.write_bytes(PNG_BYTES)   # вміст не важливий: перевіряємо заголовок
        built = llm_client.image_message("що тут?", [shot])
        parts = [part for part in built["content"]
                 if part.get("type") == "image_url"]
        self.assertEqual(len(parts), 1, "зображення не потрапило в запит")
        url = parts[0]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/webp;base64,"), url[:40])


class TestThumbnails(unittest.TestCase):
    """Малі іконки: те, що Tk читає сам, і чесна відмова для решти."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-thumb-"))
        self.png = self.folder / "shot.png"
        self.png.write_bytes(PNG_BYTES)
        self.weird = self.folder / "shot.webp"
        self.weird.write_bytes(PNG_BYTES)

    def test_png_is_showable_without_pillow(self) -> None:
        self.assertTrue(thumbs.can_show(self.png),
                        "PNG Tk читає сам — Pillow не потрібен")

    def test_unknown_suffix_is_not_showable(self) -> None:
        self.assertFalse(thumbs.can_show(self.folder / "notes.txt"))

    def test_bad_file_returns_none_instead_of_raising(self) -> None:
        """Пошкоджений PNG не має валити смугу прикріплень."""
        broken = self.folder / "broken.png"
        broken.write_bytes(b"not a png at all")
        if not thumbs.pillow_available():
            self.skipTest("Pillow не встановлено — перевірка стосується його шляху")
        self.assertIsNone(thumbs.preview_png_bytes(broken),
                          "пошкоджений файл має дати None, а не виняток")

    def test_preview_is_small_png(self) -> None:
        if not thumbs.pillow_available():
            self.skipTest("Pillow не встановлено")
        data = thumbs.preview_png_bytes(self.weird, max_px=thumbs.THUMB_PX)
        self.assertIsNotNone(data, "Pillow мав створити мініатюру")
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"),
                        "мініатюра мусить бути PNG — Tk інших форматів не читає")


class TestAttachmentStripShowsThumbs(unittest.TestCase):
    """Смуга прикріплень малює іконку, а не лише рядок з іменем."""

    def setUp(self) -> None:
        import tkinter as tk

        from blackchpok_ide import theme
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.chat_panel import ChatPanel
        from blackchpok_ide.config import Settings

        self.root = tk.Tk()
        self.root.withdraw()
        fonts = theme.Theme(self.root)
        fonts.apply()
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-strip-"))
        self.panel = ChatPanel(self.root, fonts, Settings(),
                               ToolRegistry(self.folder))
        self.panel.pack()

        class _Session:
            def __init__(self) -> None:
                self.pending_images: list[str] = []

        class _Runner:
            vision_enabled = True
            session = _Session()

        self.runner = _Runner()
        self.panel.attach_runner(self.runner)

    def tearDown(self) -> None:
        # Порядок і ``gc.collect()`` — див. пояснення в
        # tests/test_cloud_vision_files.py: ``tkinter.font.Font.__del__``
        # у чужому потоці блокується назавжди й валить інші тести.
        import gc

        self.panel = None
        self.runner = None
        gc.collect()
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001 - вікно могло закритись
            pass

    def test_chip_has_image_not_only_text(self) -> None:
        shot = self.folder / "shot.png"
        shot.write_bytes(PNG_BYTES)
        self.panel._attach_image(shot)
        self.root.update_idletasks()
        chips = self.panel._attachment_chips
        self.assertEqual(len(chips), 1, "чип прикріплення не створено")
        labels = [child for child in chips[0].winfo_children()
                  if isinstance(child, __import__("tkinter").Label)]
        self.assertTrue(labels, "у чипі немає жодного віджета")
        icons = [label for label in labels
                 if str(label.cget("image") or "")]
        self.assertTrue(icons, "чип показує лише текст, без мініатюри")

    def test_removing_attachment_clears_strip(self) -> None:
        shot = self.folder / "shot.png"
        shot.write_bytes(PNG_BYTES)
        self.panel._attach_image(shot)
        self.panel._remove_attachment(str(shot))
        self.root.update_idletasks()
        self.assertEqual(self.panel.runner.session.pending_images, [])
        self.assertEqual(self.panel._attachment_chips, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
