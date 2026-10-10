---
name: invisible-playwright
description: Use the Dot's browser (invisible_playwright) for any task on a website or search on the web: finding a page, logging in, reading pages, filling forms, clicking through a site as a person would.
---

# The browser

Your browser is invisible_playwright: a real Firefox that a site sees as a person at a computer. Everything you do in it
goes through the real pointer and the real keyboard. Use it when a task needs a website; for a plain download or an
API, `exec` with `curl` is simpler.

## Identities

A browser identity is one person on the web: its own profile, cookies, logins and fingerprint, kept on disk between
uses.

- `browser_identity_list` shows the identities, which are open, and how many may be open at once.
- `browser_identity_create` makes one, closed. Give it a name only: it then leaves through this computer's own network,
  which is right unless the person asked for this one identity to use a proxy of theirs.
- `browser_identity_launch` opens it on your desktop. The first launch of a new identity can take minutes.
- `browser_identity_close` closes it; its profile, cookies and logins stay.
- Reuse the identity that is already logged in to a site instead of making a new one, and keep one identity per
  person or account you act as: two accounts in one identity are one person to anyone looking.
- A second identity is for what must not touch the first. The usual case: signing up somewhere and needing a mailbox
  for the verification. Open a throwaway-mail site in another identity, take the address, type it into the form in the
  first one, and go back to the other for the link.

Each open identity drives one page. `browser_navigate` opens a url in it, and every other tool acts on that page.
Going somewhere else and coming back is a navigation, not a second window.

## Finding a page

A page is reached through a link you have seen or an address the person gave you, not one you remember. Sites move
their pages: an address recalled from memory often answers 404 today, and every try costs one of the task's steps.

- From a page you have: `browser_snapshot` lists its links with their selectors and URLs. Click the one that says where
  you want to go, or navigate to its URL. A site's own menu and its own search box reach what you cannot guess.
- From nothing: search. Navigate to `https://search.brave.com/search?q=<your words>` and read the results with
  `browser_snapshot`: each result's URL is real, open the one that fits. An answer panel at the top or a notice at the
  bottom is not a result. If Brave does not answer, `https://duckduckgo.com/html/?q=<your words>` gives the same.
- Read the status `browser_navigate` answers before trusting the page: a 404 or a 403 still has a document, and reading
  it as content is a mistake. After a 404, do not try another address from memory: go back to a page that loaded and
  take a link from it, or search.
- An address from memory is for a site's home page at most, once. Everything under it comes from the site's own links.

## Acting on a page: try things in this order

The order matters, because a page can tell the difference.

1. A named tool with a selector: `browser_click`, `browser_type`, `browser_select_option`, `browser_press_key`.
   `browser_snapshot` gives the selector of each visible element; pass it as it is, it is built to be unambiguous.
2. Coordinates. `browser_snapshot` reports `at: [x, y]` for every element it lists, in viewport pixels, and
   `browser_click_at` takes exactly those. This is for what a selector does not describe: a canvas, a slider, a map,
   a widget made of plain boxes.
3. Your eyes. `browser_screenshot`, find the thing in the picture, then `browser_click_at` where it is. For what the
   snapshot does not list at all. `computer_screenshot` shows your whole desktop, the browser window included.

Read with `browser_snapshot` (title, url and the interactive elements, with `checked` and `value` where they have
one) and `browser_read_text` (the text of an element). `browser_scroll`, `browser_back`, `browser_forward` and
`browser_reload` move around as a person would.

Never try to change a page except through the pointer and the keyboard: an event a script makes arrives marked as not
coming from a person, which is the clearest sign that a bot is driving.

## When it does not work

- If a tool says the browser is not open or is gone, launch the identity again and carry on.
- A date field that is a calendar wants its days clicked, not typed.
- A captcha, a block or a page that keeps refusing you: say so in your answer, with what you saw. A task reported as
  impossible is worth more than one done in a way that gets the identity blocked.
- Do not guess a number or a fact you could not read on the page.

Close an identity with `browser_identity_close` once the task no longer needs it, before you answer: an open browser
holds memory on your computer.

## Your own skills

When you work out how to do something on a site that you will do again (where its login is, which steps a form needs,
what blocks you), write it down as a skill of your own: /home/dot/skills/<name>/SKILL.md, the same shape as this file.
