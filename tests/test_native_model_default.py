"""Регресії «модель працює всередині IDE».

Три дефекти, знайдені на скріншоті користувача («локальна модель не
відповідає»), і кожен мав власну причину:

1. ``n_gpu_layers = 999`` — llama.cpp обриває завантаження з
   ``failed to fit params … set by user to 999, abort``. Правильне
   значення «усі шари» — ``-1``.
2. ``engine.native = False`` за замовчуванням — IDE йшла через зовнішній
   ``llama-server`` і залежала від стороннього сервісу.
3. ``ToolCallParser`` вирізав JSON-виклик із тексту, і агент отримував
   ``tool_calls = []``: модель «розмовляла» замість роботи.

Тести навмисно НЕ піднімають модель: вони перевіряють логіку, яка ламалась,
і виконуються за секунди.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from blackchpok_ide import config, hardware
from blackchpok_ide.native import chatfmt

ROOT = Path(__file__).resolve().parent.parent


def _profile(vram_gb: float = 12.0, ram_gb: float = 64.0):
    """Профіль заліза з відомою карткою — без звернення до nvidia-smi."""
    gpu = hardware.GpuInfo(name="Test GPU", vram_gb=vram_gb, vendor="nvidia",
                           backend="cuda", driver="1")
    return hardware.HardwareProfile(
        os_name="Windows", arch="AMD64", cpu_name="Test CPU",
        cpu_cores=6, cpu_threads=12, ram_total_gb=ram_gb,
        ram_available_gb=ram_gb, gpus=[gpu], disk_free_gb=100.0,
        disk_total_gb=200.0)


class TestFullOffloadValue(unittest.TestCase):
    """«Усі шари» — це ``-1``, а не ``999``."""

    def test_full_offload_constant_is_minus_one(self) -> None:
        self.assertEqual(hardware.FULL_OFFLOAD, -1)

    def test_gpu_plan_uses_minus_one(self) -> None:
        choice = next(c for c in hardware.MODEL_CATALOG if "Ministral" in c.label)
        fit = hardware.fit(_profile(), choice)
        self.assertEqual(fit.speed, "gpu")
        self.assertEqual(
            fit.plan.gpu_layers, hardware.FULL_OFFLOAD,
            "план має просити -1: з 999 llama.cpp обриває завантаження")

    def test_plan_args_never_ask_999(self) -> None:
        choice = next(c for c in hardware.MODEL_CATALOG if "Ministral" in c.label)
        args = hardware.fit(_profile(), choice).plan.args()
        self.assertNotIn("999", args,
                         "999 у --n-gpu-layers змушує llama.cpp перервати старт")

    def test_context_never_exceeds_fit(self) -> None:
        """План не має обіцяти контекст, який не влазить у VRAM."""
        choice = next(c for c in hardware.MODEL_CATALOG if "Ministral" in c.label)
        fit = hardware.fit(_profile(), choice)
        need = (choice.approx_gb
                + hardware.kv_cache_gb(choice, fit.plan.ctx_size) / 2
                + hardware.RUNTIME_OVERHEAD_GB)
        self.assertLessEqual(
            need, _profile().vram_budget_gb + 0.01,
            f"контекст {fit.plan.ctx_size} вимагає {need:.2f} ГБ — більше за бюджет")


class TestNativeIsDefault(unittest.TestCase):
    """Модель типово працює в процесі IDE, без сторонніх сервісів."""

    def test_native_enabled_by_default(self) -> None:
        self.assertTrue(config.EngineSettings().native,
                        "власний рушій — типовий шлях, а не опція")

    def test_default_url_is_embedded(self) -> None:
        url = config.LLMSettings().base_url
        self.assertTrue(
            url.startswith("native://"),
            f"типова адреса має бути вбудованим рушієм, а не {url}")

    def test_normalise_keeps_embedded_scheme(self) -> None:
        settings = config.LLMSettings(base_url="native://blackchpok").normalise()
        self.assertEqual(settings.base_url, "native://blackchpok",
                         "до native:// не можна дописувати /v1")

    def test_no_foreign_default_port(self) -> None:
        """Типові налаштування не мають вказувати на чужий сервіс."""
        settings = config.LLMSettings()
        for marker in ("1234", "11434", "8080"):
            self.assertNotIn(
                marker, settings.base_url,
                f"типова адреса не має залежати від стороннього сервісу ({marker})")


class TestToolCallsFindHiddenJson(unittest.TestCase):
    """Виклик інструмента шукаємо там, де він справді лежить."""

    def test_parser_text_holds_the_call(self) -> None:
        """``ToolCallParser.text`` зберігає вирізаний JSON — саме його й шукаємо.

        Це той самий сценарій, що ламався: у ``text_parts`` лишався
        «безпечний» текст без виклику, і ``_extract_calls`` нічого не
        знаходив.
        """
        parser = chatfmt.ToolCallParser(known={"list_dir"})
        shown = parser.feed('Дам відповідь. {"tool": "list_dir", '
                            '"arguments": {"path": "blackchpok_ide"}} Готово.')
        self.assertNotIn("list_dir", shown, "сирий JSON не показуємо користувачу")
        calls = chatfmt.extract_tool_calls(parser.text, known={"list_dir"})
        self.assertEqual(len(calls), 1, "виклик має знаходитись у parser.text")
        self.assertEqual(calls[0].name, "list_dir")
        self.assertEqual(calls[0].arguments.get("path"), "blackchpok_ide")

    def test_engine_searches_parser_text(self) -> None:
        """Регресія на причину: джерело пошуку має бути ``parser.text``."""
        source = (ROOT / "blackchpok_ide" / "native" / "engine.py").read_text(
            encoding="utf-8")
        self.assertIn("tool_parser.text", source,
                      "engine.py має шукати виклик у tool_parser.text")

    def test_openai_shape_recovered(self) -> None:
        raw = '{"name": "read_file", "arguments": {"path": "main.py"}}'
        calls = chatfmt.extract_tool_calls(raw, known={"read_file"})
        self.assertEqual(len(calls), 1)
        payload = calls[0].to_openai()
        self.assertEqual(payload["type"], "function")
        self.assertEqual(payload["function"]["name"], "read_file")
        self.assertIn("main.py", payload["function"]["arguments"])


class TestRecoveryPlanMonotonic(unittest.TestCase):
    """Крок відновлення не може вимагати більше, ніж попередній."""

    def test_full_offload_rank_is_highest(self) -> None:
        from blackchpok_ide import runtime

        full = hardware.LaunchPlan(gpu_layers=-1, ctx_size=8192, threads=8)
        hybrid = hardware.LaunchPlan(gpu_layers=24, ctx_size=8192, threads=8)
        self.assertGreater(runtime._layer_rank(full, 40),
                           runtime._layer_rank(hybrid, 40),
                           "-1 означає «усі шари», тобто найбільший offload")


if __name__ == "__main__":
    unittest.main(verbosity=2)
