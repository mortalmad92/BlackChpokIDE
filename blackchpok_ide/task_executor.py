"""Виконавець плану: веде чергу крок за кроком реальними діями агента.

Це «диригент» між трьома речами, які вже є в проєкті:

* :class:`queue_engine.TaskQueue` — де лежить черга й статуси;
* :class:`task_planner` — звідки беруться кроки (їх складає локальна модель);
* :class:`agent.AgentRunner` — хто насправді читає й пише файли.

Модуль тримає **правила виконання**, а не інтелект:

* не брати крок, доки не готові його залежності (послідовність плану);
* не брати новий крок паралельно з активним (один агент — один крок);
* не вірити «готово» на слово: результат перевіряє :class:`TaskValidator`;
* не зациклюватись: обмежена кількість спроб на крок;
* коректно зупинятись і продовжуватись (пауза — стан задачі, не втрата).

Свідомо без tkinter: логіку перевіряють тести, а вікно лише малює стан.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import queue_engine, task_planner

LOG = logging.getLogger("blackchpok.executor")

#: Скільки разів дозволено «продовжити» невдалий крок автоматично.
DEFAULT_MAX_ATTEMPTS = queue_engine.MAX_ATTEMPTS

#: Розширення, які вважаємо файлами коду/даних (для перевірки результату).
CODE_SUFFIXES = (
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss",
    ".json", ".md", ".txt", ".sql", ".yml", ".yaml", ".toml", ".env",
    ".sh", ".bat", ".ps1", ".ini", ".cfg", ".vue", ".php",
)


@dataclass
class ValidationResult:
    """Висновок перевірки результату кроку."""

    ok: bool
    #: Чому саме такий висновок (показується користувачу).
    reason: str = ""
    #: Файли, які справді з'явились або змінились на диску.
    files: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.ok:
            return "результат підтверджено" + (
                f" ({len(self.files)} файлів)" if self.files else "")
        return self.reason or "результат не підтверджено"


class TaskValidator:
    """Перевіряє, що крок справді дав результат, а не лише слова.

    Головна пастка локальних моделей: у відповіді написано «Файл
    створено», а на диску його немає. Тому крок, який згадує шляхи до
    файлів, не зараховуємо, поки цих файлів не існує.
    """

    def __init__(self, root_provider: Callable[[], Optional[Path]]) -> None:
        self.root_provider = root_provider

    def validate(self, task: queue_engine.QueueTask, answer: str, *,
                 changed: Iterable[str] = ()) -> ValidationResult:
        """Перевірити відповідь агента для одного кроку плану."""
        text = (answer or "").strip()
        files = [str(item) for item in changed if str(item).strip()]
        if not text and not files:
            return ValidationResult(False, "порожня відповідь агента")
        root = self.root_provider()
        # 1. Файли, які агент реально змінив (з журналу виконаних дій).
        existing = self._existing(files, root)
        if files and existing:
            return ValidationResult(True, "файли змінено", existing)
        # 2. Шляхи, які модель згадала у відповіді.
        mentioned = self._mentioned_paths(text)
        # ── 2а. Крок, який ЗОБОВ'ЯЗАНИЙ створити файл ─────────────────────
        # Найнебезпечніша пастка, і раніше вона спрацьовувала: крок плану
        # звучить як «Створення файлу greeting.py», агент відповідає
        # «Готово.» — і перевірка зараховувала це як «крок не створював
        # файлів», бо у відповіді немає шляху. Заміряно живим прогоном
        # ``tools/check_full_cycle.py``: усі 4 кроки «завершено», 0 збоїв,
        # а на диску — ПОРОЖНЬО. Користувач бачив зелений звіт без роботи.
        #
        # Тепер намір кроку беремо з ЙОГО ТЕКСТУ: якщо крок про створення
        # файлу, то файл мусить існувати — інакше крок провалено чесно.
        wanted = self._paths_in_task(task)
        if wanted:
            done = self._existing(wanted, root)
            if done:
                return ValidationResult(True, "файли кроку на диску", done)
            return ValidationResult(
                False,
                "крок просив створити файли, яких немає на диску: "
                + ", ".join(sorted(wanted)[:4]),
            )
        if not mentioned:
            # Крок не про файли (аналіз, читання, перевірка) — самих слів
            # достатньо, якщо це не порожня обіцянка.
            if self._is_empty_promise(text):
                return ValidationResult(False, "агент не виконав дій: " + text[:120])
            return ValidationResult(True, "крок не створював файлів")
        found = self._existing(mentioned, root)
        if found:
            return ValidationResult(True, "файли на диску", found)
        return ValidationResult(
            False,
            "агент згадав файли, яких немає на диску: "
            + ", ".join(sorted(mentioned)[:4]),
        )

    @staticmethod
    def _paths_in_task(task: queue_engine.QueueTask) -> set[str]:
        """Файли, які крок ЗОБОВ'ЯЗАНИЙ створити (з тексту самого кроку)."""
        return TaskValidator.paths_in_task_text(
            str(getattr(task, "text", "") or ""))

    @staticmethod
    def paths_in_task_text(text: str) -> set[str]:
        """Файли, які крок ЗОБОВ'ЯЗАНИЙ створити, — з тексту кроку.

        Публічна (без підкреслення), бо її кличе ще й ``main_window``:
        перевірка результату кроку стоїть у ДВОХ місцях (виконавець і
        вікно), і обидві мусять брати намір з одного джерела. Дублювання
        цієї логіки вже призводило до розбіжності: виконавець вимагав
        файл, а вікно зараховувало крок за словами.

        Беремо лише ті кроки, де є і дієслово створення, і назва файлу:
        «Створення файлу greeting.py». Крок «Проаналізувати greeting.py»
        нічого не обіцяє створити — для нього це не застосовується.
        """
        body = " ".join(str(text or "").split())
        if not body:
            return set()
        low = body.lower()
        creating = any(marker in low for marker in (
            "створити", "створи", "створе", "написати", "напиши", "згенеру",
            "додати файл", "додай файл", "новий файл", "write_file", "create",
        ))
        if not creating:
            return set()
        return TaskValidator._mentioned_paths(body)

    @staticmethod
    def _existing(paths: Iterable[str], root: Optional[Path]) -> list[str]:
        """Які з переданих шляхів справді існують у проєкті."""
        if root is None:
            return []
        base = Path(root)
        result: list[str] = []
        for raw in paths:
            clean = str(raw or "").strip().strip("\"'")
            if not clean:
                continue
            candidates = [base / clean, base / Path(clean).name]
            for candidate in candidates:
                try:
                    if candidate.exists() and candidate.is_file():
                        result.append(str(candidate))
                        break
                except OSError:
                    continue
        return result

    @staticmethod
    def mentioned_paths(text: str) -> set[str]:
        """Шляхи до файлів, згадані в тексті (спільна точка для вікна).

        Публічна, бо її кличе ``main_window``: там була ВЛАСНА копія regex,
        і вона брала будь-яке «слово.літери». Наслідок заміряно живим
        прогоном: команда ``python -m unittest -l`` перетворювалась на
        «файл» ``unittest.l``, і крок провалювався з «файлів немає на
        диску: unittest.l». Одна реалізація — одна поведінка.
        """
        return TaskValidator._mentioned_paths(text)

    @staticmethod
    def _mentioned_paths(text: str) -> set[str]:
        """Витягти з відповіді шляхи з розширеннями файлів."""
        pattern = r"[\w./\\-]+\.(?:" + "|".join(
            suffix.lstrip(".") for suffix in CODE_SUFFIXES) + r")\b"
        found: set[str] = set()
        for match in re.finditer(pattern, text or "", re.IGNORECASE):
            name = match.group(0).replace("/", "\\").lstrip(".\\")
            if len(name) > 3:
                found.add(name)
        return found

    @staticmethod
    def _is_empty_promise(text: str) -> bool:
        """Чи відповідь — обіцянка без дії («я зроблю це далі»)."""
        low = (text or "").strip().lower()
        if len(low) > 240:
            return False
        markers = ("я зроблю", "зараз зроблю", "потрібно зробити", "треба зробити",
                   "наступним кроком", "далі я", "буде зроблено")
        return any(marker in low for marker in markers)


class QueueExecutor:
    """Керує виконанням черги: що запускати, коли і як позначати.

    Клас не знає, ЯК саме агент виконує запит: він просить це через
    ``on_run_step`` (колбек вікна), а той викликає справжній агент.
    Такий поділ дає змогу перевіряти логіку черги без вікна й без моделі.
    """

    def __init__(
        self,
        queue: queue_engine.TaskQueue,
        *,
        validator: Optional[TaskValidator] = None,
        on_run_step: Optional[Callable[[queue_engine.QueueTask, str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_change: Optional[Callable[[], None]] = None,
        chat_id_provider: Optional[Callable[[], str]] = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self.queue = queue
        self.validator = validator or TaskValidator(lambda: None)
        self.on_run_step = on_run_step
        self.on_status = on_status
        self.on_change = on_change
        self.chat_id_provider = chat_id_provider
        self.max_attempts = max(1, int(max_attempts))
        #: Задача, яку агент виконує зараз (id).
        self.current_id: str = ""
        #: Чи зупинено виконання користувачем.
        self.stopped: bool = False

    # ── стан ───────────────────────────────────────────────────────────────
    def chat_id(self) -> str:
        if self.chat_id_provider is None:
            return ""
        try:
            return str(self.chat_id_provider() or "")
        except Exception:  # noqa: BLE001 - провайдер не має ламати чергу
            LOG.debug("chat_id_provider упав", exc_info=True)
            return ""

    @property
    def current(self) -> Optional[queue_engine.QueueTask]:
        return self.queue.get(self.current_id) if self.current_id else None

    @property
    def busy(self) -> bool:
        """Чи йде виконання просто зараз."""
        task = self.current
        return task is not None and task.active

    def _notify(self, text: str) -> None:
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:  # noqa: BLE001
                LOG.debug("on_status упав", exc_info=True)

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001 - інтерфейс не має ламати чергу
                LOG.debug("on_change упав", exc_info=True)

    # ── запуск кроку ───────────────────────────────────────────────────────
    def next_task(self) -> Optional[queue_engine.QueueTask]:
        """Наступний крок, який справді можна запускати.

        Повертає ``None``, якщо черга на паузі, виконання зупинене, агент
        зайнятий або всі кроки чекають на свої залежності.
        """
        if self.stopped or self.queue.paused:
            return None
        if self.busy:
            return None
        return self.queue.next_pending(chat_id=self.chat_id())

    def start_next(self) -> Optional[queue_engine.QueueTask]:
        """Узяти наступний крок і попросити агента його виконати."""
        task = self.next_task()
        if task is None:
            return None
        return self.start(task)

    def start(self, task: queue_engine.QueueTask) -> Optional[queue_engine.QueueTask]:
        """Почати конкретний крок (він уже обраний викликом)."""
        if self.busy:
            self._notify("Агент зайнятий — дочекаюсь завершення поточного кроку.")
            return None
        if task.attempts >= self.max_attempts:
            # Захист від нескінченного повтору: після N спроб крок
            # позначаємо остаточною помилкою, а не «знову в чергу».
            self.queue.mark_failed(
                task.id,
                f"перевищено ліміт спроб ({self.max_attempts}) — крок не вдався")
            self._notify("Крок знято з виконання після кількох невдалих спроб.")
            self._changed()
            return None
        if not self.queue.is_ready(task):
            blockers = self.queue.blocked_by(task)
            names = ", ".join(f"{b.number:02d}" for b in blockers if b.number) or "інші"
            self._notify(f"Крок чекає на завершення: {names}.")
            return None
        self.queue.mark_running(task.id)
        self.queue.set_stage(task.id, queue_engine.ANALYZING,
                             step="аналізую завдання кроку")
        self.current_id = task.id
        self.stopped = False
        self._changed()
        total = len([t for t in self.queue.tasks if t.number])
        prompt = task_planner.step_prompt(task, total=total)
        if self.on_run_step is None:
            self._release_unstarted(task)
            self._notify("Виконання кроку не підключене до агента.")
            return None
        try:
            started = self.on_run_step(task, prompt)
        except Exception as exc:  # noqa: BLE001 - збій запуску не має губити крок
            LOG.exception("Не вдалось запустити крок %s", task.id)
            self.finish(ok=False, answer=f"{type(exc).__name__}: {exc}")
            return None
        # ``on_run_step`` повертає False, якщо запит НЕ пішов агенту (він ще
        # зайнятий, теки проєкту немає тощо). ``retry()`` тут не годиться:
        # крок уже в статусі «аналіз», а ``retry`` активні кроки відхиляє.
        # ``running_id`` лишався зайнятим, ``next_task()`` вічно повертав
        # None, і решта плану стояла в «очікує», поки агент був зайнятий.
        if started is False:
            self._release_unstarted(task)
            self._notify("Крок не запустився — повернуто в чергу.")
            return None
        return task

    def _release_unstarted(self, task: queue_engine.QueueTask) -> None:
        """Повернути крок у «очікує», якщо агент його не прийняв.

        Спроба не відбулась (агент зайнятий, немає теки, старт не
        підключений), тож ліміт спроб не спалюємо: інакше кілька відмов
        поспіль знімали б крок як «перевищено ліміт», хоч модель його
        навіть не бачила.
        """
        self.current_id = ""
        task.attempts = max(0, int(getattr(task, "attempts", 0) or 0) - 1)
        if self.queue.running_id == task.id:
            self.queue.requeue_running()
        elif task.active:
            task.status = queue_engine.PENDING
            task.current_step = ""
            task.finished_at = 0.0
            task.add_history("requeue", "повернуто в чергу: старт не відбувся")
            self.queue._changed()
        self._changed()

    # ── зворотний зв'язок від агента ───────────────────────────────────────
    def note_step(self, text: str, *, status: str = "") -> None:
        """Агент повідомив, що робить (реальна подія, не припущення).

        Статус кроку рухається разом із роботою: спершу модель аналізує
        завдання (``аналіз``), а щойно вона почала викликати інструменти —
        крок стає ``виконується``. Це саме те, що видно користувачу в
        панелі, і воно відповідає реальному стану агента.
        """
        task = self.current
        if task is None:
            return
        clean = " ".join((text or "").split())
        if not clean:
            return
        task.current_step = clean[:200]
        task.add_history("activity", clean)
        target = status
        if not target:
            # Без явного статусу підвищуємо «аналіз» до «виконується»:
            # перша ж дія означає, що модель уже не просто думає.
            target = (queue_engine.RUNNING
                      if task.status == queue_engine.ANALYZING
                      else task.status)
        if target in (queue_engine.ANALYZING, queue_engine.RUNNING,
                      queue_engine.VERIFYING):
            self.queue.set_stage(task.id, target, step=clean)
        self._changed()

    def finish(self, ok: bool, answer: str = "", *, changed: Iterable[str] = (),
               error: str = "") -> None:
        """Агент завершив крок: перевіряємо результат і закриваємо статус.

        «Готово» ставимо лише тоді, коли перевірка підтвердила результат.
        Це головна вимога: модель не має права сама оголосити успіх.

        Окремий випадок — **непідтверджений результат при успішному ході
        агента**. Локальна модель іноді відповідає словами замість виклику
        інструмента (заміряно: ~25% прогонів на одному й тому самому
        запиті). Раніше такий крок одразу ставав «помилка» і знімав усі
        залежні. Тепер даємо ОДНУ повторну спробу з коригувальною
        підказкою — але лише якщо ліміт спроб не вичерпано.
        """
        task = self.current
        self.current_id = ""
        if task is None:
            return
        files = [str(item) for item in changed if str(item).strip()]
        if files:
            merged = list(dict.fromkeys(list(task.files_changed) + files))
            task.files_changed = merged
        if self.stopped:
            self.queue.mark_paused(task.id, "виконання зупинено користувачем")
            self.stopped = False
            self._changed()
            return
        if not ok:
            self._fail(task, error or answer or "крок завершився з помилкою")
            return
        self.queue.set_stage(task.id, queue_engine.VERIFYING,
                             step="перевіряю результат кроку")
        verdict = self.validator.validate(task, answer, changed=files)
        task.add_history("verify", verdict.summary)
        if verdict.ok:
            if verdict.files and not task.files_changed:
                task.files_changed = list(verdict.files)
            self.queue.mark_done(task.id, answer)
            self._notify(f"Крок {self._label(task)} завершено.")
        else:
            # Не підтверджений результат. Спершу пробуємо ОДИН раз
            # повторити з прямою підказкою — локальні моделі часто
            # «відповідають словами» замість виклику інструмента, і друга
            # спроба з поясненням зазвичай виправляє це. Якщо спроби
            # вичерпано — це справжня невдача з каскадом.
            if self._retry_with_hint(task, verdict.reason):
                self._changed()
                return
            self._fail(task, verdict.reason, prefix="не підтверджено: ")
        self._changed()

    def _retry_with_hint(self, task: queue_engine.QueueTask, reason: str) -> bool:
        """Повторити крок із підказкою «виклич інструмент». True — повторено.

        Лічильник спроб ЗБІЛЬШУЄМО тут: інакше повтор не вичерпувався б
        ніколи (``finish`` не проходив через ``mark_running``) і крок
        крутився б безкінечно — саме те, від чого захищає ліміт.
        """
        if int(task.attempts or 0) >= self.max_attempts:
            return False
        if self.on_run_step is None:
            return False
        task.attempts = int(task.attempts or 0) + 1
        task.add_history("retry", f"повтор {task.attempts} із підказкою: {reason[:120]}")
        task.status = queue_engine.RUNNING
        task.current_step = "повторюю з підказкою"
        self.current_id = task.id
        total = len([t for t in self.queue.tasks if t.number])
        prompt = task_planner.step_prompt(task, total=total)
        prompt += (
            "\n\nВАЖЛИВО: попередня спроба не дала результату на диску"
            f" ({reason[:160]}). Не описуй дії словами — ВИКЛИКАЙ "
            "інструмент (write_file / edit_file / run_command) і виконай "
            "роботу фактично."
        )
        self._notify(f"Крок {self._label(task)}: повторюю з підказкою.")
        try:
            started = self.on_run_step(task, prompt)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Повтор кроку %s не запустився", task.id)
            self._release_unstarted(task)
            return True
        if started is False:
            # Агент зайнятий або теки немає. Це не провал кроку: інакше
            # ``finish`` зняв би крок і всі залежні, хоч модель його не бачила.
            self._release_unstarted(task)
            self._notify("Повтор не стартував — крок знову в черзі.")
            return True
        return True

    def _fail(self, task: queue_engine.QueueTask, message: str, *,
              prefix: str = "") -> None:
        """Єдиний шлях невдачі кроку: статус, каскад залежних, повідомлення."""
        self.queue.mark_failed(task.id, message)
        killed = self.queue.cascade_failure(task.id)
        if killed:
            LOG.info("Після збою кроку %s знято %d залежних", task.id, len(killed))
        extra = f" Знято залежних кроків: {len(killed)}." if killed else ""
        self._notify(f"Крок {self._label(task)} {prefix}завершився з помилкою." + extra)
        self._changed()

    @staticmethod
    def _label(task: queue_engine.QueueTask) -> str:
        return f"{task.number:02d}" if task.number else "—"

    # ── керування користувачем ─────────────────────────────────────────────
    def stop(self, *, reason: str = "зупинено користувачем") -> bool:
        """Зупинити виконання: активний крок стає «призупинено».

        Скасувати агента має виклик (він знає про потік); тут лише стан
        черги, щоб панель одразу показала правду.
        """
        task = self.current
        self.stopped = True
        self.current_id = ""
        if task is not None:
            self.queue.mark_paused(task.id, reason)
            self._changed()
            return True
        if not self.queue.paused:
            self.queue.set_paused(True)
            self._notify("Чергу поставлено на паузу.")
            self._changed()
            return True
        return False

    def resume(self) -> bool:
        """Продовжити виконання після зупинки або паузи."""
        changed = False
        self.stopped = False
        if self.queue.paused:
            self.queue.set_paused(False)
            changed = True
        # Призупинені кроки повертаємо в чергу: користувач натиснув
        # «Продовжити» — це і є згода виконувати їх далі.
        for task in self.queue.tasks:
            if task.status == queue_engine.PAUSED:
                self.queue.retry(task.id)
                changed = True
        if changed:
            self._notify("Виконання продовжено.")
            self._changed()
        return changed

    def retry(self, task_id: str) -> bool:
        """Повторити конкретний невдалий крок (ліміт спроб ураховується)."""
        task = self.queue.get(task_id)
        if task is None or task.active:
            return False
        if task.attempts >= self.max_attempts:
            self._notify(
                f"Крок {self._label(task)} уже мав {task.attempts} спроб — "
                "збільш ліміт або втруться вручну.")
            return False
        done = self.queue.retry(task_id)
        if done:
            self._changed()
        return done

    def clear_finished(self) -> int:
        removed = self.queue.clear_finished(self.chat_id())
        if removed:
            self.queue.renumber(chat_id=self.chat_id())
            self._changed()
        return removed

    # ── підсумок ───────────────────────────────────────────────────────────
    def report(self, *, chat_id: str = "") -> str:
        """Підсумковий звіт по плану (Markdown для чату)."""
        tasks = [t for t in self.queue.tasks
                 if not chat_id or str(getattr(t, "chat_id", "") or "") == chat_id]
        if not tasks:
            return "Черга порожня — звітувати нема про що."
        progress = self.queue.progress(chat_id=chat_id)
        lines = ["**Підсумок роботи агента**", ""]
        lines.append(f"Усього кроків: {progress['total']} · "
                     f"завершено: {progress['done']} · "
                     f"з помилками: {progress['errors']} · "
                     f"у черзі: {progress['pending']}")
        failed = [t for t in tasks if t.status == queue_engine.FAILED]
        if failed:
            lines.append("")
            lines.append("**Не вдалось:**")
            for task in failed:
                label = f"{task.number:02d}" if task.number else "—"
                lines.append(f"- {label}. {task.title} — {task.error[:160]}")
        changed = sorted({name for t in tasks for name in t.files_changed})
        if changed:
            lines.append("")
            lines.append("**Змінені файли:**")
            for name in changed[:24]:
                lines.append(f"- `{name}`")
        return "\n".join(lines)


def describe_status(task: queue_engine.QueueTask) -> str:
    """Однорядковий підпис стану кроку для панелі."""
    if task.status == queue_engine.RUNNING and task.current_step:
        return task.current_step
    if task.status == queue_engine.ANALYZING:
        return task.current_step or "аналізую завдання"
    if task.status == queue_engine.VERIFYING:
        return task.current_step or "перевіряю результат"
    if task.status == queue_engine.FAILED and task.error:
        return task.error[:120]
    if task.status == queue_engine.DONE and task.result:
        return " ".join(task.result.split())[:120]
    return task.status_label


def files_from_history(history: Iterable[dict[str, Any]]) -> list[str]:
    """Витягти з журналу кроку шляхи, з якими агент справді працював.

    Потрібно для картки «які файли були створені або змінені»: беремо
    імена з викликів write_file/edit_file, а не з тексту відповіді.

    Абсолютні шляхи зрізаємо до імені файлу: у журналі буває
    ``C:\\…\\calc.py``, і в звіті це виглядало як чужий файл.
    """
    write_tools = ("write_file", "edit_file", "apply_patch")
    names: list[str] = []
    for entry in history or ():
        text = str(entry.get("text") or "")
        kind = str(entry.get("kind") or "")
        if kind != "tool" or not any(tool in text for tool in write_tools):
            continue
        for match in re.finditer(r"[\w./\\-]+\.\w{1,8}", text):
            name = match.group(0).replace("/", "\\")
            if Path(name).is_absolute():
                name = Path(name).name
            if name and name not in names:
                names.append(name)
    return names


__all__ = [
    "CODE_SUFFIXES",
    "DEFAULT_MAX_ATTEMPTS",
    "QueueExecutor",
    "TaskValidator",
    "ValidationResult",
    "describe_status",
    "files_from_history",
]
