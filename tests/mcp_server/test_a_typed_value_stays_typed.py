"""browser_type says "typed into" only once the field has kept the text.

Measured 2026-10-01 on Progressive's quote pages, which are Angular with an
NgRx store: an input takes the model's stored answer on every state emission,
and the model takes the input's value only on `change`. A focus, or the
previous field's commit, is answered a moment later, and that answer writes
the stored (empty) answer over whatever was typed meanwhile:

- "30" typed into a days field was gone a second later; Continue then refused
  an empty field. browser_type had answered "typed into".
- "richard@powell.dev" typed straight after a masked date of birth kept only
  "hard@powell.dev": the first keys landed before the answer, the rest after.

The fixture below is that mechanism, reduced. The unit tests hold the shape
with a double; the e2e ones hold the outcome against a real engine.
"""
from __future__ import annotations

import asyncio
import http.server
import threading

import pytest

from invisible_playwright_mcp.mcp import actions


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(actions, "SETTLE_S", 0.05)
    monkeypatch.setattr(actions, "SINCE_FOCUS_S", 0.05)


class _Locator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    async def input_value(self, timeout=None):
        return self.page.read(self.selector)

    async def get_attribute(self, name, timeout=None):
        return self.page.types.get(self.selector)


class _Keyboard:
    async def insert_text(self, text):
        raise AssertionError("short text is typed, not inserted")


class _Page:
    """A field the page empties while keys arrive, `wipes` times, keeping only
    the last `keep` characters typed after it - the Progressive email."""

    def __init__(self, wipes=1, keep=None, shows=None, types=None):
        self.wipes, self.keep, self.shows = wipes, keep, shows
        self.values, self.fills, self.types = {}, 0, types or {}
        self.keyboard = _Keyboard()

    async def wait_for_selector(self, selector, **kw):
        return True

    async def fill(self, selector, text, **kw):
        self.fills += 1
        if self.wipes:
            self.wipes -= 1
            self.values[selector] = text[-self.keep:] if self.keep else ""
        else:
            self.values[selector] = self.shows if self.shows is not None else text

    def read(self, selector):
        return self.values.get(selector, "")

    def locator(self, selector):
        return _Locator(self, selector)


class _Session:
    def __init__(self, page):
        self._page = page

    def page(self):
        return self._page


def _type(page, text, selector="#f"):
    return asyncio.run(actions.type_text(_Session(page), selector, text))


def test_a_field_emptied_while_typing_is_typed_again(quick):
    page = _Page(wipes=1)
    out = _type(page, "30")
    assert page.values["#f"] == "30"
    assert page.fills == 2
    assert out.startswith("typed into #f") and "typed 2 times" in out


def test_a_field_that_lost_its_start_is_typed_again(quick):
    page = _Page(wipes=1, keep=len("hard@powell.dev"))
    _type(page, "richard@powell.dev")
    assert page.values["#f"] == "richard@powell.dev"


def test_a_field_that_keeps_dropping_it_is_an_error_not_typed_into(quick):
    page = _Page(wipes=99)
    with pytest.raises(RuntimeError, match="did not keep what was typed"):
        _type(page, "30")
    assert page.fills == 2, "the same loss twice is the page's answer, not a race"


def test_a_field_that_kept_it_is_typed_once(quick):
    page = _Page(wipes=0)
    assert _type(page, "Richard") == "typed into #f"
    assert page.fills == 1


def test_a_reformatted_value_is_kept_not_retyped(quick):
    page = _Page(wipes=0, shows="04/12/1983")
    assert _type(page, "04121983") == "typed into #f"
    page = _Page(wipes=0, shows="Richard")
    assert _type(page, "richard") == "typed into #f"
    page = _Page(wipes=0, shows="04/12/83")
    assert _type(page, "4/12/83x") == "typed into #f; the page shows it as '04/12/83'"
    assert page.fills == 1


def test_a_password_the_page_changed_is_not_echoed(quick):
    page = _Page(wipes=0, shows="Xx", types={"#p": "password"})
    out = _type(page, "Hunter2", selector="#p")
    assert "Xx" not in out and "Hunter2" not in out


class _Unmasking(_Page):
    """A password box the page turns into a text box once it holds a value."""

    async def fill(self, selector, text, **kw):
        await super().fill(selector, text, **kw)
        self.types[selector] = "text"


def test_a_password_box_turned_text_is_still_not_echoed(quick):
    page = _Unmasking(wipes=0, shows="Hunter2x", types={"#p": "password"})
    out = _type(page, "Hunter2", selector="#p")
    assert "Hunter" not in out


# --- against a real engine -------------------------------------------------

PAGE = b"""<!doctype html><html><body>
<form onsubmit="return false">
<input id="days" type="tel">
<input id="dob" type="tel" maxlength="10">
<input id="email" type="email">
<input id="keyed">
<button id="go" type="button">Continue</button>
</form>
<script>
// The model takes a field's value on `change` only, and every answer writes
// the stored value back into the inputs, as Progressive's store does. A focus
// is answered after `focus` ms and a commit refreshes every field after
// `refresh` ms. The date is formatted as it is entered, as theirs is.
const q = new URLSearchParams(location.search);
const FOCUS = +(q.get("focus") || 600), REFRESH = +(q.get("refresh") || 900);
window.store = {days: "", dob: "", email: ""};
window.keyed = "";
const fmt = (id, v) => {
  if (id !== "dob") return v;
  const d = v.replace(/\\D/g, "");
  return d.length > 4 ? d.slice(0,2)+"/"+d.slice(2,4)+"/"+d.slice(4)
       : d.length > 2 ? d.slice(0,2)+"/"+d.slice(2) : d;
};
const render = id => { document.getElementById(id).value = fmt(id, store[id]); };
for (const id of Object.keys(store)) {
  const el = document.getElementById(id);
  el.addEventListener("focus", () => setTimeout(() => render(id), FOCUS));
  el.addEventListener("input", () => { const f = fmt(id, el.value); if (f !== el.value) el.value = f; });
  el.addEventListener("change", () => {
    store[id] = id === "dob" ? el.value.replace(/\\D/g, "") : el.value;
    setTimeout(() => Object.keys(store).forEach(render), REFRESH);
  });
}
// A model that listens to keys only and ignores a bare value set.
document.getElementById("keyed").addEventListener("keyup", e => {
  if (e.isTrusted) window.keyed = e.target.value;
});
</script></body></html>"""


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


async def _commit(session):
    """What the caller does next: Continue, which blurs and commits."""
    await actions.click(session, "#go")
    await asyncio.sleep(1.5)
    return await session.page().evaluate("JSON.stringify([store, keyed])")


@pytest.mark.e2e
@pytest.mark.parametrize("focus", [600, 1500], ids=["while-typing", "after-typing"])
def test_days_survive_the_focus_answer(url, focus):
    async def body(session):
        out = await actions.type_text(session, "#days", "30")
        await asyncio.sleep(2)
        return out, await session.page().locator("#days").input_value(), await _commit(session)

    out, value, model = asyncio.run(_with_browser(url + "?focus=%d" % focus, body))
    assert out.startswith("typed into #days")
    assert value == "30"
    assert '"days":"30"' in model


@pytest.mark.e2e
def test_an_email_after_a_masked_date_keeps_its_start(url):
    async def body(session):
        await actions.type_text(session, "#dob", "04/12/1983")
        await actions.type_text(session, "#email", "richard@powell.dev")
        page = session.page()
        return (await page.locator("#dob").input_value(),
                await page.locator("#email").input_value(), await _commit(session))

    dob, email, model = asyncio.run(_with_browser(url, body))
    assert dob == "04/12/1983"
    assert email == "richard@powell.dev"
    assert '"email":"richard@powell.dev"' in model and '"dob":"04121983"' in model


@pytest.mark.e2e
def test_a_model_that_hears_only_keys_gets_the_text(url):
    async def body(session):
        await actions.type_text(session, "#keyed", "keys only")
        return await _commit(session)

    assert asyncio.run(_with_browser(url, body)).endswith('"keys only"]')
