"""browser_type with expect_origin says "typed into" only once the field kept it.

Measured 2026-10-01 on Bluevine's MFA page (Vuetify): browser_type with
expect_origin answered "typed into #input-37", the field was empty afterwards
and Confirm stayed disabled. The same call without expect_origin, which types
key by key, worked. The engine's origin-locked write focuses the field and sets
its value in one in-page step; Vue answers the focus with a re-render that
writes the model's stored (empty) value back into the input, in a microtask
that runs before the trusted input event reaches the model. By the second
write the field already has focus, so nothing answers it.

The readback is one bit, whether the field is empty, so a credential's value,
length or digest is never read. Every retry is origin- and type-locked again.
"""
from __future__ import annotations

import asyncio
import http.server
import threading

import pytest

from invisible_playwright_mcp.mcp import actions

ORIGIN = "https://login.example.com"


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(actions, "SETTLE_S", 0.05)
    monkeypatch.setattr(actions, "SINCE_FOCUS_S", 0.05)


class _Locator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    async def evaluate(self, expression, arg=None, timeout=None):
        self.page.reads.append(expression)
        if self.page.unreadable:
            raise RuntimeError("not a form field")
        return self.page.values.get(self.selector, "") == ""


class _Page:
    """A field the page empties after the first `wipes` writes."""

    def __init__(self, wipes=0, refuse_after=None, unreadable=False):
        self.wipes, self.refuse_after, self.unreadable = wipes, refuse_after, unreadable
        self.values, self.calls, self.reads = {}, [], []

    async def fill(self, selector, text, **kw):
        self.calls.append((selector, text, kw))
        if self.refuse_after is not None and len(self.calls) > self.refuse_after:
            raise RuntimeError("fill expect_origin='%s', actual origin='https://evil.example': "
                               "error:origin: origin mismatch; nothing was written" % ORIGIN)
        if self.wipes:
            self.wipes -= 1
            self.values[selector] = ""
        else:
            self.values[selector] = text

    def locator(self, selector):
        return _Locator(self, selector)


class _Session:
    def __init__(self, page):
        self._page = page

    def page(self):
        return self._page


def _type(page, text="1234567", input_type=None):
    return asyncio.run(actions.type_text(_Session(page), "#c", text, ORIGIN, input_type))


def test_a_write_the_page_emptied_is_written_again_on_the_same_origin(quick):
    page = _Page(wipes=1)
    assert _type(page, input_type="password") == "typed into #c"
    assert page.values["#c"] == "1234567"
    assert len(page.calls) == 2
    for _, _, kw in page.calls:
        assert kw == {"timeout": 15_000, "expect_origin": ORIGIN, "expect_input_type": "password"}


def test_a_kept_write_is_written_once(quick):
    page = _Page()
    assert _type(page) == "typed into #c"
    assert len(page.calls) == 1


def test_the_readback_asks_only_whether_it_is_empty(quick):
    page = _Page(wipes=1)
    _type(page, "hunter2")
    assert page.reads
    for expression in page.reads:
        assert "hunter2" not in expression
        assert "=== ''" in expression and "length" not in expression


def test_a_field_emptied_every_time_is_an_error_that_never_says_nothing_was_written(quick):
    page = _Page(wipes=99)
    with pytest.raises(RuntimeError) as err:
        _type(page, "hunter2")
    assert len(page.calls) == actions.TYPE_ATTEMPTS
    assert "nothing was written" not in str(err.value)
    assert "outcome is unknown" in str(err.value)
    assert "hunter2" not in str(err.value)


def test_a_refused_retry_is_not_reported_as_nothing_written(quick):
    page = _Page(wipes=1, refuse_after=1)
    with pytest.raises(RuntimeError) as err:
        _type(page, "hunter2")
    assert "nothing was written" not in str(err.value)
    assert "outcome is unknown" in str(err.value)


def test_a_first_refusal_still_says_nothing_was_written(quick):
    page = _Page(refuse_after=0)
    with pytest.raises(RuntimeError, match="nothing was written$"):
        _type(page)


def test_clearing_is_not_read_back_or_retried(quick):
    page = _Page(wipes=1)
    assert _type(page, "") == "typed into #c"
    assert len(page.calls) == 1 and not page.reads


def test_a_field_that_cannot_be_asked_is_not_retried(quick):
    page = _Page(wipes=1, unreadable=True)
    assert _type(page) == "typed into #c"
    assert len(page.calls) == 1


# --- against a real engine -------------------------------------------------

# Vue's v-model, reduced: the model takes the input's value on `input`, and a
# focus schedules a re-render that writes the model back into the input in a
# microtask - which runs as soon as the engine's one-step focus-and-write
# returns, before the trusted input event arrives.
PAGE = b"""<!doctype html><html><body>
<input id="code" type="text"><button id="go" disabled>Confirm</button>
<script>
window.model = "";
const el = document.getElementById("code"), go = document.getElementById("go");
el.addEventListener("focus", () => queueMicrotask(() => { el.value = model; }));
el.addEventListener("input", () => { model = el.value; go.disabled = model.length !== 7; });
</script></body></html>"""


@pytest.fixture(scope="module")
def page_url():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.mark.e2e
async def test_a_field_whose_model_answers_the_focus_keeps_the_origin_locked_write(page_url):
    from invisible_playwright.async_api import InvisiblePlaywright

    async with InvisiblePlaywright(seed=1, headless=True) as browser:
        ctx = await browser.new_context()
        page = await ctx.new_page()

        class _S:
            def page(self):
                return page

        await page.goto(page_url + "/")
        assert await actions.type_text(_S(), "#code", "1234567", page_url, "text") == "typed into #code"
        assert await page.input_value("#code") == "1234567"
        assert await page.evaluate("model") == "1234567"
        assert await page.evaluate("document.getElementById('go').disabled") is False
        await ctx.close()
