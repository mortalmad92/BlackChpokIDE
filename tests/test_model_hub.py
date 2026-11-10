"""Тести хабу моделей, заліза й рушія (без мережі та без графіки).

Мережеві функції перевіряються з підміненими відповідями, тому тести
проходять офлайн і швидко.

Запуск:
    .venv\\Scripts\\python.exe -m unittest tests.test_model_hub -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide import hardware as hw  # noqa: E402
from blackchpok_ide import model_hub as hub  # noqa: E402
from blackchpok_ide import runtime as rt  # noqa: E402
from blackchpok_ide.agent_tools import TOOL_SCHEMAS  # noqa: E402
from blackchpok_ide.llm_client import extract_tool_calls, strip_tool_json  # noqa: E402


def fake_profile(vram: float = 0.0, ram: float = 16.0, threads: int = 8) -> hw.HardwareProfile:
    profile = hw.HardwareProfile(
        cpu_name="Test CPU",
        cpu_cores=max(1, threads // 2),
        cpu_threads=threads,
        ram_total_gb=ram,
        ram_available_gb=ram * 0.8,
        disk_free_gb=200.0,
    )
    if vram:
        profile.gpus = [hw.GpuInfo(name="Test GPU", vram_gb=vram, vendor="nvidia", backend="cuda")]
    return profile


# ─────────────────────────────────────────────────────────────────────────────
# Залізо
# ─────────────────────────────────────────────────────────────────────────────

class TestHardware(unittest.TestCase):
    def test_detect_returns_profile(self) -> None:
        profile = hw.detect(ROOT)
        self.assertGreater(profile.ram_total_gb, 0)
        self.assertGreater(profile.cpu_threads, 0)
        self.assertGreater(profile.disk_total_gb, 0)
        self.assertIn(profile.backend, {"cuda", "rocm", "vulkan", "cpu"})

    def test_recommend_scales_with_hardware(self) -> None:
        weak = hw.recommend(fake_profile(vram=0, ram=8))
        strong = hw.recommend(fake_profile(vram=24, ram=64))
        self.assertLessEqual(weak.params_b, strong.params_b)

    def test_recommended_model_fits(self) -> None:
        for vram, ram in ((0, 8), (4, 8), (8, 16), (12, 32), (24, 64)):
            profile = fake_profile(vram=vram, ram=ram)
            choice = hw.recommend(profile)
            fitted = hw.fit(profile, choice)
            # Без GPU швидкість «cpu» — це очікувано, а не помилка вибору.
            if vram:
                self.assertTrue(fitted.is_speed_ok, f"{vram}/{ram}: {choice.label} -> {fitted.speed}")
            self.assertGreaterEqual(fitted.plan.ctx_size, hw.MIN_CTX)
            self.assertLessEqual(choice.approx_gb, profile.usable_gb + 0.01)

    def test_small_gpu_does_not_claim_full_offload(self) -> None:
        """Модель, більша за VRAM, не повинна вважатися «повністю на GPU»."""
        profile = fake_profile(vram=6, ram=32)
        big = hw.MODEL_CATALOG[-1]
        fitted = hw.fit(profile, big)
        self.assertFalse(fitted.fits_vram)
        self.assertNotEqual(fitted.speed, "gpu")

    def test_cpu_only_uses_no_gpu_layers(self) -> None:
        profile = fake_profile(vram=0, ram=16)
        fitted = hw.fit(profile, hw.MODEL_CATALOG[2])
        self.assertEqual(fitted.plan.gpu_layers, 0)
        self.assertEqual(fitted.speed, "cpu")
        self.assertEqual(fitted.plan.flash_attn, "off")

    def test_kv_cache_grows_with_context(self) -> None:
        choice = hw.MODEL_CATALOG[4]
        self.assertLess(hw.kv_cache_gb(choice, 4096), hw.kv_cache_gb(choice, 16384))

    def test_summary_mentions_budget(self) -> None:
        text = fake_profile(vram=8, ram=16).summary()
        self.assertIn("Test GPU", text)
        self.assertIn("модель", text)

    def test_to_dict_has_derived_values(self) -> None:
        data = fake_profile(vram=8, ram=16).to_dict()
        self.assertIn("usable_gb", data)
        self.assertEqual(data["backend"], "cuda")
        self.assertEqual(data["vram_gb"], 8)


# ─────────────────────────────────────────────────────────────────────────────
# Хаб: розбір імен і посилань
# ─────────────────────────────────────────────────────────────────────────────

class TestHubParsing(unittest.TestCase):
    def test_parse_ref_variants(self) -> None:
        self.assertEqual(hub.parse_ref("Qwen/Qwen3-4B-GGUF"), "Qwen/Qwen3-4B-GGUF")
        self.assertEqual(hub.parse_ref("https://huggingface.co/Qwen/Qwen3-4B-GGUF"), "Qwen/Qwen3-4B-GGUF")
        self.assertEqual(hub.parse_ref("https://huggingface.co/Qwen/Qwen3-4B-GGUF/tree/main"),
                         "Qwen/Qwen3-4B-GGUF")
        self.assertEqual(hub.parse_ref("hf.co/Qwen/Qwen3-4B-GGUF"), "Qwen/Qwen3-4B-GGUF")
        self.assertEqual(hub.parse_ref("  "), "")

    def test_quant_detection(self) -> None:
        self.assertEqual(hub.quant_of("model-Q4_K_M.gguf"), "q4_k_m")
        self.assertEqual(hub.quant_of("model-q8_0.gguf"), "q8_0")
        self.assertEqual(hub.quant_of("model.gguf"), "")

    def test_multipart_detection(self) -> None:
        self.assertTrue(hub.is_multipart("m-00002-of-00004.gguf"))
        self.assertFalse(hub.is_multipart("m-q4_k_m.gguf"))

    def test_pick_best_prefers_q4_k_m_and_whole_files(self) -> None:
        chosen = hub.pick_best_gguf([
            "m-q8_0.gguf",
            "m-q4_k_m-00001-of-00002.gguf",
            "m-q4_k_m.gguf",
        ])
        self.assertEqual(chosen, "m-q4_k_m.gguf")

    def test_pick_best_empty(self) -> None:
        self.assertEqual(hub.pick_best_gguf([]), "")
        self.assertEqual(hub.pick_best_gguf(["readme.md"]), "")

    def test_safe_filename_strips_forbidden(self) -> None:
        self.assertEqual(hub.safe_filename('a:b/c*?.gguf'), "a_b_c__.gguf")
        self.assertEqual(hub.safe_filename(""), "model.gguf")

    def test_source_availability(self) -> None:
        available, _ = hub.source_available("huggingface")
        self.assertTrue(available)
        unavailable, note = hub.source_available("tensorart")
        self.assertFalse(unavailable)
        self.assertIn("API", note)

    def test_tensorart_returns_empty_not_fake(self) -> None:
        self.assertEqual(hub.search_tensorart("anything"), [])


class TestHubParsingResponses(unittest.TestCase):
    """Розбір відповідей API без реальних запитів."""

    def test_huggingface_list_parsed(self) -> None:
        payload = [
            {
                "id": "Qwen/Qwen3-4B-GGUF",
                "downloads": 1000,
                "likes": 50,
                "tags": ["gguf", "base_model:Qwen/Qwen3-4B"],
                "siblings": [{"rfilename": "Qwen3-4B-Q4_K_M.gguf"},
                             {"rfilename": "Qwen3-4B-Q8_0.gguf"}],
            }
        ]
        original = hub.fetch_json
        hub.fetch_json = lambda *a, **k: payload
        try:
            hits = hub.search_huggingface("qwen3", limit=5, with_sizes=0)
        finally:
            hub.fetch_json = original
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit.model_id, "Qwen/Qwen3-4B-GGUF")
        self.assertEqual(hit.filename, "Qwen3-4B-Q4_K_M.gguf")
        self.assertEqual(hit.base_model, "Qwen3-4B")
        self.assertEqual(hit.source, "huggingface")
        self.assertTrue(hit.download_url.endswith("Qwen3-4B-Q4_K_M.gguf"))

    def test_civitai_list_parsed(self) -> None:
        payload = {
            "items": [
                {
                    "id": 123,
                    "name": "Test LoRA",
                    "type": "LORA",
                    "description": "<p>Hello &amp; bye</p>",
                    "stats": {"downloadCount": 5000, "thumbsUpCount": 300},
                    "tags": ["anime"],
                    "modelVersions": [
                        {
                            "baseModel": "SDXL 1.0",
                            "files": [{"name": "test.safetensors", "sizeKB": 2048,
                                       "primary": True,
                                       "downloadUrl": "https://civitai.com/api/download/models/1"}],
                        }
                    ],
                }
            ]
        }
        original = hub.fetch_json
        hub.fetch_json = lambda *a, **k: payload
        try:
            hits = hub.search_civitai("anime", limit=5)
        finally:
            hub.fetch_json = original
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit.name, "Test LoRA")
        self.assertEqual(hit.base_model, "SDXL 1.0")
        self.assertGreater(hit.size_bytes, 0)
        self.assertNotIn("<p>", hit.description)

    def test_github_search_parsed(self) -> None:
        payload = {"items": [{"full_name": "ggml-org/llama.cpp", "stargazers_count": 100,
                              "description": "LLM inference", "html_url": "https://github.com/x"}]}
        original = hub.fetch_json
        hub.fetch_json = lambda *a, **k: payload
        try:
            hits = hub.search_github("llama", limit=3)
        finally:
            hub.fetch_json = original
        self.assertEqual(hits[0].model_id, "ggml-org/llama.cpp")
        self.assertEqual(hits[0].kind, "repo")

    def test_errors_are_wrapped(self) -> None:
        original = hub.fetch_json

        def boom(*_a, **_k):
            raise hub.HubError("HTTP 404: Not Found")

        hub.fetch_json = boom
        try:
            with self.assertRaises(hub.HubError):
                hub.search_huggingface("nothing-here", limit=1, with_sizes=0)
        finally:
            hub.fetch_json = original

    def test_search_job_collects_errors(self) -> None:
        original = hub._search_one
        hub._search_one = lambda source, query, limit: (_ for _ in ()).throw(hub.HubError("offline"))
        try:
            job = hub.SearchJob("x", sources=("huggingface",))
            hits = job.run_blocking(timeout=5)
        finally:
            hub._search_one = original
        self.assertEqual(hits, [])
        self.assertIn("huggingface", job.errors)


class TestRuntimePlanning(unittest.TestCase):
    RELEASES = [
        {
            "tag": "b100",
            "assets": [
                {"name": "llama-b100-bin-win-cpu-x64.zip", "size": 20, "url": "u1"},
                {"name": "llama-b100-bin-win-vulkan-x64.zip", "size": 30, "url": "u2"},
                {"name": "llama-b100-bin-win-cuda-13.4-x64.zip", "size": 40, "url": "u3"},
                {"name": "cudart-llama-bin-win-cuda-13.4-x64.zip", "size": 50, "url": "u4"},
            ],
        }
    ]

    def test_cuda_needs_two_archives(self) -> None:
        assets = rt.choose_assets(self.RELEASES, "cuda")
        self.assertEqual(len(assets), 2)
        self.assertEqual({a["name"] for a in assets},
                         {"llama-b100-bin-win-cuda-13.4-x64.zip",
                          "cudart-llama-bin-win-cuda-13.4-x64.zip"})

    def test_cpu_and_vulkan_single_archive(self) -> None:
        self.assertEqual(len(rt.choose_assets(self.RELEASES, "cpu")), 1)
        self.assertEqual(len(rt.choose_assets(self.RELEASES, "vulkan")), 1)

    def test_missing_backend_returns_empty(self) -> None:
        self.assertEqual(rt.choose_assets(self.RELEASES, "rocm"), [])

    def test_plan_falls_back_to_cpu(self) -> None:
        """Без профілю заліза план починається з Vulkan, а CPU лишається запасним."""
        no_gpu_releases = [
            {"tag": "b100", "assets": [
                {"name": "llama-b100-bin-win-cpu-x64.zip", "size": 20, "url": "u1"},
            ]},
        ]
        assets, tried = rt.plan_engine_install(None, releases=no_gpu_releases)
        self.assertEqual(tried, ["vulkan", "cpu"])
        self.assertEqual(assets[0]["name"], "llama-b100-bin-win-cpu-x64.zip")

        # Якщо Vulkan є — беремо його, і CPU навіть не пробуємо.
        assets2, tried2 = rt.plan_engine_install(None, releases=self.RELEASES)
        self.assertEqual(tried2, ["vulkan"])
        self.assertIn("vulkan", assets2[0]["name"])

    def test_backend_preference_ordering(self) -> None:
        profile = fake_profile(vram=12, ram=32)
        order = rt.backend_preference(profile)
        self.assertEqual(order[0], "cuda")
        self.assertIn("cpu", order)


class TestRuntimeServerConfig(unittest.TestCase):
    def test_command_contains_required_flags(self) -> None:
        plan = hw.LaunchPlan(gpu_layers=20, ctx_size=8192, threads=6)
        config = rt.ServerConfig(model_path="C:/m/model.gguf", port=8123, plan=plan, alias="my-model")
        command = config.command()
        self.assertIn("--model", command)
        self.assertIn("C:/m/model.gguf", command)
        self.assertIn("--jinja", command)
        self.assertIn("--alias", command)
        self.assertIn("my-model", command)
        self.assertIn("--n-gpu-layers", command)
        self.assertIn("8192", command)

    def test_base_url(self) -> None:
        config = rt.ServerConfig(model_path="x", port=9100)
        server = rt.LocalServer(config)
        self.assertEqual(server.base_url, "http://127.0.0.1:9100/v1")

    def test_free_port_is_bindable(self) -> None:
        import socket

        port = rt.free_port(9500)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))  # не падає — порт справді вільний


# ─────────────────────────────────────────────────────────────────────────────
# Відновлення викликів інструментів із тексту
# ─────────────────────────────────────────────────────────────────────────────

class TestToolCallTextRecovery(unittest.TestCase):
    def test_json_code_block(self) -> None:
        content = '```json\n{"name": "list_dir", "arguments": {"path": "."}}\n```'
        calls = extract_tool_calls(content, TOOL_SCHEMAS)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "list_dir")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"path": "."})

    def test_bare_object(self) -> None:
        calls = extract_tool_calls('{"name": "read_file", "arguments": {"path": "a.py"}}', TOOL_SCHEMAS)
        self.assertEqual(calls[0]["function"]["name"], "read_file")

    def test_tool_call_tag(self) -> None:
        calls = extract_tool_calls('<tool_call>{"name": "git_status", "arguments": {}}</tool_call>',
                                   TOOL_SCHEMAS)
        self.assertEqual(calls[0]["function"]["name"], "git_status")

    def test_nested_function_shape(self) -> None:
        calls = extract_tool_calls('{"function": {"name": "git_diff", "arguments": {}}}', TOOL_SCHEMAS)
        self.assertEqual(calls[0]["function"]["name"], "git_diff")

    def test_unknown_tool_ignored(self) -> None:
        self.assertEqual(extract_tool_calls('{"name": "rm_rf", "arguments": {}}', TOOL_SCHEMAS), [])

    def test_plain_text_ignored(self) -> None:
        self.assertEqual(extract_tool_calls("Просто відповідь без викликів.", TOOL_SCHEMAS), [])
        self.assertEqual(extract_tool_calls("", TOOL_SCHEMAS), [])

    def test_no_tools_no_calls(self) -> None:
        self.assertEqual(extract_tool_calls('{"name": "list_dir", "arguments": {}}', []), [])

    def test_strip_removes_json(self) -> None:
        stripped = strip_tool_json('Ось:\n```json\n{"name":"list_dir","arguments":{}}\n```\nГотово')
        self.assertIn("Готово", stripped)
        self.assertNotIn("list_dir", stripped)


class TestDownloadProgress(unittest.TestCase):
    def test_progress_percent_and_eta(self) -> None:
        state = hub.Progress(downloaded=512 * 1024, total=1024 * 1024, speed_bps=256 * 1024)
        self.assertAlmostEqual(state.percent, 50.0, places=1)
        self.assertIn("КБ/с", state.speed_text)
        self.assertTrue(state.eta_text)
        faster = hub.Progress(downloaded=0, total=10 * 1024 ** 3, speed_bps=5 * 1024 ** 2)
        self.assertIn("МБ/с", faster.speed_text)
        self.assertIn("хв", faster.eta_text)

    def test_progress_zero_total(self) -> None:
        state = hub.Progress(total=0)
        self.assertEqual(state.percent, 0.0)
        self.assertEqual(state.eta_text, "")

    def test_download_into_temp_dir(self) -> None:
        """Локальний файл через file:// — перевіряємо сам механізм запису."""
        import tempfile

        temp = Path(tempfile.mkdtemp(dir=str(ROOT / ".buildtmp")))
        try:
            source = temp / "source.bin"
            payload = b"x" * 200_000
            source.write_bytes(payload)
            seen: list[hub.Progress] = []
            target = temp / "target.bin"
            task = hub.Download(source.as_uri(), target, on_progress=seen.append,
                                expected_size=len(payload))
            self.assertTrue(task.run_blocking())
            self.assertTrue(target.exists())
            self.assertEqual(target.stat().st_size, len(payload))
            self.assertTrue(task.finished)
            self.assertTrue(seen)
        finally:
            import shutil

            shutil.rmtree(temp, ignore_errors=True)

    def test_complete_part_file_is_finalised(self) -> None:
        """Повний .part (докачка з нуля) має ставати готовим файлом, а не 416."""
        import tempfile

        temp = Path(tempfile.mkdtemp(dir=str(ROOT / ".buildtmp")))
        try:
            source = temp / "src.bin"
            payload = b"y" * 50_000
            source.write_bytes(payload)
            target = temp / "out.bin"
            part = target.with_suffix(target.suffix + ".part")
            part.write_bytes(payload)          # ніби все вже скачано
            task = hub.Download(source.as_uri(), target, expected_size=len(payload))
            self.assertTrue(task.run_blocking(), task.error)
            self.assertTrue(target.exists())
            self.assertEqual(target.stat().st_size, len(payload))
            self.assertFalse(part.exists())
        finally:
            import shutil

            shutil.rmtree(temp, ignore_errors=True)

    def test_truncated_part_reports_incomplete(self) -> None:
        """Обірваний .part не має вдавати успішне завантаження."""
        import tempfile

        temp = Path(tempfile.mkdtemp(dir=str(ROOT / ".buildtmp")))
        try:
            source = temp / "src.bin"
            source.write_bytes(b"z" * 1000)
            target = temp / "out.bin"
            task = hub.Download(source.as_uri(), target, expected_size=1000)
            # Імітуємо обрив: сервер віддає менше, ніж очікували.
            task.expected_size = 5000
            task.run_blocking()
            self.assertFalse(task.finished)
            self.assertIn("обірвано", task.error)
        finally:
            import shutil

            shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
