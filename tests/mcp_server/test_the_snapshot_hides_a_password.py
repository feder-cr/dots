"""A filled secret field is reported as filled, never with its value.

Two readers return a page to the model: browser_snapshot and browser_read_html.

The snapshot is returned to the model, so an element's text is printed into
the conversation. It used to be `el.innerText || el.value`, which for an
<input type=password> is the password: measured by typing a value with
browser_type and calling browser_snapshot, which returned it verbatim.

A secret is a password box, or a field whose autocomplete names a secret
(`clean.SECRET_AUTOCOMPLETE`): that token is what survives a "show password"
toggle, which turns the type into text and so makes the type say nothing.

The lines that choose an element's text are executed here with node against
printed elements, the same way test_the_handle_logic_runs.py runs the handle
logic: they read a few properties and nothing about layout.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from invisible_playwright_mcp.mcp import actions, clean

NODE = shutil.which("node")
#: The expected mask, written out rather than read from the code under test.
BULLETS = "•" * 8

needs_node = pytest.mark.skipif(not NODE, reason="needs node to EXECUTE the snapshot's text logic")

FIRST = "        const isSel = el.tagName === 'SELECT';"
LAST = "        const href = "


def text_of(el: dict) -> str:
    src = actions.SNAPSHOT_JS
    start, end = src.index(FIRST), src.index(LAST)
    body = src[start:end]
    script = (
        "const chosen = (el) => 'CHOSEN';\n"
        # The predicate the snapshot really carries, not a copy of it.
        + clean.SECRET_FIELD_JS
        + f"const el = {json.dumps(el)};\n"
        + "el.getAttribute = (n) => (el.attrs || {})[n] ?? null;\n"
        + body
        + "\nprocess.stdout.write(JSON.stringify(text));\n"
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                         encoding="utf-8", timeout=30, check=True)
    return json.loads(out.stdout)


def test_the_snapshot_carries_the_one_predicate():
    """One rule for what is secret, joined into the snapshot, so the snapshot
    and read_html cannot disagree about a field."""
    assert clean.SECRET_FIELD_JS in actions.SNAPSHOT_JS
    assert "const secret = secretField(el);" in actions.SNAPSHOT_JS


@needs_node
def test_a_filled_password_box_shows_bullets_not_the_value():
    assert text_of({"tagName": "INPUT", "type": "password", "value": "hunter2", "innerText": ""}) == BULLETS


@needs_node
def test_the_type_is_matched_whatever_its_case():
    assert text_of({"tagName": "INPUT", "type": "PassWord", "value": "hunter2", "innerText": ""}) == BULLETS


@needs_node
def test_an_empty_password_box_shows_nothing():
    assert text_of({"tagName": "INPUT", "type": "password", "value": "", "innerText": ""}) == ""


@needs_node
@pytest.mark.parametrize("autocomplete", [
    "current-password", "new-password", "one-time-code", "cc-csc",
    # Tokens come with a section and a group in front of the field name.
    "section-login current-password", "billing CC-CSC",
])
def test_a_field_whose_autocomplete_names_a_secret_is_masked_as_text(autocomplete):
    """What a "show password" toggle leaves behind: type=text, and the token.

    Known-bad: matching on the type alone. The shown password is then printed."""
    el = {"tagName": "INPUT", "type": "text", "value": "hunter2", "innerText": "",
          "attrs": {"autocomplete": autocomplete}}
    assert text_of(el) == BULLETS


@needs_node
@pytest.mark.parametrize("autocomplete", ["username", "email", "cc-name", "off", ""])
def test_a_field_whose_autocomplete_names_no_secret_shows_what_it_holds(autocomplete):
    el = {"tagName": "INPUT", "type": "text", "value": "plainname", "innerText": "",
          "attrs": {"autocomplete": autocomplete}}
    assert text_of(el) == "plainname"


@needs_node
def test_a_text_box_still_shows_what_it_holds():
    assert text_of({"tagName": "INPUT", "type": "text", "value": "plainname", "innerText": ""}) == "plainname"


def test_a_text_box_keeps_its_whitespace_rule():
    """Every other element is unchanged: the text is still trimmed and its
    runs of whitespace still collapse."""
    if not NODE:
        pytest.skip("needs node")
    assert text_of({"tagName": "INPUT", "type": "text", "value": "  a   b ", "innerText": ""}) == "a b"


# --- browser_read_html: the cleaner ------------------------------------------

PREFILLED = ("<form><input id=u name=user value=plainname>"
             "<input id=p type=PassWord name=pw value=hunter2>"
             "<input id=shown type=text autocomplete=current-password value=hunter3>"
             "<input id=otp inputmode=numeric autocomplete=one-time-code value=482913>"
             "<button>Go</button></form>")


@pytest.mark.parametrize("mode", ["form", "full"])
def test_read_html_masks_a_prefilled_secret(mode):
    out = clean.clean_page(f"<html><body>{PREFILLED}</body></html>", mode)
    for secret in ("hunter2", "hunter3", "482913"):
        assert secret not in out, (mode, secret)
    for field in ("input#p", "input#shown", "input#otp"):
        assert _field(out, field).get("value") == BULLETS, field
    assert _field(out, "input#u").get("value") == "plainname", "an ordinary input lost its value"


def _field(html, css):
    from selectolax.lexbor import LexborHTMLParser
    node = LexborHTMLParser(html).css_first(css)
    assert node is not None, f"{css} was removed from the page"
    return node.attributes


def test_read_html_leaves_an_empty_password_empty():
    out = clean.clean_page("<html><body><form><input id=p type=password name=pw value=''><button>Go</button></form></body></html>", "full")
    attrs = _field(out, "input#p")
    assert attrs.get("type") == "password"
    assert attrs.get("value") in ("", None)


def test_the_markup_rule_and_the_page_rule_name_the_same_secrets():
    """`is_secret_field` and `SECRET_FIELD_JS` are two languages for one rule,
    so both are built from `SECRET_AUTOCOMPLETE` rather than each listing it."""
    assert json.dumps(list(clean.SECRET_AUTOCOMPLETE)) in clean.SECRET_FIELD_JS
    for token in clean.SECRET_AUTOCOMPLETE:
        assert clean.is_secret_field("input", {"type": "text", "autocomplete": token})
    assert not clean.is_secret_field("textarea", {"type": "password"})


# --- both readers, on a real page ------------------------------------------

@pytest.fixture(scope="module")
def page():
    from invisible_playwright import InvisiblePlaywright

    with InvisiblePlaywright(seed=1, headless=True) as browser:
        ctx = browser.new_context()
        yield ctx.new_page()
        ctx.close()


#: A page that mirrors what is typed into the attribute, as some frameworks do,
#: so the value reaches the markup as well as the property; and a login box
#: whose "show" button has already turned it into text.
MIRRORING = (
    "<form><input id=u name=user><input id=p type=password name=pw>"
    "<input id=shown type=password name=pw2 autocomplete=current-password>"
    "<button type=button id=show>Show</button>"
    "<button>Go</button></form>"
    "<script>document.getElementById('p').addEventListener('input',"
    " e => e.target.setAttribute('value', e.target.value));"
    "document.getElementById('show').addEventListener('click',"
    " () => { document.getElementById('shown').type = 'text'; });</script>"
)


@pytest.mark.e2e
def test_neither_reader_returns_a_typed_secret(page):
    from urllib.parse import quote

    page.goto("data:text/html," + quote(f"<html><body>{MIRRORING}</body></html>"))
    page.fill("#u", "plainname")
    page.fill("#p", "hunter2")
    page.fill("#shown", "hunter3")
    page.click("#show")
    assert page.get_attribute("#p", "value") == "hunter2", "the page did not mirror the value"
    assert page.get_attribute("#shown", "type") == "text", "the toggle did not show it"

    snap = json.dumps(page.evaluate(actions.SNAPSHOT_JS), ensure_ascii=False)
    assert "hunter2" not in snap and "hunter3" not in snap
    assert BULLETS in snap
    assert "plainname" in snap

    raw = page.evaluate(clean.VISIBLE_HTML_JS)
    for mode in ("form", "full"):
        out = clean.clean_page(raw, mode)
        assert "hunter2" not in out and "hunter3" not in out, mode
        pw = _field(out, "input#p")
        assert (pw.get("type") or "").lower() == "password", mode
        assert pw.get("value") == BULLETS, mode
        assert _field(out, "input#u") is not None and _field(out, "button") is not None, mode
