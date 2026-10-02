"""A selector that fails says why, and what to do about it - from every tool.

⛔ THREE TOOLS TAKE A SELECTOR AND ONLY ONE OF THEM COULD EXPLAIN A FAILURE.
`browser_click` asked the page why and reported it. `browser_type` and
`browser_select_option` handed back Playwright's bare timeout, which names the
selector and nothing else. The same page, the same failure, and the answer was
useful or useless depending on which tool the caller happened to reach for.

⛔ AND THE ANSWER THAT WAS MISSING ALTOGETHER IS THE COMMONEST ONE: nothing
matches. Measured on a real run, on a real site: the model wrote
`.inbox-dataentry a, .inbox a, [class*="mail-item"] a`, waited the full fifteen
seconds for nothing, and then spent four more `browser_evaluate` calls hunting
through the DOM by hand before it thought of taking a fresh snapshot - which
worked first time.

It could not have read those class names anywhere in this product.
`browser_snapshot` builds its `selector` from id, name, href, data-testid or
aria-label, never from class; `browser_read_html` drops the class attribute
outright. So a class-based selector is ALWAYS one the caller wrote, the product
knew that, and it did not say so at the only moment it mattered.

That is what these tests hold: one place decides what follows from what the page
reported, and every tool that aims at a selector goes through it.
"""
from __future__ import annotations

import pytest

from invisible_playwright_mcp.mcp import actions


class _Element:
    """The first element the engine resolved; it reports the rest of `why`."""

    def __init__(self, why):
        self.why = why

    async def evaluate(self, expression, *args):
        return {k: v for k, v in self.why.items() if k != "matches"}

    async def dispose(self):
        pass


class _Page:
    """A page where the action fails and the diagnosis answers `why`.

    The diagnosis asks the ENGINE (query_selector_all), as the action does.
    `attempts` counts what was tried, since every attempt is a full timeout.
    """

    def __init__(self, why):
        self.why = why
        self.asked = []
        self.attempts = []

    async def query_selector_all(self, selector):
        self.asked.append(selector)
        if self.why.get("bad_selector"):
            raise ValueError("%r is not a valid selector" % selector)
        return [_Element(self.why)] * int(self.why.get("matches") or 0)

    async def click(self, selector, **kw):
        raise TimeoutError("Page.click: %r not actionable in 15s" % selector)

    async def fill(self, selector, text, **kw):
        raise TimeoutError("Page.fill: %r not actionable in 15s" % selector)

    async def select_option(self, selector, **kw):
        self.attempts.append(("select_option", kw))
        raise TimeoutError("Page.selectOption: %r not actionable in 15s" % selector)


class _Session:
    def __init__(self, why):
        self._page = _Page(why)

    def page(self):
        return self._page


async def _fails(fn, why):
    session = _Session(why)
    with pytest.raises(RuntimeError) as caught:
        await fn(session)
    return str(caught.value), session.page()


@pytest.mark.parametrize("nome,azione", [
    ("click", lambda s: actions.click(s, "#gone")),
    ("type", lambda s: actions.type_text(s, "#gone", "ciao")),
    ("select", lambda s: actions.select_option(s, "#gone", "MENS")),
])
async def test_every_tool_that_aims_at_a_selector_explains_itself(nome, azione):
    """⛔ THE KNOWN-BAD, AND IT IS THE ASYMMETRY. To watch this fail, take
    `_on_selector` off any one of the three: that tool goes back to answering
    with the selector and a timeout, and the other two still pass."""
    testo, page = await _fails(azione, {"matches": 0})

    assert "what to do:" in testo, (
        "%s failed without saying what follows from it: %s" % (nome, testo))
    assert "browser_snapshot" in testo, (
        "%s did not name the move that fixes it: %s" % (nome, testo))
    assert page.asked == ["#gone"], (
        "%s did not ask the page about the selector it used: %r"
        % (nome, page.asked))


async def test_nothing_matching_says_a_class_selector_cannot_come_from_here():
    """⛔ THE SENTENCE THAT WOULD HAVE SAVED THE MEASURED RUN. A caller that
    wrote its own selector has no way of knowing that this product never hands
    out one built from `class` - the snapshot uses id, name, href, data-testid
    or aria-label, and the html reader drops `class` - so the only place that
    can tell it is the failure."""
    testo, _ = await _fails(lambda s: actions.click(s, ".invented"), {"matches": 0})

    assert "class" in testo, (
        "nothing said that a class-based selector cannot come from this "
        "product's snapshot: %s" % testo)
    assert "verbatim" in testo


async def test_a_covered_element_is_told_to_deal_with_the_thing_on_top():
    """The answer that already existed and must not be lost: when something is
    on top, retrying is the wrong move and dismissing it is the right one."""
    testo, _ = await _fails(
        lambda s: actions.click(s, "#buy"),
        {"matches": 1, "width": 90, "height": 30,
         "covered_by": {"tag": "div", "id": "cookie-banner", "position": "fixed"}})

    assert "cookie-banner" in testo, "it did not say WHAT was on top: %s" % testo
    assert "different action" in testo


async def test_each_thing_the_page_can_report_has_its_own_move():
    """⛔ NO SHAPE FALLS THROUGH TO SILENCE. A diagnosis the product can produce
    and cannot advise on is a fifteen-second wait that ends in a shrug, which is
    what the whole diagnosis exists to replace."""
    forme = [
        {"bad_selector": True},
        {"matches": 0},
        {"matches": 1, "display_none": True},
        {"matches": 1, "visibility_hidden": True},
        {"matches": 1, "disabled": True},
        {"matches": 1, "pointer_events_none": True},
        {"matches": 1, "off_screen": True},
        {"matches": 1, "covered_by": {"tag": "div"}},
        {"matches": 1, "width": 10, "height": 10},
    ]
    muti = [f for f in forme if not actions.next_move(f).strip()]
    assert not muti, "these shapes produce no advice: %r" % muti
    # And the last one, where the page reports nothing wrong, must not borrow
    # somebody else's sentence.
    assert "momentary" in actions.next_move({"matches": 1, "width": 10, "height": 10})


async def test_a_page_that_cannot_be_asked_does_not_swallow_the_real_failure():
    """⛔ THE DIAGNOSIS IS A COURTESY, NOT A CONDITION. If the page cannot
    answer - it navigated, it died - the original failure must still reach the
    caller rather than being replaced by a failure to explain it."""
    class _Mute(_Page):
        async def query_selector_all(self, selector):
            raise RuntimeError("execution context was destroyed")

    session = _Session(None)
    session._page = _Mute(None)
    with pytest.raises(TimeoutError, match="not actionable"):
        await actions.click(session, "#gone")


async def test_a_select_is_attempted_once_because_the_driver_matches_both():
    """Every attempt is a full timeout, and the driver's `value=` already
    matches a value or a label (`valueOrLabel`). Known-bad: the old second
    attempt by label, which measured 30.2 s against 15.1 s for a click on the
    same selector matching nothing."""
    _, page = await _fails(lambda s: actions.select_option(s, "#gone", "MENS"),
                           {"matches": 0})
    assert [name for name, _ in page.attempts] == ["select_option"], page.attempts
    assert page.attempts[0][1].get("value") == "MENS"


class _Chooses(_Page):
    """A select that takes whatever it is asked for, and answers its values."""

    def __init__(self, options):
        super().__init__({"matches": 1})
        self.options = options

    async def select_option(self, selector, **kw):
        self.attempts.append(("select_option", kw))
        asked = kw["value"]
        return [v for v, label in self.options if asked in (v, label)][:1]


@pytest.mark.parametrize("asked,how", [("b", "value"), ("Beta", "label")])
async def test_the_answer_says_whether_it_matched_the_value_or_the_label(asked, how):
    session = _Session(None)
    session._page = _Chooses([("a", "Alpha"), ("b", "Beta")])
    said = await actions.select_option(session, "#s", asked)
    assert said == "selected #s by %s: ['b']" % how


def test_the_driver_sends_a_value_as_value_or_label():
    """The one attempt above is only enough because of this. If the driver
    ever sent `value=` as a plain value again, a label would stop matching
    and the tool would refuse what the page shows."""
    from invisible_playwright._pw._impl._element_handle import convert_select_option_values

    assert convert_select_option_values(value="Beta")["options"] == [{"valueOrLabel": "Beta"}]


class _NoSuchOption(_Page):
    async def select_option(self, selector, **kw):
        self.attempts.append(("select_option", kw))
        raise RuntimeError("Page.select_option: selectOptions: error:optionsnotfound")


async def test_a_select_with_no_such_option_says_so_and_not_momentary():
    """Measured: the driver refuses in 0.25 s with `error:optionsnotfound`, the
    diagnosis finds the element fine, and the answer was "momentary" - advice to
    retry something that can never work. Known-bad: let that error reach
    `_on_selector` untranslated."""
    session = _Session(None)
    session._page = _NoSuchOption({"matches": 1, "width": 64, "height": 23})
    with pytest.raises(RuntimeError) as caught:
        await actions.select_option(session, "#s", "Gamma")
    said = str(caught.value)
    assert said == "no option in #s has the value or the label 'Gamma'", said
