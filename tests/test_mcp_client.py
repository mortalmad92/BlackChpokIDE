"""Перевірка MCP-клієнта BlackChpok IDE на фейковому stdio-сервері.

Запуск::

    python tests/test_mcp_client.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blackchpok_ide.mcp_client import (  # noqa: E402
    McpClient,
    McpError,
    McpManager,
    McpServerConfig,
    content_to_text,
    namespaced_tool_name,
)

HERE = Path(__file__).resolve().parent
FAKE_SERVER = HERE / "fake_mcp_server.py"
# Тимчасові файли — у .buildtmp проєкту (у %TEMP% пісочниця буває без прав).
BUILD_TMP = ROOT / ".buildtmp"
BUILD_TMP.mkdir(parents=True, exist_ok=True)

failures = 0
children: list[McpClient] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures += 1


def utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def fake_config(name: str = "fake") -> McpServerConfig:
    return McpServerConfig(
        name=name,
        command=sys.executable,
        args=[str(FAKE_SERVER)],
        cwd=str(ROOT),
    )


def make_client(name: str = "fake", timeout: float = 15.0) -> McpClient:
    client = McpClient(fake_config(name), timeout=timeout)
    children.append(client)
    return client


def cleanup() -> None:
    for client in children:
        try:
            client.stop(grace=1.0)
        except Exception:  # noqa: BLE001 - прибирання не має падати
            pass
    children.clear()


def test_config_parsing() -> None:
    empty = McpServerConfig.from_dict(None)
    check("конфіг із None не падає", empty.name == "" and empty.command == "" and empty.enabled)

    weird = McpServerConfig.from_dict(
        {"command": 42, "args": "a b", "env": [1, 2], "enabled": "ні", "cwd": 3},
        name="server-1",
    )
    check("криві типи конвертуються", weird.command == "42" and weird.args == ["a", "b"])
    check("env-не-dict стає порожнім", weird.env == {})
    check("enabled з рядка «ні»", weird.enabled is False)
    check("cwd з числа", weird.cwd == "3")

    extra = McpServerConfig.from_dict({"command": "py", "unknown": {"deep": [1]}}, name="x")
    check("зайві ключі ігноруються", extra.command == "py" and extra.name == "x")
    check("to_dict/from_dict кругове", McpServerConfig.from_dict(extra.to_dict(), name="x").to_dict() == extra.to_dict())

    display = McpServerConfig(name="fs", command="node", args=["fs.js", "--root"]).display
    check("display: назва · команда аргумент", display == "fs · node fs.js", display)

    long_name = namespaced_tool_name("my-server", "x" * 100)
    check("namespaced ім'я ≤ 64", len(long_name) <= 64, long_name)
    check("namespaced зберігає префікс", long_name.startswith("mcp__my_server__"), long_name)

    text = content_to_text(
        [
            {"type": "text", "text": "перший"},
            {"type": "image", "mimeType": "image/png", "data": "..."},
            {"type": "text", "text": "другий"},
        ]
    )
    check("content: текст + опис інших типів", text == "перший\n[image image/png]\nдругий", repr(text))


def test_handshake_and_tools(client: McpClient) -> None:
    client.start()
    check("процес запущено", client.started)

    server_info = client.initialize()
    check("handshake повернув serverInfo", isinstance(server_info, dict) and bool(server_info))
    check("protocolVersion збережено", client.protocol_version == "2025-06-18", client.protocol_version)
    check("running після initialize", client.running)
    check("serverInfo.name = fake-mcp", client.server_info.get("name") == "fake-mcp", str(client.server_info))

    tools = client.list_tools()
    names = sorted(str(tool.get("name")) for tool in tools)
    check("tools/list повернув 2 інструменти", len(tools) == 2 and names == ["echo", "fail"], str(names))
    check("кеш tools заповнено", len(client.tools) == 2)

    schemas = client.tool_schemas()
    by_name = {item["function"]["name"]: item for item in schemas}
    check(
        "схема з простором імен",
        "mcp__fake__echo" in by_name and "mcp__fake__fail" in by_name,
        str(sorted(by_name)),
    )
    echo_schema = by_name.get("mcp__fake__echo") or {}
    function = echo_schema.get("function") or {}
    check("схема у форматі OpenAI", echo_schema.get("type") == "function" and "parameters" in function)
    check("parameters з inputSchema", function.get("parameters", {}).get("properties", {}).get("text", {}).get("type") == "string")
    check("опис інструмента збережено", bool(function.get("description")))


def test_calls(client: McpClient) -> None:
    ok, text = client.call_tool("echo", {"text": "привіт, MCP"})
    check("call_tool echo повертає текст", ok and text == "привіт, MCP", repr(text))

    ok, text = client.call_tool("fail", {})
    check("isError -> ok=False", ok is False and "помилка" in text, repr(text))

    ok, text = client.call_namespaced("mcp__fake__echo", {"text": "через namespace"})
    check("call_namespaced працює", ok and text == "через namespace", repr(text))

    try:
        client.call_namespaced("other__echo", {})
        check("чужий префікс -> McpError", False)
    except McpError:
        check("чужий префікс -> McpError", True)

    try:
        client._request("unknown/method", {}, timeout=5.0)  # noqa: SLF001 - перевірка транспорту
        check("невідомий метод -> McpError", False)
    except McpError as exc:
        check("невідомий метод -> McpError", True, str(exc)[:60])


def test_stop_idempotent(client: McpClient) -> None:
    client.stop(grace=1.0)
    check("stop не кидає винятків", True)
    check("running=False після stop", not client.running)
    try:
        client.stop(grace=1.0)
        client.stop()
        check("повторний stop безпечний", True)
    except Exception as exc:  # noqa: BLE001
        check("повторний stop безпечний", False, repr(exc))
    try:
        client.call_tool("echo", {"text": "x"})
        check("виклик після stop -> McpError", False)
    except McpError as exc:
        check("виклик після stop -> McpError", True, str(exc).splitlines()[0][:80])


def test_dead_process_fails_fast() -> None:
    config = McpServerConfig(
        name="broken",
        command=sys.executable,
        args=["-c", "import sys; sys.stderr.write('падіння\\n'); sys.stderr.flush()"],
        cwd=str(ROOT),
    )
    client = McpClient(config, timeout=15.0)
    children.append(client)
    client.start()
    started = time.monotonic()
    try:
        client.initialize()
        check("мертвий процес -> McpError", False)
    except McpError as exc:
        elapsed = time.monotonic() - started
        check("мертвий процес -> McpError", True, str(exc).splitlines()[0][:70])
        check("помилка швидка (<8 с)", elapsed < 8.0, f"{elapsed:.2f} с")
    finally:
        client.stop(grace=0.5)


def test_manager() -> McpManager:
    manager = McpManager()
    disabled = fake_config("off")
    disabled.enabled = False
    statuses = manager.start_all([fake_config("fake"), disabled])
    children.extend(list(manager.servers.values()))

    check("manager: статус працює", statuses.get("fake") == "працює", str(statuses))
    check("manager: вимкнений сервер не стартує", statuses.get("off") == "вимкнено", str(statuses))
    check("manager: status property", manager.status.get("fake") == "працює")

    catalog = manager.tool_catalog()
    check("manager: каталог містить 2 інструменти", len(catalog) == 2, str([item["full_name"] for item in catalog]))
    entry = next((item for item in catalog if item["name"] == "echo"), {})
    check(
        "manager: каталог має поля",
        entry.get("server") == "fake" and entry.get("full_name") == "mcp__fake__echo" and "description" in entry,
        str(entry),
    )

    schemas = manager.tool_schemas()
    check("manager: схеми агрегуються", len(schemas) == 2)

    check("manager: handles своє ім'я", manager.handles("mcp__fake__echo"))
    check("manager: не handles чуже ім'я", not manager.handles("read_file"))

    ok, text = manager.call("mcp__fake__echo", {"text": "з менеджера"})
    check("manager: маршрутизація виклику", ok and text == "з менеджера", repr(text))

    ok, text = manager.call("mcp__fake__fail", {})
    check("manager: помилка інструмента", ok is False and "помилка" in text, repr(text))

    ok, text = manager.call("mcp__nope__x", {})
    check("manager: невідома назва -> (False, текст)", ok is False and "Невідомий" in text, text[:70])

    check("manager: remove повертає True", manager.remove("fake"))
    check("manager: remove невідомого -> False", manager.remove("fake") is False)
    check("manager: handles після remove", not manager.handles("mcp__fake__echo"))
    manager.stop_all()
    check("manager: stop_all очищає", manager.servers == {} and manager.status == {})
    return manager


def test_timeout() -> None:
    """Сервер мовчить — клієнт має кинути McpError приблизно за таймаутом."""
    config = McpServerConfig(
        name="mute",
        command=sys.executable,
        args=["-c", "import sys; [line for line in sys.stdin]"],
        cwd=str(ROOT),
    )
    client = McpClient(config, timeout=1.0)
    children.append(client)
    client.start()
    started = time.monotonic()
    try:
        client.initialize()
        check("таймаут -> McpError", False)
    except McpError as exc:
        elapsed = time.monotonic() - started
        check("таймаут -> McpError", True, str(exc).splitlines()[0][:70])
        check("таймаут ~1 с, не довше 6 с", 0.5 <= elapsed <= 6.0, f"{elapsed:.2f} с")
    finally:
        client.stop(grace=0.5)


def test_config_files() -> None:
    tmp = BUILD_TMP / f"mcp-{uuid.uuid4().hex[:10]}"
    os.makedirs(tmp, exist_ok=True)
    try:
        first = tmp / "one.json"
        first.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "alpha": {"command": "python", "args": ["a.py"], "env": {"K": "1"}},
                        "beta": {"command": "node"},
                    }
                }
            ),
            encoding="utf-8",
        )
        second = tmp / "two.json"
        second.write_text(
            json.dumps({"alpha": {"command": "python3", "args": "a.py b.py", "enabled": False}}),
            encoding="utf-8",
        )
        broken = tmp / "broken.json"
        broken.write_text("{не json", encoding="utf-8")

        configs = McpManager.load_configs([first, broken, tmp / "missing.json", second])
        by_name = {config.name: config for config in configs}
        check("load_configs: обидва файли прочитано", set(by_name) == {"alpha", "beta"}, str(sorted(by_name)))
        check("load_configs: пізніший перекриває", by_name["alpha"].command == "python3")
        check("load_configs: аргументи з рядка", by_name["alpha"].args == ["a.py", "b.py"])
        check("load_configs: enabled=False збережено", by_name["alpha"].enabled is False)
        check("load_configs: source — шлях файлу", by_name["alpha"].source == str(second))
        check("load_configs: порожній список", McpManager.load_configs([]) == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    global failures
    utf8_stdout()
    started = time.monotonic()
    manager: McpManager | None = None
    try:
        test_config_parsing()
        test_config_files()

        client = make_client("fake")
        test_handshake_and_tools(client)
        test_calls(client)
        test_stop_idempotent(client)

        test_dead_process_fails_fast()
        test_timeout()
        manager = test_manager()
    except Exception as exc:  # noqa: BLE001 - тест має показати причину, а не стек
        failures += 1
        print(f"[FAIL] непередбачений виняток: {type(exc).__name__}: {exc}")
    finally:
        cleanup()
        if manager is not None:
            manager.stop_all()

    elapsed = time.monotonic() - started
    print("-" * 60)
    print(f"Провалено: {failures}" if failures else "Усе пройдено.")
    print(f"Час: {elapsed:.2f} с")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


# ── unittest-обгортка (додано 10.11.2026) ──────────────────────────────────
# Для `python -m unittest discover` ці перевірки раніше були невидимі:
# файл — скрипт із власним main(), а не TestCase. Тепер discover запускає
# його й падає, якщо main() повернув ненульовий код. Запуск як скрипт
# (`python tests/test_mcp_client.py`) поводиться як раніше.
import unittest as _unittest  # noqa: E402


class _ScriptSuite(_unittest.TestCase):
    def test_script_passes(self) -> None:
        code = main()
        self.assertEqual(code, 0, f"main() повернув {code}")
