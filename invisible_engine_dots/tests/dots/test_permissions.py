"""The one table of the Dot's tools and the permission each exercises."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.dots.permissions import (
    TOOL_PERMISSIONS,
    offered_tools,
    tool_permission,
    tool_starts_terminal,
    tool_target,
)


def test_every_tool_maps_to_the_permission_of_the_design() -> None:
    assert {name: entry.permission for name, entry in TOOL_PERMISSIONS.items()} == {
        "exec": "computer.exec",
        "exec_session": "computer.exec",
        "list_exec_sessions": "computer.exec",
        "read_file": "files.read",
        "list_dir": "files.read",
        "find_files": "files.read",
        "grep": "files.read",
        "write_file": "files.write",
        "edit_file": "files.write",
        "apply_patch": "files.write",
        "cron": "automations",
        "computer_screenshot": "computer.screenshot",
        "browser_identity_list": "browser.identity.list",
        "browser_identity_create": "browser.identity.create",
        "browser_identity_delete": "browser.identity.delete",
        "browser_identity_launch": "browser.identity.launch",
        "browser_identity_close": "browser.identity.close",
        "browser_navigate": "browser.navigate",
        "browser_snapshot": "browser.read",
        "browser_read_text": "browser.read",
        "browser_screenshot": "browser.read",
        "browser_click": "browser.act",
        "browser_click_at": "browser.act",
        "browser_type": "browser.act",
        "browser_press_key": "browser.act",
        "browser_select_option": "browser.act",
        "browser_scroll": "browser.act",
    }


def test_a_terminal_is_an_argument_of_exec_under_the_permission_of_exec(tmp_path, dot_store) -> None:
    from nanobot.dots.permissions import build_registry

    exec_tool = build_registry(_deps(tmp_path, dot_store)).get("exec")

    assert exec_tool is not None
    assert exec_tool.parameters["properties"]["tty"]["type"] == "boolean"
    assert tool_permission("exec") == "computer.exec"
    assert not {name for name in TOOL_PERMISSIONS if "tty" in name or "terminal" in name or "pty" in name}


def test_every_tool_of_the_table_states_what_of_its_call_may_be_shown() -> None:
    for name, entry in TOOL_PERMISSIONS.items():
        assert callable(entry.target), name
        # Nothing to name is None, not an error.
        assert entry.target({}) is None, name
    assert tool_target("exec", {"command": "ls"}) == "ls"
    assert tool_target("web_search", {"query": "ls"}) is None


def test_only_a_call_of_exec_that_asks_for_a_tty_starts_a_terminal_session() -> None:
    assert tool_starts_terminal("exec", {"command": "python3", "tty": True}) is True
    for params in ({"command": "python3"}, {"command": "python3", "tty": False}, {"command": "x", "tty": "yes"}):
        assert tool_starts_terminal("exec", params) is False, params
    # No other tool starts one, whatever its arguments say; nor does a call with arguments of no shape.
    for name in TOOL_PERMISSIONS:
        if name != "exec":
            assert tool_starts_terminal(name, {"command": "x", "tty": True}) is False, name
    assert tool_starts_terminal("exec", "tty") is False
    assert tool_starts_terminal("web_search", {"tty": True}) is False


def test_the_table_cannot_be_changed_by_a_caller() -> None:
    with pytest.raises(TypeError):
        TOOL_PERMISSIONS["web_search"] = TOOL_PERMISSIONS["exec"]  # type: ignore[index]


def test_a_tool_reports_its_permission_and_an_unknown_one_reports_none() -> None:
    assert tool_permission("apply_patch") == "files.write"
    for name in ("web_search", "web_fetch", "message", "spawn", "read", "process", ""):
        assert tool_permission(name) == ""


def test_the_model_is_offered_the_tools_whose_permission_is_allow_or_ask() -> None:
    assert offered_tools({"computer.exec": "ask", "files.read": "allow", "files.write": "deny", "automations": "ask"}) == [
        "cron",
        "exec",
        "exec_session",
        "find_files",
        "grep",
        "list_dir",
        "list_exec_sessions",
        "read_file",
    ]


def test_a_missing_permission_is_a_deny() -> None:
    assert offered_tools({}) == []
    assert offered_tools({"files.write": "deny"}) == []
    assert offered_tools({"files.write": "allow"}) == ["apply_patch", "edit_file", "write_file"]


def test_a_permission_the_table_does_not_know_offers_nothing() -> None:
    assert offered_tools({"web.fetch": "allow", "subagents": "allow", "message.send": "allow"}) == []


def test_the_result_is_sorted() -> None:
    allowed = {entry.permission: "allow" for entry in TOOL_PERMISSIONS.values()}
    names = offered_tools(allowed)
    assert names == sorted(names)
    assert set(names) == set(TOOL_PERMISSIONS)


def _deps(tmp_path, store):
    from fakes.browser_manager import make_browser_manager
    from fakes.local_computer import LocalComputer

    from nanobot.agent.tools.exec_session import ExecSessionManager
    from nanobot.cron.service import CronService
    from nanobot.dots.permissions import ToolDeps

    computer = LocalComputer(tmp_path)
    return ToolDeps(
        computer=computer,
        exec_session_manager=ExecSessionManager(),
        cron_service=CronService(tmp_path / "cron" / "jobs.json"),
        browser=make_browser_manager(tmp_path, store, computer),
    )


def test_build_registry_registers_exactly_the_tools_of_the_table(tmp_path, dot_store) -> None:
    from nanobot.dots.permissions import build_registry

    registry = build_registry(_deps(tmp_path, dot_store))

    assert sorted(registry.tool_names) == sorted(TOOL_PERMISSIONS)


def test_every_registered_tool_is_named_as_the_table_names_it(tmp_path, dot_store) -> None:
    from nanobot.dots.permissions import build_registry

    registry = build_registry(_deps(tmp_path, dot_store))

    for name in TOOL_PERMISSIONS:
        tool = registry.get(name)
        assert tool is not None and tool.name == name


def test_the_tools_of_one_registry_share_the_computer_of_the_deps(tmp_path, dot_store) -> None:
    from nanobot.dots.permissions import build_registry

    deps = _deps(tmp_path, dot_store)
    registry = build_registry(deps)

    for name in ("exec", "read_file", "write_file", "find_files", "grep", "apply_patch"):
        assert registry.get(name).computer is deps.computer


# --- the arguments the gate compares -----------------------------------------------------------------
#
# The gate treats two calls as the same when their arguments, after the tool's own cast and validation,
# have the same canonical JSON (store.canonical_arguments). Python's json tells 1 from 1.0, so the one
# way this could split a repeated identical call in two is a number that reaches the gate once as an int
# and once as a float. These tests close that for every tool of the table.


def _schema_nodes(schema, path):
    """Every schema node of a tool's parameters, with the path that leads to it."""
    yield path, schema
    for key, child in (schema.get("properties") or {}).items():
        yield from _schema_nodes(child, (*path, key))
    if isinstance(schema.get("items"), dict):
        yield from _schema_nodes(schema["items"], (*path, "[]"))
    if isinstance(schema.get("additionalProperties"), dict):
        yield from _schema_nodes(schema["additionalProperties"], (*path, "{}"))
    for key in ("anyOf", "oneOf", "allOf"):
        for index, child in enumerate(schema.get(key) or []):
            yield from _schema_nodes(child, (*path, f"{key}[{index}]"))


def _types(node) -> set[str]:
    declared = node.get("type")
    return set(declared) if isinstance(declared, list) else {declared}


def test_no_argument_of_a_tool_in_the_table_is_a_float_or_has_no_type(tmp_path, dot_store) -> None:
    from nanobot.dots.permissions import build_registry

    registry = build_registry(_deps(tmp_path, dot_store))
    for name in TOOL_PERMISSIONS:
        for path, node in _schema_nodes(registry.get(name).parameters, (name,)):
            types = _types(node)
            where = ".".join(path)
            assert types <= {"string", "integer", "boolean", "array", "object", "null"}, (
                f"{where} is typed {types}: a float argument makes 1 and 1.0 two calls; "
                "normalize store.canonical_arguments before adding one"
            )
            assert node.get("type") is not None, f"{where} has no type, so nothing casts it"
            if "integer" in types:
                assert len(path) == 2, f"{where} is a nested integer: extend the next test to reach it"


# What a valid call needs besides the argument under test, where the required fields alone are not enough.
_EXTRA_ARGUMENTS = {"cron": {"action": "add", "message": "m"}}


def _sample(schema):
    declared = [t for t in _types(schema) if t != "null"][0]
    if "enum" in schema:
        return schema["enum"][0]
    if declared == "string":
        return "x"
    if declared == "integer":
        return max(schema.get("minimum", 1), 1)
    if declared == "boolean":
        return True
    if declared == "array":
        return [_sample(schema["items"])]
    return {key: _sample(child) for key, child in schema.get("properties", {}).items() if key in schema.get("required", [])}


def test_an_integer_argument_reaches_the_gate_as_the_same_int_however_the_model_writes_it(tmp_path, dot_store) -> None:
    from nanobot.dots.permissions import build_registry
    from nanobot.dots.store import canonical_arguments

    registry = build_registry(_deps(tmp_path, dot_store))
    checked = []
    for name in TOOL_PERMISSIONS:
        schema = registry.get(name).parameters
        required = {key: _sample(schema["properties"][key]) for key in schema.get("required", [])}
        base = {**required, **_EXTRA_ARGUMENTS.get(name, {})}
        assert registry.prepare_call(name, dict(base))[2] is None, f"{name}: the base call of this test is not valid"
        for key, node in schema["properties"].items():
            if "integer" not in _types(node):
                continue
            value = _sample(node)

            def prepared(argument):
                _tool, params, error = registry.prepare_call(name, {**base, key: argument})
                return params, error

            as_int, error = prepared(value)
            assert error is None, f"{name}.{key}={value!r}: {error}"
            as_text, error = prepared(str(value))
            assert error is None, f"{name}.{key}={value!r} as text: {error}"
            # The two accepted spellings are one call.
            assert canonical_arguments(as_int) == canonical_arguments(as_text)
            assert as_int[key] == value and type(as_int[key]) is int
            # A float never gets through to the gate, however it is written.
            for spelling in (float(value), f"{value}.0", f"{value}e0"):
                _params, error = prepared(spelling)
                assert error is not None, f"{name}.{key}={spelling!r} was accepted"
            if value == 1:
                assert prepared(True)[1] is not None, f"{name}.{key}=True was accepted"
            checked.append(f"{name}.{key}")
    # The walk reached the integer arguments of the table, not none of them.
    assert {"exec.timeout", "read_file.limit", "grep.head_limit", "edit_file.occurrence", "cron.every_seconds"} <= set(checked)


# --- the browser tools ------------------------------------------------------------------------------------------

BROWSER_PERMISSIONS = {
    "browser.identity.list",
    "browser.identity.create",
    "browser.identity.delete",
    "browser.identity.launch",
    "browser.identity.close",
    "browser.navigate",
    "browser.read",
    "browser.act",
}
PAGE_PERMISSIONS = {"browser.navigate", "browser.read", "browser.act"}
# Words of a tool name that would mean it browses, which no tool outside the browser rows may have.
BROWSING_WORDS = {"web", "fetch", "http", "https", "url", "browse", "chromium", "chrome", "firefox", "playwright", "selenium", "puppeteer", "scrape", "crawl"}


def _mcp_tool_names() -> set[str]:
    import json

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "mcp-tools-0.70.2.json"
    return {tool["name"] for tool in json.loads(fixture.read_text(encoding="utf-8"))["tools"]}


def test_every_browser_tool_is_served_by_invisible_playwright_mcp_and_no_other_tool_browses(tmp_path, dot_store) -> None:
    # The owner's rule: the only browser of a Dot is invisible-playwright-mcp. An identity tool is the
    # BrowserManager's, which starts that server and nothing else; a page tool names the tool of that server it
    # calls, and the captured tool list of the pinned version has it. A row that is neither is refused here.
    from nanobot.dots import browser_tools
    from nanobot.dots.browser import BrowserManager
    from nanobot.dots.permissions import build_registry

    deps = _deps(tmp_path, dot_store)
    registry = build_registry(deps)
    served = _mcp_tool_names()
    manager_tools = (
        browser_tools.BrowserIdentityListTool,
        browser_tools.BrowserIdentityCreateTool,
        browser_tools.BrowserIdentityDeleteTool,
        browser_tools.BrowserIdentityLaunchTool,
        browser_tools.BrowserIdentityCloseTool,
    )
    for name, entry in TOOL_PERMISSIONS.items():
        tool = registry.get(name)
        if entry.permission.startswith("browser.identity."):
            assert isinstance(tool, manager_tools), name
            assert isinstance(tool.browser, BrowserManager) and tool.browser is deps.browser, name
        elif entry.permission in PAGE_PERMISSIONS:
            assert isinstance(tool, browser_tools.BrowserPageTool), name
            assert tool.browser is deps.browser, name
            assert name in browser_tools.PAGE_TOOLS, name
            assert browser_tools.PAGE_TOOLS[name].mcp_tool in served, f"{name} calls a tool the server does not have"
        else:
            # Whatever else the table holds is no browser: not by its permission, its name or its class.
            assert not name.startswith("browser"), name
            assert not isinstance(tool, (browser_tools.BrowserPageTool, *manager_tools)), name
            assert not set(name.split("_")) & BROWSING_WORDS, name
    # And every page tool that is defined has its row: nothing defined is left out of the permission table.
    assert set(browser_tools.PAGE_TOOLS) == {name for name, e in TOOL_PERMISSIONS.items() if e.permission in PAGE_PERMISSIONS}


def test_each_browser_permission_offers_its_own_tools_only() -> None:
    assert offered_tools({"browser.read": "allow"}) == ["browser_read_text", "browser_screenshot", "browser_snapshot"]
    assert offered_tools({"browser.navigate": "ask"}) == ["browser_navigate"]
    assert offered_tools({"browser.identity.launch": "allow"}) == ["browser_identity_launch"]
    assert offered_tools({"computer.screenshot": "allow"}) == ["computer_screenshot"]
    assert offered_tools({"browser.act": "deny", "browser.read": "deny"}) == []
    assert offered_tools({"browser.act": "allow"}) == [
        "browser_click",
        "browser_click_at",
        "browser_press_key",
        "browser_scroll",
        "browser_select_option",
        "browser_type",
    ]


def test_a_browser_call_names_its_identity_and_what_it_acted_on() -> None:
    ident = "shop-ab12cd"
    assert tool_target("browser_navigate", {"identity_id": ident, "url": "https://example.com/a?q=1"}) == (
        f"{ident}: https://example.com/a?q=1"
    )
    assert tool_target("browser_navigate", {"identity_id": ident, "url": "https://u:pw@example.com/"}) == (
        f"{ident}: https://example.com/"
    )
    assert tool_target("browser_click", {"identity_id": ident, "selector": "#buy"}) == f"{ident}: #buy"
    assert tool_target("browser_read_text", {"identity_id": ident}) == ident
    assert tool_target("browser_click_at", {"identity_id": ident, "x": 10, "y": 20}) == f"{ident}: at 10,20"
    assert tool_target("browser_scroll", {"identity_id": ident, "direction": "down"}) == f"{ident}: down"
    assert tool_target("browser_screenshot", {"identity_id": ident}) == ident
    assert tool_target("browser_identity_launch", {"identity_id": ident}) == ident
    assert tool_target("browser_identity_create", {"name": "Shopping", "proxy": "http://u:pw@h:1"}) == "Shopping"
    assert tool_target("browser_identity_list", {}) is None
    assert tool_target("computer_screenshot", {}) is None


def test_what_a_person_types_into_a_browser_is_never_a_target() -> None:
    ident = "shop-ab12cd"
    typed = {"identity_id": ident, "selector": "input[name=password]", "text": "hunter2"}
    assert tool_target("browser_type", typed) == f"{ident}: input[name=password]"
    assert tool_target("browser_select_option", {"identity_id": ident, "selector": "#c", "value": "secret-code"}) == f"{ident}: #c"
    assert tool_target("browser_press_key", {"identity_id": ident, "key": "Enter"}) == f"{ident}: Enter"


def test_the_proxy_of_an_identity_is_masked_in_the_arguments_an_approval_shows() -> None:
    from nanobot.dots.permissions import tool_arguments

    shown = tool_arguments("browser_identity_create", {"name": "shop", "proxy": "http://user:hunter2@proxy.test:8080"})

    assert shown == {"name": "shop", "proxy": "***"}
    # Nothing else of any call is changed, and a call without a proxy is as it was.
    assert tool_arguments("browser_identity_create", {"name": "shop"}) == {"name": "shop"}
    assert tool_arguments("exec", {"command": "ls", "timeout": 5}) == {"command": "ls", "timeout": 5}
    assert tool_arguments("not_a_tool", {"proxy": "http://u:p@h"}) == {"proxy": "http://u:p@h"}


def test_an_approval_shows_the_url_a_navigation_will_open_without_its_user_and_password() -> None:
    from nanobot.dots.permissions import tool_arguments

    ident = "shop-abc123"
    for url in (
        "https://example.com/a?token=s3cret&q=1",
        "https://example.com/p#access_token=abc",
        "https://example.com/c?d=exfiltrated",
        "http://example.com",
    ):
        shown = tool_arguments("browser_navigate", {"identity_id": ident, "url": url})
        # The query is what a prompt-injected model sends out: the approver sees all of it.
        assert shown == {"identity_id": ident, "url": url}
    shown = tool_arguments("browser_navigate", {"identity_id": ident, "url": "https://u:pw@example.com/a?k=v"})
    assert shown["url"] == "https://example.com/a?k=v"
    # A call without a URL, or with one that is not text, is as it was.
    assert tool_arguments("browser_navigate", {"identity_id": ident}) == {"identity_id": ident}
    assert tool_arguments("browser_navigate", {"identity_id": ident, "url": 5}) == {"identity_id": ident, "url": 5}
    # The text of a typed field stays (a person approving typing sees what is typed, architecture section 6).
    typed = {"identity_id": ident, "selector": "#a", "text": "hunter2"}
    assert tool_arguments("browser_type", typed) == typed


# --- the table as GET /tools shows it ----------------------------------------------------------------


def test_the_tool_table_has_a_row_per_tool_in_the_order_of_the_permission_table(tmp_path, dot_store) -> None:
    from nanobot.dots.permissions import build_registry, tool_table

    registry = build_registry(_deps(tmp_path, dot_store))
    rows = tool_table(registry, {"exec", "grep"})

    assert [row["name"] for row in rows] == list(TOOL_PERMISSIONS)
    for row in rows:
        assert row["permission"] == TOOL_PERMISSIONS[row["name"]].permission
        assert row["description"] == registry.get(row["name"]).description
        assert row["offered"] is (row["name"] in {"exec", "grep"})


def test_the_tool_table_refuses_a_registry_that_lacks_a_tool_of_the_table(tmp_path, dot_store) -> None:
    from nanobot.dots.permissions import build_registry, tool_table

    registry = build_registry(_deps(tmp_path, dot_store))
    registry.unregister("cron")

    with pytest.raises(LookupError, match="cron"):
        tool_table(registry, ())
