"""Пошук НЕВИЗНАЧЕНИХ імен у функціях пакета (спрощений pyflakes).

Навіщо: дефект ``NameError: name 'low' is not defined`` у ``agent_tools``
пройшов усі тести й виявився лише в живому прогоні. Цей скрипт ловить таке
статично: для кожної функції збирає локальні імена (присвоєння, аргументи,
імпорти, comprehension, ``with``/``for``/``except as``) і перевіряє, чи
кожне ЗАВАНТАЖУВАНЕ ім'я справді десь визначене.

Другий випадок, який це ловить (і який пропустили тести): ``known_tools``
використовувався в ``_stream_embedded``, хоч у ЙОГО сигнатурі такого
параметра не було — зате був у сусідньому ``chat_stream``. Тому методи
класу перевіряються ОКРЕМО, кожен у своїй області видимості.

Відоме обмеження: методи класу, оголошеного ВСЕРЕДИНІ функції, можуть
давати хибні сигнали на читанні атрибутів цього класу (``_VOID``).
Скрипт свідомо консервативний — краще пропустити, ніж «кричати» на
робочому коді. Динаміка (``getattr``, ``global``, зірочкові імпорти,
``eval``/``exec``) не аналізується: такі файли пропускаються.
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(r"C:\AI\blackchpock_ai")
BUILTINS = set(dir(builtins))
#: Імена, які Python кладе в модуль сам.
MODULE_GLOBALS = {"__file__", "__name__", "__doc__", "__package__",
                 "__spec__", "__loader__", "__builtins__", "__dict__"}


def _names_bound(node: ast.AST, out: set[str]) -> None:
    """Зібрати імена, які вузол ЗАВАНТАЖУЄ у СВОЇЙ області видимості.

    ВАЖЛИВО: не заходимо в тіло вкладених функцій і класів. Їхні аргументи
    й локальні змінні належать ІНШІЙ області — саме змішування областей
    ховало справжній дефект (``known_tools`` у методі, якого не було в його
    сигнатурі, але був у сусідньому методі).
    """
    # Сам вузол теж може бути import/def: ``ast.iter_child_nodes`` його не
    # поверне, тому перевіряємо окремо. Без цього імпорти не потрапляли в
    # модульну область, і аудитор «не бачив» жодного імпортованого імені.
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            if name != "*":
                out.add(name)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        out.add(node.name)

    def visit(current: ast.AST, *, top: bool) -> None:
        for child in ast.iter_child_nodes(current):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.add(child.name)          # ім'я функції видиме
                # Параметри вкладеної функції зв'язуємо в ТІЙ САМІЙ
                # області перевірки: ``_scope_nodes`` заходить у її тіло, і
                # без цього кожен ``def counter(text)`` давав би «text не
                # визначено». Змінні, які вона створює локально, теж
                # зв'язуємо — вони не течуть назовні, але перевіряються тут.
                for arg in (*child.args.posonlyargs, *child.args.args,
                            *child.args.kwonlyargs):
                    out.add(arg.arg)
                if child.args.vararg:
                    out.add(child.args.vararg.arg)
                if child.args.kwarg:
                    out.add(child.args.kwarg.arg)
                for inner in ast.walk(child):
                    if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Store):
                        out.add(inner.id)
                    elif isinstance(inner, ast.ExceptHandler) and inner.name:
                        # ``except X as exc`` усередині вкладеної функції:
                        # ``exc`` діє лише в ній, але перевіряємо її разом із
                        # батьком — без цього кожен такий блок давав хибний
                        # «exc не визначено».
                        out.add(inner.name)
                    elif isinstance(inner, (ast.Import, ast.ImportFrom)):
                        # Локальний імпорт усередині функції
                        # (``from . import diagnostics``) діє саме в ній.
                        for alias in inner.names:
                            local = alias.asname or alias.name.split(".")[0]
                            if local != "*":
                                out.add(local)
                continue                     # тіло — інша область
            if isinstance(child, ast.ClassDef):
                out.add(child.name)
                # Клас, оголошений УСЕРЕДИНІ функції: його методи
                # перевіряються разом із цією функцією, тож їхні параметри
                # мають бути зв'язані. Без цього кожен
                # ``def guess_type(self, path)`` у локальному класі давав
                # хибні «self/path не визначено».
                for inner in ast.walk(child):
                    if isinstance(inner, ast.arg):
                        out.add(inner.arg)
                    elif isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Store):
                        out.add(inner.id)
                    elif isinstance(inner, ast.ExceptHandler) and inner.name:
                        out.add(inner.name)
                continue
            if isinstance(child, ast.Lambda):
                # Параметри лямбди локальні для її тіла. Без цього кожен
                # ``lambda q, p, e: …`` давав хибні «q не визначено»
                # (саме так з'явились 1140 сигналів у agent_tools).
                for arg in (*child.args.posonlyargs, *child.args.args,
                            *child.args.kwonlyargs):
                    out.add(arg.arg)
                if child.args.vararg:
                    out.add(child.args.vararg.arg)
                if child.args.kwarg:
                    out.add(child.args.kwarg.arg)
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                out.add(child.id)
            elif isinstance(child, ast.arg):
                out.add(child.arg)
            elif isinstance(child, (ast.comprehension,)):
                # Змінна циклу comprehension (``[x for x in …]``) — локальна
                # для виразу, але в межах функції її видно як звичайну
                # локальну. Без цього аудитор давав тисячі хибних сигналів
                # на кожному ``for``.
                target = child.target
                if isinstance(target, ast.Name):
                    out.add(target.id)
                elif isinstance(target, (ast.Tuple, ast.List)):
                    for sub in ast.walk(target):
                        if isinstance(sub, ast.Name):
                            out.add(sub.id)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                for alias in child.names:
                    name = alias.asname or alias.name.split(".")[0]
                    if name != "*":
                        out.add(name)
            elif isinstance(child, ast.ExceptHandler) and child.name:
                out.add(child.name)
            elif isinstance(child, (ast.Global, ast.Nonlocal)):
                out.update(child.names)
            visit(child, top=False)

    visit(node, top=True)


def _scope_nodes(func: ast.AST) -> list[ast.AST]:
    """Вузли, що належать САМЕ цій функції (без вкладених областей).

    Вкладені функції мають власну область, але зовнішні імена їм видимі —
    тому їхні ВІЛЬНІ імена перевіряємо разом із зовнішньою функцією.
    Їхні ВЛАСНІ параметри при цьому мусять бути зв'язані, інакше кожен
    ``def counter(text)`` усередині давав би «text не визначено».
    """
    nodes: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        nodes.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            # Заходимо всередину: вільні імена вкладеної функції можуть
            # бути визначені тут.
            stack.extend(ast.iter_child_nodes(node))
            continue
        stack.extend(ast.iter_child_nodes(node))
    return nodes


def _closure_names(func: ast.AST) -> set[str]:
    """Імена, які бачать ВКЛАДЕНІ функції та лямбди цієї.

    Це аргументи зовнішньої функції, її локальні присвоєння на будь-якій
    глибині та параметри ЛЯМБД/вкладених ``def``. Без них кожна
    ``lambda text: …`` і кожен ``except … as exc`` у вкладеній функції
    виглядали б зламаними (60 хибних сигналів у панелях).
    """
    names: set[str] = set()
    if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = func.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            names.add(arg.arg)
        if args.vararg:
            names.add(args.vararg.arg)
        if args.kwarg:
            names.add(args.kwarg.arg)
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.Lambda):
            args = node.args
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                names.add(arg.arg)
            if args.vararg:
                names.add(args.vararg.arg)
            if args.kwarg:
                names.add(args.kwarg.arg)
    return names


def audit_function(func: ast.AST, module_names: set[str]) -> list[str]:
    problems: list[str] = []
    bound: set[str] = set()
    _names_bound(func, bound)
    if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = func.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            bound.add(arg.arg)
        if args.vararg:
            bound.add(args.vararg.arg)
        if args.kwarg:
            bound.add(args.kwarg.arg)
    loaded: list[tuple[str, int]] = []
    for node in _scope_nodes(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loaded.append((node.id, node.lineno))
    # ── Замикання ─────────────────────────────────────────────────────────
    # Вкладені функції бачать локальні змінні ЗОВНІШНЬОЇ функції. Раніше
    # цього не враховували, і кожен ``def _stop(): … should_stop …`` давав
    # «should_stop не визначено» (551 хибний сигнал). Збираємо ВСІ локальні
    # імена зовнішньої функції — вони доступні вкладеним.
    for name in _closure_names(func):
        bound.add(name)
    # Атрибути локальних класів (``_VOID = frozenset(...)`` на рівні класу)
    # видимі його методам як звичайні імена.
    for node in ast.walk(func):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        for sub in ast.walk(target):
                            if isinstance(sub, ast.Name):
                                bound.add(sub.id)
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    bound.add(item.target.id)
    for name, line in loaded:
        if name in bound or name in module_names or name in BUILTINS \
                or name in MODULE_GLOBALS:
            continue
        problems.append(f"ряд {line}: «{name}» не визначено")
    return problems


def audit_methods_in_class(node: ast.ClassDef,
                           module_names: set[str]) -> list[str]:
    """Перевірити методи класу, НЕ змішуючи їхні області видимості.

    Навіщо окремо: дефект ``known_tools`` у ``_stream_embedded`` не був
    знайдений загальним обходом, бо в сусідньому методі ``chat_stream``
    такий параметр Є. Загальний обхід додавав імена ВСІХ методів класу в
    одну «модульну» область — і помилка ховалась.
    """
    problems: list[str] = []
    # Імена рівня класу (константи, вкладені класи) видимі методам.
    #
    # ВАЖЛИВО: беремо лише НЕ-функції. Аргументи методів належать САМЕ
    # методам; якщо додати їх у класову область, параметр сусіднього методу
    # «виправдовує» помилку в іншому — саме так ховався дефект
    # ``known_tools`` (перевірено ``.buildtmp/probe_audit_methods.py``).
    class_names: set[str] = set()
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        _names_bound(item, class_names)
    for item in node.body:
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for problem in audit_function(item, module_names | class_names):
            problems.append(f"{node.name}.{item.name}(): {problem}")
    return problems


def main() -> int:
    files = [p for p in (ROOT / "blackchpok_ide").rglob("*.py")]
    files.append(ROOT / "agent_tools.py")
    files.append(ROOT / "server.py")
    total = 0
    for path in files:
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            print(f"{path.name}: СИНТАКСИС: {exc}")
            total += 1
            continue
        # Імена рівня модуля + все, що завантажується через `from x import *`.
        module_names: set[str] = set()
        star_import = False
        for node in tree.body:
            # ВАЖЛИВО: саму назву функції/класу додаємо ЯВНО.
            # ``_names_bound`` навмисно не заходить у тіло вкладених
            # областей, тому для top-level ``def _clamp``/``class X`` вона
            # не додала б нічого — і модуль «не бачив» власних функцій
            # (перевірено: 13 721 хибний сигнал).
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                module_names.add(node.name)
            else:
                _names_bound(node, module_names)
            if isinstance(node, ast.ImportFrom):
                if any(alias.name == "*" for alias in node.names):
                    star_import = True
        if star_import:
            # Зірочковий імпорт робить будь-яке ім'я «можливим» — такий
            # файл не перевіряємо, щоб не давати хибних сигналів.
            continue
        printed = False
        # Спершу класи: їхні методи перевіряємо ОКРЕМО, кожен у своїй
        # області видимості. Загальний обхід нижче пропускає методи, інакше
        # імена сусідніх методів ховали б помилки (саме так і сталось із
        # ``known_tools``).
        method_nodes: set[int] = set()
        # Вкладені функції: їх перевіряє зовнішня, разом із замиканням.
        nested_nodes: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.Lambda)):
                for inner in ast.walk(node):
                    if inner is node:
                        continue
                    if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        nested_nodes.add(id(inner))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_nodes.add(id(item))
            problems = audit_methods_in_class(node, module_names)
            if not problems:
                continue
            if not printed:
                print(f"\n{path.relative_to(ROOT)}")
                printed = True
            for problem in problems[:6]:
                print(f"   {problem}")
            total += len(problems)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if id(node) in method_nodes:
                continue          # уже перевірено в складі класу
            if id(node) in nested_nodes:
                # ВКЛАДЕНА функція: її перевіряє ЗОВНІШНЯ (разом із
                # замиканням). Окремий прохід по ній давав би хибні
                # «should_stop не визначено» — параметр батька їй видимий.
                continue
            problems = audit_function(node, module_names)
            if not problems:
                continue
            if not printed:
                print(f"\n{path.relative_to(ROOT)}")
                printed = True
            for problem in problems[:6]:
                print(f"   {node.name}(): {problem}")
            total += len(problems)
    print(f"\nневизначених імен: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
