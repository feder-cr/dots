"""The browser tools of the Dot (architecture section 8.3): the identities, the pages of an open one, and the desktop.

The model sees these names, each taking an `identity_id`, and never the names of the MCP server behind
them. Two kinds:

* The identity tools (`browser_identity_*`) are the BrowserManager's: they list, make, delete, open and close
  identities. Opening is explicit. A page tool on an identity that is not open does not open it, it says
  so, so `browser.identity.launch` alone decides whether a browser starts.
* The page tools are rows of `PAGE_TOOLS`: each says which tool of `invisible-playwright-mcp` it calls and with
  what arguments, so the one server of the Dot's browsers is the only thing a page tool can reach. The
  manager adds `browser: "main"` to every call.

A screenshot is shown to the model and not stored (images.py): the tool's result is its text and a placeholder.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.dots.browser import (
    REQUEST_TIMEOUT_S,
    BrowserIdentity,
    BrowserIdentityError,
    BrowserManager,
    result_is_error,
    result_text,
    split_result,
)
from nanobot.dots.computer import Computer, ComputerError
from nanobot.dots.identity_rules import IDENTITY_ID_MAX
from nanobot.dots.images import ToolImage, current_turn_images, placeholder
from nanobot.dots.store import iso_from_ms

_IDENTITY_ID = {
    "type": "string",
    "minLength": 1,
    "maxLength": IDENTITY_ID_MAX,
    "description": "The id of a browser identity, as browser_identity_list shows it.",
}
_OPEN_FIRST = " The identity must be open (browser_identity_launch)."

# The MCP server fills a field by typing it, key by key, at the pace of the library's typing persona: 120 to 280 ms a
# key (invisible-playwright, `_behaviour.py`). A call that outlives REQUEST_TIMEOUT_S is cancelled by the client while
# the server goes on typing, the identity's lock is released, and the next call runs against a page that is still
# being typed into. So a text may be as long as half of that time allows at the slowest pace, which leaves the other
# half to the page, the pauses and the rest of the call. (The pin of the MCP is decisions.md's; a library that does
# not type in the background would lift this.)
TYPING_SECONDS_PER_KEY_MAX = 0.28
TYPE_TEXT_MAX = int(REQUEST_TIMEOUT_S / 2 / TYPING_SECONDS_PER_KEY_MAX)


@dataclass(frozen=True)
class PageTool:
    """A page tool of the Dot: the MCP tool it calls and how it turns its own arguments into that tool's.

    name: the model's tool name.
    mcp_tool: the tool of invisible-playwright-mcp it calls.
    properties: its arguments besides `identity_id`, as a JSON schema's properties.
    required: those among them the model must give.
    arguments: the MCP tool's arguments (without `browser`) from the model's.
    shows_image: whether the image the MCP tool answers with is shown to the model; any other image is dropped.
    confirmation: what the tool says when the MCP tool said nothing.
    refusal: the reason the model's arguments must not be sent to the MCP tool, or None when they may; the tool
        then answers an error and the server is not called.
    """

    name: str
    description: str
    mcp_tool: str
    properties: Mapping[str, Mapping[str, Any]]
    required: tuple[str, ...]
    arguments: Callable[[Mapping[str, Any]], dict[str, Any]]
    shows_image: bool = False
    confirmation: Callable[[Mapping[str, Any]], str] | None = None
    read_only: bool = False
    refusal: Callable[[Mapping[str, Any]], str | None] | None = None


# What browser_navigate may open. The server passes the URL to the page unchecked, so file:///home/dot/... would
# put any file the dot user can read into browser_read_text, whatever files.read says, and about:, view-source:,
# data: and javascript: reach browser internals and run script. Each permission decides only its own action.
# The refusal below holds the rule and the schema has no `pattern`: a provider that decodes under the schema takes a
# pattern as the whole value, and this prefix as a whole value is "https://", which the model was then made to send.
_WEB_URL = r"^https?://"


def _only_web_urls(params: Mapping[str, Any]) -> str | None:
    url = params.get("url")
    if isinstance(url, str) and re.match(_WEB_URL, url):
        return None
    return "browser_navigate opens only http:// and https:// URLs"


def _none(params: Mapping[str, Any]) -> dict[str, Any]:
    return {}


def _taken(*names: str) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """The named arguments the model gave, as they are; one it left out or gave as null is left out."""
    return lambda params: {name: params[name] for name in names if params.get(name) is not None}


def _scroll(params: Mapping[str, Any]) -> dict[str, Any]:
    return {"key": "PageUp" if params.get("direction") == "up" else "PageDown"}


def _string(description: str, **more: Any) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "description": description, **more}


_SELECTOR = _string("A CSS selector or Playwright selector of the element, as browser_snapshot shows it.")

# A Playwright key name, or a key with modifiers: Enter, Tab, Escape, ArrowDown, PageDown, F5, Control+a.
PAGE_TOOLS: Mapping[str, PageTool] = {
    tool.name: tool
    for tool in (
        PageTool(
            "browser_navigate",
            "Load a URL in the browser of an identity and wait for the page to start loading." + _OPEN_FIRST,
            "browser_navigate",
            {"url": _string("The full http or https URL, with its scheme (https://...).", maxLength=4096)},
            ("url",),
            _taken("url"),
            refusal=_only_web_urls,
        ),
        PageTool(
            "browser_snapshot",
            "List the interactive elements of the page of an identity (links, buttons, fields) with their selectors "
            "and the coordinates of each, and the page's title and URL." + _OPEN_FIRST,
            "browser_snapshot",
            {},
            (),
            _none,
            read_only=True,
        ),
        PageTool(
            "browser_read_text",
            "Read the text of the page of an identity, or of the element a selector names. Long text is cut and the "
            "cut is marked: raise max_chars, or narrow the selector." + _OPEN_FIRST,
            "browser_read_text",
            {
                # The server reads with document.querySelector, so only CSS: a selector of browser_snapshot in
                # Playwright's own syntax (:nth-match(...), text=...) fails there.
                "selector": {
                    **_SELECTOR,
                    "type": ["string", "null"],
                    "description": "A CSS selector: read only this element; the whole page when left out.",
                },
                "max_chars": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "description": "The most characters to return; the server's own limit when left out.",
                },
            },
            (),
            _taken("selector", "max_chars"),
            read_only=True,
        ),
        PageTool(
            "browser_screenshot",
            "Take a screenshot of the page of an identity and look at it. Use it when the text of the page does not "
            "tell enough (layout, images, a captcha)." + _OPEN_FIRST,
            "browser_take_screenshot",
            {},
            (),
            _none,
            shows_image=True,
            read_only=True,
        ),
        PageTool(
            "browser_click",
            "Click the element a selector names, in the page of an identity." + _OPEN_FIRST,
            "browser_click",
            {"selector": _SELECTOR},
            ("selector",),
            _taken("selector"),
        ),
        PageTool(
            "browser_click_at",
            "Click the point x, y of the page of an identity, in viewport pixels. Use it for what a selector cannot "
            "reach. It does not return a screenshot: call browser_screenshot to see the result." + _OPEN_FIRST,
            "browser_click_at",
            {
                "x": {"type": "integer", "minimum": 0, "description": "Pixels from the left edge of the viewport."},
                "y": {"type": "integer", "minimum": 0, "description": "Pixels from the top edge of the viewport."},
            },
            ("x", "y"),
            _taken("x", "y"),
            confirmation=lambda params: f"clicked at {params['x']},{params['y']}",
        ),
        PageTool(
            "browser_type",
            "Fill the field a selector names with a text, replacing what it held." + _OPEN_FIRST,
            "browser_type",
            {
                "selector": _SELECTOR,
                "text": {
                    "type": "string",
                    "maxLength": TYPE_TEXT_MAX,
                    "description": f"The text to put in the field, at most {TYPE_TEXT_MAX} characters: it is typed key by key, as a person types, which takes time.",
                },
            },
            ("selector", "text"),
            _taken("selector", "text"),
        ),
        PageTool(
            "browser_press_key",
            "Press a key in the page of an identity: Enter, Tab, Escape, ArrowDown, F5, or a key with modifiers "
            "such as Control+a." + _OPEN_FIRST,
            "browser_press_key",
            {"key": _string("A Playwright key name.", maxLength=40)},
            ("key",),
            _taken("key"),
        ),
        PageTool(
            "browser_select_option",
            "Choose an option of a select element, by its visible label or by its value." + _OPEN_FIRST,
            "browser_select_option",
            {"selector": _SELECTOR, "value": _string("The visible label of the option, or its value.")},
            ("selector", "value"),
            _taken("selector", "value"),
        ),
        PageTool(
            "browser_scroll",
            "Scroll the page of an identity by one screen." + _OPEN_FIRST,
            "browser_press_key",
            {"direction": {"type": "string", "enum": ["up", "down"], "description": "up is PageUp, down is PageDown."}},
            ("direction",),
            _scroll,
            confirmation=lambda params: f"scrolled {params['direction']}",
        ),
        # No back, forward or reload: they were Alt+Left, Alt+Right and F5 through browser_press_key, and a key the
        # server presses reaches the page, never the browser's own shortcuts. Alt+Left is not even a key name of the
        # library ("unknown key: 'Left'": three calls of three failed), and F5 answered that it reloaded a page it
        # did not reload (measured on the library: the page's state survived it). browser_navigate does both: to
        # the address a page came from, and to its own address, which loads it again.
    )
}


def _error(error: BrowserIdentityError) -> ToolResult:
    return ToolResult.error(error.message)


def _identity_json(identity: BrowserIdentity) -> dict[str, Any]:
    return {
        "id": identity.id,
        "name": identity.name,
        "status": identity.status,
        "last_used_at": iso_from_ms(identity.last_used_at) if identity.last_used_at is not None else None,
        "has_proxy": identity.has_proxy,
    }


class _BrowserTool(Tool):
    def __init__(self, browser: BrowserManager) -> None:
        self.browser = browser


class BrowserIdentityListTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_identity_list"

    @property
    def description(self) -> str:
        return (
            "List the browser identities of this Dot: each is a separate browser profile with its own cookies, "
            "logins and fingerprint. Shows whether each is open, and how many may be open at once."
        )

    @property
    def read_only(self) -> bool:
        return True

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self, **kwargs: Any) -> str:
        max_open, max_identities = self.browser.limits
        return json.dumps(
            {
                "identities": [_identity_json(identity) for identity in self.browser.list_identities()],
                "max_open": max_open,
                "max_identities": max_identities,
            },
            ensure_ascii=False,
        )


class BrowserIdentityCreateTool(_BrowserTool):
    @property
    def name(self) -> str:
        return "browser_identity_create"

    @property
    def description(self) -> str:
        return (
            "Create a browser identity: a new browser profile with its own cookies, logins and fingerprint. "
            "It is created closed; open it with browser_identity_launch. Give only a name: the browser then uses "
            "this computer's own network exit, which is what it should do unless the person asked for this one "
            "identity to go through a particular proxy."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": _string("What the identity is for, for example shopping or research.", maxLength=80),
                "proxy": {
                    "type": ["string", "null"],
                    "description": (
                        "Leave this out. Only when the person gave you a proxy for this identity: its URL as they gave "
                        "it, such as http://user:pass@host:port or socks5://host:port."
                    ),
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        }

    async def execute(self, name: str = "", proxy: str | None = None, **kwargs: Any) -> str:
        try:
            identity = await self.browser.create(name, proxy)
        except BrowserIdentityError as error:
            return _error(error)
        return f'Created the identity "{identity.name}" with id {identity.id}. It is closed: call browser_identity_launch to open it.'


class _IdentityActionTool(_BrowserTool):
    """A tool that takes one `identity_id` and does one thing to that identity."""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"identity_id": dict(_IDENTITY_ID)},
            "required": ["identity_id"],
            "additionalProperties": False,
        }


class BrowserIdentityDeleteTool(_IdentityActionTool):
    @property
    def name(self) -> str:
        return "browser_identity_delete"

    @property
    def description(self) -> str:
        return "Delete a browser identity and its whole profile, logins included. This cannot be undone."

    async def execute(self, identity_id: str = "", **kwargs: Any) -> str:
        try:
            await self.browser.delete(identity_id)
        except BrowserIdentityError as error:
            return _error(error)
        return f"Deleted the identity {identity_id} and its profile."


class BrowserIdentityLaunchTool(_IdentityActionTool):
    @property
    def name(self) -> str:
        return "browser_identity_launch"

    @property
    def description(self) -> str:
        return (
            "Open the browser of an identity on the Dot's desktop. Only a few identities can be open at once; "
            "opening one more closes the one used least recently. The first launch can take minutes while the "
            "browser is prepared."
        )

    async def execute(self, identity_id: str = "", **kwargs: Any) -> str:
        was_open = {identity.id for identity in self.browser.list_identities() if identity.status == "open"}
        try:
            await self.browser.launch(identity_id)
        except BrowserIdentityError as error:
            return _error(error)
        closed = sorted(was_open - {i.id for i in self.browser.list_identities() if i.status == "open"})
        note = f" To stay within max_open it closed {', '.join(closed)}." if closed else ""
        return f"The browser of identity {identity_id} is open.{note}"


class BrowserIdentityCloseTool(_IdentityActionTool):
    @property
    def name(self) -> str:
        return "browser_identity_close"

    @property
    def description(self) -> str:
        return "Close the browser of an identity. Its profile, cookies and logins stay on disk."

    async def execute(self, identity_id: str = "", **kwargs: Any) -> str:
        try:
            await self.browser.close(identity_id)
        except BrowserIdentityError as error:
            return _error(error)
        return f"The browser of identity {identity_id} is closed; its profile is kept."


class BrowserPageTool(_BrowserTool):
    """One of `PAGE_TOOLS`: a call of invisible-playwright-mcp on an open identity."""

    def __init__(self, browser: BrowserManager, spec: PageTool) -> None:
        super().__init__(browser)
        self._spec = spec

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def description(self) -> str:
        return self._spec.description

    @property
    def read_only(self) -> bool:
        return self._spec.read_only

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"identity_id": dict(_IDENTITY_ID), **{key: dict(value) for key, value in self._spec.properties.items()}},
            "required": ["identity_id", *self._spec.required],
            "additionalProperties": False,
        }

    async def execute(self, **params: Any) -> Any:
        spec = self._spec
        identity_id = str(params.get("identity_id", ""))
        if spec.refusal is not None and (reason := spec.refusal(params)) is not None:
            return ToolResult.error(reason)
        try:
            result = await self.browser.call_tool(identity_id, spec.mcp_tool, spec.arguments(params))
        except BrowserIdentityError as error:
            return _error(error)
        if result_is_error(result):
            return result
        text, images = split_result(result)
        if not text and spec.confirmation is not None:
            text = spec.confirmation(params)
        lines = [text] if text else []
        for mime, data in images:
            if spec.shows_image:
                turn_images = current_turn_images()
                if turn_images is None:
                    return ToolResult.error("a screenshot can only be taken inside a model turn")
                turn_images.add(ToolImage(f"{spec.name} of identity {identity_id}", mime, data))
                lines.append(placeholder(data))
            else:
                lines.append(placeholder(data, note="call browser_screenshot to see the page"))
        return "\n".join(lines)


class ComputerScreenshotTool(Tool):
    """A screenshot of the Dot's whole desktop: its windows, the browsers among them."""

    def __init__(self, computer: Computer) -> None:
        self.computer = computer

    @property
    def name(self) -> str:
        return "computer_screenshot"

    @property
    def description(self) -> str:
        return "Take a screenshot of the Dot's whole desktop and look at it: its windows, open programs and browsers."

    @property
    def read_only(self) -> bool:
        return True

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self, **kwargs: Any) -> Any:
        turn_images = current_turn_images()
        if turn_images is None:
            return ToolResult.error("a screenshot can only be taken inside a model turn")
        try:
            png = await self.computer.screenshot()
        except ComputerError as error:
            return ToolResult.error(f"the desktop could not be captured ({error})")
        data = base64.b64encode(png).decode("ascii")
        turn_images.add(ToolImage("computer_screenshot of the desktop", "image/png", data))
        return f"Screenshot of the desktop.\n{placeholder(data)}"
