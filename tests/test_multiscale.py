"""Тести multi-scale аналізу та візуальних інструментів.

Фіксують вимоги:
* ділянки ріжуться з ОРИГІНАЛУ без масштабування;
* координати ділянок — у системі оригіналу;
* пропорції не спотворюються;
* перекриття між ділянками є;
* модель може сказати «не розібрано» (правило невпевненості);
* порівняння знімків дає числа й координати змін.

Запуск:
    python -m unittest tests.test_multiscale -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BLACKCHPOK_HOME", tempfile.mkdtemp(prefix="bchp-ms-"))
os.environ["BLACKCHPOK_NO_SAVE"] = "1"

from blackchpok_ide import imaging, multiscale  # noqa: E402


def make_image(path: Path, width: int, height: int, *,
               pattern: str = "stripes") -> Path:
    """Створити тестове PNG (смуги або суцільний колір)."""
    rgb = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            index = (y * width + x) * 3
            if pattern == "stripes":
                value = 255 if ((x // 8) + (y // 8)) % 2 == 0 else 0
            else:
                value = 128
            rgb[index] = value
            rgb[index + 1] = value
            rgb[index + 2] = value
    multiscale.write_png(path, width, height, bytes(rgb))
    return path


class TestPngRoundTrip(unittest.TestCase):
    """Власний PNG-кодер і декодер мають бути симетричні."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-png-"))

    def test_round_trip(self) -> None:
        source = make_image(self.folder / "a.png", 40, 30)
        width, height, rgb = multiscale.read_png(source)
        self.assertEqual((width, height), (40, 30))
        self.assertEqual(len(rgb), 40 * 30 * 3)
        # Перевіримо кілька пікселів: перший має бути білий (смуги).
        self.assertEqual(tuple(rgb[0:3]), (255, 255, 255))

    def test_read_rejects_non_png(self) -> None:
        bogus = self.folder / "x.png"
        bogus.write_bytes(b"not a png at all")
        with self.assertRaises(ValueError):
            multiscale.read_png(bogus)


class TestTilePlanning(unittest.TestCase):
    """Планування ділянок."""

    def test_small_image_needs_no_tiles(self) -> None:
        self.assertEqual(multiscale.tile_boxes(800, 600), [],
                         "невелике зображення не треба різати")

    def test_large_image_is_split(self) -> None:
        boxes = multiscale.tile_boxes(3440, 1440)
        self.assertGreater(len(boxes), 1)
        for box in boxes:
            width = box[2] - box[0]
            height = box[3] - box[1]
            self.assertLessEqual(width, multiscale.TILE_SIZE + 1)
            self.assertLessEqual(height, multiscale.TILE_SIZE + 1)
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)

    def test_tiles_cover_whole_image(self) -> None:
        """Кожен кут оригіналу має потрапити в якусь ділянку."""
        width, height = 3440, 1440
        boxes = multiscale.tile_boxes(width, height)
        corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
        for cx, cy in corners:
            covered = any(b[0] <= cx < b[2] and b[1] <= cy < b[3] for b in boxes)
            self.assertTrue(covered, f"кут ({cx},{cy}) не покритий ділянками")

    def test_tiles_overlap(self) -> None:
        """Сусідні ділянки мусять перекриватись, інакше елемент розріжеться."""
        boxes = multiscale.tile_boxes(3440, 1440)
        first_row = sorted([b for b in boxes if b[1] == 0], key=lambda b: b[0])
        self.assertGreater(len(first_row), 1)
        left, right = first_row[0], first_row[1]
        self.assertGreater(left[2], right[0],
                           "ділянки не перекриваються — елемент на межі "
                           "буде розрізаний навпіл")

    def test_tile_count_is_limited(self) -> None:
        boxes = multiscale.tile_boxes(12000, 9000)
        self.assertLessEqual(len(boxes), multiscale.MAX_TILES,
                             "забагато ділянок — аналіз стане нестерпно довгим")


class TestCropFromOriginal(unittest.TestCase):
    """Обрізання ріже ОРИГІНАЛ, а не зменшену копію."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-crop-"))
        self.source = make_image(self.folder / "big.png", 600, 400)

    def test_crop_keeps_original_resolution(self) -> None:
        data = self.source.read_bytes()
        width, height, rgb = multiscale.read_png(self.source)
        cw, ch, cropped = multiscale.crop_rgb(rgb, width, height, (100, 50, 300, 250))
        self.assertEqual((cw, ch), (200, 200),
                         "розмір обрізаного має дорівнювати запитаному "
                         "прямокутнику без масштабування")
        self.assertEqual(len(cropped), 200 * 200 * 3)

    def test_crop_clamps_to_image_bounds(self) -> None:
        width, height, rgb = multiscale.read_png(self.source)
        cw, ch, _ = multiscale.crop_rgb(rgb, width, height, (500, 300, 900, 900))
        self.assertEqual((cw, ch), (100, 100),
                         "обрізання за межами має обрізатись до меж зображення")

    def test_crop_tool_writes_file_with_coordinates(self) -> None:
        target, note = imaging.crop(self.source, (100, 50, 200, 150),
                                    out_dir=self.folder)
        self.assertIsNotNone(target)
        self.assertTrue(target.exists())
        self.assertIn("(100,50)", note)
        self.assertIn("без масштабування", note)
        info = imaging.image_info(target)
        self.assertEqual((info.width, info.height), (200, 150))


class TestMultiScalePrepare(unittest.TestCase):
    """Підготовка плану аналізу."""

    def test_prepare_large_image(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="bchp-prep-"))
        source = make_image(folder / "screen.png", 1600, 900)
        plan = multiscale.prepare(source, out_dir=folder / "tiles")
        self.assertEqual(plan.width, 1600)
        self.assertEqual(plan.height, 900)
        self.assertIsNotNone(plan.overview, "огляд мусить бути")
        self.assertGreater(len(plan.tiles), 0)
        for region in plan.tiles:
            self.assertTrue(Path(region.path).exists())
            # Координати в системі ОРИГІНАЛУ.
            self.assertLessEqual(region.x + region.width, plan.width)
            self.assertLessEqual(region.y + region.height, plan.height)

    def test_overview_is_downscaled_but_tiles_are_not(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="bchp-ov-"))
        source = make_image(folder / "large.png", 2400, 1200)
        plan = multiscale.prepare(source, out_dir=folder / "tiles")
        overview = imaging.image_info(plan.overview.path)
        self.assertLess(overview.width, plan.width,
                        "огляд має бути зменшений")
        for region in plan.tiles[:2]:
            info = imaging.image_info(region.path)
            self.assertEqual((info.width, info.height),
                             (region.width, region.height),
                             "ділянка має бути в ПОВНІЙ роздільній здатності")


class TestUncertaintyRule(unittest.TestCase):
    """Модель мусить мати змогу сказати «не розібрано»."""

    def test_rule_forbids_inventing(self) -> None:
        text = multiscale.UNCERTAINTY_RULE
        self.assertIn("не розібрано", text)
        self.assertIn("НЕ вигадуй", text)

    def test_region_caption_has_coordinates(self) -> None:
        region = multiscale.Region("x.png", 100, 200, 300, 400, label="лівий верх")
        caption = multiscale.region_caption(region, total=8, index=3)
        self.assertIn("x=100..400", caption)
        self.assertIn("y=200..600", caption)
        self.assertIn("ділянка 3 з 8", caption)


class TestCompareScreenshots(unittest.TestCase):
    """Порівняння двох знімків."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-cmp-"))
        self.first = make_image(self.folder / "a.png", 200, 100, pattern="plain")
        self.second = make_image(self.folder / "b.png", 200, 100, pattern="stripes")

    def test_identical_images(self) -> None:
        result = imaging.compare(self.first, self.first)
        self.assertTrue(result.ok)
        self.assertEqual(result.changed_pixels, 0)
        self.assertEqual(result.percent, 0.0)

    def test_different_images_report_change(self) -> None:
        result = imaging.compare(self.first, self.second, out_dir=self.folder)
        self.assertTrue(result.ok)
        self.assertGreater(result.changed_pixels, 0)
        self.assertGreater(result.percent, 0)
        self.assertTrue(Path(result.diff_path).exists(),
                        "карта різниці має бути збережена")

    def test_different_sizes_rejected(self) -> None:
        other = make_image(self.folder / "c.png", 100, 100, pattern="plain")
        result = imaging.compare(self.first, other)
        self.assertFalse(result.ok)
        self.assertIn("різні розміри", result.error)

    def test_visual_difference_crops_both_sides(self) -> None:
        registry = _registry()
        call = registry.call("analyze_visual_difference",
                             {"first": str(self.first), "second": str(self.second)})
        self.assertTrue(call.ok, call.output)
        self.assertIn("Вирізані ділянки", call.output)
        self.assertIn("до:", call.output)
        self.assertIn("після:", call.output)


class TestMetadataTools(unittest.TestCase):
    """Метадані та історія."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="bchp-meta-"))
        self.source = make_image(self.folder / "shot.png", 640, 480)

    def test_dimensions(self) -> None:
        info = imaging.image_info(self.source)
        self.assertTrue(info.exists)
        self.assertEqual((info.width, info.height), (640, 480))
        self.assertEqual(info.format, "PNG")

    def test_missing_file(self) -> None:
        info = imaging.image_info(self.folder / "nope.png")
        self.assertFalse(info.exists)
        self.assertIn("не знайдено", info.text())

    def test_history_records_artifacts(self) -> None:
        """Новий артефакт потрапляє в історію — навіть якщо вона вже повна.

        Історія обмежена :data:`imaging.HISTORY_LIMIT` записами, тому
        перевірка «стало більше» хибна, коли ліміт уже досягнуто
        (перевірено на реальній історії з 200 записів: довжина не
        зростає, хоч запис справді додався). Перевіряємо САМЕ те, що
        обіцяє ``record``: останній запис — наш, а розмір не перевищує
        ліміту.
        """
        before = len(imaging.load_history())
        imaging.record("test", self.source, note="перевірка")
        after = imaging.load_history()
        self.assertEqual(after[-1]["kind"], "test")
        self.assertLessEqual(len(after), imaging.HISTORY_LIMIT)
        if before < imaging.HISTORY_LIMIT:
            self.assertGreater(len(after), before)
        else:
            # Історія повна: старий запис витіснено, довжина та сама.
            self.assertEqual(len(after), imaging.HISTORY_LIMIT)


class TestToolRegistration(unittest.TestCase):
    """Усі візуальні інструменти мають бути в схемах і виконуватись."""

    def test_schemas_present(self) -> None:
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS

        names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
        required = {
            "capture_screen", "capture_region", "crop_screenshot",
            "get_image_dimensions", "get_screenshot_metadata",
            "inspect_screenshot_regions", "compare_screenshots",
            "analyze_visual_difference",
        }
        missing = required - names
        self.assertFalse(missing, f"немає схем: {sorted(missing)}")

    def test_every_schema_has_handler(self) -> None:
        from blackchpok_ide.agent_tools import TOOL_SCHEMAS

        registry = _registry()
        for schema in TOOL_SCHEMAS:
            name = schema["function"]["name"]
            result = registry.call(name, {})
            # Або виконано, або помилка валідації — але НЕ «невідомий інструмент».
            self.assertNotIn("невідом", str(result.output).lower(),
                             f"{name} не має реалізації")

    def test_image_tools_do_not_lie(self) -> None:
        """Інструмент без параметрів має чесно сказати, чого бракує."""
        registry = _registry()
        result = registry.call("get_image_dimensions", {"path": ""})
        self.assertFalse(result.ok)
        self.assertIn("шлях", str(result.output).lower())


class TestMmprojSafety(unittest.TestCase):
    """Проєктор зору не має робити модель незавантажуваною.

    Реальний збій (2026-11-09): ``--image-min-tokens 1600`` для Ministral
    3 14B дає

        clip_init: failed to load model '…mmproj.gguf':
        load_hparams: image_max_pixels (802816) is less than
                      image_min_pixels (1254400)

    і сервер не стартує ВЗАГАЛІ. Перевірено: 1024 працює, 1600 — ні.
    """

    def test_default_is_safe(self) -> None:
        from blackchpok_ide import runtime as rt

        folder = Path(tempfile.mkdtemp(prefix="bchp-proj-"))
        projector = folder / "mmproj-test.gguf"
        projector.write_bytes(b"GGUF")      # прапорець додається лише для наявного файлу
        config = rt.ServerConfig(model_path="m.gguf",
                                 mmproj_path=str(projector))
        self.assertLessEqual(config.image_min_tokens, 1024,
                             "1024 — перевірене безпечне значення")
        command = config.command()
        self.assertIn("--image-min-tokens", command)
        index = command.index("--image-min-tokens")
        self.assertLessEqual(int(command[index + 1]), 1024)

    def test_mmproj_failure_is_recognised(self) -> None:
        from blackchpok_ide import runtime as rt

        self.assertTrue(rt.is_mmproj_failure(
            "load_hparams: image_max_pixels (802816) is less than "
            "image_min_pixels (1605632)"))
        self.assertTrue(rt.is_mmproj_failure(
            "mtmd_init_from_file: error: Failed to load CLIP model"))
        self.assertFalse(rt.is_mmproj_failure("CUDA error: unknown error"),
                         "збій GPU не є збоєм проєктора")

    def test_text_only_retry_without_projector(self) -> None:
        """При збої проєктора сервер має спробувати запуск БЕЗ нього."""
        source = (ROOT / "blackchpok_ide" / "runtime.py").read_text(encoding="utf-8")
        body = source[source.index("def launch_with_recovery"):]
        self.assertIn("is_mmproj_failure", body,
                      "збій проєктора мусить оброблятись окремо")
        self.assertIn('mmproj_path=""', body,
                      "має бути повторний запуск без проєктора (текстовий режим)")


def _registry():
    from blackchpok_ide.agent_tools import ToolRegistry

    return ToolRegistry(ROOT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
