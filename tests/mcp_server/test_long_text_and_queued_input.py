"""browser_type finishes long text, and input to one browser queues.

Measured 2026-09-30 on the pinned engine: fill types a text field at the
session's human rhythm, about 385 ms a character, so a 1,330-character message
into a contact form's textarea was still typing when the MCP call timed out at
300 s, with 890 characters to go. And two browser_type calls issued at once
drove one page's focus and keyboard together: the second field ended up holding
"BBAAABABBABAB...", the first a single "A".

The unit tests hold the shape with doubles; the e2e ones hold the outcome
against a real engine and a local page.
"""
from __future__ import annotations

import asyncio
import http.server
import threading
import time

import pytest

from invisible_playwright_mcp.mcp import actions
from invisible_playwright_mcp.mcp.work import Work


class _Locator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    async def input_value(self, timeout=None):
        return self.page.values[self.selector]


class _Keyboard:
    def __init__(self, page):
        self.page = page

    async def insert_text(self, text):
        self.page.calls.append(("insert_text", text))
        limit = self.page.maxlength
        self.page.values[self.page.focused] = text[:limit] if limit else text


class _Page:
    def __init__(self, maxlength=None):
        self.calls, self.values, self.focused = [], {}, None
        self.maxlength = maxlength
        self.keyboard = _Keyboard(self)

    async def fill(self, selector, text, **kw):
        self.calls.append(("fill", selector, text))
        self.focused = selector
        self.values[selector] = text

    def locator(self, selector):
        return _Locator(self, selector)


class _Session:
    def __init__(self, page):
        self._page = page

    def page(self):
        return self._page


def test_short_text_is_still_typed_key_by_key():
    page = _Page()
    asyncio.run(actions.type_text(_Session(page), "#q", "x" * actions.KEYSTROKE_LIMIT))
    assert page.calls == [("fill", "#q", "x" * actions.KEYSTROKE_LIMIT)]


def test_long_text_is_cleared_then_inserted_at_once():
    page = _Page()
    text = "y" * 1330
    out = asyncio.run(actions.type_text(_Session(page), "#t", text))
    assert page.calls == [("fill", "#t", ""), ("insert_text", text)]
    assert "1330 characters" in out


def test_a_truncated_field_is_an_error_that_says_so():
    page = _Page(maxlength=2000)
    with pytest.raises(RuntimeError, match="first 2000 of 2500"):
        asyncio.run(actions.type_text(_Session(page), "#t", "z" * 2500))


class _Slow:
    """A session whose action records when it runs, so overlap is visible."""

    def __init__(self, **kwargs):
        self.spans = []

    async def start(self):
        pass

    def is_usable(self):
        return True


def _work_with(session):
    w = Work("default", factory=_Slow)
    w._open["main"] = session
    return w


async def _span(session, name):
    start = time.monotonic()
    await asyncio.sleep(0.2)
    session.spans.append((name, start, time.monotonic()))
    return name


def test_input_to_one_browser_queues():
    s = _Slow()
    w = _work_with(s)

    async def run():
        return await asyncio.gather(
            w.acting(_span, "a", exclusive=True),
            w.acting(_span, "b", exclusive=True))

    assert asyncio.run(run()) == ["a", "b"]
    (_, a0, a1), (_, b0, b1) = sorted(s.spans, key=lambda x: x[1])
    assert b0 >= a1, "two input commands ran on one browser at once"


def test_reads_do_not_wait_for_input():
    s = _Slow()
    w = _work_with(s)

    async def run():
        return await asyncio.gather(
            w.acting(_span, "type", exclusive=True),
            w.acting(_span, "watch"))

    asyncio.run(run())
    (_, a0, a1), (_, b0, b1) = sorted(s.spans, key=lambda x: x[1])
    assert b0 < a1, "a read waited behind an input command"


def test_the_input_tools_take_the_queue():
    import inspect

    from invisible_playwright_mcp.mcp import server
    for tool in (server.browser_navigate, server.browser_click, server.browser_click_at,
                 server.browser_type, server.browser_select_option, server.browser_press_key):
        fn = getattr(tool, "fn", tool)
        assert "exclusive=True" in inspect.getsource(fn), tool


# --- against a real engine -------------------------------------------------

PAGE = b"""<!doctype html><html><body>
<textarea id="comments" maxlength="2000"></textarea>
<input id="first"><input id="second">
</body></html>"""


@pytest.fixture(scope="module")
def url():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/" % srv.server_port
    srv.shutdown()


async def _with_browser(url, body):
    from invisible_playwright_mcp.mcp.plan import plan_session
    from invisible_playwright_mcp.mcp.session import StealthSession
    session = StealthSession(**plan_session().kwargs)
    await session.start()
    try:
        await actions.navigate(session, url)
        return await body(session)
    finally:
        await session.close()


@pytest.mark.e2e
def test_two_thousand_characters_fill_a_textarea_quickly(url):
    text = ("Coverage: dwelling, personal effects $5k, roadside.\n\nPlease " * 40)[:2000]

    async def body(session):
        start = time.monotonic()
        await actions.type_text(session, "#comments", text)
        took = time.monotonic() - start
        return took, await session.page().locator("#comments").input_value()

    took, value = asyncio.run(_with_browser(url, body))
    assert value == text
    assert took < 30, "2,000 characters took %.1f s" % took


@pytest.mark.e2e
def test_two_concurrent_types_each_land_whole(url):
    async def body(session):
        w = Work("default")
        w._open["main"] = session
        await asyncio.wait_for(asyncio.gather(
            w.acting(actions.type_text, "#first", "AAAAAAAAAAAA", exclusive=True),
            w.acting(actions.type_text, "#second", "BBBBBBBBBBBB", exclusive=True)), 120)
        page = session.page()
        return (await page.locator("#first").input_value(),
                await page.locator("#second").input_value())

    assert asyncio.run(_with_browser(url, body)) == ("AAAAAAAAAAAA", "BBBBBBBBBBBB")
