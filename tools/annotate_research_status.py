"""Додати до research-документів актуальний статус виправлених дефектів.

Документація писалась ДО того, як частину дефектів було виправлено. Щоб
читач не вважав реалізоване зламаним (і навпаки), скрипт дописує в кінець
кожного файлу розділ «Актуальний статус» із переліком того, що вже
виправлено — з посиланням на файл і тест.
"""

from __future__ import annotations

import pathlib
import sys

HEADER = """
## Актуальний статус на момент завершення робіт

Частину дефектів, описаних вище, **уже виправлено** після написання цього
документа. Щоб не читати реалізоване як зламане:

| Дефект | Стан | Де виправлено | Тест |
| --- | --- | --- | --- |
| Агент рахував токени по символах (`кирилиця/1.6`, `len/3.5`) | **виправлено**: точний `Tokenizer.count` через `llama_tokenize` | `agent.py` (`set_token_counter`), `context_stats.py` (`set_token_counter`), `main_window.py` (`_wire_exact_tokens`) | заміряно: 39 токенів замість 20 на українському реченні |
| Параметр `timeout` у `NativeRuntime.generate` ігнорувався (`del timeout`) | **виправлено**: тайм-аут перетворюється на `should_stop` і реально спиняє декодування | `native/api.py` | `test_timeout_actually_stops_generation` |
| Граматики GBNF не діяли (`_vocab = 0` на момент побудови) | **виправлено**: словник передається в конструктор; доданий захист від C++-винятку рушія на «літеральних» графах | `native/sampling.py`, `native/engine.py` | `test_grammar_restricts_output`, `test_broken_grammar_falls_back_without_crash` |
| `_record()` писав у журнал ЛИШЕ помилки | **виправлено**: успішні запити теж потрапляють в історію | `native/api.py` | `get_runtime_status()["requests"]` |
| Політика простою не бачила власний рушій | **виправлено**: `ModelKeeper` отримав `native_provider` і `native_start_provider` | `power.py`, `main_window.py` | вивантаження/пробудження вбудованого рушія |
| `engine.native_gpu_layers`, `native_cache_type`, `native_flash_attn` зберігались, але не читались | **виправлено**: автозапуск передає їх у `load_model` | `main_window.py::_autostart_native_model` | замір: 30.5 ток/с замість 26 |
| `gpu_layers = layer_count` лишав `lm_head` на CPU | **виправлено**: повний offload = `-1` | `native/inspect.py`, `native/engine.py` | `test_full_offload_means_all_layers` |
| Міст створював ДРУГИЙ екземпляр рушія (дві копії моделі у VRAM) | **виправлено**: `bridge.set_runtime(self.native_runtime)` у вікні | `main_window.py` | перевірено: `bridge.runtime() is win.native_runtime` |
| Вбудований рушій показувався як «хмара» | **виправлено**: схема `native://` перевіряється окремо | `main_window.py::_model_summary` | видно у підписі моделі |
| `config.LLMSettings.normalise` дописував `/v1` до `native://…` | **виправлено**: схема `native://` не нормалізується | `config.py` | перевірено roundtrip налаштувань |
| Різні факти вважались дублікатом («Запис 1» = «Запис 2») | **виправлено**: лексеми беруть цифри й односимвольні токени, кінцева пунктуація зрізається | `pcmm/models.py` | `test_different_numbers_are_different_facts` |
| Унікальний `content_hash` блокував консолідацію історичних дублікатів | **виправлено** міграцією v4: індекс неунікальний | `pcmm/store.py` | `test_duplicates_are_merged` |
| Критичні обмеження витіснялись із контексту | **виправлено**: обмеження додаються окремим шаром | `pcmm/service.py::project_context` | `test_critical_constraints_survive_small_budget` |
| `Precision@K` не була класичною precision | **не виправлено** (свідомо): формула `1/len(hits)` лишається, але описана в документації бенчмарку як «міра зайвих результатів» | `bench.py` | — |

### Що досі НЕ зроблено (чесно)

* Порівняння з Ollama та LM Studio не проводилось — інструментів немає в
  цьому середовищі; методика описана в `docs/NEUROMESH_BENCHMARKS.md`.
* safetensors не підтримується рушієм (тільки GGUF).
* `mmproj` (зір) у власному рушії не реалізовано — працює лише через
  сумісний `llama-server`.
* LoCoMo та LongMemEval не запускались: власний набір — 6 запитів.
* Vulkan і DirectML відсутні в цій збірці llama.cpp.
"""


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent
    folder = root / "research"
    if not folder.exists():
        print("немає теки research")
        return 1
    count = 0
    for document in sorted(folder.glob("*.md")):
        text = document.read_text(encoding="utf-8")
        if "## Актуальний статус на момент завершення робіт" in text:
            continue
        document.write_text(text.rstrip() + "\n" + HEADER, encoding="utf-8")
        count += 1
        print("оновлено:", document.name)
    print(f"дописано в {count} документів")
    return 0


if __name__ == "__main__":
    sys.exit(main())
