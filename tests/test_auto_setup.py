"""Перевірки автоматичного створення скілів: профіль, пропозиції, вибір моделі.

Запуск:  python tests/test_auto_setup.py
Повертає 0, якщо все гаразд. Мережа не використовується: вибір моделі —
чиста функція, а скіли пишуться лише в тимчасові теки ``.buildtmp``.
"""

from __future__ import annotations

import re
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import auto_setup  # noqa: E402
from blackchpok_ide.config import EngineSettings, LLMSettings, Settings  # noqa: E402
from blackchpok_ide.skills import discover_skills, make_skill_text, parse_skill  # noqa: E402

BUILDTMP = ROOT / ".buildtmp"
NUMBERED = re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE)
CYRILLIC = re.compile(r"[\u0400-\u04FF]")

failures = 0
temp_dirs: list[Path] = []


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def temp_dir(tag: str = "autosetup") -> Path:
    """Унікальна тимчасова тека під .buildtmp — її прибираємо у ``finally``."""
    path = BUILDTMP / f"{tag}-{uuid.uuid4().hex[:10]}"
    path.mkdir(parents=True, exist_ok=True)
    temp_dirs.append(path)
    return path


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_python_project(base: Path) -> Path:
    """Синтетичний Python-проєкт: точка входу, тести, pip, README, git."""
    write(base / "main.py", "import tkinter\n\n\ndef main() -> int:\n    return 0\n")
    write(
        base / "tests" / "test_x.py",
        "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
    )
    write(base / "requirements.txt", "requests==2.32.0\n")
    write(base / "README.md", "# Проєкт\n\nЦе тестовий проєкт для перевірки профілю.\n")
    (base / ".git").mkdir(parents=True, exist_ok=True)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# 1-3. Профіль проєкту
# ─────────────────────────────────────────────────────────────────────────────

def test_profile_synthetic() -> None:
    base = make_python_project(temp_dir("profile"))
    profile = auto_setup.profile_project(base)
    check("синтетика: основна мова — Python",
          profile.dominant_extension == ".py" and profile.languages.get(".py", 0) >= 2,
          str(profile.languages))
    check("синтетика: теку тестів знайдено", profile.tests_dir == "tests", profile.tests_dir)
    check("синтетика: git знайдено", profile.has_git is True)
    check("синтетика: пакетний менеджер pip", profile.package_manager == "pip",
          profile.package_manager)
    check("синтетика: точка входу main.py", profile.entry_points == ["main.py"],
          str(profile.entry_points))
    check("синтетика: README прочитано",
          bool(profile.readme.strip()) and profile.readme_file == "README.md",
          profile.readme_file)
    check("синтетика: тотальна кількість файлів > 0", profile.total_files >= 4,
          str(profile.total_files))
    check("синтетика: спостереження непорожні й по одному рядку",
          bool(profile.notes) and all("\n" not in note and note.strip() for note in profile.notes),
          f"{len(profile.notes)} шт.")


def test_profile_empty() -> None:
    base = temp_dir("empty")
    try:
        profile = auto_setup.profile_project(base)
    except Exception as exc:  # noqa: BLE001 — тест саме про «не падає»
        check("порожня тека: не падає", False, f"{type(exc).__name__}: {exc}")
        return
    check("порожня тека: не падає", True)
    check("порожня тека: нуль файлів", profile.total_files == 0, str(profile.total_files))
    check("порожня тека: мов немає", profile.languages == {}, str(profile.languages))
    check("порожня тека: нотатки все одно є", bool(profile.notes), str(profile.notes[:1]))
    missing = auto_setup.profile_project(base / "неіснуюча-тека")
    check("неіснуюча тека: не падає", missing.total_files == 0 and bool(missing.notes))


def test_profile_real_repo() -> None:
    started = time.perf_counter()
    profile = auto_setup.profile_project(ROOT)
    elapsed = time.perf_counter() - started
    check("репо: профіль швидший за 2.5 с", elapsed < 2.5, f"{elapsed * 1000:.0f} мс")
    check("репо: Python домінує", profile.dominant_extension == ".py",
          str(list(profile.languages.items())[:3]))
    check("репо: теку тестів знайдено", profile.tests_dir == "tests", profile.tests_dir)
    check("репо: файлів понад 20", profile.total_files > 20, str(profile.total_files))
    check("репо: точки входу з кореня", "main.py" in profile.entry_points,
          str(profile.entry_points))


# ─────────────────────────────────────────────────────────────────────────────
# 4-5. Пропозиції скілів
# ─────────────────────────────────────────────────────────────────────────────

def test_proposals() -> None:
    base = make_python_project(temp_dir("propose"))
    write(base / "BlackChpokIDE.spec", "# spec\n")
    write(base / "build_exe.bat", "@echo off\n")
    profile = auto_setup.profile_project(base)
    proposals = auto_setup.propose_skills(profile)

    names = [item.name for item in proposals]
    check("пропозиції: є скіл про тести", "tests" in names, str(names))
    check("пропозиції: не більше 8", 0 < len(proposals) <= 8, str(len(proposals)))
    check("пропозиції: відсортовані за пріоритетом",
          [item.priority for item in proposals] == sorted((i.priority for i in proposals), reverse=True),
          str([item.priority for item in proposals]))
    check("пропозиції: описи непорожні", all(item.description.strip() for item in proposals))
    check("пропозиції: причина українською",
          all(CYRILLIC.search(item.reason) for item in proposals))
    check("пропозиції: у тілі щонайменше 2 нумеровані рядки",
          all(len(NUMBERED.findall(item.body)) >= 2 for item in proposals),
          str({item.name: len(NUMBERED.findall(item.body)) for item in proposals}))
    check("пропозиції: згадано реальну теку тестів",
          any("tests" in item.body for item in proposals if item.name == "tests"))
    check("пропозиції: згадано реальний скрипт збірки",
          any("build_exe.bat" in item.body for item in proposals if item.name == "build"),
          str(names))
    check("пропозиції: згадано реальну точку входу",
          any("main.py" in item.body for item in proposals if item.name == "run-app"))
    check("пропозиції: детерміновані",
          [item.name for item in auto_setup.propose_skills(profile)] == names)

    # Порожній профіль не має вигадувати команд.
    empty_profile = auto_setup.profile_project(temp_dir("emptyprop"))
    empty_props = auto_setup.propose_skills(empty_profile)
    check("порожній профіль: без вигаданих команд", empty_props == [], str([i.name for i in empty_props]))


def test_proposals_existing() -> None:
    base = make_python_project(temp_dir("existing"))
    profile = auto_setup.profile_project(base)
    full = auto_setup.propose_skills(profile)
    tests_name = next((item.name for item in full if "тест" in (item.description + item.body).lower()), "")
    check("наявні: скіл про тести знайдено за описом", bool(tests_name), tests_name)

    filtered = auto_setup.propose_skills(profile, existing=["tests"])
    check("наявні: 'tests' зникає з переліку", "tests" not in [i.name for i in filtered],
          str([i.name for i in filtered]))
    check("наявні: решта пропозицій лишається",
          len(filtered) == len(full) - 1, f"{len(full)} → {len(filtered)}")

    slugged = auto_setup.propose_skills(profile, existing=[auto_setup.skill_slug(tests_name)])
    check("наявні: тека-слаг теж фільтрує", "tests" not in [i.name for i in slugged])
    check("наявні: чужа назва нічого не фільтрує",
          len(auto_setup.propose_skills(profile, existing=["щось-інше"])) == len(full))


# ─────────────────────────────────────────────────────────────────────────────
# 6-8. Запис скілів
# ─────────────────────────────────────────────────────────────────────────────

def test_install() -> None:
    base = make_python_project(temp_dir("install"))
    profile = auto_setup.profile_project(base)
    proposals = auto_setup.propose_skills(profile)
    created = auto_setup.install_proposals(base, proposals)
    check("запис: створено файли", len(created) == len(proposals), f"{len(created)} файлів")
    check("запис: усі файли існують та мають ім'я SKILL.md",
          all(path.is_file() and path.name == "SKILL.md" for path in created))
    check("запис: жодного файлу поза .agents/skills",
          all(path.parent.parent == base / ".agents" / "skills" for path in created))

    found = discover_skills(base)
    found_names = {skill.name for skill in found}
    check("запис: discover_skills бачить усі скіли",
          found_names == {item.name for item in proposals}, str(sorted(found_names)))

    again = auto_setup.install_proposals(base, proposals)
    check("запис: повторний прогін нічого не дублює", again == [], str(again))
    check("запис: кількість скілів на диску не змінилась",
          len(discover_skills(base)) == len(found))

    disabled = auto_setup.SkillProposal(
        name="manual-only", description="Ручний скіл", body="1. Нічого.\n2. Перевірити.",
        reason="Не автоматичний.", auto=False,
    )
    check("запис: only_auto пропускає ручні",
          auto_setup.install_proposals(base, [disabled]) == []
          and not (base / ".agents" / "skills" / "manual-only").exists())
    check("запис: only_auto=False записує ручні",
          len(auto_setup.install_proposals(base, [disabled], only_auto=False)) == 1)


def test_overwrite() -> None:
    base = temp_dir("overwrite")
    proposal = auto_setup.SkillProposal(
        name="style-demo", description="Опис А", body="1. Перше.\n2. Друге.", reason="Причина.",
    )
    created = auto_setup.install_proposals(base, [proposal], only_auto=False)
    check("перезапис: перший запис створив файл", len(created) == 1, str(created))
    target = created[0]
    original = target.read_text(encoding="utf-8")

    changed = auto_setup.SkillProposal(
        name="style-demo", description="Опис Б", body="1. Змінене.\n2. Перевірене.", reason="Причина.",
    )
    skipped = auto_setup.install_proposals(base, [changed], only_auto=False, overwrite=False)
    check("перезапис=False: файл не чіпаємо",
          skipped == [] and target.read_text(encoding="utf-8") == original)

    written = auto_setup.install_proposals(base, [changed], only_auto=False, overwrite=True)
    updated = target.read_text(encoding="utf-8")
    check("перезапис=True: повернуто шлях", written == [target], str(written))
    check("перезапис=True: вміст замінено",
          updated != original and "Опис Б" in updated and "Змінене" in updated)


def test_proposal_text_roundtrip() -> None:
    base = make_python_project(temp_dir("text"))
    proposal = auto_setup.propose_skills(auto_setup.profile_project(base))[0]
    name, description, body = parse_skill(proposal.text)
    check("text: назва збігається", name == proposal.name, repr(name))
    check("text: опис збігається", description == proposal.description.strip(), repr(description))
    check("text: тіло містить нумеровані кроки", len(NUMBERED.findall(body)) >= 2)
    check("text: це той самий формат, що робить make_skill_text",
          proposal.text == make_skill_text(proposal.name, proposal.description, proposal.body))


# ─────────────────────────────────────────────────────────────────────────────
# 9-10. Вибір моделі та українські рядки
# ─────────────────────────────────────────────────────────────────────────────

def test_model_plan() -> None:
    settings = Settings(
        llm=LLMSettings(base_url="http://127.0.0.1:1234/v1", model="qwen2.5-coder"),
        engine=EngineSettings(managed=True, model_path="C:/models/qwen3-4b.gguf"),
    )

    started = time.perf_counter()
    alive = auto_setup.describe_model_setup(
        settings, engine_installed=True, local_models=["qwen3-4b.gguf"], server_alive=True
    )
    ready = auto_setup.describe_model_setup(
        settings, engine_installed=True, local_models=["qwen3-4b.gguf"], server_alive=False
    )
    download = auto_setup.describe_model_setup(
        settings, engine_installed=True, local_models=[], server_alive=False
    )
    nothing = auto_setup.describe_model_setup(
        settings, engine_installed=False, local_models=[], server_alive=False
    )
    elapsed = time.perf_counter() - started

    check("модель: живий локальний сервер → local-server-ready",
          alive.action == "local-server-ready" and alive.base_url.endswith("/v1"),
          f"{alive.action} {alive.base_url}")
    check("модель: рушій + файл моделі → local-server-ready",
          ready.action == "local-server-ready" and ready.model == "qwen3-4b", ready.model)
    check("модель: рушій без моделі → download-needed", download.action == "download-needed",
          download.action)
    check("модель: нічого немає → none", nothing.action == "none", nothing.action)
    check("модель: миттєво (без мережі)", elapsed < 0.5, f"{elapsed * 1000:.1f} мс на 4 виклики")

    external = auto_setup.describe_model_setup(
        Settings(llm=LLMSettings(base_url="https://api.example.com/v1")),
        engine_installed=False, local_models=[], server_alive=True,
    )
    check("модель: зовнішній сервер → external-server", external.action == "external-server",
          external.action)
    defensive = auto_setup.describe_model_setup(
        object(), engine_installed=False, local_models=[], server_alive=False
    )
    check("модель: чужий об'єкт налаштувань не ламає функцію", defensive.action == "none")


def test_ukrainian_strings() -> None:
    base = make_python_project(temp_dir("ukr"))
    profile = auto_setup.profile_project(base)
    proposals = auto_setup.propose_skills(profile)
    check("укр: скіли мають українські описи й причини",
          all(CYRILLIC.search(i.description) and CYRILLIC.search(i.reason) and CYRILLIC.search(i.body)
              for i in proposals),
          str([i.name for i in proposals]))
    check("укр: нотатки профілю українською", all(CYRILLIC.search(note) for note in profile.notes))
    plan = auto_setup.describe_model_setup(
        object(), engine_installed=True, local_models=[], server_alive=False
    )
    check("укр: note і reason плану непорожні",
          bool(plan.note.strip()) and bool(plan.reason.strip()))
    check("укр: reason плану українською", bool(CYRILLIC.search(plan.reason)))
    check("укр: усі дії плану — з відомого переліку",
          {alive.action for alive in [
              auto_setup.describe_model_setup(
                  Settings(), engine_installed=True, local_models=["a.gguf"], server_alive=True),
              auto_setup.describe_model_setup(
                  Settings(), engine_installed=True, local_models=[], server_alive=False),
              auto_setup.describe_model_setup(
                  Settings(), engine_installed=False, local_models=[], server_alive=False),
          ]} <= {"local-server-ready", "external-server", "download-needed", "none"})


# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    _utf8_stdout()
    BUILDTMP.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        test_profile_synthetic()
        test_profile_empty()
        test_profile_real_repo()
        test_proposals()
        test_proposals_existing()
        test_install()
        test_overwrite()
        test_proposal_text_roundtrip()
        test_model_plan()
        test_ukrainian_strings()
    finally:
        for path in temp_dirs:
            shutil.rmtree(path, ignore_errors=True)
        temp_dirs.clear()
    elapsed = time.perf_counter() - started
    print("-" * 70)
    if failures:
        print(f"[FAIL] Провалено перевірок: {failures} ({elapsed:.2f} с)")
        return 1
    print(f"[OK] Усі перевірки пройдено ({elapsed:.2f} с)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
