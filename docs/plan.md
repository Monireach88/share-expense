# Share Expense — MVP Plan

Status: approved on 2026-10-25 (the owner answered "Yes to all" to D1–D8). V1 built; see `README.md`.

## 1. Goal

A mobile-friendly web app that replaces the trip spreadsheet `archive/share_expense_history_2025_2026.xlsx`. One person (or a few) records each expense during a trip; at the end, everyone sees who owes whom. The settlement numbers must be identical to the spreadsheet's numbers.

Audience: the owner's family and friends first; open source so others can self-host it. Not a commercial product, so there is no market research and no payment feature.

## 2. How the spreadsheet works (the logic the app must copy)

Checked on the 4 newest sheets (`VN_20261125`, `VN_20260531`, `VN_20260111_15`, `VN_20251106`). A Python reimplementation of the rules below gave the same settlement balance as the sheet for every person on all 4 sheets (largest difference: 0.003 USD, which is rounding).

**Expense row:** date, payer (one person), beneficiaries (one or more people), expense type, description, amount, currency.

1. **Convert:** each trip has one fixed exchange rate (for example 1 USD = 26,200 VND). An amount in the foreign currency becomes USD as `round(amount / rate, 2)`.
2. **Split:** the USD amount is split equally among the beneficiaries of that row.
3. **Individual trip expense** of a person = the sum of their equal shares over all rows.
4. **Shared expense contribution** of a person = the sum of USD amounts they paid.
5. **Beneficiary table ("Paid By", here called sponsor):** each person may be covered by one or more sponsors. A covered person's share is moved to the sponsors, split equally among them (for example, a child's share moves to the parent). No sponsor means the person covers themselves.
6. **Settlement balance** = amount paid − own share (only if self-covered) − the shares of everyone this person sponsors. Positive means the group owes this person money; negative means this person owes the group.

Two weaknesses the app fixes:

- The sheet finds a person with a text match (`REGEXMATCH`), so a person named "Aunt" also matches every row of "Aunt-in-law". The app stores people by ID, so this cannot happen.
- Rounding makes the balances not add up to exactly zero (`VN_20260111_15`: +267.02 and −267.03). The app keeps shares exact and gives each leftover cent to the person who lost the most in rounding, so balances always add up to zero.

What the sheet does by hand that the app will do automatically: the "Remarks" column, where the owner writes who must transfer how much to whom. The app shows a "who pays whom" list.

## 3. Decisions (recommended answers)

| # | Question | Recommendation | Why |
|---|---|---|---|
| D1 | Web app or phone app? | Web app only, mobile-first layout, installable to the phone home screen (a PWA: a website that can be added to the home screen like an app). | One code base, no app store, works on every phone and laptop. A native app adds nothing the MVP needs. |
| D2 | Who must log in? | Only people who record or view expenses. A trip **participant** is just a name and does not need an account. A participant can later be linked to an account. | In the real sheets, most participants (older relatives) would never log in. Requiring an account for every person would block the main use. |
| D3 | How do accounts get created? | Anyone can submit a sign-up request; the account stays inactive until the admin approves it. The admin can also create an account directly. | Both cases cost almost nothing with Django's built-in admin page. No email service needed in the MVP. |
| D4 | Roles | System level: **admin** (the owner) and **user**. Trip level: **owner** (who created the trip: edit trip settings, participants, members, rates, delete the trip) and **member** (add, edit and delete expenses; see everything). No "request write" flow. Every expense records who created and last changed it. | Trips are among people who trust each other; a request-and-approve flow adds work on every expense. The "created by / changed by" record gives accountability at almost no cost. A read-only **viewer** role is easy to add later. |
| D5 | Microservices? | No. One application (a modular monolith: one program, split into separate modules inside). Modules: `accounts`, `trips`, `expenses`, `settlement`. The `settlement` module is pure Python with no database code, so it can be tested alone or moved to its own service later. | Microservices solve problems of large teams and heavy traffic. Here they would add network calls, several deployments and data copied between services, for one developer and a few dozen users. Clear module borders give the same option to split later. |
| D6 | Tech stack | Python 3.14, Django 6.1 (built-in accounts, admin page, sessions, protection against forged form posts, database migrations), HTMX (small library: parts of the page update without writing JavaScript), PostgreSQL, Docker Compose, pytest. | Django ships the login, sign-up approval and admin screens that FastAPI would need to be built by hand. One language, one container for the app. FastAPI + React would mean two code bases and a hand-made login system. |
| D7 | Money | Store amounts as exact decimals (`Decimal`, 2 places) with the currency code; the settlement keeps shares as exact fractions and rounds to cents once, at the end. Each trip has a base currency (default USD) and a fixed manual rate for each other currency it uses. | Floating-point numbers lose cents. A fixed manual rate matches how the sheet works and how the group agrees on it. |
| D8 | Where it runs | The owner's personal server, behind Nginx with HTTPS. | Already available; no new cost. |

## 4. MVP scope (V1)

In:

1. Sign up (request), admin approval, log in, log out, change password.
2. Create a trip: name, country, dates, base currency, exchange rates.
3. Participants: add by name; optional link to an account; set sponsor(s).
4. Members: the trip owner adds account holders to the trip.
5. Expenses: add, edit, delete. Beneficiaries are checkboxes with "everyone" selected by default. Expense types: a fixed list (Transport, Accommodation, Food & drink, Medical, Translation, Shopping, Activities, Other). Custom types per trip are in the backlog.
6. Summary page: per person (paid, own share, sponsored shares, balance), totals by expense type, and the "who pays whom" list.
7. Mobile-first pages, English text, all text ready for translation.
8. Tests: the settlement module is tested against the 3 real sheets with numbers (names replaced by "Person A", "Person B" so no family data enters the public repo).

Out of the MVP (see `docs/ideas_backlog.md`): live exchange rates, receipt photos, import of old sheets, Khmer translation, export to Excel, unequal splits, notifications.

## 5. Build order

Each step ends with tests passing and a working app.

1. **Scaffold:** git repo, `/start-local-dev` (Django + PostgreSQL in Docker Compose), project status files.
2. **Settlement engine:** pure Python module + golden tests from the 3 real sheets. This is the heart of the app, so it is built and proven first.
3. **Data model + accounts:** User, Trip, TripMember, Participant, Sponsor, Expense, ExpenseBeneficiary, ExchangeRate; sign-up approval in the admin page.
4. **Trip and expense pages** (HTMX forms).
5. **Summary page** with "who pays whom".
6. **Permissions check:** a member of trip A cannot see or change trip B (tests for each page).
7. **Deploy** to the personal server; the owner records one real trip with it.
8. **Open-source release:** README, licence, `.env.example`, screenshots.

## 6. Answers from the owner

2026-10-25: "Yes to all" — D1 to D8 above are approved as written.
