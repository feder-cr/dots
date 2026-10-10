---
title: "Browser calls that lead nowhere"
description: "45 browser tasks of real Dots, call by call: 90 of 773 page calls led nowhere and took a third of the time spent on pages. Grouped by cause, with what was changed for each and what was not."
parent: "Studies"
nav_order: 6
---

# Browser calls that lead nowhere

Two Dots in front of their owner spent their steps on calls that went nowhere:
an address that answered 404, then another, then a search. Instead of fixing
the case in view, every browser call of the saved runs was counted and each
wasted one given a cause. The numbers came first, then the rules.

## The data

All the tasks that drove a page: 41 from the benchmark runs of 7 to 9 October
2026 (LongMemEval questions and the long language-history task, mostly
z-ai/glm-5.3-flash) and 4 from a test Dot on 10 October. That is 45 tasks,
1,403 calls, 773 of them on a page (355 navigations), 2,823 seconds spent in
page calls. The events keep, for each call, the tool, its target, whether it
succeeded and how long it took, not what it returned. So a navigation
abandoned without being read was checked afterwards: its address was fetched
again on 10 October and compared with the addresses that were read.

## What led nowhere

90 page calls (12%), 961 seconds: a third of the time spent on pages.

| Cause | Calls | Seconds | What it was |
|---|---:|---:|---|
| An address from memory | 58 | 416 | 54 navigations dropped without reading the page, 4 to domains that no longer exist. Of the 54, 27 answer 404 (or have no archived copy), 5 redirect to an index, 7 land on another date of the Wayback Machine. Of 40 addresses that were read, 1 answers 404. |
| The first page after a launch | 5 | 155 | The first navigation failed at 31 seconds and the same one, again, loaded. Only on a loaded host, where the launch itself took 36 to 115 seconds. |
| A page over 45 seconds | 5 | 238 | Three Wayback Machine captures, and one Starbucks page tried twice. |
| A read right after the navigation | 10 | 50 | `browser_read_text` failed once and worked when called again. Four came right after a Google search. One passed a `text=` selector, which is not CSS. |
| A click under Google's consent dialog | 4 | 66 | The click on a result waited its 15 seconds and failed. The model then answered the dialog and the same click worked. |
| Other clicks | 2 | 33 | A selector the model wrote itself instead of the snapshot's, and a link inside a closed menu. |
| `browser_back` | 3 | 1 | It failed three times out of three. |
| Other | 3 | 1 | A custom select, and a call with no arguments. |

No snapshot was taken twice without something done in between.

## Back, forward and reload never worked

The Dot's `browser_back`, `browser_forward` and `browser_reload` pressed
Alt+Left, Alt+Right and F5 on the page. They were run on the library itself:

| Key | What happened |
|---|---|
| Alt+Left, Alt+Right | `unknown key: 'Left'`: the library's names are `ArrowLeft` and `ArrowRight` |
| Alt+ArrowLeft, Alt+ArrowRight | Pressed, and the page stayed where it was |
| F5 | Pressed, and the page was not loaded again (a value set on the window survived it) |
| PageDown (`browser_scroll`) | Scrolled, from 0 to 913 pixels |
| A navigation to the page's own address | Loaded it again (HTTP 200, the value gone) |

A key the server presses reaches the page, never the browser's own shortcuts.
So the three tools were removed: going back is a navigation to the address the
page came from, and loading a page again is a navigation to its own address.
The five "reloaded the page" answers in the runs were five reloads that did not
happen.

## What was changed

- **Finding a page** (PR #1438): an address comes from a link seen in a
  snapshot, from the site's own search, or from a search engine, never from
  memory; after a 404 the next address comes from a page that loaded. On a Dot
  asked for three documentation pages whose addresses are not guessable,
  2 addresses from memory that answered 404 became 0; the task cost $0.037
  instead of $0.019, the difference being the snapshots of the results. Brave
  is the engine named because it was the one that gave the Dot's Firefox
  usable results: DuckDuckGo's HTML version wraps its links in a redirect,
  and Bing gave an empty results area.
- **Back, forward and reload** removed, as above.
- **`browser_read_text` takes a CSS selector**, and its description says so:
  the server reads with `document.querySelector`, so a snapshot selector in
  Playwright's own syntax (`:nth-match(...)`, `text=...`) fails there.
- **A consent dialog is answered first.** The skill says to click one of its
  buttons when the snapshot shows one. On the same Google task, run once
  with the old skill and once with the new one on a fresh Dot, both answered
  the dialog before clicking. So this run shows no gain; the rule is for the four
  clicks above.

## What was not changed, and why

- **The snapshot with the navigation.** Another agent framework, OpenClaw,
  returns the page's snapshot with every navigation, so a page costs one call.
  Here, what follows a navigation that loaded is a text read 72% of the time,
  another navigation 15%, and a snapshot 7%. An inline snapshot would save 25
  calls of 773. Not worth the tokens it would add to every navigation.
- **The two timeouts belong to the library.** The 31-second failure matches
  the 30 seconds `invisible_playwright` gives `Browser.newPage`, which the first
  navigation of a launch calls, while the navigation itself has 45. It is
  reported there, not worked around in the engine.
- **The reads that fail right after a Google search** are not explained. The
  events do not keep the error text, and a probe with the local copy of the
  library (older than the Dots') did not reproduce it.

## The method's limit

The events say that a call failed, not why. The causes above come from the
target, the duration, the call that came next, and the addresses fetched
again; the error text is only in the Dot's own database, which the benchmark
does not save.

## Sources

- The analysis scripts read the saved events of `tests/bench/` runs
  (`/work/bench-jobs/*/events/*.json`) and the test server's Dots.
- [invisible_playwright](https://github.com/feder-cr/invisible_playwright):
  key names (`_juggler/keyboard.py`), `Browser.newPage` (`_juggler/server.py`).
- [invisible-playwright-mcp](https://github.com/feder-cr/invisible_playwright_mcp):
  `browser_read_text` and `browser_snapshot` (`mcp/actions.py`).
