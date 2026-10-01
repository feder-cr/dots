"""browser_upload_files attaches local files the way a person picks them.

Measured 2026-10-01: a credit application's "Supporting Documents" page wanted
four PDFs, and no tool could answer the file chooser "Add Document" opened.
browser_evaluate rightly refuses to build the upload in script. The unit tests
hold the path guard and the shape of the action with a double; the e2e ones
hold the outcome against a real engine: a visible input, a styled button in
front of a hidden one, and a page that listens for a trusted change.
"""
from __future__ import annotations

import asyncio
import http.server
import os
import threading

import pytest

from invisible_playwright_mcp.mcp import actions


@pytest.fixture
def allowed(tmp_path):
    root = tmp_path / "up"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"%PDF-1.4 a")
    (root / "b.pdf").write_bytes(b"%PDF-1.4 b")
    return root


def _env(*dirs):
    return {actions.UPLOAD_DIRS_ENV: os.pathsep.join(str(d) for d in dirs)}


# --- the path guard -------------------------------------------------------------

def test_with_no_directory_named_uploads_are_off(allowed):
    with pytest.raises(RuntimeError, match="uploads are off"):
        actions.uploadable([str(allowed / "a.pdf")], env={})


def test_a_file_inside_a_named_directory_is_sent_resolved(allowed, tmp_path):
    link = allowed / "link.pdf"
    link.symlink_to(allowed / "a.pdf")
    assert actions.uploadable([str(link)], env=_env(allowed)) == [
        os.path.realpath(allowed / "a.pdf")]


def test_a_file_outside_every_named_directory_is_refused(allowed, tmp_path):
    other = tmp_path / "secret.txt"
    other.write_text("x")
    with pytest.raises(PermissionError, match="not inside a directory"):
        actions.uploadable([str(other)], env=_env(allowed))


def test_a_link_out_of_the_directory_is_judged_by_where_it_lands(allowed, tmp_path):
    other = tmp_path / "secret.txt"
    other.write_text("x")
    (allowed / "innocent.pdf").symlink_to(other)
    with pytest.raises(PermissionError, match="not inside a directory"):
        actions.uploadable([str(allowed / "innocent.pdf")], env=_env(allowed))


def test_dot_dot_does_not_climb_out(allowed, tmp_path):
    other = tmp_path / "secret.txt"
    other.write_text("x")
    with pytest.raises(PermissionError):
        actions.uploadable([str(allowed / ".." / "secret.txt")], env=_env(allowed))


def test_a_hidden_directory_is_not_sent_from(allowed):
    (allowed / ".ssh").mkdir()
    (allowed / ".ssh" / "id_ed25519").write_text("key")
    (allowed / ".env").write_text("TOKEN=1")
    for path in (allowed / ".ssh" / "id_ed25519", allowed / ".env"):
        with pytest.raises(PermissionError, match="hidden"):
            actions.uploadable([str(path)], env=_env(allowed))


def test_what_is_not_a_readable_regular_file_is_refused(allowed):
    with pytest.raises(ValueError, match="not a regular file"):
        actions.uploadable([str(allowed)], env=_env(allowed))
    with pytest.raises(FileNotFoundError):
        actions.uploadable([str(allowed / "missing.pdf")], env=_env(allowed))


def test_relative_paths_and_bad_shapes_are_refused(allowed, monkeypatch):
    monkeypatch.chdir(allowed)
    with pytest.raises(ValueError, match="absolute"):
        actions.uploadable(["a.pdf"], env=_env(allowed))
    with pytest.raises(ValueError, match="list"):
        actions.uploadable(str(allowed / "a.pdf"), env=_env(allowed))
    with pytest.raises(ValueError, match="list"):
        actions.uploadable([], env=_env(allowed))
    with pytest.raises(ValueError, match="twice"):
        actions.uploadable([str(allowed / "a.pdf")] * 2, env=_env(allowed))
    with pytest.raises(RuntimeError, match="not an absolute path"):
        actions.uploadable([str(allowed / "a.pdf")], env={actions.UPLOAD_DIRS_ENV: "up"})


def test_a_root_that_is_a_symlink_turns_uploads_off(allowed, tmp_path):
    """Replacing the staging directory with a link to its parent must not
    widen uploads to the parent's whole tree."""
    link = tmp_path / "staging"
    link.symlink_to(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    with pytest.raises(RuntimeError, match="uploads are off"):
        actions.uploadable([str(secret)], env=_env(link))
    with pytest.raises(RuntimeError, match="uploads are off"):
        actions.uploadable([str(allowed / "a.pdf")], env=_env(allowed, link))


def test_a_root_that_does_not_exist_turns_uploads_off(tmp_path):
    with pytest.raises(RuntimeError, match="uploads are off"):
        actions.uploadable(["/x"], env=_env(tmp_path / "missing"))


def test_a_file_over_the_limit_is_refused(allowed, monkeypatch):
    monkeypatch.setattr(actions, "UPLOAD_MAX_BYTES", 4)
    with pytest.raises(ValueError, match="over the"):
        actions.uploadable([str(allowed / "a.pdf")], env=_env(allowed))


# --- the action, against a double -------------------------------------------------

class _Element:
    def __init__(self, page):
        self.page = page

    async def evaluate(self, js):
        return self.page.held


class _Chooser:
    def __init__(self, page, multiple):
        self.page, self.element, self._multiple = page, _Element(page), multiple

    def is_multiple(self):
        return self._multiple

    async def set_files(self, files, timeout=None):
        self.page.held = [os.path.basename(f) for f in files]
        self.page.calls.append(("chooser", files))


class _Expect:
    def __init__(self, page):
        self.page = page

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if exc[0] is None and not self.page.clicked:
            raise TimeoutError("Timeout 10000ms exceeded while waiting for event \"filechooser\"")
        return False

    @property
    def value(self):
        async def chooser():
            return _Chooser(self.page, self.page.target["multiple"])
        return chooser()


class _Page:
    def __init__(self, target, opens=True):
        self.target, self.opens = target, opens
        self.calls, self.held, self.clicked = [], None, False

    async def wait_for_selector(self, selector, **kw):
        return True

    async def eval_on_selector(self, selector, js):
        return self.held if "files" in js and "tagName" not in js else self.target

    def expect_file_chooser(self, timeout=None):
        return _Expect(self)

    async def click(self, selector, timeout=None):
        self.calls.append(("click", selector))
        self.clicked = self.opens

    async def set_input_files(self, selector, files, timeout=None):
        self.held = [os.path.basename(f) for f in files]
        self.calls.append(("direct", files))


class _Session:
    def __init__(self, page):
        self._page = page

    def page(self):
        return self._page


def _upload(page, paths, selector="#f"):
    return asyncio.run(actions.upload_files(_Session(page), selector, paths))


@pytest.fixture
def env(allowed, tmp_path, monkeypatch):
    monkeypatch.setenv(actions.UPLOAD_DIRS_ENV, str(allowed))
    (tmp_path / "snapshots").mkdir()
    monkeypatch.setattr(actions.tempfile, "tempdir", str(tmp_path / "snapshots"))
    return allowed


def test_a_visible_input_is_clicked_and_its_chooser_answered(env):
    page = _Page({"file": True, "multiple": False, "shown": True})
    out = _upload(page, [str(env / "a.pdf")])
    assert [c[0] for c in page.calls] == ["click", "chooser"]
    assert out == "attached 1 file to #f (picked in the file chooser): a.pdf"


def test_a_button_in_front_of_a_hidden_input_opens_the_chooser(env):
    page = _Page({"file": False, "multiple": True, "shown": True})
    out = _upload(page, [str(env / "a.pdf"), str(env / "b.pdf")], selector="#add")
    assert [c[0] for c in page.calls] == ["click", "chooser"]
    assert out.startswith("attached 2 files to #add") and out.endswith("a.pdf, b.pdf")


def test_a_hidden_input_is_given_the_files_without_a_click(env):
    page = _Page({"file": True, "multiple": False, "shown": False})
    out = _upload(page, [str(env / "a.pdf")])
    assert [c[0] for c in page.calls] == ["direct"]
    assert "hidden" in out


def test_a_click_that_opens_no_chooser_says_what_to_select(env):
    page = _Page({"file": False, "multiple": False, "shown": True}, opens=False)
    with pytest.raises(RuntimeError, match="opened no file chooser"):
        _upload(page, [str(env / "a.pdf")], selector="#nothing")


def test_several_files_for_a_single_input_attach_nothing(env):
    two = [str(env / "a.pdf"), str(env / "b.pdf")]
    page = _Page({"file": True, "multiple": False, "shown": True})
    with pytest.raises(RuntimeError, match="one at a time"):
        _upload(page, two)
    assert page.held is None
    page = _Page({"file": True, "multiple": False, "shown": False})
    with pytest.raises(RuntimeError, match="one at a time"):
        _upload(page, two)
    assert page.calls == []


def test_a_refused_path_touches_no_page(env, tmp_path):
    page = _Page({"file": True, "multiple": False, "shown": True})
    (tmp_path / "x").write_text("x")
    with pytest.raises(PermissionError):
        _upload(page, [str(tmp_path / "x")])
    assert page.calls == []


# --- against a real engine ---------------------------------------------------------

PAGE = b"""<!doctype html><html><body>
<input id="one" type="file">
<input id="many" type="file" multiple>
<input id="hidden" type="file" multiple style="display:none">
<button id="add" type="button" onclick="document.getElementById('hidden').click()">Add Document</button>
<button id="inert" type="button">Nothing</button>
<script>
// What a page sees: the change event, whether it was trusted, and the names.
window.seen = {};
for (const id of ["one", "many", "hidden"]) {
  document.getElementById(id).addEventListener("change", e => {
    window.seen[id] = {trusted: e.isTrusted, names: Array.from(e.target.files, f => f.name),
                       sizes: Array.from(e.target.files, f => f.size)};
  });
}
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


@pytest.mark.e2e
def test_files_reach_the_page_with_a_trusted_change(url, env):
    a, b = str(env / "a.pdf"), str(env / "b.pdf")

    async def body(session):
        outs = [await actions.upload_files(session, "#one", [a]),
                await actions.upload_files(session, "#many", [a, b]),
                await actions.upload_files(session, "#add", [b])]
        with pytest.raises(RuntimeError, match="opened no file chooser"):
            await actions.upload_files(session, "#inert", [a])
        return outs, await session.page().evaluate("JSON.stringify(seen)")

    outs, seen = asyncio.run(_with_browser(url, body))
    import json
    seen = json.loads(seen)
    assert outs[0] == "attached 1 file to #one (picked in the file chooser): a.pdf"
    assert outs[1].startswith("attached 2 files to #many (picked in the file chooser)")
    assert outs[2] == "attached 1 file to #add (picked in the file chooser): b.pdf"
    assert seen["one"]["names"] == ["a.pdf"] and seen["one"]["sizes"] == [10]
    assert seen["many"]["names"] == ["a.pdf", "b.pdf"]
    assert seen["hidden"]["names"] == ["b.pdf"]
    assert all(v["trusted"] for v in seen.values()), seen


@pytest.mark.e2e
def test_a_hidden_input_named_directly_gets_the_files(url, env):
    async def body(session):
        out = await actions.upload_files(session, "#hidden", [str(env / "a.pdf")])
        return out, await session.page().evaluate("JSON.stringify(seen)")

    out, seen = asyncio.run(_with_browser(url, body))
    assert "hidden" in out and out.endswith("a.pdf")
    assert '"names":["a.pdf"]' in seen and '"trusted":true' in seen


# --- the snapshot: what is uploaded is the file that was checked -------------

@pytest.fixture
def private_tmp(tmp_path, monkeypatch):
    base = tmp_path / "tmp"
    base.mkdir()
    monkeypatch.setattr(actions.tempfile, "tempdir", str(base))
    return base


def test_the_engine_gets_a_private_copy_of_what_was_checked(allowed, private_tmp):
    real = actions.uploadable([str(allowed / "a.pdf")], env=_env(allowed))
    copy, = actions.snapshot_files(real, env=_env(allowed))
    assert os.path.basename(copy) == "a.pdf"
    assert copy.startswith(str(private_tmp)) and open(copy, "rb").read() == b"%PDF-1.4 a"
    assert os.stat(os.path.dirname(os.path.dirname(copy))).st_mode & 0o077 == 0
    (allowed / "a.pdf").write_bytes(b"changed afterwards")
    assert open(copy, "rb").read() == b"%PDF-1.4 a", "the copy is not the name"


def test_a_name_swapped_for_a_link_after_the_check_is_not_followed(allowed, tmp_path, private_tmp):
    """The race in a shared staging directory: checked as a file, replaced by
    a link to something outside before the chooser is answered."""
    secret = tmp_path / "secret.txt"
    secret.write_text("key")
    real = actions.uploadable([str(allowed / "a.pdf")], env=_env(allowed))
    os.remove(allowed / "a.pdf")
    (allowed / "a.pdf").symlink_to(secret)
    with pytest.raises(PermissionError, match="not sent"):
        actions.snapshot_files(real, env=_env(allowed))
    assert os.listdir(private_tmp) == [], "a refused snapshot leaves nothing behind"


def test_a_directory_swapped_out_from_under_the_name_is_caught(allowed, tmp_path, private_tmp):
    sub = allowed / "sub"
    sub.mkdir()
    (sub / "c.pdf").write_bytes(b"ok")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "c.pdf").write_bytes(b"secret")
    real = actions.uploadable([str(sub / "c.pdf")], env=_env(allowed))
    os.rename(sub, allowed / "gone")
    sub.symlink_to(outside)
    with pytest.raises(PermissionError, match="no longer inside"):
        actions.snapshot_files(real, env=_env(allowed))


def test_a_file_that_grew_past_the_limit_is_not_sent(allowed, private_tmp, monkeypatch):
    real = actions.uploadable([str(allowed / "a.pdf")], env=_env(allowed))
    monkeypatch.setattr(actions, "UPLOAD_MAX_BYTES", 4)
    with pytest.raises(ValueError, match="limit"):
        actions.snapshot_files(real, env=_env(allowed))
    assert os.listdir(private_tmp) == []


def test_old_snapshots_expire_and_fresh_ones_stay(allowed, private_tmp):
    real = actions.uploadable([str(allowed / "a.pdf")], env=_env(allowed))
    old, = actions.snapshot_files(real, env=_env(allowed))
    old_root = os.path.dirname(os.path.dirname(old))
    os.utime(old_root, (0, 0))
    new, = actions.snapshot_files(real, env=_env(allowed))
    assert not os.path.exists(old_root)
    assert os.path.exists(new)


def test_several_files_have_a_budget_together(allowed, private_tmp, monkeypatch):
    two = [str(allowed / "a.pdf"), str(allowed / "b.pdf")]
    monkeypatch.setattr(actions, "UPLOAD_MAX_TOTAL_BYTES", 15)
    with pytest.raises(ValueError, match="together"):
        actions.uploadable(two, env=_env(allowed))
    monkeypatch.setattr(actions, "UPLOAD_MAX_TOTAL_BYTES", 20)
    real = actions.uploadable(two, env=_env(allowed))
    (allowed / "b.pdf").write_bytes(b"%PDF-1.4 b grew")
    with pytest.raises(ValueError, match="together"):
        actions.snapshot_files(real, env=_env(allowed))
    assert os.listdir(private_tmp) == []


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="the kernel's own record of an open file")
def test_a_file_unlinked_while_copied_keeps_its_name(allowed, private_tmp, monkeypatch):
    """A cleanup that deletes the staged file between open and copy: the
    descriptor still holds what was checked, and its readback gains the
    kernel's " (deleted)" mark, which must never reach the upload's name."""
    opened = actions._opened_path

    def unlinked_meanwhile(fd, real, st):
        os.unlink(real)
        return opened(fd, real, st)

    monkeypatch.setattr(actions, "_opened_path", unlinked_meanwhile)
    real = actions.uploadable([str(allowed / "a.pdf")], env=_env(allowed))
    copy, = actions.snapshot_files(real, env=_env(allowed))
    assert os.path.basename(copy) == "a.pdf"
    assert open(copy, "rb").read() == b"%PDF-1.4 a"
