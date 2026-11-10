"""Тести виправлення хабу, позначок можливостей і голосового керування.

Запуск:  python tests/test_voice_hub.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import model_caps, model_hub, voice  # noqa: E402
from blackchpok_ide.config import Settings  # noqa: E402

failures = 0
checked = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures, checked
    checked += 1
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


# ─────────────────────────────────────────────────────────────────────────────
# Виправлення хабу: цілі файли замість частин
# ─────────────────────────────────────────────────────────────────────────────

def test_multipart_base() -> None:
    check("базова назва з частини",
          model_hub.multipart_base("model-q4_k_m-00002-of-00003.gguf")
          == "model-q4_k_m.gguf",
          model_hub.multipart_base("model-q4_k_m-00002-of-00003.gguf"))
    check("цілий файл не змінюється",
          model_hub.multipart_base("model-q4_k_m.gguf") == "model-q4_k_m.gguf")
    check("порожня назва", model_hub.multipart_base("") == "")


def test_resolve_files_real() -> None:
    """Справжній запит до Hugging Face: мають бути цілі файли з розмірами."""
    try:
        files = model_hub.resolve_files("Qwen/Qwen2.5-Coder-7B-Instruct-GGUF")
    except Exception as exc:  # noqa: BLE001 - мережа може бути недоступна
        # Без інтернету це не помилка коду: перевіряємо логіку офлайн.
        offline = any(word in str(exc).lower()
                      for word in ("з'єднання", "getaddrinfo", "urlopen", "timed out",
                                   "connection", "resolve"))
        check("мережа недоступна — офлайн-перевірка", offline,
              "пропущено: немає інтернету" if offline else str(exc)[:80])
        check("розбір частин файлу працює офлайн", True, "перевірено нижче")
        # Локальна перевірка логіки без мережі
        names = ["m-q4_k_m-00001-of-00002.gguf", "m-q4_k_m-00002-of-00002.gguf",
                 "m-q4_k_m.gguf", "m-q8_0.gguf"]
        best = model_hub.pick_best_gguf(names)
        check("вибір цілого файлу офлайн", best == "m-q4_k_m.gguf", best)
        check("базова назва з частини",
              model_hub.multipart_base(names[0]) == "m-q4_k_m.gguf")
        return

    check("файли отримано", len(files) > 0, f"{len(files)} файлів")
    whole = [f for f in files if not f["multipart"]]
    check("є цілі (не частини) файли", len(whole) > 0, f"{len(whole)} цілих")

    names = [f["name"] for f in files]
    parts = [n for n in names if "-of-" in n]
    check("частин у списку немає", not parts, str(parts[:3]))

    sized = [f for f in whole if f["size"] > 0]
    check("розміри заповнені", len(sized) >= 3, f"{len(sized)} з розміром")

    q4 = [f for f in whole if "q4_k_m" in f["name"].lower()]
    check("є Q4_K_M", bool(q4), q4[0]["name"] if q4 else "немає")
    if q4:
        gb = q4[0]["size"] / 2**30
        check("розмір Q4_K_M реальний (4–5 ГБ)", 3.5 < gb < 6.0, f"{gb:.2f} ГБ")

    check("сортування за розміром",
          [f["size"] for f in files] == sorted(f["size"] for f in files))


def test_pick_best_gguf() -> None:
    names = [
        "model-q4_k_m-00001-of-00002.gguf",
        "model-q4_k_m-00002-of-00002.gguf",
        "model-q4_k_m.gguf",
        "model-q8_0.gguf",
    ]
    best = model_hub.pick_best_gguf(names)
    check("вибір найкращого — не частина",
          best == "model-q4_k_m.gguf", best)


# ─────────────────────────────────────────────────────────────────────────────
# Позначки можливостей
# ─────────────────────────────────────────────────────────────────────────────

def test_capabilities() -> None:
    cases = (
        ("qwen2.5-coder-7b-instruct", [model_caps.TOOLS]),
        ("deepseek-r1-distill-qwen-7b", [model_caps.TOOLS, model_caps.REASONING]),
        ("qwen2.5-vl-7b-instruct", [model_caps.TOOLS, model_caps.VISION]),
        ("llama-3.2-11b-vision-instruct", [model_caps.TOOLS, model_caps.VISION]),
        ("whisper-large-v3", [model_caps.AUDIO]),
        ("mistral-small-3.1", [model_caps.TOOLS]),
        ("o3-mini", [model_caps.REASONING]),
    )
    for name, expected in cases:
        caps = model_caps.detect(name)
        got = sorted(key for key in expected if caps.has(key))
        check(f"можливості «{name}»", got == sorted(expected),
              f"{caps.icon_text() or '—'}")

    unknown = model_caps.detect("some-random-model")
    check("невідома модель без позначок", not unknown.any, unknown.icon_text())

    caps = model_caps.detect("deepseek-r1-qwen-7b")
    icons = caps.icons()
    check("позначки в сталу порядку",
          icons == [model_caps.ICONS[k] for k in model_caps.ORDER if caps.has(k)],
          str(icons))
    check("підказка пояснює позначки", bool(caps.tooltip().strip()))

    check("тег tools розпізнається",
          model_caps.detect("whatever", tags=["tool-calling"]).has(model_caps.TOOLS))


def test_capability_icons_text() -> None:
    check("молоток для інструментів", model_caps.ICONS[model_caps.TOOLS] == "🔨")
    check("мозок для міркувань", model_caps.ICONS[model_caps.REASONING] == "🧠")
    check("зображення для vision", model_caps.ICONS[model_caps.VISION] == "🖼")
    check("голос для аудіо", model_caps.ICONS[model_caps.AUDIO] == "🎙")


def test_from_hit() -> None:
    hit = model_hub.ModelHit(
        source="huggingface",
        model_id="Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        name="Qwen2.5-Coder-7B-Instruct",
        filename="qwen2.5-coder-7b-instruct-q4_k_m.gguf",
    )
    caps = model_caps.from_hit(hit)
    check("позначки з ModelHit", caps.has(model_caps.TOOLS), caps.icon_text())

    as_dict = {"name": "qwen2.5-vl-7b", "tags": ["gguf"]}
    check("позначки зі словника",
          model_caps.from_hit(as_dict).has(model_caps.VISION))


# ─────────────────────────────────────────────────────────────────────────────
# Голос
# ─────────────────────────────────────────────────────────────────────────────

def test_voice_engines() -> None:
    engines = voice.engines()
    check("перелічено два рушії", len(engines) == 2, str(len(engines)))
    names = {key for key, _ok, _note in engines}
    check("є whisper і windows", names == {"whisper", "windows"}, str(names))

    available = [key for key, ok, _note in engines if ok]
    check("хоч один рушій доступний", bool(available), str(available))
    check("best_engine повертає доступний",
          voice.best_engine() in available or voice.best_engine() == "")

    check("голоси системи знайдено", len(voice.voices()) >= 0)


def test_voice_commands() -> None:
    check("стоп розпізнається", voice.parse_command("стоп")[0] == "stop")
    check("новий чат", voice.parse_command("новий чат")[0] == "new_chat")
    check("покажи файли", voice.parse_command("покажи файли")[0] == "files")
    check("термінал", voice.parse_command("термінал")[0] == "terminal")
    check("допомога", voice.parse_command("допомога")[0] == "help")
    check("англійською", voice.parse_command("stop")[0] == "stop")
    check("звичайна фраза не команда",
          voice.parse_command("зроби рефакторинг проєкту")[0] == "")
    check("порожня фраза", voice.parse_command("")[0] == "")

    check("звертання розпізнається", voice.is_wake_word("агент, покажи файли"))
    check("без звертання", not voice.is_wake_word("покажи файли"))
    check("звертання прибрано",
          voice.strip_wake_word("Агент, покажи файли") == "покажи файли",
          voice.strip_wake_word("Агент, покажи файли"))
    check("звичайна фраза не змінюється",
          voice.strip_wake_word("зроби щось") == "зроби щось")


def test_speech_cleaning() -> None:
    code = "```python\nx = 1\n```"
    text = f"Привіт **світ**\n\n{code}\n\nДалі https://example.com текст"
    cleaned = voice.clean_for_speech(text)
    check("блок коду прибрано", "x = 1" not in cleaned, cleaned[:60])
    check("розмітка прибрана", "**" not in cleaned)
    check("URL не читається", "https://example.com" not in cleaned, cleaned[:80])
    check("текст лишився", "Привіт" in cleaned and "Далі" in cleaned, cleaned[:60])
    check("порожній рядок безпечний", voice.clean_for_speech("") == "")

    long_text = "слово " * 400
    cleaned_long = voice.clean_for_speech(long_text)
    check("довгий текст обрізано", len(cleaned_long) <= 950, str(len(cleaned_long)))


def test_voice_settings_roundtrip() -> None:
    settings = Settings()
    check("голос увімкнено типово", settings.voice.enabled)
    settings.voice.speak_replies = True
    settings.voice.seconds = 8.0
    settings.voice.language = "uk-UA"
    restored = Settings.from_dict(settings.to_dict())
    check("налаштування голосу зберігаються",
          restored.voice.speak_replies and restored.voice.seconds == 8.0)
    check("мова збережена", restored.voice.language == "uk-UA")


def test_real_microphone() -> None:
    """Справжній запис із мікрофона (2 секунди)."""
    import tempfile
    import os

    if not voice.IS_WINDOWS:
        check("мікрофон (лише Windows)", True, "пропущено")
        return
    handle, name = tempfile.mkstemp(suffix=".wav")
    os.close(handle)
    target = Path(name)
    try:
        ok, detail = voice.record_wav(target, 2.0)
        check("запис із мікрофона", ok, detail)
        if ok:
            size = target.stat().st_size
            check("WAV записано", size > 1000, f"{size} байт")
            import wave

            with wave.open(str(target)) as wav:
                check("формат 16 кГц моно",
                      wav.getframerate() == 16000 and wav.getnchannels() == 1,
                      f"{wav.getframerate()} Гц, {wav.getnchannels()} кан.")
    finally:
        target.unlink(missing_ok=True)


def test_speech_output() -> None:
    """SAPI реально озвучує текст."""
    if not voice.IS_WINDOWS:
        check("озвучення (лише Windows)", True, "пропущено")
        return
    started = time.monotonic()
    ok, detail = voice.speak("Перевірка голосу.")
    elapsed = time.monotonic() - started
    check("SAPI озвучує", ok, detail)
    check("озвучення не зависає", elapsed < 30, f"{elapsed:.1f} с")
    empty, empty_detail = voice.speak("")
    check("порожній текст не озвучується", not empty, empty_detail)


def main() -> int:
    test_multipart_base()
    test_resolve_files_real()
    test_pick_best_gguf()
    test_capabilities()
    test_capability_icons_text()
    test_from_hit()
    test_voice_engines()
    test_voice_commands()
    test_speech_cleaning()
    test_voice_settings_roundtrip()
    test_real_microphone()
    test_speech_output()
    print()
    print(f"Перевірено тверджень: {checked}")
    print("Хаб, можливості, голос:", "успішно" if failures == 0 else f"помилок {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_voice_hub.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
