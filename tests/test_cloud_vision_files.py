"""Тести зору й прикріплення файлів: локальні ТА хмарні моделі.

Фіксують дві вимоги:

1. Хмарна мультимодальна модель (GPT-4o, Claude, Gemini) мусить мати
   ``vision_enabled=True`` — у неї немає ``mmproj``, і раніше саме через
   це картинки не прикріплювались узагалі.
2. Зображення мусять доходити до кожного провайдера у ЙОГО форматі:
   OpenAI — ``image_url``, Anthropic — ``source.base64``, Gemini —
   ``inline_data``. Раніше список частин ставав рядком, і модель
   отримувала текст «{'type': 'image_url', …}» замість картинки.

Запуск: python -m unittest tests.test_cloud_vision_files -v
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

from blackchpok_ide import llm_client, provider_adapters, vision  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402

#: Найменший справжній PNG (1×1, прозорий).
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class TestVisionDetection(unittest.TestCase):
    """Хто бачить зображення — і чому."""

    def test_cloud_multimodal_models_see_images(self) -> None:
        for model, url in (
            ("gpt-4o", "https://api.openai.com/v1"),
            ("gpt-4o-mini", "https://api.openai.com/v1"),
            ("claude-sonnet-4-20250514", "https://api.anthropic.com/v1"),
            ("gemini-2.0-flash",
             "https://generativelanguage.googleapis.com/v1beta/openai"),
            ("pixtral-large-latest", "https://api.mistral.ai/v1"),
        ):
            with self.subTest(model=model):
                self.assertTrue(
                    vision.model_sees_images(model, url),
                    f"{model}: хмарна мультимодальна модель мусить мати зір")

    def test_text_only_cloud_models_do_not(self) -> None:
        for model, url in (
            ("deepseek-chat", "https://api.deepseek.com/v1"),
            ("qwen-2.5-coder-32b", "https://api.groq.com/openai/v1"),
            ("llama-3.3-70b-versatile", "https://api.groq.com/openai/v1"),
        ):
            with self.subTest(model=model):
                self.assertFalse(
                    vision.model_sees_images(model, url),
                    f"{model}: текстова модель не має отримувати картинки")

    def test_local_model_without_mmproj_has_no_vision(self) -> None:
        """Назва «vl» не дає зору, якщо файлу проєктора немає."""
        folder = Path(tempfile.mkdtemp(prefix="bchp-nommproj-"))
        model = folder / "qwen2.5-vl-7b-instruct-q4_k_m.gguf"
        model.write_bytes(b"fake")
        self.assertFalse(
            vision.model_sees_images("qwen2.5-vl-7b-instruct-q4_k_m",
                                     "http://127.0.0.1:8080/v1",
                                     local_path=model),
            "без mmproj локальна модель не бачить зображень")

    def test_local_model_with_mmproj_has_vision(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="bchp-mmproj-"))
        model = folder / "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf"
        model.write_bytes(b"fake")
        (folder / "Ministral-3-14B-Instruct-2512-BF16-mmproj.gguf").write_bytes(b"p")
        self.assertTrue(
            vision.model_sees_images("Ministral-3-14B-Instruct-2512-Q4_K_M",
                                     "http://127.0.0.1:8080/v1",
                                     local_path=model),
            "з mmproj поруч модель мусить бачити зображення")

    def test_local_url_is_recognised(self) -> None:
        for url in ("http://127.0.0.1:8080/v1", "http://localhost:1234/v1",
                    "native://blackchpok"):
            self.assertTrue(vision.is_local_url(url), url)
        for url in ("https://api.openai.com/v1", "https://api.deploy.com/api/v1"):
            self.assertFalse(vision.is_local_url(url), url)

    def test_describe_differs_for_local_and_cloud(self) -> None:
        """Підказка мусить називати СПРАВЖНЮ причину."""
        local = vision.describe("qwen2.5-coder-14b", "http://127.0.0.1:8080/v1")
        cloud = vision.describe("deepseek-chat", "https://api.deepseek.com/v1")
        self.assertIn("mmproj", local,
                      "для локальної моделі причина — відсутній mmproj")
        self.assertNotIn("mmproj", cloud,
                         "для хмарної моделі mmproj не згадується — його там немає")

    def test_manual_override_wins(self) -> None:
        """Ручний вибір перекриває евристику за назвою в обидва боки.

        ── ЧОМУ ПРИКЛАД ЗМІНЕНО (20.11.2026) ──────────────────────────────
        Раніше «невідомою текстовою» тут стояла
        ``deepseek-ai/deepseek-v4.1-flash-1017``. Це було фактично
        неправдою: у документації Deploy ця модель позначена як
        ``Input Modality: Text, Image``, і саме через цю помилку
        користувач не міг прикріпити скриншот (див.
        ``tests/test_image_attachments.py``). Тепер каталог знає її як
        мультимодальну, тож для перевірки «невідома модель» потрібна
        справді невідома назва.

        Вимога та сама: без ручного вибору невідома модель вважається
        текстовою, «Увімкнено» дає їй зір, «Вимкнено» забирає зір навіть
        у свідомо мультимодальної.
        """
        unknown = "some-vendor/unknown-model-2026"
        url = "https://api.deploy.com/api/v1"
        self.assertFalse(vision.model_sees_images(unknown, url, provider="deploy"),
                         "без ручного вибору невідома модель вважається текстовою")
        self.assertTrue(
            vision.model_sees_images(unknown, url, provider="deploy", override=True),
            "«Увімкнено» мусить давати зір навіть невідомій моделі")
        self.assertFalse(
            vision.model_sees_images("gpt-4o", "https://api.openai.com/v1",
                                     override=False),
            "«Вимкнено» мусить вимикати зір навіть у мультимодальної моделі")

    def test_override_changes_explanation(self) -> None:
        detail = vision.describe("x", "https://api.example.com/v1", override=True)
        self.assertIn("вручну", detail)
        self.assertNotIn("не заявлена", detail)


class TestImageReachesProvider(unittest.TestCase):
    """Кожен провайдер отримує зображення у СВОЄМУ форматі."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-vis-"))
        self.image = self.folder / "shot.png"
        self.image.write_bytes(PNG_BYTES)

    def _messages(self) -> list[dict]:
        built = llm_client.image_message("що на екрані?", [self.image])
        return [{"role": "system", "content": "ти агент"},
                {"role": "user", "content": built["content"]}]

    def test_openai_keeps_image_url(self) -> None:
        messages = self._messages()
        parts = messages[-1]["content"]
        kinds = [part.get("type") for part in parts]
        self.assertIn("image_url", kinds, "OpenAI-формат зламано")
        url = next(part["image_url"]["url"] for part in parts
                   if part.get("type") == "image_url")
        self.assertTrue(url.startswith("data:image/png;base64,"), url[:40])

    def test_anthropic_gets_base64_source(self) -> None:
        payload = provider_adapters.anthropic_payload(
            self._messages(), model="claude-sonnet-4", max_tokens=100)
        blocks = payload["messages"][-1]["content"]
        images = [block for block in blocks if block.get("type") == "image"]
        self.assertEqual(len(images), 1,
                         "Anthropic не отримав зображення (перетворилось на текст)")
        source = images[0]["source"]
        self.assertEqual(source["type"], "base64")
        self.assertEqual(source["media_type"], "image/png")
        self.assertTrue(source["data"], "base64-дані порожні")
        # Текст теж мусить лишитись, і окремим блоком.
        texts = [block for block in blocks if block.get("type") == "text"]
        self.assertTrue(texts, "текст запиту зник")
        self.assertIn("що на екрані", texts[0]["text"])

    def test_gemini_gets_inline_data(self) -> None:
        payload = provider_adapters.gemini_payload(self._messages(), max_tokens=100)
        parts = payload["contents"][-1]["parts"]
        inline = [part for part in parts if "inline_data" in part]
        self.assertEqual(len(inline), 1, "Gemini не отримав зображення")
        self.assertEqual(inline[0]["inline_data"]["mime_type"], "image/png")
        self.assertTrue(inline[0]["inline_data"]["data"])

    def test_no_repr_leak_in_prompts(self) -> None:
        """Службове представлення списку не має потрапляти в ТЕКСТ запиту.

        Перевіряємо саме значення текстових блоків, а не ``str(payload)``:
        у словнику payload ключі теж виглядають як ``'type': 'text'``, і
        перевірка всього словника завжди спрацьовувала б хибно.
        """
        payload = provider_adapters.anthropic_payload(
            self._messages(), model="claude-sonnet-4", max_tokens=100)
        texts = [block.get("text", "")
                 for block in payload["messages"][-1]["content"]
                 if block.get("type") == "text"]
        for text in texts:
            self.assertNotIn("{'type'", text,
                             "у текст запиту потрапив str(list) замість блоків")
            self.assertNotIn("'image_url'", text,
                             "у текст запиту потрапило представлення картинки")
        self.assertTrue(any("що на екрані" in text for text in texts),
                        "справжній текст запиту загубився")

        gem = provider_adapters.gemini_payload(self._messages(), max_tokens=100)
        for part in gem["contents"][-1]["parts"]:
            text = str(part.get("text") or "")
            self.assertNotIn("'type'", text,
                             "Gemini отримав рядок замість блоків")

    def test_text_only_message_unchanged(self) -> None:
        """Повідомлення без картинок не мусить ламатись."""
        messages = [{"role": "user", "content": "привіт"}]
        payload = provider_adapters.anthropic_payload(
            messages, model="claude-sonnet-4", max_tokens=100)
        blocks = payload["messages"][0]["content"]
        self.assertEqual(blocks, [{"type": "text", "text": "привіт"}])
        gem = provider_adapters.gemini_payload(messages, max_tokens=100)
        self.assertEqual(gem["contents"][0]["parts"], [{"text": "привіт"}])

    def test_http_url_is_skipped_for_anthropic(self) -> None:
        """Anthropic приймає лише base64 — посилання не має ламати запит."""
        block = provider_adapters._anthropic_image("https://example.com/a.png")
        self.assertIsNone(block)


class TestAttachFileToChat(unittest.TestCase):
    """Прикріплення файлу в чаті: картинка й текстові файли."""

    def setUp(self) -> None:
        import tkinter as tk

        from blackchpok_ide import theme
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.chat_panel import ChatPanel

        self.root = tk.Tk()
        self.root.withdraw()
        fonts = theme.Theme(self.root)
        fonts.apply()
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-attach-"))
        self.panel = ChatPanel(self.root, fonts, Settings(),
                               ToolRegistry(self.folder))
        self.panel.pack()
        #: Скільки повідомлень показав чат.
        self.notes: list[str] = []
        self.panel._note = lambda text, kind="info": self.notes.append(str(text))

    def tearDown(self) -> None:
        # ── ЧОМУ ТУТ ПОРЯДОК І ``gc.collect()`` ────────────────────────────
        # Об'єкти ``tkinter.font.Font`` мають ``__del__``, який звертається
        # до Tk. Якщо такий об'єкт переживе ``root.destroy()`` і буде
        # знищений збирачем сміття в ІНШОМУ потоці (а в наборі тестів
        # поруч працюють HTTP-стаби своїми потоками), ``__del__`` блокується
        # назавжди — і зовнішньо це виглядає як таймаут зовсім іншого тесту
        # в іншому модулі.
        #
        # Тому: спершу прибираємо посилання й збираємо сміття ТУТ, у
        # головному потоці, поки Tk ще живий. Лише потім destroy().
        import gc

        self.panel = None
        gc.collect()
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001 - вікно могло закритись
            pass

    def _runner(self, *, vision_enabled: bool):
        """Мінімальний агент із чергою зображень."""

        class _Session:
            pending_images: list[str] = []

        class _Runner:
            pass

        runner = _Runner()
        runner.session = _Session()
        runner.session.pending_images = []
        runner.vision_enabled = vision_enabled
        return runner

    def test_image_attached_when_vision_enabled(self) -> None:
        self.panel.attach_runner(self._runner(vision_enabled=True))
        image = self.folder / "shot.png"
        image.write_bytes(PNG_BYTES)
        self.panel._attach_image(image)
        self.assertEqual(self.panel.runner.session.pending_images, [str(image)])

    def test_image_refused_with_clear_reason(self) -> None:
        self.panel.attach_runner(self._runner(vision_enabled=False))
        self.panel.set_vision_detail("модель не заявлена як мультимодальна")
        image = self.folder / "shot.png"
        image.write_bytes(PNG_BYTES)
        self.panel._attach_image(image)
        self.assertEqual(self.panel.runner.session.pending_images, [])
        joined = " ".join(self.notes)
        self.assertIn("не читає зображення", joined)
        self.assertNotIn("mmproj", joined,
                         "для хмарної моделі підказка про mmproj — неправда")

    def test_text_file_goes_into_prompt(self) -> None:
        self.panel.attach_runner(self._runner(vision_enabled=True))
        source = self.folder / "app.py"
        source.write_text("def f():\n    return 1\n", encoding="utf-8")
        self.panel._insert_file(source)
        text = self.panel.input_box.get("1.0", "end")
        self.assertIn("def f():", text, "вміст файлу не потрапив у запит")
        self.assertIn("app.py", text, "ім'я файлу не підписано")


if __name__ == "__main__":
    unittest.main(verbosity=2)
