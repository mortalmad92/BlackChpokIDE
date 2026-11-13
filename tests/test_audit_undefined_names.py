"""Чи аудит усе ще ЛОВИТЬ справжні дефекти після виправлення замикань?

Небезпека очевидна: прибрати хибні сигнали можна й «вимкнувши перевірку».
Цей тест перевіряє протилежне — що справжні невизначені імена знаходяться,
зокрема ПОРУЧ із замиканнями (щоб фікс не «проковтнув» реальну помилку).

Запуск: python tests/test_audit_undefined_names.py
"""

from __future__ import annotations

import ast
import sys
import textwrap
from pathlib import Path
from unittest import TestCase, main

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import audit_undefined_names as audit  # noqa: E402


def _audit(source: str) -> list[str]:
    """Прогнати аудит так само, як це робить ``main()``."""
    tree = ast.parse(textwrap.dedent(source).strip() + "\n")
    module_names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names.add(node.name)
        else:
            audit._names_bound(node, module_names)
    nested_class_closure: dict[int, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            closure = audit._closure_names(node)
            for inner in ast.walk(node):
                if isinstance(inner, ast.ClassDef) and inner is not node:
                    nested_class_closure[id(inner)] = closure
    problems: list[str] = []
    method_ids: set[int] = set()
    nested_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if inner is not node and isinstance(
                        inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nested_ids.add(id(inner))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_ids.add(id(item))
            problems.extend(audit.audit_methods_in_class(
                node, module_names, nested_class_closure.get(id(node))))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if id(node) in method_ids or id(node) in nested_ids:
            continue
        problems.extend(f"{node.name}: {item}"
                        for item in audit.audit_function(node, module_names))
    return problems


class TestStillCatchesRealDefects(TestCase):
    """Справжні дефекти мусять знаходитись — інакше аудит марний."""

    def test_plain_undefined_name(self) -> None:
        problems = _audit("""
            def broken():
                return missing_name + 1
        """)
        self.assertTrue(any("missing_name" in item for item in problems),
                        f"не знайдено справжній дефект: {problems}")

    def test_undefined_inside_method(self) -> None:
        problems = _audit("""
            class Sample:
                def method(self):
                    return undefined_value
        """)
        self.assertTrue(any("undefined_value" in item for item in problems),
                        f"не знайдено дефект у методі: {problems}")

    def test_sibling_method_argument_does_not_hide_defect(self) -> None:
        """Параметр СУСІДНЬОГО методу не має «виправдовувати» помилку.

        Саме цей дефект (``known_tools``) і мотивував окремий прохід по
        класах: у сусідньому методі такий параметр є, і загальний обхід
        помилку ховав.
        """
        problems = _audit("""
            class Stream:
                def good(self, known_tools):
                    return known_tools

                def broken(self):
                    return known_tools
        """)
        joined = " ".join(problems)
        self.assertIn("broken", joined,
                      f"дефект у broken() загублено: {problems}")
        self.assertNotIn("good", joined,
                         f"хибний сигнал у good(): {problems}")

    def test_defect_beside_closure_still_found(self) -> None:
        """Поруч із вкладеною функцією справжня помилка не має губитись."""
        problems = _audit("""
            def outer():
                local = 1
                def inner():
                    return local
                return inner() + totally_missing
        """)
        joined = " ".join(problems)
        self.assertIn("totally_missing", joined,
                      f"справжня помилка загубилась: {problems}")
        self.assertNotIn("«local»", joined,
                         f"хибний сигнал на замиканні: {problems}")
        self.assertNotIn("«inner»", joined,
                         f"хибний сигнал на вкладеній функції: {problems}")


class TestNoFalsePositives(TestCase):
    """Те, що я виправив: замикання й подвійне вкладення — не помилки."""

    def test_double_nested_function(self) -> None:
        problems = _audit("""
            def attach(menu):
                def guard(handler):
                    def inner(event=None):
                        return handler(event)
                    return inner
                return guard
        """)
        self.assertEqual(problems, [], f"хибні сигнали: {problems}")

    def test_class_inside_function_reads_local(self) -> None:
        problems = _audit("""
            def parse():
                IGNORED = frozenset({"script"})
                VOID = frozenset({"br"})
                class Collector:
                    def start(self, tag):
                        if tag not in IGNORED and tag not in VOID:
                            return tag
                        return ""
                return Collector
        """)
        self.assertEqual(problems, [], f"хибні сигнали: {problems}")

    def test_class_level_constant(self) -> None:
        problems = _audit("""
            class Sample:
                LIMIT = 10
                def method(self):
                    return LIMIT
        """)
        self.assertEqual(problems, [], f"хибні сигнали: {problems}")


if __name__ == "__main__":
    main()
