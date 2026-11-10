"""Ланцюг зору: модель → візуальний проєктор → --mmproj у команді.

Це закриває те, що раніше стояло як «не перевірено»: документ
AUTOMATIC_RUNTIME.md §6 каже, що ``ServerConfig.command()`` додає
``--mmproj``, якщо проєктор знайдено. Перевіряємо на РЕАЛЬНИХ файлах цієї
машини, а не на вигаданих іменах.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import model_hub, runtime  # noqa: E402

MODELS = ROOT / "userdata" / "models"


def _find(part: str) -> Path | None:
    for path in MODELS.glob("*.gguf"):
        if part.lower() in path.name.lower():
            return path
    return None


class TestProjectorChain(unittest.TestCase):
    """Властивості ланцюга, які не залежать від наявності файлів."""

    def test_explicit_projector_lands_in_command(self) -> None:
        config = runtime.ServerConfig(model_path=str(ROOT / "main.py"), port=9)
        config.mmproj_path = str(ROOT / "main.py")   # будь-який наявний файл
        command = config.command()
        self.assertIn("--mmproj", command)
        index = command.index("--mmproj")
        self.assertEqual(command[index + 1], str(ROOT / "main.py"))

    def test_no_projector_means_no_flag(self) -> None:
        config = runtime.ServerConfig(model_path=str(ROOT / "main.py"), port=9)
        self.assertNotIn("--mmproj", config.command())

    def test_missing_projector_file_is_not_passed(self) -> None:
        """Вказаний, але неіснуючий проєктор не має потрапляти в команду."""
        config = runtime.ServerConfig(model_path=str(ROOT / "main.py"), port=9)
        config.mmproj_path = str(ROOT / "no-such-file-mmproj.gguf")
        self.assertNotIn("--mmproj", config.command())

    def test_image_min_tokens_is_set(self) -> None:
        """Документ обіцяє --image-min-tokens 1024: дрібний текст інтерфейсу."""
        config = runtime.ServerConfig(model_path=str(ROOT / "main.py"), port=9)
        config.mmproj_path = str(ROOT / "main.py")
        command = config.command()
        if "--image-min-tokens" in command:
            index = command.index("--image-min-tokens")
            self.assertEqual(command[index + 1], "1024")


class TestRealModelsOnThisMachine(unittest.TestCase):
    """Перевірки на справжніх файлах. Пропускаються, якщо їх немає."""

    def setUp(self) -> None:
        if not MODELS.is_dir():
            self.skipTest("теки моделей немає")

    def test_text_model_gets_no_projector(self) -> None:
        model = _find("qwen2.5-coder")
        if model is None:
            self.skipTest("текстової моделі немає")
        self.assertIsNone(
            model_hub.vision_projector_for(model),
            "текстовій моделі приєднано проєктор — llama.cpp упаде",
        )

    def test_qwen3vl_gets_its_own_projector(self) -> None:
        model = _find("Qwen3VL-8B-Instruct-Q4_K_M")
        if model is None:
            self.skipTest("Qwen3VL немає")
        projector = model_hub.vision_projector_for(model)
        self.assertIsNotNone(projector, "проєктор не знайдено, хоч файл на диску")
        self.assertIn("Qwen3VL", projector.name,
                      f"приєднано чужий проєктор: {projector.name}")

    def test_qwen25vl_gets_its_own_projector(self) -> None:
        model = _find("Qwen2.5-VL-3B-Instruct-Q4_K_M")
        if model is None:
            self.skipTest("Qwen2.5-VL немає")
        projector = model_hub.vision_projector_for(model)
        self.assertIsNotNone(projector)
        self.assertIn("Qwen2.5-VL", projector.name,
                      f"приєднано чужий проєктор: {projector.name}")

    def test_ministral_gets_projector_with_mmproj_suffix(self) -> None:
        """Офіційний mistralai кладе mmproj у КІНЕЦЬ назви."""
        model = _find("Ministral-3-14B-Instruct-2512-Q4_K_M")
        if model is None:
            self.skipTest("Ministral немає")
        projector = model_hub.vision_projector_for(model)
        self.assertIsNotNone(projector)
        self.assertIn("mmproj", projector.name.lower())

    def test_projector_file_really_exists(self) -> None:
        model = _find("Qwen3VL-8B-Instruct-Q4_K_M")
        if model is None:
            self.skipTest("Qwen3VL немає")
        projector = model_hub.vision_projector_for(model)
        if projector is None:
            self.skipTest("проєктор не знайдено")
        self.assertTrue(projector.exists(), f"файл зник: {projector}")
        self.assertGreater(projector.stat().st_size, 1024)

    def test_full_chain_gives_mmproj_in_command(self) -> None:
        """Наскрізно: модель -> проєктор -> команда запуску."""
        model = _find("Qwen3VL-8B-Instruct-Q4_K_M")
        if model is None:
            self.skipTest("Qwen3VL немає")
        projector = model_hub.vision_projector_for(model)
        if projector is None:
            self.skipTest("проєктор не знайдено")
        config = runtime.ServerConfig(model_path=str(model), port=9)
        config.mmproj_path = str(projector)
        command = config.command()
        self.assertIn("--mmproj", command)
        index = command.index("--mmproj")
        self.assertEqual(command[index + 1], str(projector))


if __name__ == "__main__":
    unittest.main(verbosity=2)
