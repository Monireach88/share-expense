# UI Redesign Spec

Status: proposal, 2026-10-25. Nothing in this file is built yet.

This spec is for the people who will change `templates/` and `static/css/`. It has four parts: what is wrong today (audit), the design rules and parts (design direction), what each page should look like (target layouts), and the order of work (implementation plan).

The audit used a demo trip with fake names (Anna, Ben, Chandra, Dara, Eli; 5 people, 8 expenses, 1 USD = 26,200 VND, Eli covered by Dara). Screenshots were taken with headless Chrome at 390x844 (a common phone), at 1280x900 (a laptop), and in dark mode. They are local working files and are not in the repo; the file names below (for example `04_trip_390.png`) say which page and size each finding comes from.

## 1. Audit

The app works, but every page looks like an unstyled admin form. The main causes are the same on every page:

- Pico CSS defaults decide the layout, not the two core jobs. Every form is one long column of equal-weight boxes, and every page is a heading plus a list.
- Nothing is sized for a thumb or for a quick glance. Amounts, names and actions all have the same size and colour.
- The trip header and tabs repeat on every page and use about 210 px (a quarter of the phone screen) before any content.
- Desktop pages stretch to 1200 px wide, so a label and its amount sit 1000 px apart.

Findings per page, worst first. "Job 1" is recording an expense; "Job 2" is reading who pays whom.

### 1.1 Add / edit expense form (Job 1) — `05_expense_new_390*.png`, `06_expense_edit_390*.png`, `14_expense_errors_390*.png`

1. The Save button is at about y = 1195 px on a 844 px screen. A user must scroll 1.5 screens to save, after every single expense.
2. The trip header, the four tabs and the "Add expense" heading use the first 270 px. The Amount field starts at y = 305 px. The "Expenses" tab is shown as active, which suggests the user is still on the list.
3. Amount and Currency are side by side on desktop, but Pico's `.grid` stacks them below 768 px. So on a phone Currency is a separate full-width drop-down, 110 px below Amount.
4. "Paid by" is a drop-down. Choosing a person takes 3 taps (open, scroll, pick) for a choice among 5 names that could be 1 tap.
5. The beneficiary picker ("For whom") is 5 small checkboxes (about 20 px) plus two outline buttons "Everyone" and "Nobody" that look like empty boxes at the fold (`05_expense_new_390.png`, bottom edge). Nothing says how much each person pays, and nothing shows that Eli's share goes to Dara.
6. "Type" is a drop-down with 8 options. It hides the choice and gives no visual cue in the list later.
7. "Save and add another" is a filled slate-grey button with the same size and weight as "Save", so the two compete. On the edit page, "Delete expense" is a neutral outline button that looks like "Cancel"; there is no Cancel or Back at all.
8. The edit page shows the amount as `600000.00` for VND (`06_expense_edit_390.png`): no thousands separator and two useless decimals. The amount is not converted, so the user cannot check "is this about 23 USD?".
9. Error state (`14_expense_errors_390.png`): after a failed save the page opens at the top; the "For whom" error is 2 screens down with no summary at the top. Each error has a stray red square bullet in the left page margin (Pico list style), and the text is Django's generic "This field is required."
10. The date field is last, shows the browser format `10/10/2026` (month first in US Chrome, which is easy to misread as 10 October vs 10 day of month), and for a trip in the past it silently defaults to the trip's first day.
11. Dark mode (`05_expense_new_390_dark.png`): field borders are almost invisible against the background, so empty fields look like dark stripes.

### 1.2 Summary page "Who pays whom" (Job 2) — `07_summary_390*.png`, `07_summary_1280.png`

1. On a phone the "Balance" column, the most important number on the page, is off-screen to the right. Only "Paid", "Own share" and half of "Respo…" are visible, and nothing shows that the table scrolls sideways.
2. The transfers read `Dara → Anna   152.09 USD` in the same 16 px text as every other row. There is no verb ("pays"), and the arrow is small, so a non-technical reader must guess the direction.
3. Positive and negative balances differ only by colour (green/red) and a minus sign (desktop screenshot). A colour-blind reader, or anyone in sunlight, sees no difference.
4. The explanation paragraph ("Balance = paid − share they are responsible for (their own share, unless someone covers them, plus …)") is one long sentence with a formula. Most family members will not read it.
5. "Who pays whom" appears twice: as the active tab and again as the H2 right below it.
6. "By type" is a plain list of 6 rows with no visual weight; it is fine but takes a full screen at the bottom.
7. There is no "you" on the page: the logged-in user (Anna) must find her own row in the table.

### 1.3 Trip page (expense list, Job 1 and 2) — `04_trip_390*.png`, `04_trip_1280.png`, `15_flash_after_add_390.png`

1. The floating "+ Add expense" button covers the amount of the row under it (`04_trip_390.png`: "275,000 VND" of "Breakfast pho" is hidden). At the end of the list the last row can also be hidden.
2. The tabs overflow: "Settings" is cut to "S" at the right edge, with no scroll hint. At 1280 px the four tabs are spread across 1200 px (Pico `nav` uses `space-between`).
3. Rows show the amount only in the paid currency (VND or USD mixed), while the total at the top is in USD. The reader cannot add up or compare rows.
4. The page does not say what matters to the user: "you will get back 284.89 USD" or "you owe 65.45 USD". That answer is two taps away.
5. Rows have no type cue (no icon), and an expense without a description shows the type name ("Shopping") as its title, which looks like a real description.
6. Day headings repeat the year ("TUE 13 OCT 2026") on every group.
7. After "Save", the flash "Expense added." (`15_flash_after_add_390.png`) is a grey box above the trip name. It does not say which expense, and the new row is often not on the first screen (here it was dated on the first trip day, at the bottom of the list).

### 1.4 App header (all pages)

1. The header is "Share Expense" in small blue text plus a drop-down with the user's name. On trip pages there is no way back to the trip list except that brand link, and on sub-pages (edit expense, edit person) there is no back link at all.
2. The account drop-down holds "Log out" as an outline button inside a menu; it is the only place for "Change password" and "Admin".
3. The header is not safe-area aware (`viewport-fit=cover` is missing), so on phones with a notch the sticky header and the floating button do not respect the edges.

### 1.5 Home (trip list) — `03_home_390*.png`, `03_home_1280.png`

1. Each trip is one bold line plus "10 Oct 2026 · 5 people · 8 expenses". It shows only the start date, no total and no personal balance.
2. With one trip, 75% of the phone screen is empty white, and the "+ New trip" pill floats alone at the bottom right.
3. The empty state is a plain grey box of text.

### 1.6 People — `08_people_390_full.png`; Edit person — `09_participant_390_full.png`

1. One page holds four jobs: the traveller list, an "Add a traveller" form, the account list and a "Give an account access" form. They run together with no visual separation; "Add a traveller" starts right under Eli's row.
2. "Edit" is a small text link (about 20 px high) at the far right.
3. The "Covered by" checkboxes in the add form list everyone, with a long help text. The sponsor link is the most unusual idea in the app, but it looks like any other field.
4. "Linked account" shows Django's "- Select an option -". "Remove person" is a neutral outline button, the same style as Cancel elsewhere.

### 1.7 Trip settings — `10_settings_390_full.png`

1. The rate shows as `1 USD = 26200 VND` (no separator). The add-rate form has "- Select an option -" and a "Rate" field whose meaning is only in small help text.
2. "Danger zone" is just a heading with a neutral "Delete trip" outline button; nothing is red.
3. Two "Save" buttons (trip, rate) on one long page, one blue, one slate.

### 1.8 Confirm delete — `11_confirm_delete_390*.png`

1. The destructive "Delete expense" button is the normal blue primary button; "Cancel" is a small outline button below it. The page invites the wrong tap.
2. The amount shows as `600000.00 VND`. There is no date, payer or reassurance about what happens (the expense leaves the totals).

### 1.9 Log in, Request an account, Change password, New trip — `01_*`, `02_*`, `12_*`, `13_*`

1. Log in does not say what the app is. On desktop (`01_login_1280.png`) the login card is 1200 px wide.
2. Request an account and Change password show Django's raw help text: "Letters, digits and @/./+/-/_ only." and four bullet points of password rules. This is the hardest English in the app, on the first page a new user sees.
3. New trip shows "---------" in the Country field and `mm/dd/yyyy` in both date fields.

## 2. Design direction

### 2.1 Principles

1. **One job per screen.** The add-expense screen only adds an expense; the summary screen only answers "who pays whom". Trip header and tabs appear only on the three main trip screens.
2. **The answer first.** Each screen opens with the number the user came for: their balance, the transfers, or the amount being typed.
3. **One tap per choice.** Choices among a few known items (payer, people, currency, type, day) are visible buttons, not drop-downs.
4. **The main action sits under the thumb.** Every task screen has one primary button in a sticky bottom bar, and nothing is hidden behind it.
5. **Money is never ambiguous.** Amounts always show the currency, use thousands separators, drop ".00" for currencies without cents, and show the base-currency value next to foreign amounts. Sign is shown in words ("gets back", "owes"), not only colour.
6. **Plain words, short labels.** Grade-6 English, a verb on every action button ("Save expense", "Delete trip"), no formulas in the interface.
7. **Calm, high contrast, both themes.** One accent colour, semantic colours only for money direction and warnings, every pair checked to WCAG AA.
8. **Light and self-contained.** No build step, no web font download, under 20 KB of CSS and 3 KB of JS in total.

### 2.2 Colour tokens

Define once on `:root`, override under `@media (prefers-color-scheme: dark)` with `:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`. Contrast ratios below were computed with the WCAG formula; text needs 4.5:1, borders and icons 3:1.

| Token | Use | Light | Dark | Contrast (light / dark) |
|---|---|---|---|---|
| `--bg` | page background | `#f5f6f8` | `#0f1115` | — |
| `--surface` | cards, bars, fields | `#ffffff` | `#1a1d23` | — |
| `--fg` | body text | `#16191f` | `#e9ebef` | 17.6 / 14.1 on surface |
| `--muted` | secondary text | `#596170` | `#a3aab6` | 6.2 / 7.2 on surface |
| `--line` | dividers only | `#d9dde4` | `#2f343d` | decorative |
| `--field` | field and chip borders | `#8a93a3` | `#6b7383` | 3.1 / 3.5 on surface |
| `--accent` | primary buttons, links, selected chips | `#2448c8` | `#8fa6ff` | 7.4 / 7.3 on surface |
| `--on-accent` | text on accent | `#ffffff` | `#0f1115` | 7.4 / 8.2 |
| `--accent-soft` | selected chip fill, active tab | `#e6ebfb` | `#1f2846` | accent on it 6.2 / 6.3 |
| `--pos` | "gets back", success | `#11703a` | `#5fd38a` | 6.2 / 9.0 on surface |
| `--pos-soft` | success flash fill | `#e3f4e8` | `#13301f` | pos on it 5.4 / 7.6 |
| `--neg` | "owes", errors, danger | `#b3261e` | `#ff8f85` | 6.5 / 7.7 on surface |
| `--neg-soft` | error box fill | `#fbe7e5` | `#3a1a18` | neg on it 5.5 / 7.1 |
| `--warn` | warning border and icon | `#8a5300` | `#f2c14e` | 6.3 / 10.1 on surface |
| `--warn-soft` | warning box fill | `#fdf3dc` | `#33290f` | fg on it 16.0 / 12.0 |

The accent is a deep blue, not green, so that green always means "gets money back". Danger buttons use `--neg` with `--on-accent`-style white text in light mode (`#ffffff` on `#b3261e` is 6.5:1).

### 2.3 Type

- Font: the system UI stack, `system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif`. Reason: zero download on roaming mobile data, each phone's own font renders best, and all of these fonts have tabular figures. When the Khmer translation (backlog) ships, add `"Noto Sans Khmer"` to the stack and self-host one subset `woff2` file in `static/fonts/` with `line-height: 1.9` for Khmer text, as the reference rating page does.
- All amounts use `font-variant-numeric: tabular-nums` so digits line up in lists.
- Scale (px): 13 (meta, captions), 15 (secondary text, labels), 17 (body, list titles, buttons), 20 (section titles), 24 (page title), 32 (hero numbers: the amount being typed, "you get back"). Body line height 1.5, headings 1.25.
- Weights: 400 body, 600 labels, buttons and names, 700 hero numbers only.
- Body text is 17 px, not 16, because many readers are older; inputs stay at 17 px or more so iOS does not zoom on focus.

### 2.4 Spacing, radius, size

- Spacing scale: 4, 8, 12, 16, 24, 32, 48 px as `--s1` … `--s7`. Page gutter `max(16px, env(safe-area-inset-left))`.
- Content width: `max-width: 640px`, centred, on every page (summary may use 720 px). On desktop the app becomes a centred column, not a stretched form.
- Radius: 8 px fields and buttons, 12 px cards, 999 px chips.
- Touch targets: 48 px high for primary buttons and fields, 44 px minimum for chips, tabs, list rows and icon buttons, with at least 8 px between targets.
- Sticky bottom bar: 64 px plus `env(safe-area-inset-bottom)`; `main` gets matching bottom padding so no row is ever hidden.

### 2.5 Components

**App header.** 56 px, sticky, `--surface` background, bottom border `--line`. Left: on top-level pages a small brand ("Share Expense", 17 px, 600); on sub-pages a back link with a chevron and the parent name ("‹ Da Lat trip"). Right: a 44 px round button with the user's initial, opening a menu (`<details>`) with "Change password", "Admin" (staff only) and "Log out" as plain full-width menu rows.

**Trip header.** Only on the Expenses, Who pays whom and People tabs. Trip name at 20 px 600 on one line (ellipsis if long), and one muted 13 px line "Vietnam · 10–14 Oct 2026 · USD". Owners get a 44 px gear icon button on the right that opens Settings; Settings leaves the tab bar.

**Tabs.** Three equal-width tabs: "Expenses", "Who pays whom", "People". Each is a third of the width, 44 px high; the active tab has `--accent-soft` fill and `--accent` text, inside a rounded 48 px track (a segmented control). Three tabs fit 358 px without scrolling.

**Buttons.** Primary: `--accent` fill, `--on-accent` text, 48 px, full width on phones, label is a verb + noun ("Save expense"). Secondary: `--surface` fill, 1 px `--field` border, `--fg` text. Danger: `--neg` fill and white text, used only on confirm pages; elsewhere a danger *link* style (text in `--neg`, 44 px row) that leads to the confirm page. Disabled: 50% opacity. Focus: 2 px `--accent` outline with 2 px offset on every interactive element.

**Form fields.** Label above the field (15 px, 600). Field 48 px, `--surface` fill, 1 px `--field` border, 8 px radius, 17 px text. Help text below in 13 px `--muted`, one sentence. Error: 2 px `--neg` border, error text below the field in 15 px `--neg` with a small icon, no list bullet. Field groups are 16 px apart, sections 32 px apart.

**Chip picker (used for payer, beneficiaries, currency, type, day).** The real `<input type="radio">` or `<input type="checkbox">` stays in the markup, visually hidden but focusable, inside its `<label>`; the label is the chip. Chip: 44 px high, 999 px radius, 1 px `--field` border, 15–17 px text, padding 0 16 px; checked: `--accent-soft` fill, `--accent` border and text, and a check mark (✓) before the name so the state is not shown by colour alone. Chips wrap in rows with 8 px gaps. Keyboard and screen-reader behaviour stays native because the inputs stay.

**Beneficiary picker ("For whom").** A chip picker of checkboxes, all people selected by default. Above it, one line: "Split between **5 people** · **4.58 USD each**", updated live by JS. A single "Everyone" chip at the start toggles all on or off (replaces the two "Everyone" / "Nobody" buttons). A covered person's chip shows a small muted note under the picker: "Eli's share is paid by Dara." This makes sponsors visible at the moment they matter.

**Money display.** One template filter (for example `{{ amount|money:currency }}`) so every page formats the same way: thousands separator, no decimals for zero-decimal currencies (VND, KHR, JPY…), 2 decimals otherwise, the code after the number in 13 px muted ("600,000 VND"). Foreign amounts get a second muted line "≈ 22.90 USD". Balances: "gets back 284.89 USD" in `--pos` with a ↑ icon, "owes 65.45 USD" in `--neg` with a ↓ icon, "even" in `--muted`. Never a bare minus sign.

**Expense row (list card).** 64–72 px row, whole row is the link. Left: a 36 px round icon for the type (`--accent-soft` background). Middle: title (description, or "Food & drink" in muted italics if empty), and below it 13 px muted "Chandra paid · everyone". Right: amount, and the base value under it for foreign amounts. Rows are grouped by day under a 13 px uppercase muted heading "TUE 13 OCT" (year only if the trip spans two years), with a day subtotal on the right.

**Transfer card ("who pays whom").** One card per transfer, 72 px: "**Dara** pays **Anna**" on the left (17 px), amount on the right (20 px 700, tabular). A line under the names: "Dara owes 152.09 USD in total" only when useful. If the logged-in user is in the transfer, the card has a 3 px `--accent` left border and the label "You".

**Person balance card.** Name, a "covered by Dara" tag if any, and the balance in words ("gets back 284.89 USD"). A `<details>` disclosure "How was this calculated?" opens three lines: "Paid 365.04", "Own share 80.15", "Shares they cover 0.00". This replaces the 5-column table on phones; on screens ≥ 720 px the table may come back as an option.

**Empty states.** A 48 px icon in `--muted`, one sentence that says what to do, and one primary button. Example (trip without expenses): "No expenses yet. Add the first one when someone pays." + [Add expense].

**Flash messages.** Below the header, a card with an icon: success uses `--pos-soft` fill and `--pos` icon; error uses `--neg-soft`. Text names the thing: "Added: Coffee, 95,000 VND (Anna paid)". Success messages fade after 6 s (CSS animation, disabled under `prefers-reduced-motion`); errors stay. Keep `role="status"`.

**Warning box.** For "this cannot be undone" or "add an exchange rate first": `--warn-soft` fill, 3 px `--warn` left border, ⚠ icon, 15 px text. Same idea as the reference page's check notes.

**Error summary.** At the top of any form that failed: a `--neg-soft` box "Please fix 2 things" with links to each field, and the page scrolls to it (`autofocus` on the box with `tabindex="-1"`).

**Icons.** One self-hosted SVG sprite (`static/img/icons.svg`, about 15 icons: back, gear, plus, check, arrow up/down, warning, the 8 type icons, user). Take them from an MIT/ISC-licensed set such as Lucide and keep the licence line in the file.

## 3. Per-page target layout

Sizes are for a 390x844 screen. "First screen" means visible without scrolling.

### 3.1 Trip page (Expenses tab)

First screen: header, trip header, tabs, the balance card, and 4–5 expense rows. Primary action: sticky bottom bar "+ Add expense". The floating button goes away.

```
┌──────────────────────────────────────┐
│ Share Expense                    (A) │  app header 56
├──────────────────────────────────────┤
│ Demo: Da Lat family trip         [⚙] │  trip header 56
│ Vietnam · 10–14 Oct 2026 · USD       │
│ [ Expenses ][Who pays whom][ People ]│  tabs 48
│ ┌──────────────────────────────────┐ │
│ │ You get back        284.89 USD ↑ │ │  balance card 72,
│ │ Trip total 469.38 USD   See all ›│ │  links to Who pays whom
│ └──────────────────────────────────┘ │
│ TUE 13 OCT                 50.52 USD │  day heading + subtotal
│ (🚕) Grab to waterfall  210,000 VND  │
│      Chandra paid · everyone ≈ 8.02  │
│ (🛍) Shopping            42.50 USD   │
│      Dara paid · Dara, Eli           │
│ MON 12 OCT                 48.28 USD │
│ (🍜) Dinner at night…  1,180,000 VND │
├──────────────────────────────────────┤
│ [          + Add expense           ] │  sticky bar 64 + safe area
└──────────────────────────────────────┘
```

Order: balance card, then days newest first. The balance card shows "You owe …" in `--neg` or "You are even" when needed; if the user has no linked participant it shows "Trip total" only. The total line moves into the card. Empty state replaces the list.

### 3.2 Add / edit expense

No trip header, no tabs. The header shows "‹ Da Lat trip". First screen: amount, currency, description, payer and the beneficiary picker. Type and date are below, with good defaults. Primary action: sticky "Save expense". "Save and add another" becomes a secondary text button in the same bar on the add page.

```
┌──────────────────────────────────────┐
│ ‹ Da Lat trip                   (A)  │
├──────────────────────────────────────┤
│ Add expense                          │  24 px title
│ Amount                               │
│ ┌──────────────────────┐ (USD)(VND✓) │  32 px input, inputmode=decimal
│ │ 450,000              │             │  currency chips beside it
│ └──────────────────────┘             │
│ ≈ 17.18 USD                          │  live preview
│ What for?                            │
│ [ Taxi from airport               ]  │
│ Who paid?                            │
│ (Anna✓)(Ben)(Chandra)(Dara)(Eli)     │  radio chips
│ For whom?  Split 5 ways · 3.44 USD   │
│ (Everyone✓)(Anna✓)(Ben✓)(Chandra✓)   │  checkbox chips
│ (Dara✓)(Eli✓)                        │
│ Eli's share is paid by Dara.         │  sponsor note, muted
│ Type                                 │
│ (🍜 Food)(🚕 Transport)(🏨 Stay)…     │  radio chips, 2 rows
│ Day                                  │
│ (Sat 10)(Sun 11)(Mon 12)(Tue 13)…    │  trip-day chips + "Other date"
├──────────────────────────────────────┤
│ [Save + add another]  [Save expense] │  sticky bar
└──────────────────────────────────────┘
```

Details:
- Amount input: `type="text" inputmode="decimal" autocomplete="off"`, autofocus on the add page only, value without trailing ".00" for VND. It accepts "450000" and "450,000".
- Currency chips show only the trip's currencies (usually 2). If the trip has one currency, show it as plain text after the input.
- Day chips list each trip day when the trip has 14 days or fewer and dates are set; an "Other date" chip reveals the normal date input. Otherwise use the date input. The default stays as in `_initial()`.
- Edit page: same layout, title "Edit expense", bar has "Save changes"; below the form a 44 px danger link "Delete this expense" and the "Added by … / Last changed by …" line in 13 px muted.
- Errors: error summary at the top, field errors in place, page scrolls to the summary.

### 3.3 Who pays whom (summary)

First screen: the transfers and the user's own balance. Primary action: none needed (read-only page); the bottom bar is not shown.

```
┌──────────────────────────────────────┐
│ Share Expense                    (A) │
├──────────────────────────────────────┤
│ Demo: Da Lat family trip         [⚙] │
│ [ Expenses ][Who pays whom][ People ]│
│ To settle the trip, 3 payments:      │  15 px muted
│ ┌──────────────────────────────────┐ │
│ │ Dara  pays  Anna      152.09 USD │ │  transfer cards
│ ├──────────────────────────────────┤ │
│ │ Chandra pays Anna      67.35 USD │ │
│ ├──────────────────────────────────┤ │
│ │ Ben  pays  Anna        65.45 USD │ │
│ └──────────────────────────────────┘ │
│ Each person                          │  20 px section title
│ Anna (you)      gets back 284.89 ↑   │  person cards
│ Ben                 owes 65.45 ↓     │
│ Chandra             owes 67.35 ↓     │
│ Dara                owes 152.09 ↓    │
│ Eli  covered by Dara       even      │
│   ▸ How was this calculated?         │
│ By type                              │
│ Stay      ███████████████  320.00    │  CSS bars, width = share
│ Food      ███              55.54     │
└──────────────────────────────────────┘
```

Details:
- The H2 "Who pays whom" is removed; the tab already says it. A short line "To settle the trip, 3 payments:" replaces it. The "Everyone is even" state is a success card.
- The formula paragraph is replaced by the per-person disclosure. One plain sentence stays at the end: "All amounts in USD. Rates: 1 USD = 26,200 VND."
- The error state (missing exchange rate) becomes a warning box with a button "Add the rate" to Settings (owners) or "Ask the trip owner to add the rate" (members).
- Tests: `tests/test_trips.py::test_summary_page_shows_who_pays_whom` checks the exact string `Friend</strong> → <strong>Owner`; update it together with this template.

### 3.4 Home (My trips)

First screen: up to 4 trip cards. Primary action: sticky "+ New trip". Each card: trip name (17 px 600), "10–14 Oct 2026 · Vietnam", "5 people · 8 expenses · 469.38 USD", and the user's balance in words. Empty state: "You have no trips yet." + [New trip], and a second line "Or ask a trip owner to add you. Your username: demo_ui" with the username in a copyable box.

### 3.5 People

First screen: the list of travellers. Each row: name, tags "covered by Dara" and "has account", whole row links to edit (owners). Primary action for owners: sticky "+ Add traveller", which opens the add form on its own page (reuse `participant_form.html` with an empty participant) instead of the inline form. The "Who can open this trip" section stays below as a separate card with a short form "Add by username" inline; "Remove access" becomes a danger link with the existing `hx-confirm`.

### 3.6 Edit traveller

Header "‹ People". Fields: Name; "Who pays for this person?" as checkbox chips with the help line "Leave empty if they pay for themselves."; "Linked account" select with the empty option labelled "No account". Sticky "Save changes". Danger link "Remove this person" at the bottom.

### 3.7 Trip settings

Header "‹ Da Lat trip" (Settings is no longer a tab). Three cards: "Trip details" (form + "Save trip"), "Exchange rates" (rows "1 USD = 26,200 VND" with a danger link "Remove", and an inline add row "1 USD = [______] [VND ▾]" + "Add rate"), "Delete trip" in a card with a `--neg` border and a warning sentence. No sticky bar here because the page has three separate forms.

### 3.8 Confirm delete (expense, person, rate, trip)

Header "‹ back". A card that shows what will be deleted (for an expense: title, amount, payer, date). A warning box with what happens ("It will be left out of all totals." / "This cannot be undone."). Buttons in the bottom bar: "Cancel" (secondary) and "Delete expense" (danger fill), side by side, Cancel on the left. The `blocked` case shows the warning box and only a "Back" button.

### 3.9 Log in, Request an account, Change password, New trip

- A centred column of 400 px max. Log in starts with the app name and one line: "Share trip costs with your family. See who pays whom at the end."
- Request an account: replace Django's help texts with plain ones: username "Letters and numbers, no spaces."; password "At least 8 characters, not only numbers." (one line); confirmation "Type the password again." Same for Change password.
- New trip: country empty option "Choose a country (optional)"; dates side by side even on phones (two 48 px fields fit at 390 px); base currency with its help line. Primary "Create trip".

## 4. Implementation plan

### 4.1 Pico: replace it

Decision: remove Pico and write our own `static/css/app.css` (target under 20 KB unminified).

Reason: the redesign restyles every element Pico styles (header, nav, tabs, buttons, fields, checkboxes, cards, tables, menus). Keeping Pico would mean overriding its 83 KB file element by element, and several audit problems come straight from its defaults: `nav` with `space-between` (tabs spread across 1200 px), `.grid` stacking below 768 px (currency under amount), list bullets on `.errorlist`, `article` shadows on auth pages, and low-contrast field borders in dark mode. A small own stylesheet with tokens is easier to read and maintain for an open-source project with no build step. The cost is one larger first step, which section 4.2 step 1 keeps verifiable by screenshots of every page.

Delete `static/vendor/pico.min.css` in the last step, after no template uses a Pico-only class (`grid`, `striped`, `overflow-auto`, `dropdown`, `secondary`, `outline`, `container`).

### 4.2 Ordered steps

Each step is small enough to check alone: `make test`, `make lint`, and 390 px light, 390 px dark and 1280 px screenshots of the pages it touches. "CSS" = CSS only, "Markup" = template changes, "Python" = a view, form or template-tag change.

1. **Base stylesheet and Pico removal.** (CSS + Markup) Rewrite `static/css/app.css`: tokens (2.2), reset, type (2.3), spacing, links, focus ring, buttons (`.btn`, `.btn-secondary`, `.btn-danger`, `.link-danger`), fields, `.container` 640 px, `.card`, `.list`, `.muted`, `.num`. In `templates/base.html`: remove the Pico `<link>`, add `viewport-fit=cover` to the viewport meta, add `<meta name="theme-color">` for light and dark. Convert `role="button"` links and `class="secondary outline"` to the new classes in all templates (search-and-replace). Check: every page renders with readable forms in both themes.
2. **Field partials and error states.** (Markup + CSS) `templates/_field.html`: wrap in `<div class="field">`, add `aria-describedby` for help and errors, render errors as `<p class="field-error">`. New `templates/_form_errors.html` with the error summary; include it in every form template. Remove the `.errorlist` bullet styles. Check: submit the empty expense form and the empty signup form.
3. **Money filter.** (Python + Markup) Add a template filter `money` (for example in a new `apps/trips/templatetags/money.py`) with a zero-decimal currency set; use it in `expenses/list.html`, `trips/summary.html`, `trips/confirm_delete.html`, `trips/settings.html`. Add a unit test for 600000 VND → "600,000 VND" and 42.5 USD → "42.50 USD". Change the amount widget in `apps/expenses/forms.py` to `TextInput(attrs={"inputmode": "decimal"})` and strip the trailing ".00" for zero-decimal currencies on edit.
4. **App header and sub-page header.** (Markup + CSS) `templates/base.html`: user-initial menu button, menu rows; add a `{% block back %}` so sub-pages show "‹ parent". Add the icon sprite `static/img/icons.svg`. Check: header at 390 and 1280, keyboard focus through the menu.
5. **Trip header and tabs.** (Markup + CSS) `templates/trips/_trip_header.html`: compact header, gear button for owners, three-tab segmented control; remove the Settings tab. Include it only in `expenses/list.html`, `trips/summary.html`, `trips/people.html`. Check: no tab clipping at 320 px and 390 px.
6. **Sticky bottom bar.** (Markup + CSS) A `.bottom-bar` class with safe-area padding, and `main` bottom padding to match. Replace `.fab` in `expenses/list.html` and `trips/home.html`. Check: the last row of a long list is fully visible.
7. **Expense list rows.** (Markup + CSS + Python) `templates/expenses/list.html`: type icon, title fallback in muted italics, base-currency second line, day heading without year, day subtotal. In `apps/expenses/views.py::expense_list` pass the base amount per expense and per day (it already computes `to_base`).
8. **Balance card on the trip page.** (Python + Markup) In `expense_list`, call `trip_settlement()` and find the row for the participant linked to `request.user`; render the card. Handle `SettlementError` (show the missing-rate warning instead).
9. **Expense form layout.** (Markup + CSS + Python) `templates/expenses/form.html`: new order, sub-page header, no trip header. In `apps/expenses/forms.py`: `payer` → `RadioSelect`, `category` → `RadioSelect`, `currency` → `RadioSelect`. Chip CSS for radio and checkbox labels. Sticky bar with "Save expense" and "Save + add another". Check: Save visible without scrolling at 390x844; keyboard can reach every chip; `make test`.
10. **Beneficiary picker and sponsor note.** (Markup + CSS + small JS) "Everyone" toggle chip, live "Split N ways · X each" line, sponsor note from the participants' sponsors. New `static/js/expense_form.js` (under 3 KB, no library): reads `data-rates` and `data-base` from the form, updates the base preview and per-person split, toggles all chips. The page must still work with JS off (the server already validates). Load it with `defer` only on the form page.
11. **Day chips.** (Markup + Python) Pass the list of trip days to the form template from `expense_create` / `expense_edit`; render radio chips bound to the `date` field, plus "Other date" that reveals the date input (`<details>` with no JS).
12. **Summary page.** (Markup + CSS) `templates/trips/summary.html`: transfer cards, person cards with `<details>`, by-type bars (inline `style="--w: 68%"` computed in the view or with `widthratio`), warning box for the error state. Update `tests/test_trips.py::test_summary_page_shows_who_pays_whom` to the new markup.
13. **Flash messages.** (Markup + CSS + Python) Restyle `.messages` in `base.html`; change the success text in `apps/expenses/views.py` to name the expense ("Added: {description}, {amount}").
14. **Home page.** (Markup + Python) Trip cards with date range, total and the user's balance (`apps/trips/views.py::home`); new empty state.
15. **People and edit traveller.** (Markup + CSS) `templates/trips/people.html`: list rows as links, "Add traveller" moves to its own page via the existing participant form template; members card. `templates/trips/participant_form.html`: chip picker for sponsors, "No account" empty label (set `empty_label` in `apps/trips/forms.py`). Check the existing people tests still pass.
16. **Settings and confirm pages.** (Markup + CSS) `templates/trips/settings.html`: three cards, inline rate row, danger card. `templates/trips/confirm_delete.html`: object card, warning box, danger button in the bottom bar.
17. **Auth and new-trip pages.** (Markup + Python) Centred 400 px column for `templates/registration/*.html`; plain help texts in `apps/accounts/forms.py` (username) and a single plain password hint; `templates/trips/trip_form.html` with dates side by side and a friendly empty country option.
18. **Clean-up and check.** (CSS) Delete `static/vendor/pico.min.css`, grep templates for old Pico classes, retake all screenshots at 390 light, 390 dark and 1280, and run an accessibility pass (keyboard only, 200% zoom, VoiceOver on the expense form).

Steps 1–6 are the base and must go in order. Steps 7–17 can then be done in any order, but steps 9–12 give the most value for the two core jobs and should come first.
