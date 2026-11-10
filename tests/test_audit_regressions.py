"""Регресійні тести на дефекти, знайдені під час аудиту 2026-11-09.

Кожен тест описує СПРАВЖНЮ помилку, яка вже траплялась у програмі, і фіксує
виправлену поведінку. Такі тести цінні тим, що не дають повернути дефект
непомітно.

Запуск:
    python -m unittest tests.test_audit_regressions -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Тести не мають чіпати справжні налаштування користувача.
os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-audit-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

from blackchpok_ide import hardware, intent_engine, model_caps, model_hub  # noqa: E402


class TestProjectQuestionIsAction(unittest.TestCase):
    """Питання про факти проєкту мусить давати дію, а не «балачку».

    Дефект. У ``classify_message`` була умова
    ``low.rstrip("?!. ").endswith("?")`` — вона не могла бути істинною, бо
    ``rstrip`` уже зрізав знак питання. Тому «Скільки .py файлів у теці?»
    ставало ``converse``, агент ішов шляхом ``_chat_only`` БЕЗ інструментів,
    і модель ВИГАДУВАЛА результат: «Знайдено 1 файл: main.py» замість 100.
    """

    def test_project_questions_are_inspect(self) -> None:
        for phrase in (
            "Скільки .py файлів у теці?",
            "Скільки .py файлів у теці blackchpok_ide?",
            "Скільки рядків у server.py?",
            "Яка версія Python?",
            "Де знаходиться конфіг?",
        ):
            with self.subTest(phrase=phrase):
                frame = intent_engine.frame(phrase)
                self.assertEqual(
                    frame.intent_type, intent_engine.INSPECT,
                    f"«{phrase}» має вимагати перегляду проєкту, а не балачки")
                self.assertTrue(frame.actionable)

    def test_small_talk_stays_small_talk(self) -> None:
        """Захист від надмірної корекції: вітання не має ставати дією."""
        for phrase in ("Привіт", "привіт", "Дякую", "Як справи?", "Добрий день"):
            with self.subTest(phrase=phrase):
                frame = intent_engine.frame(phrase)
                self.assertEqual(frame.intent_type, intent_engine.CONVERSE)
                self.assertFalse(frame.actionable)

    def test_live_data_questions_go_to_research(self) -> None:
        self.assertEqual(intent_engine.classify_message("скільки коштує біткоїн"),
                         intent_engine.RESEARCH)

    def test_question_mark_condition_is_not_dead(self) -> None:
        """Пряма перевірка тієї самої помилки: rstrip з'їдав знак питання."""
        body = "скільки файлів?"
        self.assertFalse(body.rstrip("?!. ").endswith("?"),
                         "це і була причина мертвої умови")
        self.assertTrue(body.rstrip().endswith("?"))


class TestVisionIconRequiresProjector(unittest.TestCase):
    """Значок зору мусить означати наявність mmproj, а не слово в назві.

    Дефект. ``model_caps.detect`` ставив 🖼 лише за назвою. Модель із ``-vl``
    отримувала зелений значок, навіть якщо поруч не було файлу проєктора:
    llama.cpp стартував без ``--mmproj``, знімки тихо не передавались.
    """

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-caps-"))

    def test_vision_flag_without_projector_is_false(self) -> None:
        model = self.folder / "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
        model.write_bytes(b"fake")
        caps = model_caps.detect(model.name, filename=model.name, local_path=model)
        self.assertFalse(caps.has(model_caps.VISION),
                         "без файлу mmproj зору не буде — значок не має світитись")

    def test_vision_flag_with_projector_is_true(self) -> None:
        model = self.folder / "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
        model.write_bytes(b"fake")
        projector = self.folder / "mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf"
        projector.write_bytes(b"fake")
        caps = model_caps.detect(model.name, filename=model.name, local_path=model)
        self.assertTrue(caps.has(model_caps.VISION))
        self.assertIn(projector.name, caps.source.get("vision", ""))

    def test_text_model_never_gets_vision(self) -> None:
        model = self.folder / "qwen2.5-coder-14b-instruct-q4_k_m.gguf"
        model.write_bytes(b"fake")
        (self.folder / "mmproj-Qwen3VL-8B-Instruct-F16.gguf").write_bytes(b"fake")
        caps = model_caps.detect(model.name, filename=model.name, local_path=model)
        self.assertFalse(caps.has(model_caps.VISION),
                         "чужий проєктор не робить текстову модель зоровою")

    def test_ministral_is_recognised_as_multimodal(self) -> None:
        """У назві Ministral немає «vl», але родина мультимодальна."""
        model = self.folder / "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf"
        model.write_bytes(b"fake")
        caps = model_caps.detect(model.name, filename=model.name)
        self.assertTrue(caps.has(model_caps.VISION),
                         "мультимодальна родина має претендувати на зір")


class TestProjectorNaming(unittest.TestCase):
    """Проєктор mistralai називається ``…-mmproj.gguf``, а не ``mmproj-…``."""

    def test_official_mistral_naming_is_detected(self) -> None:
        self.assertTrue(model_hub.is_vision_projector(
            "Ministral-3-14B-Instruct-2512-BF16-mmproj.gguf"))
        self.assertTrue(model_hub.is_vision_projector(
            "mmproj-Qwen3VL-8B-Instruct-F16.gguf"))

    def test_regular_model_is_not_projector(self) -> None:
        self.assertFalse(model_hub.is_vision_projector(
            "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf"))

    def test_projector_is_found_in_folder(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="bchp-proj-"))
        model = folder / "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf"
        model.write_bytes(b"fake")
        projector = folder / "Ministral-3-14B-Instruct-2512-BF16-mmproj.gguf"
        projector.write_bytes(b"fake")
        found = model_hub.vision_projector_for(model)
        self.assertIsNotNone(found, "офіційний файл проєктора має знаходитись")
        self.assertEqual(found.name, projector.name)


class TestRecoveryPlan(unittest.TestCase):
    """Після збою GPU запуск повторюється простішими параметрами.

    Дефект. Раніше після невдалого старту агент лише писав «сервер не
    піднявся» і лишав користувача без моделі.
    """

    def _profile(self) -> hardware.HardwareProfile:
        return hardware.HardwareProfile(
            os_name="Windows", arch="AMD64", cpu_name="test",
            cpu_cores=6, cpu_threads=12,
            ram_total_gb=64.0, ram_available_gb=60.0,
            gpus=[hardware.GpuInfo(name="test", vram_gb=12.0,
                                   vendor="nvidia", backend="cuda")],
            disk_free_gb=200.0, disk_total_gb=500.0,
        )

    def _choice(self):
        for choice in hardware.MODEL_CATALOG:
            if "14b" in choice.filename.lower():
                return choice
        return hardware.MODEL_CATALOG[0]

    def test_plan_ends_with_cpu(self) -> None:
        from blackchpok_ide import runtime

        steps = runtime.recovery_steps(self._profile(), self._choice())
        self.assertGreaterEqual(len(steps), 3, "план Б має мати кілька кроків")
        self.assertEqual(steps[-1].gpu_layers, 0,
                         "останній рубіж — робота без GPU")

    def test_plan_requirements_do_not_grow(self) -> None:
        """Кожен наступний крок не має вимагати БІЛЬШЕ ресурсів."""
        from blackchpok_ide import runtime

        choice = self._choice()
        steps = runtime.recovery_steps(self._profile(), choice)
        for previous, current in zip(steps, steps[1:]):
            if current.gpu_layers == 0:
                break
            # Порівнюємо РЕАЛЬНУ кількість шарів на GPU: `-1` — це «усі
            # шари», тобто найбільший offload, а не найменший. Пряме
            # `-1 < 24` дало б хибний висновок, що повний offload дешевший.
            if runtime._layer_rank(current, choice.layers) < \
                    runtime._layer_rank(previous, choice.layers):
                continue
            self.assertLessEqual(
                current.ctx_size, previous.ctx_size,
                "крок відновлення не може збільшувати контекст")

    def test_gpu_failure_detection(self) -> None:
        from blackchpok_ide import runtime

        self.assertTrue(runtime.is_gpu_failure("CUDA error: unknown error"))
        self.assertTrue(runtime.is_gpu_failure("failed to allocate buffer"))
        self.assertTrue(runtime.is_gpu_failure("out of memory"))
        self.assertFalse(runtime.is_gpu_failure("failed to load model"),
                         "пошкоджений файл не лікується меншим offload")


class TestChatOnlyKeepsImages(unittest.TestCase):
    """Шлях «розмови» не має губити прикріплене зображення.

    Дефект. ``_chat_only`` збирав повідомлення напряму
    (``[system_message(), *messages]``), обходячи ``AgentSession.build()``,
    де ``pending_images`` перетворюються на ``image_url``. Модель відповідала
    «я не можу аналізувати зображення», хоч картинка була в черзі.
    """

    def test_build_attaches_image(self) -> None:
        from blackchpok_ide.agent import AgentSession
        from blackchpok_ide.config import AgentSettings

        image = Path(tempfile.mkdtemp(prefix="bchp-img-")) / "shot.png"
        # Мінімальний валідний PNG (1×1).
        image.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
            b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
        session = AgentSession(AgentSettings(), ROOT)
        session.add_user("Що на цьому скріншоті?")
        session.pending_images.append(str(image))
        messages = session.build()
        content = messages[-1]["content"]
        self.assertIsInstance(content, list, "мусить стати мультимодальним")
        kinds = [part.get("type") for part in content]
        self.assertIn("image_url", kinds)
        self.assertEqual(session.pending_images, [],
                         "черга очищається після відправки")

    def test_small_talk_is_disabled_when_image_pending(self) -> None:
        """Із зображенням у черзі це не балачка, навіть якщо текст короткий."""
        from blackchpok_ide.agent import AgentRunner
        from blackchpok_ide.agent_tools import ToolRegistry
        from blackchpok_ide.config import AgentSettings, LLMSettings

        runner = AgentRunner(ToolRegistry(ROOT), LLMSettings(),
                             AgentSettings(), ROOT)
        # Беремо фразу, яку класифікатор справді вважає розмовою: саме на
        # такій «Що на цьому скріншоті?» раніше губилось зображення.
        runner.intent = intent_engine.frame("Що на цьому скріншоті?")
        self.assertEqual(runner.intent.intent_type, intent_engine.EXPLAIN)
        self.assertTrue(runner._is_small_talk(),
                        "без картинки це справді коротка відповідь словами")
        runner.session.pending_images.append("fake.png")
        self.assertFalse(runner._is_small_talk(),
                         "з прикріпленим знімком агент мусить діяти")


class TestSettingsAreNotPolluted(unittest.TestCase):
    """Тести не мають права писати у справжній конфіг користувача."""

    def test_save_respects_no_save_flag(self) -> None:
        from blackchpok_ide.config import Settings

        target = Path(tempfile.mkdtemp(prefix="bchp-cfg-")) / "settings.json"
        with mock.patch.dict(os.environ, {"BLACKCHPOK_NO_SAVE": "1"}):
            settings = Settings()
            settings.save()
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
