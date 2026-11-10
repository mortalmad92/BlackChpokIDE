"""Атомарний запис файлів стану: дані користувача не губляться.

Два справжні дефекти, знайдені дебагом збереження:

1. Запис був НЕ атомарним. ``write_text`` одразу обрізає файл, тому збій
   живлення посеред запису лишав обірваний JSON. ``load()`` це переживав
   (типові налаштування), але налаштування користувача — модель, ключ,
   робоча тека, нещодавні проєкти — були ВТРАЧЕНІ назавжди.

2. Перша версія фіксу створила НОВИЙ дефект: усі потоки писали в один
   ``settings.json.tmp``, ``os.replace`` падав із ``WinError 32``, і
   20 потоків не зберегли НІЧОГО. Виявлено прогоном, а не міркуванням.
   Виправлено унікальним ім'ям тимчасового файлу + замком.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import config, queue_engine, trace_store  # noqa: E402


class AtomicWriteCase(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="atomic-"))
        self._old_home = os.environ.get("BLACKCHPOK_HOME")
        self._old_save = os.environ.get("BLACKCHPOK_NO_SAVE")
        os.environ["BLACKCHPOK_HOME"] = str(self.folder)
        os.environ.pop("BLACKCHPOK_NO_SAVE", None)

    def tearDown(self) -> None:
        for key, value in (("BLACKCHPOK_HOME", self._old_home),
                           ("BLACKCHPOK_NO_SAVE", self._old_save)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.folder, ignore_errors=True)


class TestWriteJsonAtomic(AtomicWriteCase):
    def test_writes_valid_json(self) -> None:
        target = self.folder / "data.json"
        config.write_json_atomic(target, {"ключ": "значення", "число": 42})
        self.assertTrue(target.exists())
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                         {"ключ": "значення", "число": 42})

    def test_creates_parent_folders(self) -> None:
        target = self.folder / "глибоко" / "вкладено" / "data.json"
        config.write_json_atomic(target, {"a": 1})
        self.assertTrue(target.exists())

    def test_overwrites_atomically(self) -> None:
        target = self.folder / "data.json"
        config.write_json_atomic(target, {"версія": 1})
        config.write_json_atomic(target, {"версія": 2})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                         {"версія": 2})

    def test_no_temp_files_left(self) -> None:
        target = self.folder / "data.json"
        config.write_json_atomic(target, {"a": 1})
        leftovers = [p.name for p in self.folder.iterdir() if ".tmp" in p.name]
        self.assertEqual(leftovers, [], f"лишились тимчасові файли: {leftovers}")

    def test_unicode_preserved(self) -> None:
        target = self.folder / "data.json"
        config.write_json_atomic(target, {"текст": "Привіт, їжак ґава 🚀"})
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(data["текст"], "Привіт, їжак ґава 🚀")

    def test_write_text_atomic(self) -> None:
        target = self.folder / "notes.txt"
        config.write_text_atomic(target, "рядок 1\nрядок 2\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "рядок 1\nрядок 2\n")


class TestConcurrentWrites(AtomicWriteCase):
    """Регресія на дефект, який створила перша версія фіксу."""

    def test_twenty_threads_all_write(self) -> None:
        target = self.folder / "settings.json"
        errors: list[str] = []
        lock = threading.Lock()

        def writer(index: int) -> None:
            try:
                settings = config.Settings()
                settings.llm.model = f"модель-{index}"
                settings.recent = [f"C:/проєкт-{index}"]
                settings.save(target)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(f"{index}: {type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(errors, [], f"помилки запису: {errors[:3]}")
        self.assertTrue(target.exists(),
                        "файл не створено — усі записи загинули в гонці")

    def test_final_file_is_valid_and_consistent(self) -> None:
        target = self.folder / "settings.json"

        def writer(index: int) -> None:
            settings = config.Settings()
            settings.llm.model = f"модель-{index}"
            settings.recent = [f"C:/проєкт-{index}"]
            settings.save(target)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(15)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        data = json.loads(target.read_text(encoding="utf-8"))
        model = data.get("llm", {}).get("model", "")
        recent = data.get("recent", [])
        self.assertTrue(model, "model порожній")
        self.assertTrue(recent, "recent порожній")
        suffix = model.rsplit("-", 1)[-1]
        self.assertIn(f"C:/проєкт-{suffix}", recent,
                      f"РОЗІРВАНИЙ СТАН: model={model!r}, recent={recent!r}")

    def test_queue_concurrent_save(self) -> None:
        path = self.folder / "queue.json"
        queue = queue_engine.TaskQueue(path)
        errors: list[str] = []

        def adder(index: int) -> None:
            try:
                queue.tasks.append(queue_engine.QueueTask(
                    text=f"завдання {index}", number=index))
                queue.save()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{index}: {type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=adder, args=(i,)) for i in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(errors, [])
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("tasks", data)
        reopened = queue_engine.TaskQueue(path)
        self.assertIsInstance(reopened.tasks, list)


class TestNoLeftoversOnFailure(AtomicWriteCase):
    def test_unwritable_path_does_not_leave_temp(self) -> None:
        """Невдалий запис не має лишати сміття й не має кидати назовні."""
        settings = config.Settings()
        bad = Path("Z:/немає/такого/диска/settings.json")
        settings.save(bad)          # не має кинути
        self.assertFalse(bad.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
