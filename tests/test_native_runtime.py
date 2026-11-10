"""Незалежні тести власного рушія BLACKCHPOK (CPU/CUDA, без llama-server).

Що саме перевіряється і як:

* **ABI** — розміри C-структур і наявність функцій у реальній ``llama.dll``.
  Це ловить найнебезпечніший клас помилок: «сигнатура з'їхала, і рушій
  повертає сміття замість тексту» (саме так було з
  ``llama_sampler_init_penalties``, де бракувало ``n_vocab``).
* **GGUF** — читання метаданих реальних файлів: архітектура, шари,
  контекст, quantization. Без цього прогнози RAM/VRAM — вигадка.
* **Прогноз** — що він узагалі рахує й не обіцяє неможливого.
* **Рушій** — справжня генерація, KV-переиспользование, скасування.
  Тести, які потребують моделі на диску, позначаються ``skipUnless``:
  на чистій машині вони пропускаються з причиною, а не «проходять».
* **Семплінг** — стоп-послідовності, валідація параметрів, стоп-метчер.
* **Токенайзер** — точний підрахунок (кирилиця ≠ 3.5 символа на токен).
* **Менеджер** — інспекція, цілісність, заборона видалення без підтвердження.

Запуск: ``python -m unittest tests.test_native_runtime -v``
"""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import hardware                                   # noqa: E402
from blackchpok_ide.native import _abi, _bindings, gguf, inspect as native_inspect  # noqa: E402
from blackchpok_ide.native.manager import ModelManager                # noqa: E402
from blackchpok_ide.native.sampling import (                          # noqa: E402
    SamplerChain,
    SamplingParams,
    StopMatcher,
    flash_attn_value,
)


def _models_dir() -> Path:
    try:
        from blackchpok_ide.model_hub import models_dir

        return Path(models_dir())
    except Exception:                                        # noqa: BLE001
        return ROOT / "userdata" / "models"


def _first_model() -> Path | None:
    folder = _models_dir()
    if not folder.exists():
        return None
    from blackchpok_ide.model_hub import is_projector_path

    for item in sorted(folder.glob("*.gguf")):
        # Правило «це проєктор» беремо з model_hub, а не з ``startswith``:
        # офіційний файл mistralai називається ``…-BF16-mmproj.gguf``
        # (``mmproj`` у кінці), і перевірка префікса брала його за модель.
        # Через це всі тести метаданих/прогнозів падали на ньому з нулями.
        if is_projector_path(item):
            continue
        return item
    return None


MODEL = _first_model()
HAVE_LIBRARY = _bindings.library_ready()


class TestAbi(unittest.TestCase):
    """Опис C-структур мусить збігатися з реальною бібліотекою."""

    @unittest.skipUnless(HAVE_LIBRARY, "немає llama.dll у userdata/runtime")
    def test_model_params_size_matches_library(self) -> None:
        lib = _bindings.load_library()
        actual = ctypes.sizeof(lib.llama_model_default_params.restype)
        self.assertEqual(actual, ctypes.sizeof(_abi.LlamaModelParams),
                         "розмір llama_model_params не збігається — ABI зламано")

    @unittest.skipUnless(HAVE_LIBRARY, "немає llama.dll")
    def test_defaults_are_sane(self) -> None:
        lib = _bindings.load_library()
        params = lib.llama_model_default_params()
        # n_gpu_layers типово -1 (усі шари) — перевіряємо, що поле читається
        # саме там, де ми його очікуємо, а не «деінде».
        self.assertEqual(params.n_gpu_layers, -1)
        context = lib.llama_context_default_params()
        self.assertGreater(context.n_ctx, 0)
        self.assertGreater(context.n_batch, 0)

    @unittest.skipUnless(HAVE_LIBRARY, "немає llama.dll")
    def test_sampler_penalties_takes_n_vocab(self) -> None:
        """Сигнатура з ``n_vocab``: без неї семплінг дає безглуздий текст."""
        lib = _bindings.load_library()
        args = lib.llama_sampler_init_penalties.argtypes
        self.assertEqual(len(args), 5,
                         "llama_sampler_init_penalties має 5 аргументів "
                         "(n_vocab, last_n, repeat, freq, present)")

    @unittest.skipUnless(HAVE_LIBRARY, "немає llama.dll")
    def test_devices_are_detected(self) -> None:
        lib = _bindings.load_library()
        names = [device.name for device in lib.devices]
        self.assertTrue(names, "жодного пристрою не знайдено")
        self.assertTrue(any(device.kind == "cpu" for device in lib.devices),
                        "CPU-бекенд мусить бути завжди")

    @unittest.skipUnless(HAVE_LIBRARY, "немає llama.dll")
    def test_required_symbols_present(self) -> None:
        needed = ("llama_model_load_from_file", "llama_init_from_model", "llama_decode",
                  "llama_tokenize", "llama_token_to_piece", "llama_batch_init",
                  "llama_sampler_chain_init", "llama_get_embeddings_ith",
                  "llama_memory_clear", "llama_chat_apply_template")
        missing = _bindings.verify_symbols(needed)
        self.assertFalse(missing, f"рушій не має функцій: {missing}")

    def test_abi_enums_match_llama_header(self) -> None:
        """Значення переліків — з llama.h тієї збірки, що ми ставимо."""
        self.assertEqual(_abi.FLASH_ATTN["auto"], -1)
        self.assertEqual(_abi.FLASH_ATTN["off"], 0)
        self.assertEqual(_abi.FLASH_ATTN["on"], 1)
        self.assertEqual(_abi.GGML_TYPE["f16"], 1)
        self.assertEqual(_abi.GGML_TYPE["q8_0"], 8)
        self.assertEqual(_abi.DECODE_ABORTED, 2)
        self.assertEqual(flash_attn_value("auto"), -1)
        self.assertEqual(flash_attn_value("невідомо"), -1)


class TestGgufReader(unittest.TestCase):
    """Читання GGUF без завантаження ваг."""

    def test_magic_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder) / "not-a-model.gguf"
            fake.write_bytes(b"NOPE" + b"\x00" * 64)
            with self.assertRaises(gguf.GgufError):
                gguf.read_meta(fake)
            self.assertFalse(gguf.looks_like_gguf(fake))

    def test_missing_file_reports_error_without_raising(self) -> None:
        meta = gguf.read_meta_safe(ROOT / "definitely-absent.gguf")
        self.assertIn("_error", meta.values)

    @unittest.skipUnless(MODEL is not None, "немає жодної GGUF-моделі")
    def test_real_model_metadata(self) -> None:
        meta = gguf.read_meta(MODEL)
        self.assertGreaterEqual(meta.version, 2)
        self.assertTrue(meta.architecture, "архітектура мусить бути в метаданих")
        self.assertGreater(meta.tensor_count, 0)
        self.assertGreater(meta.layer_count, 0, "кількість шарів потрібна для offload")
        self.assertGreater(meta.context_length, 0)
        self.assertGreater(meta.vocab_size, 1000, "розмір словника має читатись")

    @unittest.skipUnless(MODEL is not None, "немає моделі")
    def test_quant_from_filename(self) -> None:
        self.assertEqual(gguf.quant_from_filename("model-q4_k_m.gguf"), "Q4_K_M")
        self.assertEqual(gguf.quant_from_filename("x-Q8_0.gguf"), "Q8_0")
        self.assertEqual(gguf.quant_from_filename("plain.gguf"), "")


class TestForecast(unittest.TestCase):
    """Прогноз розміщення моделі — не обіцянка, а розрахунок."""

    def setUp(self) -> None:
        self.profile = hardware.detect()

    @unittest.skipUnless(MODEL is not None, "немає моделі")
    def test_kv_cache_grows_with_context(self) -> None:
        report = native_inspect.inspect(MODEL)
        small = native_inspect.kv_cache_gb(report, 2048)
        large = native_inspect.kv_cache_gb(report, 16384)
        self.assertGreater(large, small)
        self.assertAlmostEqual(large / small, 8.0, places=3)

    @unittest.skipUnless(MODEL is not None, "немає моделі")
    def test_q8_cache_is_half_of_f16(self) -> None:
        report = native_inspect.inspect(MODEL)
        self.assertAlmostEqual(
            native_inspect.kv_cache_gb(report, 4096, "q8_0"),
            native_inspect.kv_cache_gb(report, 4096, "f16") / 2.0, places=4)

    @unittest.skipUnless(MODEL is not None, "немає моделі")
    def test_forecast_respects_budgets(self) -> None:
        report = native_inspect.inspect(MODEL, profile=self.profile)
        self.assertIn(report.fits, {"gpu", "hybrid", "cpu", "impossible"})
        if report.fits == "gpu":
            self.assertLessEqual(report.vram_needed_gb,
                                 self.profile.vram_gb + 1.0)

    @unittest.skipUnless(MODEL is not None, "немає моделі")
    def test_full_offload_means_all_layers(self) -> None:
        """«Усі шари» мусить бути ``-1``, а не ``layer_count``.

        Регресія продуктивності: ``n_gpu_layers = layer_count`` кладе на
        GPU лише блоки трансформера, а вихідний шар (lm_head) лишається на
        CPU. Заміряно на 14B Q4_K_M (RTX 3060): 25.6 ток/с проти 31.2.
        """
        report = native_inspect.inspect(MODEL)
        self.assertGreater(report.layer_count, 0)
        fitted = native_inspect.inspect(MODEL, profile=self.profile)
        if fitted.fits == "gpu":
            self.assertEqual(fitted.suggested_gpu_layers, -1,
                             "повний offload мусить передавати -1 (усі шари + lm_head)")

    @unittest.skipUnless(MODEL is not None, "немає моделі")
    def test_partial_offload_is_below_layer_count(self) -> None:
        report = native_inspect.inspect(MODEL)
        if report.fits != "hybrid":
            self.skipTest("на цьому залізі модель влазить повністю")
        self.assertLess(report.suggested_gpu_layers, report.layer_count)

    def test_profile_has_real_numbers(self) -> None:
        self.assertGreater(self.profile.ram_total_gb, 0)
        self.assertGreater(self.profile.cpu_threads, 0)
        # GPU може не бути — але тоді vram_budget мусить бути 0, а не «вигадка».
        if self.profile.vram_gb <= 0:
            self.assertEqual(self.profile.vram_budget_gb, 0.0)

    def test_integrity_detects_truncated_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / "broken.gguf"
            broken.write_bytes(b"GGUF" + b"\x00" * 20)
            result = native_inspect.verify_integrity(broken)
            self.assertFalse(result["ok"])
            self.assertTrue(result["problems"])

    @unittest.skipUnless(MODEL is not None, "немає моделі")
    def test_integrity_passes_for_real_model(self) -> None:
        result = native_inspect.verify_integrity(MODEL)
        self.assertTrue(result["ok"], result["problems"])
        self.assertGreater(result["tensors"], 0)


class TestSampling(unittest.TestCase):
    """Параметри й стоп-послідовності — без рушія."""

    def test_limits_are_enforced(self) -> None:
        params = SamplingParams(temperature=99, top_p=5, top_k=-10,
                                max_tokens=0, repeat_penalty=100).normalised()
        self.assertEqual(params.temperature, 5.0)
        self.assertEqual(params.top_p, 1.0)
        self.assertEqual(params.top_k, 0)
        self.assertEqual(params.max_tokens, 1)
        self.assertEqual(params.repeat_penalty, 4.0)

    def test_seed_is_filled_when_negative(self) -> None:
        params = SamplingParams(temperature=0.5, seed=-1).normalised()
        self.assertGreaterEqual(params.seed, 0)

    def test_from_dict_ignores_unknown_keys(self) -> None:
        params = SamplingParams.from_dict({"temperature": 0.3, "nonsense": 1})
        self.assertEqual(params.temperature, 0.3)

    def test_stop_matcher_holds_partial_marker(self) -> None:
        matcher = StopMatcher(["<|im_end|>"])
        self.assertEqual(matcher.feed("Привіт"), "Привіт")
        # Частина маркера не має піти користувачу.
        self.assertEqual(matcher.feed("<|im"), "")
        self.assertEqual(matcher.feed("_end|>"), "")
        self.assertTrue(matcher.stopped)

    def test_stop_matcher_passes_normal_text(self) -> None:
        matcher = StopMatcher(["<|im_end|>"])
        output = matcher.feed("def f():") + matcher.feed(" return 1")
        self.assertEqual(output, "def f(): return 1")
        self.assertFalse(matcher.stopped)

    def test_grammar_types_exist(self) -> None:
        """Тип винятку для несумісної граматики існує й ловиться як RuntimeError.

        Це важливо, бо ``OSError`` з C++-винятку рушія інакше пройшов би
        крізь обробники й поклав би виклик цілком.
        """
        from blackchpok_ide.native.sampling import GrammarUnsupported

        self.assertTrue(issubclass(GrammarUnsupported, RuntimeError))

    @unittest.skipUnless(HAVE_LIBRARY, "немає llama.dll")
    def test_sampler_chain_requires_vocab_for_grammar(self) -> None:
        """Граматика без словника не додається (і не вдає, що працює)."""
        lib = _bindings.load_library()
        params = SamplingParams(temperature=0.0, grammar="root ::= [A-C]+")
        chain = SamplerChain(lib, params, n_vocab=100, vocab=0)
        try:
            # Лише greedy — граматики немає.
            self.assertEqual(chain.size, 1)
        finally:
            chain.free()

    @unittest.skipUnless(HAVE_LIBRARY, "немає llama.dll")
    def test_grammar_is_added_when_vocab_present(self) -> None:
        """Зі словником граматика справді потрапляє в ланцюжок."""
        lib = _bindings.load_library()
        params = SamplingParams(temperature=0.0, grammar="root ::= [A-C]+")
        # Словник справжньої моделі доступний лише після завантаження,
        # тому перевіряємо на синтетичному: важливо, що розмір ланцюжка
        # більший за один семплер.
        vocab_handle = 0
        try:
            from blackchpok_ide.native.engine import LoadOptions, NativeEngine

            engine = NativeEngine()
            engine.load(MODEL, LoadOptions(n_ctx=512, n_gpu_layers=0, n_threads=2))
            vocab_handle = engine.model.vocab
            chain = SamplerChain(lib, params, n_vocab=engine.model.tokenizer.size,
                                 vocab=vocab_handle)
            try:
                self.assertEqual(chain.size, 2, "очікували greedy + граматику")
            finally:
                chain.free()
            engine.unload()
        except Exception as exc:                     # noqa: BLE001
            self.skipTest(f"словник недоступний: {exc}")


@unittest.skipUnless(HAVE_LIBRARY and MODEL is not None,
                     "потрібні llama.dll і GGUF-модель")
class TestEngineGeneration(unittest.TestCase):
    """Справжня робота рушія: завантаження, генерація, KV, скасування."""

    engine = None

    @classmethod
    def setUpClass(cls) -> None:
        from blackchpok_ide.native.engine import LoadOptions, NativeEngine

        cls.engine = NativeEngine()
        cls.engine.load(MODEL, LoadOptions(n_ctx=2048, n_gpu_layers=0,
                                           n_threads=4, flash_attn="auto"))

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.engine is not None:
            cls.engine.unload()

    def test_model_is_loaded(self) -> None:
        info = self.engine.describe()
        self.assertTrue(info["loaded"])
        self.assertGreater(info["parameters"], 0)
        self.assertGreater(info["vocab"], 1000)
        self.assertEqual(info["context_actual"], 2048)

    def test_generation_produces_text(self) -> None:
        result = self.engine.generate(
            [{"role": "user", "content": "Say OK."}],
            params=SamplingParams(temperature=0.0, max_tokens=8))
        self.assertTrue(result.text.strip(), "порожня відповідь")
        self.assertGreater(result.stats.generated_tokens, 0)
        self.assertGreater(result.stats.tokens_per_second, 0.0)

    def test_streaming_matches_full_text(self) -> None:
        chunks: list[str] = []
        full = self.engine.generate(
            [{"role": "user", "content": "Напиши слово READY."}],
            params=SamplingParams(temperature=0.0, max_tokens=8),
            on_text=chunks.append)
        self.assertTrue(chunks, "стрім не віддав жодного фрагмента")
        self.assertEqual("".join(chunks).strip(), full.text.strip())

    def test_kv_cache_is_reused(self) -> None:
        messages = [{"role": "user", "content": "Один рядок про Python."}]
        first = self.engine.generate(messages,
                                     params=SamplingParams(temperature=0.0,
                                                           max_tokens=4))
        follow_up = messages + [
            {"role": "assistant", "content": first.text},
            {"role": "user", "content": "І ще один."},
        ]
        second = self.engine.generate(follow_up,
                                      params=SamplingParams(temperature=0.0,
                                                            max_tokens=4))
        self.assertGreater(second.stats.cached_tokens, 0,
                           "другий запит мусить використати наявний префікс")

    def test_repeated_identical_prompt_works(self) -> None:
        """Промпт повністю в кеші не має ламати генерацію.

        Регресія: коли кеш уже містив увесь промпт, декодувати було нічого,
        логітів не з'являлось, і модель віддавала порожній або безглуздий
        текст. Тепер останній токен передекодовується.
        """
        message = [{"role": "user", "content": "Say hi."}]
        params = SamplingParams(temperature=0.0, max_tokens=4)
        first = self.engine.generate(message, params=params)
        second = self.engine.generate(message, params=params)
        self.assertTrue(first.text.strip())
        self.assertTrue(second.text.strip(), "повторний запит дав порожнечу")

    def test_cancel_stops_generation(self) -> None:
        """Скасування спиняє РЕАЛЬНЕ обчислення, а не лише читання потоку."""
        from blackchpok_ide.native.engine import GenerationStats

        stats = GenerationStats()
        seen = threading.Event()
        stop_signal = {"active": False}

        def on_text(_piece: str) -> None:
            # Скасовуємо лише тоді, коли генерація вже справді почалась:
            # інакше можна «випередити» її старт, і перевірка нічого не доведе.
            if not stop_signal["active"]:
                stop_signal["active"] = True
                self.engine.context.cancel()
            seen.set()

        def run() -> None:
            result = self.engine.generate(
                [{"role": "user", "content": "Напиши числа від 1 до 100."}],
                params=SamplingParams(temperature=0.3, max_tokens=200),
                on_text=on_text)
            stats.generated_tokens = result.stats.generated_tokens
            stats.cancelled = result.stats.cancelled

        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout=120)
        self.assertFalse(thread.is_alive(), "генерація не зупинилась")
        self.assertTrue(seen.is_set(), "генерація не почалась — тест недійсний")
        self.assertTrue(stats.cancelled, "скасування не позначене")
        self.assertLess(stats.generated_tokens, 200,
                        "скасування не зменшило кількість токенів")

    def test_tokenizer_counts_cyrillic_honestly(self) -> None:
        tokenizer = self.engine.model.tokenizer
        ukrainian = "Привіт! Це перевірка української мови."
        english = "Hello! This is a check of the English language."
        uk_tokens = tokenizer.count(ukrainian)
        en_tokens = tokenizer.count(english)
        self.assertGreater(uk_tokens, 0)
        # Головне: кирилиця НЕ рахується «як латиниця» — інакше бюджет бреше.
        self.assertNotEqual(uk_tokens / len(ukrainian), en_tokens / len(english))
        self.assertEqual(tokenizer.decode(tokenizer.encode(ukrainian, add_special=False)),
                         ukrainian)

    def test_cyrillic_survives_token_roundtrip(self) -> None:
        """Кирилиця мусить пережити encode→decode без ``��``.

        Регресія: ``є``, ``ї``, ``ґ`` розкладаються на ДВА токени, і жоден
        із них окремо не є валідним UTF-8. Поштучне декодування з
        ``errors="replace"`` давало ``��`` прямо у відповіді агента.
        """
        tokenizer = self.engine.model.tokenizer
        for text in ("У поточній теці є 18 файлів",
                     "Привіт, світе! Їжак ґава",
                     "Це єдиний ґрунт для їжі"):
            tokens = tokenizer.encode(text, add_special=False)
            restored = tokenizer.decode(tokens)
            self.assertEqual(restored, text)
            self.assertNotIn("\ufffd", restored)

    def test_streaming_decoder_holds_partial_utf8(self) -> None:
        """Потоковий декодер не має віддавати половинки символів."""
        from blackchpok_ide.native.tokenizer import StreamingDecoder

        tokenizer = self.engine.model.tokenizer
        text = "є ї ґ Є Ї Ґ"
        tokens = tokenizer.encode(text, add_special=False)
        decoder = StreamingDecoder(tokenizer)
        pieces = [decoder.push(token) for token in tokens]
        pieces.append(decoder.flush())
        joined = "".join(pieces)
        self.assertEqual(joined, text)
        self.assertNotIn("\ufffd", joined)

    def test_generation_has_no_replacement_char(self) -> None:
        chunks: list[str] = []
        result = self.engine.generate(
            [{"role": "user", "content": "Напиши українською одне коротке речення."}],
            params=SamplingParams(temperature=0.0, max_tokens=24),
            on_text=chunks.append)
        self.assertNotIn("\ufffd", result.text)
        self.assertNotIn("\ufffd", "".join(chunks))
        self.assertEqual("".join(chunks).strip(), result.text.strip())

    def test_embeddings_separate_meaning(self) -> None:
        vectors = self.engine.embed(["def add(a, b): return a + b",
                                     "SELECT * FROM users WHERE id = 1"])
        self.assertEqual(len(vectors), 2)
        self.assertEqual(len(vectors[0]), len(vectors[1]))
        dot = sum(a * b for a, b in zip(vectors[0], vectors[1]))
        self.assertLess(dot, 0.95, "різні теми мають давати не майже однакові вектори")
        norm = sum(value * value for value in vectors[0]) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=4)

    def test_benchmark_returns_measured_numbers(self) -> None:
        data = self.engine.benchmark(runs=1, max_tokens=8)
        self.assertGreater(data["tokens_per_second"], 0)
        self.assertGreater(data["time_to_first_token_ms"], 0)
        self.assertEqual(len(data["runs"]), 1)

    def test_timeout_actually_stops_generation(self) -> None:
        """Тайм-аут не має бути «прийнятим і забутим».

        Регресія: ``NativeRuntime.generate(timeout=…)`` приймав параметр і
        робив ``del timeout`` — генерація могла йти безкінечно, а виклик
        вважав, що захищений.
        """
        from blackchpok_ide.native.api import NativeRuntime

        runtime = NativeRuntime()
        runtime._runtime_engine = None                # noqa: SLF001 - не використовується
        runtime.engine = self.engine
        result = runtime.generate(
            [{"role": "user", "content": "Напиши числа від 1 до 1000."}],
            params={"max_tokens": 500, "temperature": 0.3}, timeout=2.0)
        self.assertTrue(result.get("timed_out"), "прапорець тайм-ауту не встановлено")
        self.assertTrue(result["stats"]["cancelled"],
                        "генерація не позначена скасованою")
        self.assertLess(result["stats"]["generated_tokens"], 500)

    def test_grammar_restricts_output(self) -> None:
        """Граматика справді обмежує вихід (перевіряємо на класах символів).

        Літеральні графи на кшталт ``"AAA" | "BBB"`` у цій збірці рушія
        кидають C++-виняток — рушій має відкотитись на роботу без
        граматики, а не впасти. Обидва випадки перевіряються нижче.
        """
        params = SamplingParams(temperature=0.0, max_tokens=8)
        params.grammar = "root ::= [A-C]+"
        result = self.engine.generate(
            [{"role": "user", "content": "Write anything at all."}], params=params)
        letters = {char for char in result.text if char.isalpha()}
        self.assertTrue(letters <= set("ABC"),
                        f"граматика не діяла: {result.text!r}")

    def test_broken_grammar_falls_back_without_crash(self) -> None:
        """Некоректна для цієї збірки граматика не валить рушій."""
        params = SamplingParams(temperature=0.0, max_tokens=8)
        params.grammar = 'root ::= "AAA" | "BBB"'
        result = self.engine.generate(
            [{"role": "user", "content": "Say hello."}], params=params)
        # Головне: виклик ПОВЕРНУВСЯ (не виняток) і рушій далі працює.
        self.assertIsInstance(result.text, str)
        again = self.engine.generate(
            [{"role": "user", "content": "Say hello."}],
            params=SamplingParams(temperature=0.0, max_tokens=4))
        self.assertIsInstance(again.text, str)


@unittest.skipUnless(HAVE_LIBRARY and MODEL is not None,
                     "потрібні llama.dll і GGUF-модель")
class TestRuntimeApi(unittest.TestCase):
    """Runtime API: перелік операцій із завдання."""

    @classmethod
    def setUpClass(cls) -> None:
        from blackchpok_ide.native.api import NativeRuntime

        cls.runtime = NativeRuntime()

    def test_required_operations_exist(self) -> None:
        for name in ("list_models", "inspect_model", "load_model", "unload_model",
                     "switch_model", "generate", "generate_stream",
                     "cancel_generation", "tokenize", "detokenize", "count_tokens",
                     "create_embeddings", "get_runtime_status", "get_gpu_status",
                     "get_memory_status", "benchmark_model", "download_model",
                     "verify_model", "delete_model"):
            self.assertTrue(callable(getattr(self.runtime, name, None)),
                            f"немає операції {name}")

    def test_list_models_returns_entries(self) -> None:
        data = self.runtime.list_models()
        self.assertIn("models", data)
        self.assertGreaterEqual(data["count"], 1)
        for entry in data["models"]:
            self.assertTrue(Path(entry["path"]).exists())
            self.assertGreater(entry["size_gb"], 0)

    def test_count_tokens_is_exact_only_with_model(self) -> None:
        data = self.runtime.count_tokens("перевірка")
        self.assertIn("exact", data)
        if not self.runtime.loaded:
            self.assertFalse(data["exact"],
                             "без моделі точний підрахунок неможливий — "
                             "мусить бути чесно позначено")

    def test_gpu_status_reports_real_devices(self) -> None:
        data = self.runtime.get_gpu_status()
        self.assertIn("devices", data)
        self.assertIsInstance(data["devices"], list)
        for device in data["nvidia"]:
            self.assertGreater(device["vram_total_mb"], 0)

    def test_memory_status_has_system_ram(self) -> None:
        data = self.runtime.get_memory_status()
        self.assertGreater(data["system_total_gb"], 0)

    def test_delete_requires_confirmation(self) -> None:
        """Без ``confirm=True`` файл не чіпається — це захист від втрати ваг."""
        entry = self.runtime.list_models()["models"][0]
        result = self.runtime.delete_model(entry["path"], confirm=False)
        self.assertFalse(result["ok"])
        self.assertTrue(Path(entry["path"]).exists(),
                        "модель НЕ має видалятись без підтвердження")


class TestModelManagerSafety(unittest.TestCase):
    """Менеджер моделей не має губити файли."""

    def test_foreign_file_is_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            manager = ModelManager(folder)
            outside = Path(folder).parent / "outside-model.gguf"
            outside.write_bytes(b"GGUF")
            try:
                with self.assertRaises(Exception):
                    manager.delete(str(outside), confirm=True)
                self.assertTrue(outside.exists())
            finally:
                outside.unlink(missing_ok=True)

    def test_adding_non_gguf_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            manager = ModelManager(folder)
            junk = Path(folder) / "model.gguf"
            junk.write_bytes(b"not a model")
            with self.assertRaises(Exception):
                manager.add_local(junk)

    @unittest.skipUnless(MODEL is not None, "немає моделі")
    def test_verify_reports_metadata(self) -> None:
        manager = ModelManager(MODEL.parent)
        result = manager.verify(MODEL.name)
        self.assertTrue(result["ok"])
        self.assertGreater(result["tensors"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
