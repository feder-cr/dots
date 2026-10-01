"""A click that does not land has to say what stopped it.

Playwright reports a failed click as "not actionable in 15s after N attempts",
which tells a caller that something is wrong and nothing about what. Measured
across eighteen real sites, four clicks failed and every one failed that way: a
logo, a footer link, a shipping button. Fifteen seconds spent to learn nothing.

The answer worth having is `covered_by`. If a cookie banner is sitting over the
button, the next move is to dismiss the banner, and that is a different action
from retrying - which is what a caller does with an opaque timeout.
"""

import pytest

from invisible_playwright_mcp.mcp import actions


class _Session:
    def __init__(self, page):
        self._page = page

    def page(self):
        return self._page

    def pages(self):
        return [self._page]


@pytest.fixture(scope="module")
def page():
    from invisible_playwright import InvisiblePlaywright

    with InvisiblePlaywright(seed=1, headless=True) as browser:
        ctx = browser.new_context()
        yield ctx.new_page()
        ctx.close()


class _Async:
    """The sync page, awaitable, so the REAL `actions._diagnose` runs on it
    rather than a copy of it written into this file."""

    def __init__(self, target):
        self._target = target

    def __getattr__(self, name):
        attr = getattr(self._target, name)

        async def call(*a, **k):
            out = attr(*a, **k)
            return [_Async(e) for e in out] if isinstance(out, list) else out
        return call


def _complete(coro):
    """Run a coroutine that never suspends. The sync page already owns this
    thread's event loop, so asyncio.run() is refused here, and `_Async` awaits
    nothing that waits."""
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError("the diagnosis suspended on a page that cannot")


def _why(page, body, selector="#b"):
    """Click and return the diagnosis, or None if the click worked."""
    from urllib.parse import quote

    page.goto("data:text/html," + quote(f"<html><body>{body}</body></html>"))
    page.wait_for_timeout(250)
    try:
        # actions.click is async and the page here is sync; the diagnosis itself
        # is what is under test, so it is driven directly.
        page.click(selector, timeout=2000)
        return None
    except Exception:
        return _complete(actions._diagnose(_Async(page), selector))


@pytest.mark.e2e
def test_a_covering_element_is_named(page):
    """The one that matters. A caller told "covered by a fixed div saying
    Cookie" knows what to do next; a caller told "not actionable" does not."""
    body = ("<button id='b' style='position:absolute;top:50px;left:50px'>Send</button>"
            "<div id='banner' style='position:fixed;top:0;left:0;width:900px;"
            "height:900px;background:rgba(0,0,0,.5);z-index:9'>Cookie</div>")
    why = _why(page, body)
    assert why, "the click succeeded; this case is supposed to be blocked"
    assert why.get("covered_by"), f"nothing said what was in the way: {why}"
    assert why["covered_by"].get("id") == "banner"
    assert why["covered_by"].get("position") == "fixed"


@pytest.mark.e2e
def test_a_disabled_control_says_so(page):
    why = _why(page, "<button id='b' disabled>Send</button>")
    assert why and why.get("disabled") is True, why


@pytest.mark.e2e
def test_a_selector_that_matches_nothing_says_zero(page):
    """Distinct from every other failure: nothing to cover, nothing to enable.
    The caller's next move is a fresh snapshot, not a retry."""
    why = _why(page, "<p>empty</p>")
    assert why and why.get("matches") == 0, why


@pytest.mark.e2e
def test_a_click_that_works_is_not_diagnosed(page):
    """The diagnosis runs only after a failure. A check that never sees the
    negative case is not a check."""
    assert _why(page, "<button id='b'>Send</button>") is None


@pytest.mark.e2e
def test_the_engine_s_own_refusal_of_a_bad_selector_is_recognised(page):
    """`bad_selector` is read off the engine's message, so the message has to be
    one `_UNPARSABLE` knows; otherwise a typo reads as a page that cannot be
    asked, and the caller is told nothing."""
    why = _why(page, "<button id='b'>Send</button>", selector="#b[")
    assert why == {"bad_selector": True}, why


class _Refusing:
    def __init__(self, message):
        self.message = message

    async def query_selector_all(self, selector):
        raise RuntimeError(self.message)


async def test_the_diagnosis_never_throws_on_a_bad_selector():
    """It runs inside an exception handler. If it raised, it would replace the
    real error with its own, which is worse than saying nothing."""
    why = await actions._diagnose(_Refusing("'#b[' is not a valid selector"), "#b[")
    assert why == {"bad_selector": True}


async def test_a_page_that_cannot_be_asked_is_not_called_a_bad_selector():
    """A navigation mid-diagnosis is not the caller's typo, and saying it was
    would send them to rewrite a selector that is fine."""
    assert await actions._diagnose(_Refusing("execution context was destroyed"), "#b") is None
