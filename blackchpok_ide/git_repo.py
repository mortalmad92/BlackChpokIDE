"""Git-публікація проєкту: стан репозиторію, коміт і відправка на GitHub.

Навіщо окремий модуль. Уже були ``git_status`` і ``git_diff`` — вони лише
ЧИТАЮТЬ. Користувач просить інше: «щоб агент міг запитувати, чи потрібно
оновити файли на GitHub». Тобто потрібен шлях від «агент попрацював» до
«зміни на GitHub», із чесним питанням перед незворотною дією.

Правила, від яких не відступаємо:

* **Нічого не відправляємо без згоди.** ``push`` — незворотна зовнішня дія.
  :func:`publish` викликається ЛИШЕ після відповіді «так».
* **Токен не потрапляє ні в argv, ні в лог, ні в помилку.** На Windows
  аргументи команди видно іншим процесам через ``GetCommandLine``. Тому
  токен передається через оточення (``GIT_ASKPASS`` + змінна), а в текстах
  він завжди замінений на ``•••``.
* **Жодного ``--force``.** Сила ламає чужу історію; для «оновити файли»
  вона не потрібна ніколи.
* **Секрети не комітяться.** Перед комітом перевіряємо, чи серед змінених
  файлів немає ``.env``, ключів і подібного; якщо є — кажемо прямо.

Модуль не тягне tkinter: усе — чисті функції та ``subprocess``.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

LOG = logging.getLogger("blackchpok.git_repo")

#: Скільки чекати на локальні git-команди (status/add/commit) — секунди.
LOCAL_TIMEOUT = 60.0

#: Скільки чекати на мережеві команди (push/pull) — секунди.
REMOTE_TIMEOUT = 180.0

#: Файли, які НЕ можна комітити навіть випадково: там ключі й паролі.
SECRET_NAMES: frozenset[str] = frozenset({
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".npmrc", ".pypirc", "credentials.json", "secrets.json",
})

#: Розширення/шаблони, які теж вважаємо секретами.
SECRET_SUFFIXES: tuple[str, ...] = (".pem", ".pfx", ".p12", ".key", ".keystore")

#: Теки, які створює САМА IDE в теці проєкту, і які не мають їхати в чужий
#: репозиторій без відома людини.
#:
#: Заміряно живим прогоном: після відкриття проєкту в ньому з'являлась тека
#: ``.agents/`` (скіли, які IDE ставить автоматично), і ``git add -A``
#: закомітив її РАЗОМ із роботою агента — «оновлено app.py, .agents/».
#: Людина просила оновити свій сайт, а не вивантажити внутрішні файли IDE.
#:
#: Тому такі теки автоматично виводяться з-під контролю версій: додаємо їх
#: у ``.git/info/exclude`` (це ЛОКАЛЬНИЙ файл, він не змінює чужий
#: ``.gitignore`` у спільному репозиторії).
TOOL_OWNED_DIRS: tuple[str, ...] = (".agents", ".buildtmp", ".dsh")


class GitError(RuntimeError):
    """Git недоступний або команда не виконалась."""


@dataclass
class RepoState:
    """Що зараз із репозиторієм — одним знімком."""

    ok: bool = False
    #: Повідомлення для людини (причина, якщо ``ok`` = False).
    message: str = ""
    root: str = ""
    branch: str = ""
    #: Адреса ``origin`` (може бути порожня).
    remote: str = ""
    #: Змінені/нові файли (відносні шляхи).
    changed: list[str] = field(default_factory=list)

    @property
    def is_github(self) -> bool:
        return "github.com" in (self.remote or "").lower()

    @property
    def dirty(self) -> bool:
        return bool(self.changed)

    def has_secrets(self) -> list[str]:
        """Чи серед змінених файлів є схожі на секрети."""
        return [name for name in self.changed if looks_like_secret(name)]

    def describe(self) -> str:
        """Короткий стан людською мовою (для моделі й для журналу)."""
        if not self.ok:
            return self.message or "це не git-репозиторій"
        parts = [f"гілка {self.branch or '?'}"]
        if self.remote:
            parts.append(f"origin {self.remote}")
        else:
            parts.append("origin не налаштовано")
        parts.append(f"змін: {len(self.changed)}" if self.changed
                     else "змін немає")
        return " · ".join(parts)


def looks_like_secret(name: str) -> bool:
    """Чи схожий шлях на файл із секретами (не можна комітити)."""
    low = str(name or "").replace("\\", "/").lower()
    base = low.rsplit("/", 1)[-1]
    if base in SECRET_NAMES:
        return True
    if base.startswith(".env"):
        return True
    return any(base.endswith(suffix) for suffix in SECRET_SUFFIXES)


def tool_owned(name: str) -> bool:
    """Чи це внутрішня тека IDE, яку не треба вивантажувати в чужий репозиторій.

    Нормалізація важлива: git віддає ``.agents/`` (з рискою), а модель або
    ``git diff`` можуть дати ``./.agents`` чи ``.agents\\skills\\x.md``.
    ``lstrip("./")`` тут НЕ годиться — він зрізає будь-які символи з набору,
    тож ``.agents`` перетворювалось на ``agents`` і перевірка не спрацьовувала.
    """
    low = str(name or "").replace("\\", "/").strip()
    while low.startswith("./"):
        low = low[2:]
    low = low.lstrip("/").rstrip("/")
    head = low.split("/", 1)[0].lower()
    return head in TOOL_OWNED_DIRS


def exclude_tool_dirs(root: Path | str) -> list[str]:
    """Додати внутрішні теки IDE в ``.git/info/exclude`` (локально).

    Саме ``info/exclude``, а не ``.gitignore``: ``.gitignore`` — це файл
    ПРОЄКТУ, його бачать усі, і правка його без прохання змінювала б чужий
    репозиторій. ``info/exclude`` діє лише на цій машині.

    Повертає перелік доданих правил (порожній — нічого не змінилось).
    """
    try:
        base = Path(root)
        git_dir = base / ".git"
        if git_dir.is_file():
            # Worktree: ``.git`` — це файл із посиланням на справжню теку.
            text = git_dir.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"gitdir:\s*(.+)", text)
            if not match:
                return []
            git_dir = Path(match.group(1).strip())
            if not git_dir.is_absolute():
                git_dir = (base / git_dir).resolve()
        if not git_dir.is_dir():
            return []
        target = git_dir / "info" / "exclude"
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8", errors="replace") \
            if target.exists() else ""
        lines = {line.strip() for line in existing.splitlines()}
        added: list[str] = []
        for name in TOOL_OWNED_DIRS:
            rule = f"/{name}/"
            if rule in lines:
                continue
            added.append(rule)
        if not added:
            return []
        with target.open("a", encoding="utf-8", newline="\n") as stream:
            if existing and not existing.endswith("\n"):
                stream.write("\n")
            stream.write("# Теки, які створює BlackChpok IDE (не для чужих репозиторіїв)\n")
            for rule in added:
                stream.write(rule + "\n")
        LOG.info("Внутрішні теки IDE виключено з git: %s", ", ".join(added))
        return added
    except OSError:
        LOG.debug("info/exclude не оновлено", exc_info=True)
        return []


def git_available() -> bool:
    return shutil.which("git") is not None


def redact(text: str) -> str:
    """Прибрати з тексту все схоже на токен або пароль у URL."""
    body = str(text or "")
    # https://user:TOKEN@github.com/... → https://•••@github.com/...
    body = re.sub(r"(https?://)[^@/\s]+@", r"\1•••@", body)
    # ghp_xxx, github_pat_xxx, glpat-xxx тощо.
    body = re.sub(r"\b(gh[pousr]_|github_pat_|glpat-)[A-Za-z0-9_\-]{10,}",
                  "•••", body)
    body = re.sub(r"\b[A-Fa-f0-9]{40}\b", "•••", body)
    return body


def _run(args: Sequence[str], *, cwd: Path, timeout: float = LOCAL_TIMEOUT,
         env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Виконати git і повернути ``(код, stdout, stderr)`` — без винятків."""
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=merged,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise GitError("Git недоступний: встанови його з https://git-scm.com") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} не завершився за {int(timeout)} с") from exc
    except OSError as exc:
        raise GitError(f"git {args[0]} не запустився: {exc}") from exc
    return (completed.returncode, completed.stdout or "", completed.stderr or "")


def repo_root(folder: Path | str) -> Path:
    """Корінь репозиторію для теки (``folder`` — якщо це вже корінь)."""
    base = Path(folder)
    if not base.is_dir():
        raise GitError(f"Теки немає: {base}")
    code, out, _err = _run(["rev-parse", "--show-toplevel"], cwd=base)
    if code != 0 or not out.strip():
        raise GitError("це не git-репозиторій")
    return Path(out.strip())


def state(folder: Path | str) -> RepoState:
    """Зібрати стан репозиторію. Ніколи не кидає — причина в полі."""
    if not git_available():
        return RepoState(message="Git не встановлено на цій машині")
    base = Path(folder)
    if not base.is_dir():
        return RepoState(message=f"Теки немає: {base}")
    try:
        root = repo_root(base)
    except GitError as exc:
        return RepoState(message=str(exc))
    code, branch, _err = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    current = branch.strip() if code == 0 else ""
    code, remote, _err = _run(["remote", "get-url", "origin"], cwd=root)
    origin = remote.strip() if code == 0 else ""
    code, status, _err = _run(["status", "--porcelain"], cwd=root)
    changed: list[str] = []
    if code == 0:
        for line in status.splitlines():
            if not line.strip():
                continue
            # Формат: "XY path" або "XY old -> new" (перейменування).
            path = line[3:].strip()
            if "->" in path:
                path = path.split("->", 1)[1].strip()
            changed.append(path.strip('"').replace("\\", "/"))
    return RepoState(ok=True, root=str(root), branch=current,
                     remote=redact(origin),
                     # Внутрішні теки IDE не показуємо як «зміни проєкту»:
                     # людина не робила їх і не просила їх відправляти.
                     changed=[item for item in changed
                              if not tool_owned(item)])


def is_clean_enough(folder: Path | str) -> tuple[bool, str]:
    """Чи можна публікувати: репозиторій є, origin є, секретів немає."""
    current = state(folder)
    if not current.ok:
        return False, current.message or "не git-репозиторій"
    if not current.remote:
        return False, ("origin не налаштовано — додай адресу GitHub, "
                       "напр. git remote add origin https://github.com/…")
    found = current.has_secrets()
    if found:
        return False, ("серед змін є файли з секретами: " + ", ".join(found)
                       + " — їх не можна відправляти на GitHub")
    if not current.branch:
        return False, "не вдалось визначити поточну гілку"
    return True, current.describe()


def default_message(changed: Sequence[str]) -> str:
    """Повідомлення коміту, яке описує ЗМІНУ, а не «оновлення»."""
    items = [name for name in changed if name]
    if not items:
        return "оновлення з BlackChpok IDE"
    if len(items) == 1:
        return f"оновлено {items[0]} (BlackChpok IDE)"
    head = ", ".join(items[:3])
    tail = f" та ще {len(items) - 3}" if len(items) > 3 else ""
    return f"оновлено {head}{tail} (BlackChpok IDE)"


def _askpass_env(token: str) -> tuple[dict[str, str], Path | None]:
    """Оточення, яке віддає токен git БЕЗ появи в командному рядку.

    Навіщо так. ``git push https://user:TOKEN@…`` видно іншим процесам
    через список аргументів, а ``git remote set-url`` ще й записує токен у
    ``.git/config`` назавжди. ``GIT_ASKPASS`` розв'язує обидві проблеми:
    токен лежить у тимчасовому файлі, а git питає його сам.
    """
    if not token:
        return {}, None
    if os.name == "nt":
        script = "@echo off\r\necho %BLACKCHPOK_GIT_TOKEN%\r\n"
        suffix = ".bat"
    else:
        script = "#!/bin/sh\nprintf '%s\\n' \"$BLACKCHPOK_GIT_TOKEN\"\n"
        suffix = ".sh"
    handle, name = tempfile.mkstemp(prefix="blackchpok-askpass-", suffix=suffix)
    path = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(script)
        if os.name != "nt":
            path.chmod(0o700)
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass
        return {}, None
    return ({"GIT_ASKPASS": str(path),
             "BLACKCHPOK_GIT_TOKEN": token,
             "GIT_TERMINAL_PROMPT": "0"}), path


def _drop_askpass(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        LOG.debug("Тимчасовий askpass не видалено: %s", path, exc_info=True)


@dataclass
class PublishResult:
    """Що сталося під час публікації."""

    ok: bool = False
    committed: bool = False
    pushed: bool = False
    message: str = ""
    commit: str = ""
    remote: str = ""
    branch: str = ""


def publish(
    folder: Path | str,
    *,
    message: str = "",
    token: str = "",
    timeout: float = REMOTE_TIMEOUT,
) -> PublishResult:
    """Закомітити зміни й відправити їх на ``origin``.

    Викликати ЛИШЕ після згоди користувача: ``push`` незворотний.

    Повертає :class:`PublishResult` — з чесною причиною, якщо щось не так.
    """
    if not git_available():
        return PublishResult(message="Git не встановлено на цій машині")
    ready, reason = is_clean_enough(folder)
    if not ready:
        return PublishResult(message=reason)
    current = state(folder)
    root = Path(current.root)
    result = PublishResult(remote=current.remote, branch=current.branch)

    if not current.changed:
        # Комітити нічого — але відправити вже закомічене все одно може бути
        # потрібно (локальні коміти без push).
        result.message = "змін для коміту немає"
    else:
        # Спершу ховаємо те, що створила сама IDE: інакше ``git add -A``
        # докомітить ``.agents/`` до чужого репозиторію.
        exclude_tool_dirs(root)
        code, out, err = _run(["add", "-A"], cwd=root)
        if code != 0:
            return PublishResult(message="git add не вдався: "
                                         + redact((err or out).strip())[:400])
        text = (message or "").strip() or default_message(current.changed)
        code, out, err = _run(["commit", "-m", text], cwd=root)
        if code != 0:
            body = redact((err or out).strip())
            # «nothing to commit» — не помилка, а стан.
            if "nothing to commit" in body.lower():
                result.message = "змін для коміту немає"
            else:
                return PublishResult(
                    message="git commit не вдався: " + body[:400],
                    remote=current.remote, branch=current.branch)
        else:
            result.committed = True
        code, sha, _err = _run(["rev-parse", "--short", "HEAD"], cwd=root)
        if code == 0:
            result.commit = sha.strip()

    env, askpass = _askpass_env(token)
    try:
        code, out, err = _run(["push", "origin", current.branch],
                              cwd=root, timeout=timeout, env=env)
    finally:
        _drop_askpass(askpass)
    if code != 0:
        body = redact((err or out).strip())
        hint = _push_hint(body)
        return PublishResult(
            ok=False, committed=result.committed, pushed=False,
            message=(f"git push не вдався: {body[:400]}" + (f"\n{hint}" if hint else "")),
            commit=result.commit, remote=current.remote, branch=current.branch)

    result.ok = True
    result.pushed = True
    parts = []
    if result.committed:
        parts.append(f"закомічено {result.commit or 'зміни'}")
    else:
        # Коміту немає — це важлива частина підсумку: інакше людина читає
        # «відправлено» й думає, що поїхали ЇЇ зміни, хоч їх не було.
        parts.append("нових змін для коміту не було")
    parts.append(f"відправлено на {current.remote or 'origin'} "
                 f"({current.branch})")
    result.message = ", ".join(parts)
    LOG.info("Git-публікація: %s → %s (%s)", root, current.remote,
             result.commit or "без нового коміту")
    return result


def _push_hint(body: str) -> str:
    """Підказка під конкретну причину збою push (а не «спробуй ще раз»)."""
    low = (body or "").lower()
    if "authentication failed" in low or "could not read username" in low \
            or "403" in low or "permission denied" in low:
        return ("GitHub не прийняв вхід. Збережи токен у Налаштуваннях → "
                "Git (потрібен доступ «repo»), або увійди через "
                "Git Credential Manager.")
    if "rejected" in low and "fetch first" in low:
        return ("Віддалена гілка пішла вперед. Спершу отримай зміни "
                "(git pull), потім відправляй.")
    if "remote origin already exists" in low:
        return "Origin уже налаштований — зміни його адресу за потреби."
    if "repository not found" in low:
        return ("GitHub не бачить репозиторій: перевір адресу origin і права "
                "токена на цей репозиторій.")
    if "no configured push destination" in low:
        return "Додай адресу: git remote add origin https://github.com/…"
    return ""


__all__ = [
    "GitError",
    "LOCAL_TIMEOUT",
    "REMOTE_TIMEOUT",
    "PublishResult",
    "RepoState",
    "TOOL_OWNED_DIRS",
    "default_message",
    "exclude_tool_dirs",
    "git_available",
    "is_clean_enough",
    "looks_like_secret",
    "publish",
    "redact",
    "repo_root",
    "state",
    "tool_owned",
]


def ensure_folder_git(folder: Path | str) -> Path:
    """????'????? ????? ?? ????? ?? ???????? ???????????? Git-???????????."""
    root = Path(folder).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        _run(["init", "-b", "main"], cwd=root)
        exclude_tool_dirs(root)
    return root


def has_meaningful_changes(folder: Path | str, min_lines: int = 15) -> tuple[bool, int, list[str]]:
    """??????????, ?? ? ? ????? ??????? ??????? ????? (????? git status --porcelain ?? numstat)."""
    root = Path(folder).resolve()
    if not (root / ".git").exists():
        return False, 0, []
    ignored_ext = (".log", ".tmp", ".pyc", ".pyo", ".cache")
    try:
        st_res = _run(["status", "--porcelain"], cwd=root)
        raw_lines = [ln for ln in (st_res.stdout or "").splitlines() if len(ln) > 3]
        files = [ln[3:].strip().strip('"') for ln in raw_lines]
        files = [f for f in files if f and not any(f.lower().endswith(x) for x in ignored_ext)]
    except Exception:
        return False, 0, []
    if not files:
        return False, 0, []
    changed_lines = 0
    try:
        res = _run(["diff", "--numstat"], cwd=root)
        for ln in (res.stdout or "").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                changed_lines += int(parts[0]) + int(parts[1])
    except Exception:
        pass
    untracked_bonus = sum(20 for f in files if not (root / f).is_dir())
    total_weight = max(changed_lines, untracked_bonus if len(files) >= 1 else 0)
    return (total_weight >= min_lines or len(files) >= 2), total_weight, files


def smart_auto_sync(folder: Path | str, token: str = "", min_lines: int = 15) -> tuple[bool, str]:
    """??????????? ??????? GitHub ??? ???????? ?????, ?????? ???? ? ??????? ?????."""
    root = Path(folder).resolve()
    ok, weight, files = has_meaningful_changes(root, min_lines=min_lines)
    if not ok:
        return False, f"???????? ???? ????? ({weight} ??????)  ??????? ????."
    st = state(root)
    if not st.remote_url:
        return False, "??? ???? ????? ?? ?? ?????????? ?????????? ??????????? GitHub."
    msg = default_message(files)
    pub = publish(root, message=msg, token=token)
    return pub.ok, pub.summary

_ASKED_GH_FOLDERS: set[str] = set()


def prompt_create_and_publish_github(folder: Path | str, token: str = "", suggested_name: str = "") -> tuple[bool, str]:
    """Ask user to confirm repository name and publish on GitHub when project has meaningful code."""
    root = Path(folder).resolve()
    key = str(root).lower()
    if key in _ASKED_GH_FOLDERS:
        return False, "Already prompted for this folder."
    ok_meaningful, lines_cnt, _ = has_meaningful_changes(root, min_lines=25)
    if not ok_meaningful:
        return False, f"Not enough meaningful lines ({lines_cnt}) yet."
    st = state(root)
    if st.remote_url:
        return smart_auto_sync(root, token=token)
    tok = str(token or "").strip()
    if not tok:
        return False, "GitHub account not linked."
    _ASKED_GH_FOLDERS.add(key)

    import re as _re_gh, json as _j_gh, urllib.request as _u_gh
    base_slug = _re_gh.sub(r"[^a-zA-Z0-9._-]+", "-", (suggested_name or root.name or "blackchpok-project")).strip("-").lower()
    if not base_slug or base_slug in ("tests", "blackchpokprojects", "project"):
        base_slug = "smart-project-2026"

    repo_name = base_slug
    try:
        import tkinter as _tk_gh
        from tkinter import simpledialog as _sd_gh
        if getattr(_tk_gh, "_default_root", None) is not None:
            ans = _sd_gh.askstring(
                "GitHub",
                f"Project ready ({lines_cnt} lines). Confirm GitHub repository name to create and publish:",
                initialvalue=base_slug,
                parent=_tk_gh._default_root,
            )
            if not ans or not ans.strip():
                return False, "Cancelled by user."
            repo_name = _re_gh.sub(r"[^a-zA-Z0-9._-]+", "-", ans.strip()).strip("-")
    except Exception:
        pass

    try:
        req_body = _j_gh.dumps({"name": repo_name, "private": False, "auto_init": False}).encode("utf-8")
        req = _u_gh.Request(
            "https://github.com",
            data=req_body,
            headers={
                "Authorization": f"token {tok}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "BlackChpokIDE",
            },
        )
        with _u_gh.urlopen(req, timeout=12) as resp:
            created = _j_gh.loads(resp.read().decode("utf-8"))
        clone_url = str(created.get("clone_url") or "")
        if clone_url:
            ensure_folder_git(root)
            _run(["git", "remote", "add", "origin", clone_url], cwd=root)
            return publish(root, token=tok, message=f"feat: initial release of {repo_name}")
    except Exception as exc:
        return False, f"GitHub create failed: {exc}"
    return False, "Could not obtain repository URL."
