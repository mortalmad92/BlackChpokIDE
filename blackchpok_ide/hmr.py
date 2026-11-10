"""Справжній live-reload без повного перезавантаження сторінки (HMR).

Проблема. Перезавантаження сторінки через ``Page.reload`` втрачає стан:
прокрутку, відкриті меню, введений у форму текст, стан JS-змінних. Для
правки CSS/HTML у циклі «змінив → подивився» це дратує: після кожного
збереження все смикається.

Рішення. Підключаємо до сторінки маленький клієнт (через CDP), який:

1. отримує від IDE файл, що змінився (CSS / HTML / JS);
2. **CSS** — замінює вміст ``<style>`` або ``<link>`` **без**
   перезавантаження: вигляд оновлюється, прокрутка й стан лишаються;
3. **HTML** — оновлює ``innerHTML`` лише того вузла, що змінився, якщо
   структура збігається; інакше чесно просить повне перезавантаження;
4. **JS** — повне перезавантаження (виконати новий скрипт без перезапуску
   сторінки неможливо без ризику подвійних слухачів), але ПІСЛЯ нього
   відновлює прокрутку.

Тобто це справжній HMR в межах того, що дозволяє браузер: миттєве
оновлення стилів і точкове оновлення розмітки, а не «F5 на кожну правку».

Модуль не тягне tkinter і нічого не робить під час імпорту.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

LOG = logging.getLogger("blackchpok.hmr")

#: Розширення, які оновлюються БЕЗ перезавантаження сторінки.
STYLE_SUFFIXES = frozenset({".css"})
MARKUP_SUFFIXES = frozenset({".html", ".htm"})
#: Решта (JS/TS тощо) вимагає перезавантаження, але з відновленням стану.
CODE_SUFFIXES = frozenset({".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
                           ".vue", ".svelte"})


@dataclass
class UpdateResult:
    """Що саме сталося зі сторінкою після зміни файлу."""

    mode: str            # "css" | "markup" | "reload" | "skipped" | "failed"
    detail: str = ""
    reloaded: bool = False

    @property
    def ok(self) -> bool:
        return self.mode in ("css", "markup", "reload")


#: Скрипт «зберегти стан сторінки» перед перезавантаженням.
_SAVE_STATE_JS = """
(() => {
  try {
    sessionStorage.setItem('__ide_scroll', JSON.stringify({
      x: window.scrollX, y: window.scrollY,
      at: Date.now()
    }));
    return true;
  } catch (e) { return false; }
})()
"""

#: Скрипт «відновити стан» після перезавантаження.
_RESTORE_STATE_JS = """
(() => {
  try {
    const raw = sessionStorage.getItem('__ide_scroll');
    if (!raw) return false;
    const state = JSON.parse(raw);
    // Відновлюємо лише свіжий стан (до 10 секунд) і лише якщо
    // користувач не прокрутив сторінку сам.
    if (!state || Date.now() - (state.at || 0) > 10000) return false;
    if (Math.abs(window.scrollX) + Math.abs(window.scrollY) > 2) return false;
    window.scrollTo(state.x || 0, state.y || 0);
    sessionStorage.removeItem('__ide_scroll');
    return true;
  } catch (e) { return false; }
})()
"""


def _read(path: Path) -> str:
    """Прочитати файл як текст (порожньо — якщо не вийшло)."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _js(value: str) -> str:
    """Безпечно вставити рядок у JavaScript."""
    return json.dumps(value, ensure_ascii=False)


def apply_css(session: Any, path: Path) -> UpdateResult:
    """Замінити вміст таблиці стилів БЕЗ перезавантаження сторінки.

    Знаходимо ``<link rel=stylesheet>`` із тим самим іменем файлу. Якщо
    знайшли — підміняємо ``href`` (додаючи мітку часу, щоб браузер не взяв
    з кешу). Якщо ні — шукаємо ``<style>`` із міткою ``/* ide:<ім'я> */``
    або одноіменний файл у ``document.styleSheets`` і оновлюємо його вміст.
    """
    body = _read(path)
    name = path.name
    stamp = int(time.time() * 1000)
    expression = f"""
(() => {{
  const name = {_js(name)};
  const css = {_js(body)};
  const stamp = {stamp};

  // 1. <link href="…/name">
  const links = Array.from(document.querySelectorAll('link[rel="stylesheet"]'));
  const match = links.find(l => (l.getAttribute('href') || '').split('?')[0]
                                 .split('/').pop() === name);
  if (match) {{
    const base = (match.getAttribute('href') || '').split('?')[0];
    match.setAttribute('href', base + '?v=' + stamp);
    return 'link:' + name;
  }}

  // 2. <style data-ide="name"> (вставлений раніше цим самим HMR)
  let tag = document.querySelector('style[data-ide="' + name + '"]');
  if (tag) {{ tag.textContent = css; return 'style:' + name; }}

  // 3. Вбудований <style> без мітки — оновлюємо перший, якщо він єдиний.
  const styles = Array.from(document.querySelectorAll('style'));
  if (styles.length === 1) {{
    styles[0].textContent = css;
    styles[0].setAttribute('data-ide', name);
    return 'inline:' + name;
  }}

  // 4. Нічого не знайшли — додаємо власний <style>. Це коректно: нові
  // правила застосуються одразу й не зламають наявні.
  const fresh = document.createElement('style');
  fresh.setAttribute('data-ide', name);
  fresh.textContent = css;
  document.head.appendChild(fresh);
  return 'added:' + name;
}})()
"""
    try:
        result = session.evaluate(expression, timeout=8.0)
    except Exception:  # noqa: BLE001 - HMR не має ламати панель
        LOG.debug("CSS-оновлення впало", exc_info=True)
        return UpdateResult("failed", "помилка виконання скрипта")
    if not result:
        return UpdateResult("failed", "сторінка не підтвердила оновлення")
    return UpdateResult("css", str(result))


def apply_markup(session: Any, path: Path, *, root_selector: str = "body") -> UpdateResult:
    """Точкове оновлення розмітки без перезавантаження.

    Безпечний варіант: беремо з нового HTML лише вміст ``<body>`` і
    порівнюємо. Якщо структура (набір тегів верхнього рівня) збігається —
    підміняємо ``innerHTML`` цільового вузла, зберігаючи прокрутку й стан
    JS. Якщо ні — просимо повне перезавантаження.
    """
    body = _read(path)
    if not body:
        return UpdateResult("failed", "файл порожній або недоступний")
    try:
        from html.parser import HTMLParser

        #: Теги, які браузер НЕ вважає звичайними (не створюють ``children``).
        #: Їх треба виключати з порівняння структури, інакше набір тегів
        #: ніколи не збігається з тим, що бачить браузер.
        _IGNORED = frozenset({"script", "template", "noscript"})
        #: «Порожні» елементи: у них НЕМАЄ закривного тегу, тому глибину
        #: вони не змінюють. Без цього ``<input>`` лишав глибину рівною 1,
        #: і всі наступні теги помилково вважались вкладеними — структура
        #: «не збігалась» із браузерною, і HMR марно перезавантажував
        #: сторінку замість точкового оновлення.
        _VOID = frozenset({
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        })

        class _Collect(HTMLParser):
            """Зібрати ВМІСТ ``<body>`` і теги його верхнього рівня."""

            def __init__(self) -> None:
                super().__init__(convert_charrefs=False)
                self.inside_body = False
                self.depth = 0
                self.top_tags: list[str] = []
                self.parts: list[str] = []

            def handle_starttag(self, tag, attrs):
                if tag == "body":
                    self.inside_body = True
                    return
                if not self.inside_body:
                    return
                if self.depth == 0 and tag not in _IGNORED:
                    self.top_tags.append(tag)
                # Порожні елементи та «сирі» (script/style) не збільшують
                # глибину: у перших немає закривного тегу, у других вміст
                # не розбирається як HTML.
                if tag not in _VOID and tag not in ("script", "style", "template"):
                    self.depth += 1
                attr_text = "".join(
                    f' {name}="{value or ""}"' if value is not None
                    else f" {name}"
                    for name, value in attrs)
                self.parts.append(f"<{tag}{attr_text}>")

            def handle_startendtag(self, tag, attrs):
                # <img/> — самозакривний: у порожніх елементах уже враховано.
                if not self.inside_body:
                    return
                if self.depth == 0 and tag not in _IGNORED:
                    self.top_tags.append(tag)
                attr_text = "".join(
                    f' {name}="{value or ""}"' if value is not None
                    else f" {name}"
                    for name, value in attrs)
                self.parts.append(f"<{tag}{attr_text}/>")

            def handle_endtag(self, tag):
                if not self.inside_body:
                    return
                if tag == "body":
                    self.inside_body = False
                    return
                if tag not in _VOID and tag not in ("script", "style", "template"):
                    self.depth = max(0, self.depth - 1)
                self.parts.append(f"</{tag}>")

            def handle_data(self, data):
                if self.inside_body:
                    self.parts.append(data)

        collector = _Collect()
        collector.feed(body)
        inner = "".join(collector.parts)
        wanted = collector.top_tags
    except Exception:  # noqa: BLE001 - розбір HTML не має ламати HMR
        LOG.debug("Розбір HTML не вдався", exc_info=True)
        return UpdateResult("failed", "не вдалось розібрати HTML")

    if not inner.strip():
        return UpdateResult("failed", "у файлі немає вмісту <body>")
    expression = f"""
(() => {{
  const target = document.querySelector({_js(root_selector)});
  if (!target) return 'no-target';
  const html = {_js(inner)};
  const wanted = {json.dumps(wanted)};
  // Порівнюємо набір тегів верхнього рівня: якщо він інший, точкове
  // оновлення зламало б обробники й структуру — тоді перезавантаження.
  //
  // ВАЖЛИВО: ``<script>``/``<template>`` у порівнянні не беруть участі.
  // Браузер створює для них вузли, але виконувати їх у вже завантаженій
  // сторінці не можна — тому вони лишаються осторонь, і структура
  // вважається такою, що збігається.
  const ignored = new Set(['script', 'template', 'noscript']);
  const holder = document.createElement('div');
  holder.innerHTML = html;
  const got = Array.from(holder.children)
    .map(child => child.tagName.toLowerCase())
    .filter(tag => !ignored.has(tag));
  const expected = wanted.filter(tag => !ignored.has(tag));
  if (JSON.stringify(got) !== JSON.stringify(expected)) return 'shape-mismatch';

  // ── Зберегти стан форм ПЕРЕД заміною розмітки ────────────────────────
  // ``innerHTML = …`` створює нові елементи, тому введений текст,
  // відмічені чекбокси й вибране в <select> зникали. Збираємо стан за
  // стабільним ключем (id, потім ім'я, потім порядковий номер) і
  // повертаємо його після підміни.
  const fields = Array.from(target.querySelectorAll('input, textarea, select'));
  const saved = fields.map((el, index) => ({{
    key: el.id || el.name || ('#' + index),
    tag: el.tagName.toLowerCase(),
    type: (el.type || '').toLowerCase(),
    value: el.value,
    checked: el.checked,
    selected: el.selectedIndex
  }}));

  const before = {{x: window.scrollX, y: window.scrollY}};
  target.innerHTML = html;

  const restored = Array.from(target.querySelectorAll('input, textarea, select'));
  for (let index = 0; index < restored.length && index < saved.length; index++) {{
    const el = restored[index];
    const was = saved[index];
    if (!was || !el) continue;
    if (el.id && was.key !== el.id && was.key !== el.name) continue;
    try {{
      if (was.tag === 'select') {{
        el.selectedIndex = was.selected;
      }} else if (was.type === 'checkbox' || was.type === 'radio') {{
        el.checked = was.checked;
      }} else if (was.value) {{
        el.value = was.value;
      }}
    }} catch (e) {{ /* поле могло зникнути — це нормально */ }}
  }}

  window.scrollTo(before.x, before.y);
  return 'markup:' + got.length + ':' + got.join(',');
}})()
"""
    try:
        result = session.evaluate(expression, timeout=10.0)
    except Exception:  # noqa: BLE001
        LOG.debug("Оновлення розмітки впало", exc_info=True)
        return UpdateResult("failed", "помилка виконання скрипта")
    if isinstance(result, str) and result.startswith("markup:"):
        return UpdateResult("markup", result)
    if result == "shape-mismatch":
        return UpdateResult("reload", "структура сторінки змінилась")
    if result == "no-target":
        return UpdateResult("reload", "цільовий вузол не знайдено")
    return UpdateResult("failed", str(result or "без відповіді"))


def full_reload(session: Any, *, keep_scroll: bool = True) -> UpdateResult:
    """Повне перезавантаження ЗІ ЗБЕРЕЖЕННЯМ прокрутки.

    Для JS-файлів іншого шляху немає: виконати новий скрипт у вже
    завантаженій сторінці означає подвійні обробники подій. Тому
    перезавантажуємо, але перед цим зберігаємо позицію прокрутки й
    відновлюємо її після завантаження.
    """
    if keep_scroll:
        try:
            session.evaluate(_SAVE_STATE_JS, timeout=5.0)
        except Exception:  # noqa: BLE001
            LOG.debug("Стан прокрутки не збережено", exc_info=True)
    ok = session.reload()
    if not ok:
        return UpdateResult("failed", "сторінка не перезавантажилась")
    if keep_scroll:
        # Після перезавантаження треба дочекатись нового документа.
        for _attempt in range(20):
            time.sleep(0.2)
            try:
                ready = session.evaluate("document.readyState", timeout=3.0)
            except Exception:  # noqa: BLE001
                continue
            if ready in ("interactive", "complete"):
                break
        try:
            session.evaluate(_RESTORE_STATE_JS, timeout=5.0)
        except Exception:  # noqa: BLE001
            LOG.debug("Стан прокрутки не відновлено", exc_info=True)
    return UpdateResult("reload", "сторінку перезавантажено", reloaded=True)


def update_for_file(session: Any, path: Path, *,
                    allow_markup: bool = True) -> UpdateResult:
    """Оновити сторінку після зміни КОНКРЕТНОГО файлу.

    Правила:

    * ``.css`` — підміна стилів без перезавантаження (стан зберігається);
    * ``.html`` — точкова підміна ``innerHTML``, якщо структура збігається;
    * ``.js``/``.ts`` та інше — перезавантаження зі збереженням прокрутки;
    * решта (зображення, шрифти, дані) — нічого не робимо: їх підхопить
      звичайне оновлення за потреби.
    """
    target = Path(path)
    suffix = target.suffix.lower()
    if not target.exists():
        return UpdateResult("skipped", "файлу вже немає")
    if suffix in STYLE_SUFFIXES:
        return apply_css(session, target)
    if suffix in MARKUP_SUFFIXES:
        if allow_markup:
            result = apply_markup(session, target)
            if result.ok:
                return result
        return full_reload(session)
    if suffix in CODE_SUFFIXES:
        return full_reload(session)
    return UpdateResult("skipped", f"розширення {suffix or '—'} не потребує оновлення")


def describe(result: UpdateResult) -> str:
    """Короткий підпис для рядка стану."""
    names = {
        "css": "стилі оновлено без перезавантаження",
        "markup": "розмітку оновлено точково",
        "reload": "сторінку перезавантажено",
        "skipped": "оновлення не потрібне",
        "failed": "не вдалось оновити",
    }
    label = names.get(result.mode, result.mode)
    return f"{label} · {result.detail}" if result.detail else label


__all__ = [
    "CODE_SUFFIXES",
    "MARKUP_SUFFIXES",
    "STYLE_SUFFIXES",
    "UpdateResult",
    "apply_css",
    "apply_markup",
    "describe",
    "full_reload",
    "update_for_file",
]
