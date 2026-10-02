"""browser_type with expect_origin hands the origin check to the engine.

A credential manager filling a login needs the value to land on the login's
own site and nowhere else. Checking the page first and typing afterwards leaves
a gap in which the page can navigate, and fill types a text field key by key,
so a navigation during typing sends the rest of the text to the next page.
The engine checks the field's own document origin in the same step as the
write; these tests hold that the server passes the request through, and that
a call without it is exactly the call it always was.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from invisible_playwright_mcp.mcp import actions, server


class _Page:
    def __init__(self):
        self.calls = []

    async def fill(self, selector, text, **kw):
        self.calls.append((selector, text, kw))

    async def eval_on_selector(self, selector, expression, arg=None):
        return False  # the field kept what was written


class _Session:
    def __init__(self):
        self._page = _Page()

    def page(self):
        return self._page


def test_expect_origin_reaches_the_engine():
    s = _Session()
    out = asyncio.run(actions.type_text(s, "#p", "secret", "https://login.example.com"))
    assert out == "typed into #p"
    assert s._page.calls == [("#p", "secret", {"timeout": 15_000, "expect_origin": "https://login.example.com"})]


def test_without_it_the_fill_is_unchanged():
    s = _Session()
    asyncio.run(actions.type_text(s, "#q", "hello"))
    assert s._page.calls == [("#q", "hello", {"timeout": 15_000})]


def test_expect_input_type_rides_with_expect_origin():
    s = _Session()
    asyncio.run(actions.type_text(s, "#p", "secret", "https://login.example.com", "password"))
    assert s._page.calls[-1][2] == {"timeout": 15_000, "expect_origin": "https://login.example.com",
                                    "expect_input_type": "password"}
    with pytest.raises(ValueError):
        asyncio.run(actions.type_text(s, "#p", "secret", None, "password"))


def test_the_tool_declares_it_as_optional():
    params = inspect.signature(server.browser_type).parameters
    assert "expect_origin" in params
    assert params["expect_origin"].default is None
    assert params["expect_input_type"].default is None



class _FailingPage:
    """A page whose fill fails with `message`, and which records any attempt
    to read it afterwards: the credential path must not diagnose by reading
    page text, which may by then hold the value."""

    def __init__(self, message):
        self.message = message
        self.read = False

    async def fill(self, selector, text, **kw):
        raise RuntimeError(self.message)

    async def evaluate(self, *a, **kw):
        self.read = True
        return {"covered_by": {"text": "hunter2"}}


class _FailingSession:
    def __init__(self, message):
        self._page = _FailingPage(message)

    def page(self):
        return self._page


def _fail(message):
    s = _FailingSession(message)
    with pytest.raises(RuntimeError) as err:
        asyncio.run(actions.type_text(s, "#p", "hunter2", "https://login.example.com"))
    return s._page, err.value


def test_a_refusal_says_nothing_was_written_in_one_fixed_sentence():
    page, err = _fail("fill expect_origin='https://login.example.com', actual origin='https://evil.example': "
                      "error:origin: origin mismatch or target detached/stale; nothing was written")
    assert str(err) == ("expect_origin refused: the field's page is not on https://login.example.com "
                        "or the field changed; nothing was written")
    assert err.__cause__ is None and err.__suppress_context__
    assert not page.read


def test_an_unknown_outcome_never_claims_nothing_was_written():
    page, err = _fail("fill expect_origin='https://login.example.com', actual origin='https://login.example.com': "
                      "TargetClosedError: target unavailable, detached or stale; value was written; trusted event delivery failed")
    assert "nothing was written" not in str(err)
    assert "outcome is unknown" in str(err)
    assert not page.read


def test_the_value_never_comes_back_in_an_error():
    page, err = _fail("fill expect_origin='https://login.example.com': something echoed hunter2 back; value was written")
    assert "hunter2" not in str(err)
    assert err.__cause__ is None and err.__suppress_context__


# --- through the real engine -------------------------------------------------


@pytest.fixture(scope="module")
def login_page():
    import http.server
    import threading

    body = b"<html><body><input id=p type=password></body></html>"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.mark.e2e
async def test_the_engine_writes_on_the_expected_origin_and_nowhere_else(login_page):
    from invisible_playwright.async_api import InvisiblePlaywright

    async with InvisiblePlaywright(seed=1, headless=True) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()

        class _S:
            def page(self):
                return page

        s = _S()
        await page.goto(login_page + "/login")
        with pytest.raises(Exception) as refused:
            await actions.type_text(s, "#p", "hunter2", "https://login.example.com")
        assert "hunter2" not in str(refused.value)
        assert await page.input_value("#p") == ""

        with pytest.raises(Exception) as wrong_type:
            await actions.type_text(s, "#p", "hunter2", login_page, "text")
        assert "nothing was written" in str(wrong_type.value)
        assert await page.input_value("#p") == ""

        assert await actions.type_text(s, "#p", "hunter2", login_page, "password") == "typed into #p"
        assert await page.input_value("#p") == "hunter2"
        await ctx.close()
