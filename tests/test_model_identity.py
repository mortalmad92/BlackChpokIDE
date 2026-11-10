"""Тест: IDE правильно визначає модель, контекст і підхоплює сервер.

Регресії, знайдені на живому прогоні:
* локальна модель на 127.0.0.1 показувалась як «хмара», щойно в
  налаштуваннях лишався запис хмарного провайдера;
* смуга контексту показувала 8192 замість фактичних 16384.

Запуск: python -m unittest tests.test_model_identity -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestModelKind(unittest.TestCase):
    """Вид моделі визначається адресою, а не залишками налаштувань."""

    def _summary(self, base_url: str, model: str = "qwen2.5-coder-14b",
                 cloud_provider: str = ""):
        from blackchpok_ide.main_window import BlackChpokIDE

        settings = SimpleNamespace(
            llm=SimpleNamespace(model=model, base_url=base_url, api_key="local"),
            cloud=SimpleNamespace(provider=cloud_provider),
        )
        host = SimpleNamespace(
            settings=settings,
            _server_alive=lambda: True,
        )
        return BlackChpokIDE._model_summary(host)

    def test_localhost_is_local_even_with_cloud_config(self) -> None:
        """127.0.0.1 — локальна, навіть якщо в налаштуваннях є хмара."""
        name, kind = self._summary("http://127.0.0.1:8080/v1",
                                   cloud_provider="deepseek")
        self.assertEqual(name, "qwen2.5-coder-14b")
        self.assertIn("локальна", kind, kind)

    def test_localhost_variants(self) -> None:
        for url in ("http://localhost:1234/v1", "http://127.0.0.1:11434/v1",
                    "http://[::1]:8080/v1"):
            _name, kind = self._summary(url)
            self.assertIn("локальна", kind, f"{url} → {kind}")

    def test_lan_address_is_local(self) -> None:
        _name, kind = self._summary("http://192.168.1.50:8080/v1")
        self.assertIn("локальна", kind, kind)

    def test_remote_is_cloud(self) -> None:
        _name, kind = self._summary("https://api.deepseek.com/v1",
                                    cloud_provider="deepseek")
        self.assertIn("хмара", kind, kind)

    def test_no_model_is_reported_honestly(self) -> None:
        name, kind = self._summary("http://127.0.0.1:8080/v1", model="")
        self.assertEqual(name, "не вибрана")
        self.assertIn("вибрати", kind)


class TestContextLimit(unittest.TestCase):
    """Ліміт контексту береться з реального джерела, не з константи."""

    def test_server_props_are_parsed(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._server_context_limit)
        self.assertIn("/props", source)
        self.assertIn("n_ctx", source)

    def test_limit_prefers_settings_then_server(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._apply_context_limit)
        self.assertLess(source.index("engine.ctx_size"),
                        source.index("_server_context_limit"),
                        "спершу налаштування, далі живий сервер")
        # Жорсткої вісімки як ЄДИНОГО значення бути не повинно.
        self.assertIn("if not limit:", source)
        self.assertNotIn("or 8192\n        try:", source)


class TestEngineSupportsFlags(unittest.TestCase):
    """Усі прапорці, які ми передаємо рушію, мають бути ним підтримані."""

    def test_launch_args_are_known_flags(self) -> None:
        from blackchpok_ide import hardware, runtime

        plan = hardware.LaunchPlan(gpu_layers=999, ctx_size=16384, threads=8,
                                   cache_type="q8_0", kv_in_ram=True)
        args = runtime.ServerConfig(model_path="m.gguf", plan=plan).command()
        known = {
            "--model", "--host", "--port", "--api-key", "--jinja",
            "--no-webui", "--alias", "--n-gpu-layers", "--ctx-size",
            "--threads", "--batch-size", "--parallel", "--flash-attn",
            "--cache-type-k", "--cache-type-v", "--no-kv-offload",
        }
        flags = {item for item in args if str(item).startswith("--")}
        unknown = flags - known
        self.assertFalse(unknown, f"невідомі прапорці: {unknown}")

    def test_model_path_is_absolute(self) -> None:
        """Відносний шлях ламав запуск: рушій стартує з іншої теки."""
        import inspect

        from blackchpok_ide import runtime

        source = inspect.getsource(runtime.LocalServer.start)
        self.assertIn("resolve()", source,
                      "шлях до моделі має ставати абсолютним")


class TestCallbacksBind(unittest.TestCase):
    """Колбеки, які передають у ``safe.call_quiet``, мають приймати аргументи.

    Регресія: ``_after_task_finished`` викликав
    ``safe.call_quiet(self.chat.advance_stage, ok)`` позиційно, а метод
    оголошено як ``advance_stage(self, *, ok)``. ``safe`` ковтає TypeError,
    тому етапи не рухались зовсім — і це було видно лише в журналі
    прихованих збоїв.
    """

    def test_advance_stage_accepts_keyword(self) -> None:
        import inspect

        from blackchpok_ide.chat_panel import ChatPanel

        signature = inspect.signature(ChatPanel.advance_stage)
        signature.bind(None, ok=True)      # має не кинути TypeError

    def test_finish_stages_accepts_keyword(self) -> None:
        import inspect

        from blackchpok_ide.chat_panel import ChatPanel

        signature = inspect.signature(ChatPanel.finish_stages)
        signature.bind(None, ok=True)

    def test_main_window_passes_ok_as_keyword(self) -> None:
        import inspect

        from blackchpok_ide.main_window import BlackChpokIDE

        source = inspect.getsource(BlackChpokIDE._after_task_finished)
        self.assertIn("advance_stage, ok=ok", source,
                      "ok треба передавати ключем, інакше TypeError")


if __name__ == "__main__":
    unittest.main(verbosity=2)
