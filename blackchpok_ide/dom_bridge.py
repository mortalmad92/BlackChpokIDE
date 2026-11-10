"""DOM-міст Live Preview: структура сторінки як дані.

Навіщо. Візуальна модель бачить «кнопку зліва», але не знає, який CSS-клас
за неї відповідає. DOM-міст дає точний зв'язок «вигляд → елемент → файл»:
селектор, bounding box, обчислені стилі, текст.

Принципи:

1. **Доповнення, не заміна.** DOM не скасовує візуальну перевірку: стилі
   можуть застосовуватись псевдокласами, анімаціями, canvas — цього в DOM
   немає. Скріншот лишається джерелом істини про ВИГЛЯД.
2. **Лише власний Live Preview.** Міст працює через CDP-сесію вбудованого
   браузера IDE. Для довільних зовнішніх сайтів він недоступний без
   явного дозволу.
3. **Мінімум даних.** Не тягнемо весь DOM дерева з усіма стилями: це
   мегабайти. Беремо обмежену глибину й лише потрібні властивості.

Модуль не залежить від tkinter.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

LOG = logging.getLogger("blackchpok.dombridge")

#: Скільки вузлів максимум повертаємо (щоб не завалити контекст моделі).
MAX_NODES = 120
#: Максимальна глибина обходу.
MAX_DEPTH = 6


@dataclass
class Node:
    """Один елемент сторінки."""

    tag: str = ""
    selector: str = ""
    text: str = ""
    box: tuple[int, int, int, int] = (0, 0, 0, 0)
    role: str = ""
    children: int = 0

    def line(self) -> str:
        x, y, width, height = self.box
        parts = [f"<{self.tag}>"]
        if self.selector:
            parts.append(self.selector)
        parts.append(f"@ ({x},{y}) {width}×{height}")
        if self.role:
            parts.append(f"role={self.role}")
        if self.text:
            short = self.text if len(self.text) <= 60 else self.text[:57] + "…"
            parts.append(f"«{short}»")
        if self.children:
            parts.append(f"дітей {self.children}")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {"tag": self.tag, "selector": self.selector, "text": self.text,
                "box": list(self.box), "role": self.role,
                "children": self.children}


# ─────────────────────────────────────────────────────────────────────────────
# JavaScript-знімки (безпечні: лише читання)
# ─────────────────────────────────────────────────────────────────────────────

#: Побудувати стабільний CSS-селектор для елемента.
_SELECTOR_JS = r"""
function bpSelector(el) {
  if (!el || el.nodeType !== 1) return "";
  if (el.id) return "#" + CSS.escape(el.id);
  const parts = [];
  let node = el;
  let guard = 0;
  while (node && node.nodeType === 1 && guard < 6) {
    let part = node.tagName.toLowerCase();
    const cls = (node.className && typeof node.className === "string")
      ? node.className.trim().split(/\s+/).filter(Boolean).slice(0, 2) : [];
    if (cls.length) part += "." + cls.map(CSS.escape).join(".");
    const parent = node.parentElement;
    if (parent) {
      const same = Array.from(parent.children).filter(
        (c) => c.tagName === node.tagName);
      if (same.length > 1) part += ":nth-of-type(" + (same.indexOf(node) + 1) + ")";
    }
    parts.unshift(part);
    if (node.id) break;
    node = node.parentElement;
    guard += 1;
  }
  return parts.join(" > ");
}
"""


def _tree_expression(depth: int, limit: int) -> str:
    """JS, який збирає дерево DOM із координатами й ролями."""
    return _SELECTOR_JS + f"""
(() => {{
  const out = [];
  function walk(el, level) {{
    if (out.length >= {limit}) return;
    if (level > {depth}) return;
    if (!el || el.nodeType !== 1) return;
    const tag = (el.tagName || "").toLowerCase();
    if (["script", "style", "meta", "link", "noscript"].includes(tag)) return;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return;
    const text = (el.innerText || el.textContent || "").trim();
    out.push({{
      tag: tag,
      selector: bpSelector(el),
      text: text.slice(0, 120),
      x: Math.round(rect.x), y: Math.round(rect.y),
      w: Math.round(rect.width), h: Math.round(rect.height),
      role: el.getAttribute("role") || "",
      children: el.children ? el.children.length : 0,
      depth: level,
    }});
    for (const child of el.children) walk(child, level + 1);
  }}
  walk(document.body, 0);
  return JSON.stringify(out);
}})()
"""


def _styles_expression(selector: str) -> str:
    """JS, який віддає обчислені стилі конкретного елемента."""
    safe = json.dumps(selector)
    return _SELECTOR_JS + f"""
(() => {{
  const el = document.querySelector({safe});
  if (!el) return JSON.stringify(null);
  const cs = getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  const pick = {{}};
  const wanted = ["display","position","width","height","margin","padding",
    "color","background-color","font-family","font-size","font-weight",
    "line-height","border","border-radius","gap","z-index","opacity",
    "flex-direction","justify-content","align-items","grid-template-columns"];
  for (const key of wanted) pick[key] = cs.getPropertyValue(key);
  return JSON.stringify({{
    selector: bpSelector(el),
    tag: (el.tagName || "").toLowerCase(),
    text: (el.innerText || "").slice(0, 200),
    box: {{x: Math.round(rect.x), y: Math.round(rect.y),
           width: Math.round(rect.width), height: Math.round(rect.height)}},
    styles: pick,
    attributes: Array.from(el.attributes).reduce((acc, a) => {{
      acc[a.name] = String(a.value).slice(0, 120); return acc; }}, {{}}),
  }});
}})()
"""


def _console_expression(limit: int = 20) -> str:
    """JS, який повертає помилки сторінки, якщо їх зібрано на сторінці."""
    return f"""
(() => {{
  const errors = (window.__blackchpok_errors || []).slice(-{limit});
  return JSON.stringify({{count: errors.length, items: errors}});
}})()
"""


# ─────────────────────────────────────────────────────────────────────────────
# Високорівневий доступ
# ─────────────────────────────────────────────────────────────────────────────

def available(client: Any) -> bool:
    """Чи підключено CDP-сесію вбудованого браузера."""
    return client is not None and hasattr(client, "evaluate_json")


def dom_tree(client: Any, *, depth: int = MAX_DEPTH,
             limit: int = MAX_NODES) -> tuple[list[Node], str]:
    """Зібрати дерево DOM. Повертає ``(вузли, людський опис)``."""
    if not available(client):
        return [], ("DOM недоступний: Live Preview не запущено. "
                    "Запусти сторінку й повтори.")
    data = client.evaluate_json(_tree_expression(max(1, depth), max(1, limit)))
    if not isinstance(data, list):
        return [], ("DOM не прочитано: сторінка не відповіла або "
                    "вкладка закрита.")
    nodes: list[Node] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        nodes.append(Node(
            tag=str(item.get("tag") or ""),
            selector=str(item.get("selector") or ""),
            text=str(item.get("text") or ""),
            box=(int(item.get("x") or 0), int(item.get("y") or 0),
                 int(item.get("w") or 0), int(item.get("h") or 0)),
            role=str(item.get("role") or ""),
            children=int(item.get("children") or 0),
        ))
    note = (f"DOM: {len(nodes)} елементів (глибина {depth}). "
            f"Координати — у пікселях сторінки.")
    if len(nodes) >= limit:
        note += f" Показано перші {limit}; звузь запит через selector."
    return nodes, note


def element_styles(client: Any, selector: str) -> tuple[Optional[dict], str]:
    """Обчислити стилі елемента за селектором."""
    if not available(client):
        return None, "DOM недоступний: Live Preview не запущено."
    if not (selector or "").strip():
        return None, "Порожній селектор."
    data = client.evaluate_json(_styles_expression(selector))
    if not isinstance(data, dict):
        return None, f"Елемент «{selector}» не знайдено на сторінці."
    return data, describe_styles(data)


def describe_styles(data: dict) -> str:
    """Людський опис обчислених стилів."""
    box = data.get("box") or {}
    lines = [
        f"{data.get('tag', '?')} {data.get('selector', '')} "
        f"@ ({box.get('x', 0)},{box.get('y', 0)}) "
        f"{box.get('width', 0)}×{box.get('height', 0)}",
    ]
    text = str(data.get("text") or "").strip()
    if text:
        lines.append(f"  текст: «{text[:80]}»")
    styles = data.get("styles") or {}
    interesting = ("display", "position", "width", "height", "color",
                   "background-color", "font-size", "font-family", "margin",
                   "padding", "gap", "border-radius")
    pairs = [f"{key}: {styles.get(key)}" for key in interesting
             if styles.get(key)]
    if pairs:
        lines.append("  стилі: " + "; ".join(pairs))
    return "\n".join(lines)


def by_text(client: Any, fragment: str, *, limit: int = 10) -> list[Node]:
    """Знайти елементи, у тексті яких є фрагмент."""
    nodes, _ = dom_tree(client, depth=MAX_DEPTH, limit=MAX_NODES * 2)
    needle = (fragment or "").strip().lower()
    if not needle:
        return []
    found = [node for node in nodes if needle in node.text.lower()]
    return found[:limit]


def console_errors(client: Any, limit: int = 20) -> tuple[list[dict], str]:
    """Помилки сторінки: спершу РЕАЛЬНИЙ канал CDP, потім сторінковий збір.

    Раніше єдиним джерелом був ``window.__blackchpok_errors`` — змінна, яку
    ніхто й ніколи не створював. Через це ``dom_console`` завжди відповідав
    «Помилок на сторінці не зібрано», навіть коли консоль справді мала
    помилки. Тепер джерела йдуть за надійністю:

    1. ``client.console_entries()`` — справжні події CDP (``Runtime.exception``,
       ``Log.entryAdded``, ``Network.loadingFailed``, HTTP 4xx/5xx);
    2. ``window.__blackchpok_errors`` — якщо сторінка сама збирає помилки;
    3. чесна відповідь «джерела немає», а не «помилок немає».
    """
    if not available(client):
        return [], "DOM недоступний: Live Preview не запущено."
    wanted = max(1, limit)
    reader = getattr(client, "console_entries", None)
    if callable(reader):
        try:
            entries = list(reader(errors_only=True) or [])
        except TypeError:
            entries = list(reader() or [])
        except Exception:  # noqa: BLE001 - консоль не має ламати міст
            entries = []
        if entries:
            items: list[dict] = []
            for entry in entries[-wanted:]:
                items.append({
                    "level": str(getattr(entry, "level", "error") or "error"),
                    "text": str(getattr(entry, "text", "") or ""),
                    "source": str(getattr(entry, "source", "") or ""),
                    "url": str(getattr(entry, "url", "") or ""),
                })
            return items, f"Помилок на сторінці: {len(entries)}"
        # Порожній список від CDP — це справжній факт «помилок немає», і він
        # не потребує запасного джерела.
        return [], "Консоль сторінки без помилок (перевірено через CDP)."
    data = client.evaluate_json(_console_expression(wanted))
    if not isinstance(data, dict):
        return [], "Помилки сторінки недоступні."
    items = data.get("items") or []
    count = int(data.get("count") or 0)
    if not count:
        return [], "Помилок на сторінці не зібрано."
    return [item for item in items if isinstance(item, dict)], \
        f"Помилок на сторінці: {count}"


def page_state(client: Any) -> str:
    """Короткий знімок стану сторінки для статусу."""
    if not available(client):
        return "Live Preview: не запущено"
    try:
        url = client.evaluate("location.href") or ""
        title = client.evaluate("document.title") or ""
    except Exception:  # noqa: BLE001
        return "Live Preview: стан не прочитано"
    return f"Live Preview: {title or 'без назви'} · {url}"


__all__ = [
    "MAX_DEPTH",
    "MAX_NODES",
    "Node",
    "available",
    "by_text",
    "console_errors",
    "describe_styles",
    "dom_tree",
    "element_styles",
    "page_state",
]
