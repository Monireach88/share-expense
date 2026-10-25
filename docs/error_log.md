# Error Log

> Debugging investigations: errors that required diagnosis, several attempts, and a fix that was not obvious.
> Use the `/log-error` skill to add entries.

---

## Index

| Date | Error | Root Cause | File |
|------|-------|------------|------|
| 2026-10-25 | Add expense: Day chips hidden under the bottom bar on a phone | HTMX `hx-boost` keeps the old `<body>` tag, so a body class set by the template is stale | `static/css/app.css` |

---

## 2026-10-25 — Bottom bar covers the end of the page after HTMX navigation

**Symptom:** On a phone, the Add expense page could not scroll far enough to show the Day chips; the sticky "Save expense" bar covered them. Screenshots taken by loading the page directly looked fine.

**Cause:** Each template set `{% block body_class %}has-bar{% endblock %}`, and the CSS reserved the bar's height with `body.has-bar main.container`. `hx-boost` on `<body>` swaps the body's content but keeps the `<body>` element and its attributes. Coming from "Who pays whom" (no bar, no class), the class stayed empty, so `main` kept 32 px of bottom padding instead of 96 px.

**How it was found:** A headless Chrome script opened "Who pays whom", clicked the Expenses tab, then "Add expense", and read `document.body.className` (empty) and the computed `padding-bottom` of `main` (32px).

**Fix:** The padding now comes from `body:has(.bottom-bar) main.container`, which follows the swapped content; the `body_class` block is gone. Rule: with `hx-boost`, never put per-page state on `<body>` or `<html>`; put it inside the swapped content.

**Trap during the check:** the test browser profile cached the old `app.css` in dev (no hashed file names there), so the first re-test still showed 32 px. Production uses `CompressedManifestStaticFilesStorage`, so phones get the new file after a deploy.

