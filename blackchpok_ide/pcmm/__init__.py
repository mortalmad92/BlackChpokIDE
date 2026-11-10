"""BLACKCHPOK NEUROMESH Ω — Predictive Causal Memory Mesh (PCMM).

Система пам'яті, яка:

* зберігає ФАКТИ, РІШЕННЯ, ПОМИЛКИ, ВИПРАВЛЕННЯ, ЗАВДАННЯ,
  ЗАЛЕЖНОСТІ, РЕЗУЛЬТАТИ ІНСТРУМЕНТІВ і ОБМЕЖЕННЯ з походженням;
* шукає по них гібридно (лексема + вектор + граф + час) і пояснює оцінку;
* прогнозує, який контекст знадобиться далі, і ВИМІРЮЄ точність прогнозу;
* збирає контекст під реальний бюджет токенів моделі;
* ніколи не втрачає підтверджені факти: застаріле позначається, не видаляється.

Назви «алгоритмів» тут описові. Використані відомі механізми: BM25 (FTS5),
косинусна схожість векторів, Reciprocal Rank Fusion, пошук у графі в
ширину з обмеженою глибиною, часовий спад. Власних «винаходів» не
заявляється — див. ``research/NOVELTY_REGISTER.md``.

Склад:

``store``       SQLite: WAL, міграції, бекапи, цілісність
``models``      Memory: типи, provenance, впевненість, зв'язки
``repository``  запис, дублікати, конфлікти, версії, консолідація
``retrieval``   гібридний пошук + прогнозування контексту
``budget``      бюджет контексту на реальних токенах
``service``     фасад для IDE й інструментів агента
"""

from __future__ import annotations

__all__ = [
    "BudgetGovernor",
    "BudgetReport",
    "ContextPiece",
    "Memory",
    "MemoryRepository",
    "MemoryStore",
    "Neuromesh",
    "Prediction",
    "Retriever",
    "choose_policy",
]

from .budget import BudgetGovernor, BudgetReport, ContextPiece
from .models import Memory
from .repository import MemoryRepository
from .retrieval import Prediction, Retriever, choose_policy
from .store import MemoryStore

# ``Neuromesh`` імпортується ліниво, щоб пакет можна було використати
# без рушія (наприклад, у тестах сховища).
def __getattr__(name: str):
    if name == "Neuromesh":
        from .service import Neuromesh

        return Neuromesh
    raise AttributeError(name)
