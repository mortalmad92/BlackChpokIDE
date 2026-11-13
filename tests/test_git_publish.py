"""Git-публікація на GitHub: прив'язка до чату, згода людини, безпека.

Головне правило, яке тут перевіряється: агент ПИТАЄ, чи оновити файли на
GitHub, і НІКОЛИ не відправляє їх сам. ``push`` незворотний — коміт одразу
бачать інші люди.

Перевірки йдуть на СПРАВЖНЬОМУ git: тимчасовий репозиторій із bare-копією
замість GitHub. Це важливо: підроблена ``subprocess`` не побачила б ні
токена в аргументах, ні справжньої поведінки ``git commit``.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blackchpok_ide import chat_store, git_repo, permissions  # noqa: E402


def git_ready() -> bool:
    return shutil.which("git") is not None


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


@unittest.skipUnless(git_ready(), "git не встановлено")
class TestRealRepository(unittest.TestCase):
    """Справжній репозиторій: коміт і відправка у bare-копію."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="git-test-"))
        # «GitHub» — це bare-репозиторій: та сама семантика push, без мережі.
        self.remote = self.tmp / "origin.git"
        self.remote.mkdir()
        run(self.remote, "init", "--bare", "--initial-branch=main")
        self.work = self.tmp / "work"
        self.work.mkdir()
        run(self.work, "init", "--initial-branch=main")
        run(self.work, "config", "user.name", "Тест")
        run(self.work, "config", "user.email", "test@example.com")
        run(self.work, "config", "commit.gpgsign", "false")
        run(self.work, "remote", "add", "origin", str(self.remote))
        (self.work / "app.py").write_text("print('v1')\n", encoding="utf-8")
        run(self.work, "add", "-A")
        run(self.work, "commit", "-m", "початок")
        run(self.work, "push", "-u", "origin", "main")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── стан ───────────────────────────────────────────────────────────────
    def test_state_reports_branch_and_changes(self) -> None:
        (self.work / "app.py").write_text("print('v2')\n", encoding="utf-8")
        current = git_repo.state(self.work)
        self.assertTrue(current.ok)
        self.assertEqual(current.branch, "main")
        self.assertTrue(current.remote.startswith(str(self.remote).replace("\\", "/"))
                        or str(self.remote) in current.remote)
        self.assertIn("app.py", current.changed)
        self.assertTrue(current.dirty)

    def test_state_of_plain_folder_is_not_a_crash(self) -> None:
        plain = self.tmp / "just-folder"
        plain.mkdir()
        current = git_repo.state(plain)
        self.assertFalse(current.ok)
        self.assertIn("не git-репозиторій", current.message)

    def test_state_tolerates_missing_folder(self) -> None:
        current = git_repo.state(self.tmp / "nope")
        self.assertFalse(current.ok)

    # ── публікація ─────────────────────────────────────────────────────────
    def test_publish_commits_and_pushes(self) -> None:
        (self.work / "app.py").write_text("print('v2')\n", encoding="utf-8")
        (self.work / "new.txt").write_text("привіт\n", encoding="utf-8")
        result = git_repo.publish(self.work)
        self.assertTrue(result.ok, result.message)
        self.assertTrue(result.committed)
        self.assertTrue(result.pushed)
        self.assertTrue(result.commit)
        # Коміт СПРАВДІ є у віддаленому репозиторії.
        log = run(self.remote, "log", "--oneline", "main")
        self.assertIn("app.py", log.stdout + " new.txt")
        moved = run(self.work, "status", "--porcelain")
        self.assertEqual(moved.stdout.strip(), "", "робоче дерево має лишитись чистим")

    def test_publish_uses_given_message(self) -> None:
        (self.work / "app.py").write_text("print('v3')\n", encoding="utf-8")
        result = git_repo.publish(self.work, message="мій текст коміту")
        self.assertTrue(result.ok, result.message)
        log = run(self.work, "log", "-1", "--pretty=%s")
        self.assertEqual(log.stdout.strip(), "мій текст коміту")

    def test_publish_without_changes_does_not_fail(self) -> None:
        """Немає змін — не помилка, але підсумок мусить це СКАЗАТИ.

        Інакше людина читає «відправлено» й думає, що поїхали її зміни, хоч
        коміту не було.
        """
        result = git_repo.publish(self.work)
        self.assertTrue(result.ok, result.message)
        self.assertFalse(result.committed)
        self.assertIn("нових змін для коміту не було", result.message)

    def test_publish_refuses_secret_files(self) -> None:
        (self.work / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
        result = git_repo.publish(self.work)
        self.assertFalse(result.ok)
        self.assertIn(".env", result.message)
        # Нічого не закомічено й не відправлено.
        log = run(self.remote, "log", "--oneline", "main")
        self.assertNotIn(".env", log.stdout)

    def test_publish_needs_remote(self) -> None:
        lonely = self.tmp / "lonely"
        lonely.mkdir()
        run(lonely, "init")
        (lonely / "x.txt").write_text("x\n", encoding="utf-8")
        ready, reason = git_repo.is_clean_enough(lonely)
        self.assertFalse(ready)
        self.assertIn("origin", reason)

    # ── порядок коміту історії ─────────────────────────────────────────────
    def test_two_publishes_build_history(self) -> None:
        for version in ("v2", "v3"):
            (self.work / "app.py").write_text(f"print('{version}')\n",
                                              encoding="utf-8")
            result = git_repo.publish(self.work, message=f"версія {version}")
            self.assertTrue(result.ok, result.message)
        log = run(self.remote, "log", "--pretty=%s", "main")
        body = log.stdout
        self.assertIn("версія v2", body)
        self.assertIn("версія v3", body)


class TestSecretDetection(unittest.TestCase):
    """Файли з ключами не мають потрапити в коміт."""

    def test_secret_names(self) -> None:
        for name in (".env", "app/.env", ".env.local", "keys/id_rsa",
                     "cert.pem", "server/credentials.json", ".npmrc"):
            with self.subTest(name=name):
                self.assertTrue(git_repo.looks_like_secret(name))

    def test_normal_files(self) -> None:
        for name in ("app.py", "README.md", "src/main.js", "data.json",
                     "tests/test_app.py"):
            with self.subTest(name=name):
                self.assertFalse(git_repo.looks_like_secret(name))


class TestTokenNeverLeaks(unittest.TestCase):
    """Токен не має потрапляти ні в командний рядок, ні в тексти."""

    def test_redact_url_with_token(self) -> None:
        text = "fatal: https://user:ghp_abcdefghij1234567890@github.com/x"
        self.assertNotIn("ghp_abcdefghij", git_repo.redact(text))
        self.assertIn("github.com", git_repo.redact(text))

    def test_redact_standalone_token(self) -> None:
        text = "remote: Invalid token ghp_abcdefghij1234567890 for repo"
        self.assertNotIn("ghp_abcdefghij", git_repo.redact(text))

    def test_askpass_env_hides_token_from_argv(self) -> None:
        """Токен іде в оточенні, а не в аргументах ``git push``."""
        env, path = git_repo._askpass_env("ghp_test_token_value_123456")
        try:
            self.assertIn("GIT_ASKPASS", env)
            self.assertEqual(env["GIT_ASKPASS"], str(path))
            self.assertTrue(path.exists())
            body = path.read_text(encoding="utf-8", errors="replace")
            # Сам токен у скрипті НЕ лежить — лише посилання на змінну.
            self.assertNotIn("ghp_test_token_value_123456", body)
            self.assertIn("BLACKCHPOK_GIT_TOKEN", body)
        finally:
            git_repo._drop_askpass(path)
        self.assertFalse(path.exists(), "тимчасовий askpass треба прибрати")

    def test_empty_token_gives_no_askpass(self) -> None:
        env, path = git_repo._askpass_env("")
        self.assertEqual(env, {})
        self.assertIsNone(path)


class TestChatBinding(unittest.TestCase):
    """Git прив'язаний до ЧАТУ й проєкту, а не до програми загалом."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="git-chat-"))
        self.store = chat_store.ChatStore(self.tmp / "chats.json")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_each_chat_keeps_its_own_remote(self) -> None:
        first = self.store.create(title="Проєкт А", workspace="C:/a")
        second = self.store.create(title="Проєкт Б", workspace="C:/b")
        self.store.remember_git(first.id, remote="https://github.com/u/a.git")
        self.store.remember_git(second.id, remote="https://github.com/u/b.git")
        self.assertEqual(self.store.git_remote(first.id),
                         "https://github.com/u/a.git")
        self.assertEqual(self.store.git_remote(second.id),
                         "https://github.com/u/b.git")

    def test_remote_survives_restart(self) -> None:
        chat = self.store.create(title="т", workspace="C:/x")
        self.store.remember_git(chat.id, remote="https://github.com/u/r.git",
                                pushed_at=1700000000.0)
        again = chat_store.ChatStore(self.tmp / "chats.json")
        restored = again.get(chat.id)
        self.assertEqual(restored.git_remote, "https://github.com/u/r.git")
        self.assertEqual(restored.git_last_push, 1700000000.0)

    def test_auto_ask_can_be_turned_off_per_chat(self) -> None:
        chat = self.store.create(title="т", workspace="C:/x")
        self.assertTrue(self.store.get(chat.id).git_auto_ask)
        self.store.set_git_auto_ask(chat.id, False)
        self.assertFalse(self.store.get(chat.id).git_auto_ask)

    def test_unknown_chat_is_harmless(self) -> None:
        self.assertEqual(self.store.git_remote("нема"), "")
        self.assertFalse(self.store.remember_git("нема", remote="x"))


class TestPublishRequiresConsent(unittest.TestCase):
    """``git_publish`` без ``confirm=true`` не робить НІЧОГО."""

    def setUp(self) -> None:
        from blackchpok_ide import agent_tools

        self.tmp = Path(tempfile.mkdtemp(prefix="git-consent-"))
        self.registry = agent_tools.ToolRegistry(self.tmp)
        self.original = git_repo.publish
        self.calls: list[dict] = []

    def tearDown(self) -> None:
        git_repo.publish = self.original
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _spy(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return git_repo.PublishResult(ok=True, pushed=True, message="ок")

    def test_without_confirm_publish_is_not_called(self) -> None:
        git_repo.publish = self._spy
        text = self.registry.git_publish()
        self.assertEqual(self.calls, [], "без згоди не має бути жодного push")
        self.assertTrue(text.startswith("✗"), text)
        self.assertIn("згод", text)

    def test_confirm_false_also_blocks(self) -> None:
        git_repo.publish = self._spy
        self.registry.git_publish(confirm=False)
        self.assertEqual(self.calls, [])

    def test_confirm_true_publishes(self) -> None:
        git_repo.publish = self._spy
        text = self.registry.git_publish(confirm=True)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(text.startswith("✓"), text)

    def test_registry_has_no_token_by_default(self) -> None:
        from blackchpok_ide import agent_tools

        fresh = agent_tools.ToolRegistry(self.tmp)
        self.assertEqual(fresh.git_token, "")


class TestPermissions(unittest.TestCase):
    """Публікація — зовнішня дія: завжди з підтвердженням."""

    def test_publish_needs_confirmation_in_workspace(self) -> None:
        decision = permissions.check_tool("git_publish", {},
                                          mode=permissions.WORKSPACE, root=".")
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.needs_confirmation,
                        "push незворотний — питати завжди")

    def test_publish_blocked_in_read_only(self) -> None:
        decision = permissions.check_tool("git_publish", {},
                                          mode=permissions.READ_ONLY, root=".")
        self.assertFalse(decision.allowed)

    def test_remote_info_is_read_only(self) -> None:
        for mode in (permissions.READ_ONLY, permissions.WORKSPACE):
            with self.subTest(mode=mode):
                decision = permissions.check_tool("git_remote_info", {},
                                                  mode=mode, root=".")
                self.assertTrue(decision.allowed)
                self.assertFalse(decision.needs_confirmation)


class TestGitOfferFlow(unittest.TestCase):
    """Питання «оновити файли на GitHub?» і відповідь на нього."""

    def setUp(self) -> None:
        from blackchpok_ide import agent, agent_tools, config

        settings = config.Settings()
        self.runner = agent.AgentRunner(
            agent_tools.ToolRegistry(ROOT), settings.llm,
            settings.agent, ROOT)

    def test_yes_answers(self) -> None:
        self.runner._git_asked = True
        for text in ("так", "так, онови", "давай", "ок", "запуш", "yes",
                     "онови файли", "звісно"):
            with self.subTest(text=text):
                self.assertTrue(self.runner._answers_git_offer(text))

    def test_no_answers_and_unrelated(self) -> None:
        self.runner._git_asked = True
        for text in ("ні", "не треба", "пізніше", "скасуй", "дякую",
                     "розкажи про тактику", "зроби потік даних",
                     "створи файл app.py"):
            with self.subTest(text=text):
                self.assertFalse(self.runner._answers_git_offer(text))

    def test_no_consent_when_never_asked(self) -> None:
        """«так» у звичайній розмові НЕ означає ``git push``."""
        self.assertFalse(self.runner._answers_git_offer("так"))

    def test_no_second_publish(self) -> None:
        self.runner._git_asked = True
        self.runner._git_published = True
        self.assertFalse(self.runner._answers_git_offer("так"))

    def test_flags_start_clean(self) -> None:
        self.assertFalse(self.runner._git_asked)
        self.assertFalse(self.runner._git_published)

    def test_prompt_mentions_consent(self) -> None:
        """Модель має знати правило згоди ще до виклику інструмента."""
        from blackchpok_ide import agent_tools, tool_specs

        schemas = {item["function"]["name"]: item
                   for item in agent_tools.TOOL_SCHEMAS}
        self.assertIn("git_publish", schemas, "модель не побачить інструмент")
        spec = tool_specs.spec_for(schemas["git_publish"])
        self.assertEqual(spec.risk, tool_specs.RISK_EXTERNAL)
        self.assertIn("confirm", spec.required)


class TestToolOwnedFolders(unittest.TestCase):
    """Теки, які створила IDE, не мають їхати в чужий репозиторій.

    Заміряно живим прогоном у вікні: після відкриття проєкту в ньому
    з'являлась тека ``.agents`` (скіли, які IDE ставить сама), і ``git add
    -A`` закомітив її РАЗОМ із роботою агента — «оновлено app.py, .agents/».
    """

    def test_tool_owned_detected(self) -> None:
        for name in (".agents/skills/x/SKILL.md", ".agents", ".buildtmp/a.txt",
                     ".dsh/x", r".agents\skills\build\SKILL.md"):
            with self.subTest(name=name):
                self.assertTrue(git_repo.tool_owned(name))

    def test_project_files_are_not_tool_owned(self) -> None:
        for name in ("app.py", "src/.agents_copy/x.py", "agents/x.py",
                     ".gitignore", "README.md"):
            with self.subTest(name=name):
                self.assertFalse(git_repo.tool_owned(name))


@unittest.skipUnless(git_ready(), "git не встановлено")
class TestToolFoldersNotPublished(unittest.TestCase):
    """Реальний push не має тягнути ``.agents``."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="git-owned-"))
        self.remote = self.tmp / "origin.git"
        self.remote.mkdir()
        run(self.remote, "init", "--bare", "--initial-branch=main")
        self.work = self.tmp / "work"
        self.work.mkdir()
        run(self.work, "init", "--initial-branch=main")
        run(self.work, "config", "user.name", "Тест")
        run(self.work, "config", "user.email", "test@example.com")
        run(self.work, "config", "commit.gpgsign", "false")
        run(self.work, "remote", "add", "origin", str(self.remote))
        (self.work / "app.py").write_text("print('v1')\n", encoding="utf-8")
        run(self.work, "add", "-A")
        run(self.work, "commit", "-m", "початок")
        run(self.work, "push", "-u", "origin", "main")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_agents_folder_is_not_committed(self) -> None:
        (self.work / "app.py").write_text("print('v2')\n", encoding="utf-8")
        skills = self.work / ".agents" / "skills" / "build"
        skills.mkdir(parents=True)
        (skills / "SKILL.md").write_text("# скіл\n", encoding="utf-8")

        result = git_repo.publish(self.work, message="робота агента")
        self.assertTrue(result.ok, result.message)

        tree = run(self.remote, "ls-tree", "-r", "--name-only", "main")
        files = tree.stdout
        self.assertIn("app.py", files)
        self.assertNotIn(".agents", files,
                         "внутрішні файли IDE не мають потрапляти в репозиторій")

    def test_changed_list_hides_tool_folders(self) -> None:
        skills = self.work / ".agents" / "skills" / "x"
        skills.mkdir(parents=True)
        (skills / "SKILL.md").write_text("# x\n", encoding="utf-8")
        (self.work / "app.py").write_text("print('v3')\n", encoding="utf-8")
        current = git_repo.state(self.work)
        self.assertIn("app.py", current.changed)
        self.assertFalse([item for item in current.changed
                          if item.startswith(".agents")],
                         f"показано внутрішні файли IDE: {current.changed}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
