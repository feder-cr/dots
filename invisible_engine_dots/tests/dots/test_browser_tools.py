"""The browser tools of the Dot against the real BrowserManager and a fake MCP server, and through a real turn.

Each tool is run the way the engine runs one (`run_tool`: registry, cast, validation, error wrapping). The
MCP server is `fake_mcp_server.py`, which serves the captured tool list of invisible-playwright-mcp and
records every call it gets, so what a tool sends is read off the server and not off the tool.
"""

from __future__ import annotations

import base64
import inspect
import json
import re
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes.browser_manager import make_browser_manager, mcp_home
from fakes.dot_config import ALLOW_ALL
from fakes.fake_mcp_server import FIXTURE, PNG, read_record, write_control
from fakes.local_computer import LocalComputer
from fakes.run_tool import run_tool
from fakes.scripted_provider import call, calls, says
from fakes.turn_harness import Harness

from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.cron.service import CronService
from nanobot.dots import store as s
from nanobot.dots.browser import REQUEST_TIMEOUT_S, BrowserManager
from nanobot.dots.browser_tools import PAGE_TOOLS, TYPE_TEXT_MAX, TYPING_SECONDS_PER_KEY_MAX
from nanobot.dots.images import IMAGES_HEADER, TurnImages, bind_turn_images, reset_turn_images
from nanobot.dots.permissions import ToolDeps, build_registry
from nanobot.dots.store import DotStore
from nanobot.dots.turns import OpeningMessage, TurnUnit

BROWSER_ALLOWED = {
    permission: "allow"
    for permission in (
        "computer.screenshot",
        "browser.identity.list",
        "browser.identity.create",
        "browser.identity.delete",
        "browser.identity.launch",
        "browser.identity.close",
        "browser.navigate",
        "browser.read",
        "browser.act",
    )
}
PNG_PLACEHOLDER = "[screenshot, 1x1, not stored]"
# What the runner adds to the message of every failed tool call.
RETRY_HINT = "\n\n[Analyze the error above and try a different approach.]"
NOT_OPEN = "identity {} is not open; call browser_identity_launch first"


class Env:
    def __init__(self, tmp_path: Path, store: DotStore, **limits: int) -> None:
        self.tmp_path = tmp_path
        (tmp_path / "computer").mkdir()
        self.computer = LocalComputer(tmp_path / "computer")
        self.manager: BrowserManager = make_browser_manager(tmp_path, store, self.computer, **limits)
        self.registry: ToolRegistry = build_registry(
            ToolDeps(self.computer, ExecSessionManager(), CronService(tmp_path / "cron" / "jobs.json"), self.manager)
        )
        self.images = TurnImages()

    async def run(self, tool: str, /, **params: Any) -> Any:
        return await run_tool(self.registry, tool, params)

    async def open_identity(self, name: str = "shop") -> str:
        identity = await self.manager.create(name)
        await self.manager.launch(identity.id)
        return identity.id

    def calls(self, identity_id: str) -> list[tuple[str, dict[str, Any]]]:
        record = read_record(mcp_home(self.tmp_path, identity_id))
        return [(entry["name"], entry["args"]) for entry in record if entry["kind"] == "call"]

    def page_calls(self, identity_id: str) -> list[tuple[str, dict[str, Any]]]:
        """What the server was asked after the browser opened."""
        return [(name, args) for name, args in self.calls(identity_id) if name != "browser_open"]


@pytest.fixture
async def bare_env(request: pytest.FixtureRequest, tmp_path: Path, dot_store: DotStore) -> AsyncIterator[Env]:
    """Tools and a manager, run outside any turn; `@pytest.mark.limits(max_open=..., max_identities=...)` sets the manager's."""
    marker = request.node.get_closest_marker("limits")
    made = Env(tmp_path, dot_store, **(marker.kwargs if marker else {}))
    yield made
    await made.manager.close_all()


@pytest.fixture
def env(bare_env: Env) -> Iterator[Env]:
    """The same, in a turn: the images the tools return are kept in `env.images`."""
    token = bind_turn_images(bare_env.images)
    yield bare_env
    reset_turn_images(token)


def said(result: Any) -> str:
    """The message of an error result as the tool wrote it, without the hint the runner adds."""
    assert isinstance(result, ToolResult) and result.is_error, result
    return str(result).removesuffix(RETRY_HINT)


def created_id(text: str) -> str:
    """The id in the answer of browser_identity_create."""
    found = re.search(r"with id (\S+?)\. It is closed", text)
    assert found, text
    return found.group(1)


def _fixture_tools() -> dict[str, dict[str, Any]]:
    return {tool["name"]: tool for tool in json.loads(FIXTURE.read_text(encoding="utf-8"))["tools"]}


# ---------------------------------------------------------------------------
# The page tools call the tool of the server they name
# ---------------------------------------------------------------------------

# model tool, its arguments (besides identity_id), the MCP tool called and the arguments it gets (besides browser)
PAGE_CALLS: list[tuple[str, dict[str, Any], str, dict[str, Any]]] = [
    ("browser_navigate", {"url": "https://example.com/"}, "browser_navigate", {"url": "https://example.com/"}),
    ("browser_snapshot", {}, "browser_snapshot", {}),
    ("browser_read_text", {}, "browser_read_text", {}),
    ("browser_read_text", {"selector": "h1"}, "browser_read_text", {"selector": "h1"}),
    ("browser_read_text", {"max_chars": 20000}, "browser_read_text", {"max_chars": 20000}),
    ("browser_read_text", {"selector": "h1", "max_chars": 50}, "browser_read_text", {"selector": "h1", "max_chars": 50}),
    ("browser_screenshot", {}, "browser_take_screenshot", {}),
    ("browser_click", {"selector": "#go"}, "browser_click", {"selector": "#go"}),
    ("browser_click_at", {"x": 10, "y": 20}, "browser_click_at", {"x": 10, "y": 20}),
    ("browser_type", {"selector": "#q", "text": "hello"}, "browser_type", {"selector": "#q", "text": "hello"}),
    ("browser_press_key", {"key": "Enter"}, "browser_press_key", {"key": "Enter"}),
    ("browser_select_option", {"selector": "#c", "value": "it"}, "browser_select_option", {"selector": "#c", "value": "it"}),
    ("browser_scroll", {"direction": "down"}, "browser_press_key", {"key": "PageDown"}),
    ("browser_scroll", {"direction": "up"}, "browser_press_key", {"key": "PageUp"}),
]


@pytest.mark.parametrize(("tool", "arguments", "mcp_tool", "mcp_arguments"), PAGE_CALLS)
async def test_a_page_tool_calls_the_mcp_tool_it_names_on_the_main_browser(
    env: Env, tool: str, arguments: dict[str, Any], mcp_tool: str, mcp_arguments: dict[str, Any]
) -> None:
    identity_id = await env.open_identity()

    result = await env.run(tool, identity_id=identity_id, **arguments)

    assert not isinstance(result, ToolResult) or not result.is_error, result
    assert env.page_calls(identity_id) == [(mcp_tool, {**mcp_arguments, "browser": "main"})]


def test_every_page_tool_is_exercised_by_the_table_above() -> None:
    assert {row[0] for row in PAGE_CALLS} == set(PAGE_TOOLS)


@pytest.mark.parametrize(("tool", "arguments", "mcp_tool", "mcp_arguments"), PAGE_CALLS)
def test_every_call_a_page_tool_makes_is_one_the_pinned_server_has_with_arguments_it_takes(
    tool: str, arguments: dict[str, Any], mcp_tool: str, mcp_arguments: dict[str, Any]
) -> None:
    served = _fixture_tools()
    sent = PAGE_TOOLS[tool].arguments({"identity_id": "x", **arguments})

    assert sent == mcp_arguments
    assert mcp_tool == PAGE_TOOLS[tool].mcp_tool
    schema = served[mcp_tool]["inputSchema"]
    assert set(sent) <= set(schema["properties"]), f"{tool}: {set(sent) - set(schema['properties'])}"
    assert set(schema.get("required", [])) <= set(sent) | {"browser"}, f"{tool} leaves out a required argument"


async def test_the_model_cannot_choose_the_browser_or_add_an_argument_the_tool_does_not_have(env: Env) -> None:
    identity_id = await env.open_identity()

    support = await env.run("browser_navigate", identity_id=identity_id, url="https://example.com/", browser="support")
    seed = await env.run("browser_snapshot", identity_id=identity_id, seed=7)

    assert isinstance(support, ToolResult) and support.is_error and "browser" in support
    assert isinstance(seed, ToolResult) and seed.is_error
    assert env.page_calls(identity_id) == []


async def test_the_longest_text_is_typed_and_a_longer_one_is_refused_before_it_reaches_the_server(env: Env) -> None:
    identity_id = await env.open_identity()
    longest = "x" * TYPE_TEXT_MAX

    typed = await env.run("browser_type", identity_id=identity_id, selector="#q", text=longest)
    refused = await env.run("browser_type", identity_id=identity_id, selector="#q", text=longest + "y")

    assert not isinstance(typed, ToolResult) or not typed.is_error, typed
    assert f"at most {TYPE_TEXT_MAX}" in said(refused)
    # The server was asked once: a text it could still be typing when the call times out never reaches it.
    assert env.page_calls(identity_id) == [("browser_type", {"selector": "#q", "text": longest, "browser": "main"})]


def test_the_longest_text_is_typed_in_half_the_time_of_a_call_at_the_slowest_pace_and_one_more_key_is_not() -> None:
    assert TYPE_TEXT_MAX * TYPING_SECONDS_PER_KEY_MAX <= REQUEST_TIMEOUT_S / 2
    assert (TYPE_TEXT_MAX + 1) * TYPING_SECONDS_PER_KEY_MAX > REQUEST_TIMEOUT_S / 2
    # The call waits that long: the one number is the manager's default, and the text is described to the model.
    assert inspect.signature(BrowserManager).parameters["request_timeout_s"].default == REQUEST_TIMEOUT_S
    assert str(TYPE_TEXT_MAX) in PAGE_TOOLS["browser_type"].properties["text"]["description"]


# ---------------------------------------------------------------------------
# Opening is explicit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("tool", "arguments", "_mcp", "_args"), PAGE_CALLS)
async def test_a_page_tool_on_an_identity_that_is_not_open_says_so_and_starts_nothing(
    env: Env, tool: str, arguments: dict[str, Any], _mcp: str, _args: dict[str, Any]
) -> None:
    identity = await env.manager.create("closed one")

    result = await env.run(tool, identity_id=identity.id, **arguments)

    assert isinstance(result, ToolResult) and result.is_error
    assert said(result) == NOT_OPEN.format(identity.id)
    assert not env.manager.is_open(identity.id)
    assert env.calls(identity.id) == []
    assert read_record(mcp_home(env.tmp_path, identity.id)) == []
    assert env.images.images == ()


async def test_an_identity_id_that_could_leave_the_browsers_directory_reaches_nothing(env: Env) -> None:
    for bad in ("../etc", "a/b", "A-B", "-x", "x" * 65):
        result = await env.run("browser_navigate", identity_id=bad, url="https://example.com/")
        assert isinstance(result, ToolResult) and result.is_error, bad
        assert "launch" in result or "at most 64" in result, (bad, result)
    assert not (env.tmp_path / "etc").exists()


async def test_launch_opens_the_browser_and_close_keeps_the_profile(env: Env) -> None:
    created = await env.run("browser_identity_create", name="Research")
    identity_id = created_id(created)
    assert "closed: call browser_identity_launch" in created

    launched = await env.run("browser_identity_launch", identity_id=identity_id)
    page = await env.run("browser_navigate", identity_id=identity_id, url="https://example.com/")
    closed = await env.run("browser_identity_close", identity_id=identity_id)

    assert launched == f"The browser of identity {identity_id} is open."
    assert page == "200 https://example.com/"
    assert closed == f"The browser of identity {identity_id} is closed; its profile is kept."
    assert (env.tmp_path / "browsers" / identity_id / "profile").is_dir()
    after = await env.run("browser_navigate", identity_id=identity_id, url="https://example.com/")
    assert said(after) == NOT_OPEN.format(identity_id)


@pytest.mark.limits(max_open=1)
async def test_launching_past_max_open_says_which_browser_it_closed(env: Env) -> None:
    first = await env.open_identity("first")
    second = (await env.manager.create("second")).id

    launched = await env.run("browser_identity_launch", identity_id=second)

    assert launched == f"The browser of identity {second} is open. To stay within max_open it closed {first}."


# ---------------------------------------------------------------------------
# The identity tools
# ---------------------------------------------------------------------------


async def test_the_list_shows_every_identity_with_its_status_and_the_limits_and_no_password(env: Env) -> None:
    open_id = await env.open_identity("open one")
    proxied = await env.manager.create("proxied", "socks5://user:hunter2@proxy.test:1080")

    listing = json.loads(await env.run("browser_identity_list"))

    assert listing["max_open"] == 3 and listing["max_identities"] == 20
    by_id = {identity["id"]: identity for identity in listing["identities"]}
    assert by_id[open_id]["status"] == "open" and by_id[open_id]["last_used_at"] is not None
    assert by_id[proxied.id]["status"] == "available" and by_id[proxied.id]["last_used_at"] is None
    assert by_id[proxied.id]["has_proxy"] is True and by_id[open_id]["has_proxy"] is False
    assert not any(text in json.dumps(listing) for text in ("hunter2", "user", "proxy.test"))
    assert all("proxy" not in identity for identity in listing["identities"])


async def test_creating_with_a_proxy_works_and_the_launch_gives_it_to_the_browser_only(env: Env) -> None:
    created = await env.run("browser_identity_create", name="proxied", proxy="http://user:hunter2@proxy.test:8080")

    assert "hunter2" not in created
    identity_id = created_id(created)
    await env.run("browser_identity_launch", identity_id=identity_id)
    starts = [entry for entry in read_record(mcp_home(env.tmp_path, identity_id)) if entry["kind"] == "start"]
    assert starts[0]["env"]["STEALTHFOX_PROXY"] == "http://user:hunter2@proxy.test:8080"


async def test_creating_with_a_name_alone_is_the_normal_case_and_the_browser_gets_no_proxy_at_all(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STEALTHFOX_PROXY", "http://leak:1")
    alone = created_id(await env.run("browser_identity_create", name="alone"))
    null = created_id(await env.run("browser_identity_create", name="null", proxy=None))
    blank = created_id(await env.run("browser_identity_create", name="blank", proxy="  "))

    for identity_id in (alone, null, blank):
        await env.run("browser_identity_launch", identity_id=identity_id)
        [start] = [entry for entry in read_record(mcp_home(env.tmp_path, identity_id)) if entry["kind"] == "start"]
        assert "STEALTHFOX_PROXY" not in start["env"], identity_id
    listing = json.loads(await env.run("browser_identity_list"))
    assert [identity["has_proxy"] for identity in listing["identities"]] == [False, False, False]


def test_the_create_tool_offers_the_proxy_as_an_explicit_option_and_never_requires_it(env: Env) -> None:
    tool = env.registry.get("browser_identity_create")

    assert tool.parameters["required"] == ["name"]
    assert tool.parameters["properties"]["proxy"]["description"].startswith("Leave this out.")
    assert "network exit" in tool.description


async def test_a_refused_request_is_an_error_result_that_says_why(env: Env) -> None:
    empty = await env.run("browser_identity_create", name="   ")
    gone = await env.run("browser_identity_delete", identity_id="nope-aaaaaa")
    launch_gone = await env.run("browser_identity_launch", identity_id="nope-aaaaaa")

    for result in (empty, gone, launch_gone):
        assert isinstance(result, ToolResult) and result.is_error
    assert "non-empty name" in empty
    assert said(gone) == 'no browser identity "nope-aaaaaa"' == said(launch_gone)


@pytest.mark.limits(max_open=1, max_identities=1)
async def test_the_limit_on_identities_is_reported_to_the_model(env: Env) -> None:
    await env.run("browser_identity_create", name="one")

    over = await env.run("browser_identity_create", name="two")

    assert isinstance(over, ToolResult) and over.is_error and "max_identities 1" in over


async def test_delete_removes_the_identity_and_its_profile(env: Env) -> None:
    identity_id = await env.open_identity("doomed")

    deleted = await env.run("browser_identity_delete", identity_id=identity_id)

    assert deleted == f"Deleted the identity {identity_id} and its profile."
    assert not (env.tmp_path / "browsers" / identity_id).exists()
    assert not mcp_home(env.tmp_path, identity_id).exists()
    assert env.manager.get(identity_id) is None


async def test_a_launch_the_server_refuses_is_an_error_result(env: Env) -> None:
    identity = await env.manager.create("failing", "http://user:hunter2@proxy.test:8080")
    write_control(mcp_home(env.tmp_path, identity.id), fail_open=True)

    result = await env.run("browser_identity_launch", identity_id=identity.id)

    assert isinstance(result, ToolResult) and result.is_error
    assert "did NOT start" in result
    assert not env.manager.is_open(identity.id)


# ---------------------------------------------------------------------------
# What the server says
# ---------------------------------------------------------------------------


async def test_what_the_server_answers_in_text_is_the_result(env: Env) -> None:
    identity_id = await env.open_identity()

    snapshot = await env.run("browser_snapshot", identity_id=identity_id)
    text = await env.run("browser_read_text", identity_id=identity_id, selector="h1")
    key = await env.run("browser_press_key", identity_id=identity_id, key="Enter")

    assert 'button "Go" selector: #go at: [10, 20]' in snapshot
    assert text == "text of h1"
    assert key == "pressed Enter"


async def test_a_max_chars_given_as_null_is_left_out_and_one_below_one_is_refused(env: Env) -> None:
    identity_id = await env.open_identity()

    await env.run("browser_read_text", identity_id=identity_id, max_chars=None)
    refused = await env.run("browser_read_text", identity_id=identity_id, max_chars=0)

    assert env.page_calls(identity_id) == [("browser_read_text", {"browser": "main"})]
    assert isinstance(refused, ToolResult) and refused.is_error


def _words(text: str) -> str:
    return " ".join(text.split())


def test_the_page_tools_say_what_the_pinned_server_says_of_the_arguments_they_pass_on() -> None:
    """One fact, one owner: what an argument means is the server's, captured in the fixture, and ours repeats no more."""
    served = _fixture_tools()
    select = PAGE_TOOLS["browser_select_option"]
    # The server picks an option by its visible label or by its value; the Dot's tool says the same, in that order.
    assert "by its visible label or by its value" in _words(served["browser_select_option"]["description"])
    assert "by its visible label or by its value" in select.description
    assert "visible label" in select.properties["value"]["description"]
    assert "not its label" not in select.description + select.properties["value"]["description"]
    # The server cuts a long text at max_chars, marks the cut and has a default of its own: the Dot passes the
    # argument on and states no number of its own.
    read = PAGE_TOOLS["browser_read_text"]
    assert served["browser_read_text"]["inputSchema"]["properties"]["max_chars"]["type"] == "integer"
    assert set(read.properties) == {"selector", "max_chars"}
    assert str(served["browser_read_text"]["inputSchema"]["properties"]["max_chars"]["default"]) not in read.description


async def test_a_selector_given_as_null_is_left_out_and_the_server_reads_the_page(env: Env) -> None:
    identity_id = await env.open_identity()

    await env.run("browser_read_text", identity_id=identity_id, selector=None)

    assert env.page_calls(identity_id) == [("browser_read_text", {"browser": "main"})]


async def test_a_browser_the_server_lost_is_an_error_result_that_says_to_launch_the_identity_again(env: Env) -> None:
    identity_id = await env.open_identity()
    write_control(mcp_home(env.tmp_path, identity_id), lose_browser_always=True)
    await env.manager.close(identity_id)
    await env.manager.launch(identity_id)

    result = await env.run("browser_snapshot", identity_id=identity_id)

    assert isinstance(result, ToolResult) and result.is_error
    assert "is gone: it closed or crashed" in result
    assert "call browser_identity_launch to open it again" in result
    assert not env.manager.is_open(identity_id)
    # Asked once, not repeated on a reopened browser.
    assert [name for name, _ in env.page_calls(identity_id)].count("browser_snapshot") == 1
    assert [name for name, _ in env.calls(identity_id)].count("browser_open") == 2


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file://localhost/home/dot/.ssh/id_ed25519",
        "FILE:///etc/passwd",
        "about:config",
        "view-source:https://example.com/",
        "data:text/html,<h1>x</h1>",
        "javascript:alert(1)",
        "ftp://example.com/",
        " https://example.com/",
        "example.com",
    ],
)
async def test_navigate_refuses_every_url_that_is_not_http_or_https_and_the_server_sees_nothing(
    env: Env, url: str
) -> None:
    identity_id = await env.open_identity()

    result = await env.run("browser_navigate", identity_id=identity_id, url=url)

    assert said(result) == "browser_navigate opens only http:// and https:// URLs"
    assert env.page_calls(identity_id) == []
    # The refusal holds the rule, not the schema: a provider that decodes under a pattern takes it as the whole
    # value, and "^https?://" left the model nothing to send but "https://".
    schema = env.registry.get("browser_navigate").parameters["properties"]["url"]
    assert "pattern" not in schema


async def test_navigate_still_opens_http_and_https_urls(env: Env) -> None:
    identity_id = await env.open_identity()

    for url in ("http://example.com/a?b=c", "https://example.com/"):
        assert await env.run("browser_navigate", identity_id=identity_id, url=url) == f"200 {url}"


async def test_a_browser_process_that_dies_in_a_call_is_a_crash_the_model_is_told_about(env: Env) -> None:
    identity_id = await env.open_identity()

    result = await env.run("browser_navigate", identity_id=identity_id, url="https://crash.test/now")

    assert isinstance(result, ToolResult) and result.is_error
    assert "exited during browser_navigate" in result and "launch it again" in result
    after = await env.run("browser_snapshot", identity_id=identity_id)
    assert said(after) == NOT_OPEN.format(identity_id)


# ---------------------------------------------------------------------------
# Screenshots: seen by the model, not stored
# ---------------------------------------------------------------------------


async def test_a_screenshot_is_kept_for_the_model_and_the_result_holds_a_placeholder(env: Env) -> None:
    identity_id = await env.open_identity()

    result = await env.run("browser_screenshot", identity_id=identity_id)

    assert result == PNG_PLACEHOLDER
    assert PNG not in result and "base64" not in result
    assert [(image.mime, image.data) for image in env.images.images] == [("image/png", PNG)]
    assert env.images.images[0].caption == f"browser_screenshot of identity {identity_id}"


async def test_the_png_a_click_at_returns_is_dropped_to_a_placeholder_that_says_how_to_look(env: Env) -> None:
    identity_id = await env.open_identity()

    result = await env.run("browser_click_at", identity_id=identity_id, x=10, y=20)

    assert result == "clicked at 10,20\n[screenshot, 1x1, not stored; call browser_screenshot to see the page]"
    assert env.images.images == ()


async def test_a_screenshot_outside_a_model_turn_has_nowhere_to_go(bare_env: Env) -> None:
    identity_id = await bare_env.open_identity()

    shot = await bare_env.run("browser_screenshot", identity_id=identity_id)
    desktop = await bare_env.run("computer_screenshot")

    for result in (shot, desktop):
        assert isinstance(result, ToolResult) and result.is_error
        assert "inside a model turn" in result


async def test_the_desktop_screenshot_is_the_png_the_computer_gives(env: Env) -> None:
    env.computer.desktop_png = base64.b64decode(PNG)

    result = await env.run("computer_screenshot")

    assert result == f"Screenshot of the desktop.\n{PNG_PLACEHOLDER}"
    assert [(image.mime, image.data, image.caption) for image in env.images.images] == [
        ("image/png", PNG, "computer_screenshot of the desktop")
    ]


async def test_a_desktop_that_cannot_be_captured_is_an_error_result_with_the_status(env: Env) -> None:
    env.computer.screenshot_status = 503

    result = await env.run("computer_screenshot")

    assert isinstance(result, ToolResult) and result.is_error
    assert said(result) == "the desktop could not be captured (GET /v1/screenshot failed with status 503)"
    assert env.images.images == ()


# ---------------------------------------------------------------------------
# Through a turn: what the model is asked, and what is stored
# ---------------------------------------------------------------------------

MakeHarness = Callable[..., Harness]


def chat(text: str = "look at the page") -> TurnUnit:
    return TurnUnit(s.CHAT_SESSION_KEY, None, (OpeningMessage(text, {"dots_inbound_id": "in1"}),))


@pytest.fixture
def browsing(make_harness: MakeHarness) -> Callable[..., Harness]:
    def make(script: list[Any], **options: Any) -> Harness:
        return make_harness(script, {**ALLOW_ALL, **BROWSER_ALLOWED}, **options)

    return make


def image_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message["content"]
    return [part for part in content if isinstance(part, dict) and part.get("type") == "image_url"] if isinstance(content, list) else []


async def open_one(h: Harness) -> str:
    identity = await h.browser.create("shop")
    await h.browser.launch(identity.id)
    return identity.id


async def test_the_model_sees_the_screenshot_after_the_tool_message_and_the_transcript_never_holds_it(
    browsing: Callable[..., Harness],
) -> None:
    h = browsing([])
    identity_id = await open_one(h)
    h.provider.script[:] = [
        calls(call("c1", "browser_screenshot", identity_id=identity_id)),
        says("I see a page"),
    ]

    outcome = await h.run(chat())

    assert outcome.kind == "completed"
    first, second = h.provider.requests
    assert not any(image_parts(message) for message in first["messages"])
    last_tool = max(i for i, message in enumerate(second["messages"]) if message["role"] == "tool")
    assert second["messages"][last_tool]["content"] == PNG_PLACEHOLDER
    shown = second["messages"][last_tool + 1]
    assert shown["role"] == "user"
    assert shown["content"][0] == {"type": "text", "text": f"{IMAGES_HEADER}:"}
    assert [part["image_url"]["url"] for part in image_parts(shown)] == [f"data:image/png;base64,{PNG}"]
    assert f"browser_screenshot of identity {identity_id}" in json.dumps(shown["content"])
    assert len(second["messages"]) == last_tool + 2
    # Stored: the text and the placeholder, no bytes, in the transcript or in any event.
    stored = h.messages()
    assert [m["role"] for m in stored if m["role"] == "tool"] == ["tool"]
    tool_message = next(m for m in stored if m["role"] == "tool")
    assert tool_message["content"] == PNG_PLACEHOLDER
    assert PNG not in json.dumps(stored) and PNG not in json.dumps(h.events())
    called = [data for data in h.events_of("tool.called")]
    assert called[0]["tool"] == "browser_screenshot" and called[0]["permission"] == "browser.read" and called[0]["ok"] is True
    assert called[0]["target"] == identity_id


async def test_a_turn_keeps_the_newest_three_images_in_one_message_and_says_what_it_dropped(
    browsing: Callable[..., Harness],
) -> None:
    h = browsing([])
    identity_id = await open_one(h)
    shots = [call(f"c{n}", "browser_screenshot", identity_id=identity_id) for n in range(1, 5)]
    h.provider.script[:] = [*(calls(shot) for shot in shots), says("done")]

    await h.run(chat())

    requests = h.provider.requests
    assert len(requests) == 5
    shown_counts = []
    for request in requests:
        parts = [part for message in request["messages"] for part in image_parts(message)]
        shown_counts.append(len(parts))
    assert shown_counts == [0, 1, 2, 3, 3]
    last = requests[-1]["messages"]
    holders = [message for message in last if image_parts(message)]
    # One message holds them all, and it follows the last tool message.
    assert len(holders) == 1
    assert last[last.index(holders[0]) - 1]["role"] == "tool"
    assert "the newest 3 are shown; 1 earlier of this turn are dropped" in holders[0]["content"][0]["text"]
    assert [part["text"] for part in holders[0]["content"] if part.get("text", "").startswith("Image ")] == [
        f"Image {n}: browser_screenshot of identity {identity_id}" for n in (1, 2, 3)
    ]


async def test_a_later_turn_replays_the_placeholder_and_no_image(browsing: Callable[..., Harness]) -> None:
    h = browsing([])
    identity_id = await open_one(h)
    h.provider.script[:] = [
        calls(call("c1", "browser_screenshot", identity_id=identity_id)),
        says("first answer"),
        says("second answer"),
    ]
    await h.run(chat("first"))
    h.store.write(lambda conn: s.record_inbound(conn, {"id": "in2", "type": "user.message", "ts": "2026-10-05T10:00:00.000Z", "data": {"text": "again"}}, "accepted"))

    await h.run(TurnUnit(s.CHAT_SESSION_KEY, None, (OpeningMessage("again", {"dots_inbound_id": "in2"}),)))

    third = h.provider.requests[-1]["messages"]
    assert not any(image_parts(message) for message in third)
    assert PNG_PLACEHOLDER in json.dumps(third)


async def test_the_desktop_screenshot_reaches_the_model_the_same_way(browsing: Callable[..., Harness]) -> None:
    h = browsing([])
    h.computer.desktop_png = base64.b64decode(PNG)
    h.provider.script[:] = [calls(call("c1", "computer_screenshot")), says("a desktop")]

    await h.run(chat("what is on the screen"))

    second = h.provider.requests[1]["messages"]
    shown = second[-1]
    assert shown["role"] == "user" and len(image_parts(shown)) == 1
    assert "computer_screenshot of the desktop" in json.dumps(shown["content"])
    assert PNG not in json.dumps(h.messages())


async def test_a_policy_that_asks_before_navigating_shows_the_person_the_url_and_runs_after_approval(
    make_harness: MakeHarness,
) -> None:
    permissions = {**ALLOW_ALL, **BROWSER_ALLOWED, "browser.navigate": "ask"}
    h = make_harness([], permissions)
    identity_id = await open_one(h)
    h.provider.script[:] = [calls(call("c1", "browser_navigate", identity_id=identity_id, url="https://example.com/a"))]

    outcome = await h.run(chat("open it"))

    assert outcome.kind == "parked"
    [asked] = h.events_of("approval.requested")
    assert (asked["tool"], asked["permission"]) == ("browser_navigate", "browser.navigate")
    assert asked["arguments"] == {"identity_id": identity_id, "url": "https://example.com/a"}
    assert h.browser.is_open(identity_id)
    # Nothing was sent to the page.
    record = read_record(mcp_home(h.tmp_path, identity_id))
    assert [entry["name"] for entry in record if entry["kind"] == "call"] == ["browser_open"]


async def test_an_approval_to_navigate_shows_the_query_it_will_send_and_not_the_user_and_password(make_harness: MakeHarness) -> None:
    permissions = {**ALLOW_ALL, **BROWSER_ALLOWED, "browser.navigate": "ask"}
    h = make_harness([], permissions)
    identity_id = await open_one(h)
    url = "https://user:pw@example.com/a?token=s3cret&q=1"
    h.provider.script[:] = [calls(call("c1", "browser_navigate", identity_id=identity_id, url=url))]

    await h.run(chat("open it"))

    [asked] = h.events_of("approval.requested")
    assert asked["arguments"] == {"identity_id": identity_id, "url": "https://example.com/a?token=s3cret&q=1"}
    assert "user:pw" not in json.dumps(asked)
    # The call waits with its full arguments, so the approved call goes to the address as asked.
    [pending] = h.store.read(lambda conn: s.list_approvals(conn, "pending"))
    assert pending.arguments["url"] == url


async def test_the_proxy_password_never_reaches_the_host_through_an_approval(make_harness: MakeHarness) -> None:
    permissions = {**ALLOW_ALL, **BROWSER_ALLOWED, "browser.identity.create": "ask"}
    h = make_harness([], permissions)
    h.provider.script[:] = [
        calls(call("c1", "browser_identity_create", name="proxied", proxy="http://user:hunter2@proxy.test:8080"))
    ]

    outcome = await h.run(chat("make one"))

    assert outcome.kind == "parked"
    [asked] = h.events_of("approval.requested")
    assert asked["arguments"] == {"name": "proxied", "proxy": "***"}
    assert "hunter2" not in json.dumps(h.events())
    # The call waits with its full arguments, so the approved call is made as asked.
    [pending] = h.store.read(lambda conn: s.list_approvals(conn, "pending"))
    assert pending.arguments["proxy"] == "http://user:hunter2@proxy.test:8080"


async def test_the_tool_called_event_names_the_identity_and_never_the_text_typed(browsing: Callable[..., Harness]) -> None:
    h = browsing([])
    identity_id = await open_one(h)
    h.provider.script[:] = [
        calls(
            call("c1", "browser_navigate", identity_id=identity_id, url="https://user:pw@example.com/a?q=1"),
            call("c2", "browser_type", identity_id=identity_id, selector="#password", text="hunter2"),
        ),
        says("done"),
    ]

    await h.run(chat("log in"))

    targets = {data["tool"]: data["target"] for data in h.events_of("tool.called")}
    assert targets == {
        "browser_navigate": f"{identity_id}: https://example.com/a?q=1",
        "browser_type": f"{identity_id}: #password",
    }
    assert "hunter2" not in json.dumps(h.events())

