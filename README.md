# Share Expense

A simple, mobile-first web app for sharing costs on a group trip. One or two people record each expense as it happens; at the end, everyone sees how much they spent and who is owed or owes; the travellers settle between themselves, and the owner marks the trip as settled.

It was built to replace a spreadsheet, and it gives the same numbers as that spreadsheet.

## Features

- **Trips** with a base currency (for example USD) and one fixed exchange rate for each other currency (for example 1 USD = 26,200 VND).
- **Travelers are just names.** Grandma does not need an account to be part of a trip.
- **Covering:** a traveler can be covered by one or more travelers who pay for themselves (the **Everyone** chip ticks them all). The covered traveler's share is split equally among them. Balances and Stats show each traveler's own share, plus "Covered by … +amount" or "Covers … −amount", so every row adds up to its balance.
- **Expenses:** date, payer, beneficiaries (everyone by default), type, description, amount and currency. The amount is split equally among the beneficiaries. Deleted expenses are kept in the database but left out of the totals.
- **Balances:** each person's balance (is owed / owes / nothing owed), with the paid and share amounts that make it up, and a breakdown of your own balance.
- **Mark as settled:** once the travellers have paid each other back (in whatever way they choose), the owner marks the trip as settled after a confirmation. The trip then shows **Settled** with the date, and its expenses, people and rates are locked. The owner can reopen it.
- **AI (DeepSeek, optional):** **Add expense → Add with AI** fills the form from one sentence ("Maly paid 40,000 VND for drinks for Maly and Sophorn yesterday"). It fills only what the sentence states, matches each name to exactly one traveler, and lists what is still missing; nothing is saved until you press Save. The ✨ button in the Description box suggests a better wording, in the style of the trip's other descriptions. Sent to DeepSeek: that sentence or description, the trip's traveler and type names, and up to 20 earlier descriptions. Without `DEEPSEEK_API_KEY` both are off.
- **Types:** every trip starts with 8 types (Transport, Food & drink, ...). Travelers add their own with **+ Add type** on the expense form and pick an icon; a long press on a type shows a minus badge to remove it (only when no expense uses it) and lets you rename it.
- **Expenses list:** days fold into one line each (date, count, total), with the newest day open; a search box finds expenses by description, payer, type or amount; a long press on a card lets you drag it up or down within its day.
- **Stats:** a page with filters (traveler, type, date range), totals by type and by day, a traveler's share of each expense in its own currency, and a download of the filtered list as CSV or Excel.
- **Mobile navigation:** a fixed bottom tab bar (Expenses, Balances, Stats, Travelers) and one floating button for the main action of the tab.
- **Fast repeat visits:** a service worker shows the last copy of a page at once, then fetches the fresh copy and swaps it in if anything changed. Any save, delete, login or logout clears the stored pages, and pages with a one-time message are never stored. Static files have content-hashed names and are cached for a year.
- **Long lists** show about 25 rows, then a "Load more" button; a page never splits a day, so day totals match their rows.
- **Exact money:** amounts are stored as decimals, shares are kept as exact fractions, and balances are rounded once so they always add up to exactly zero.
- **Accounts:** anyone can request an account; it stays inactive until the admin approves it in the admin page. The admin can also create accounts directly. Login is locked for 1 hour after 5 wrong passwords.
- **Roles per trip:** the **owner** manages people, members, rates and the trip itself; a **member** adds, edits and deletes expenses. Every expense records who created and who last changed it.

## How the money is calculated

1. Convert each expense to the base currency: `round(amount / rate, 2)`.
2. Split it equally among its beneficiaries.
3. Move each covered person's share to their sponsors, split equally.
4. `balance = paid − shares you are responsible for`. Positive means the group owes you; negative means you owe the group.

The calculation lives in `apps/settlement/engine.py`. It uses no database, and it is tested against three real trips (names removed) in `tests/test_settlement_engine.py`.

## Stack

- Python 3.14, Django 6.1, HTMX 2, own CSS (no framework), Lucide icons
- PostgreSQL 18
- Docker (development and production targets), gunicorn, whitenoise
- pytest, ruff, GitHub Actions

## Run it locally

Prerequisites: Docker with Compose v2, `make`, and an [nginx-proxy](https://github.com/nginx-proxy/nginx-proxy) container on an external Docker network called `proxy-network`. The dev compose file publishes no ports; nginx-proxy routes traffic by host name.

```bash
make up                 # first run copies .env.example to .env
make superuser          # your admin account
sudo sh -c 'echo "127.0.0.1 share-expense.local" >> /etc/hosts'
```

Open http://share-expense.local and log in.

| Command | What it does |
|---|---|
| `make up` / `make down` | Start / stop every service (add `ENV=prod` for production) |
| `make logs` | Follow the web logs |
| `make test` | Run all tests against the real Postgres |
| `make lint` | ruff check and format check |
| `make migrations` / `make migrate` | Create / apply database migrations |

## Approving accounts

1. A new user opens **Request an account**, then waits.
2. The admin opens `/admin/` → Users, ticks the request, and chooses **Approve selected sign-up requests**.
3. The user can now log in. The trip owner adds them to a trip on the trip's **Travelers** page, with the **+** button → **Add account**.

**Sign in with Google.** With `GOOGLE_CLIENT_ID` set, the login page shows **Continue with Google**. An approved account whose email matches the Google email signs in; anyone else's first Google sign-in creates an account that waits for the admin's approval, like a request from the sign-up page. A signed-in user can connect Google from the account menu (**Google sign-in**) and from then on sign in without the password.

## Self-hosting

Production runs the app, Postgres and a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) from one compose file, so the server opens no ports and Cloudflare provides HTTPS: `make up ENV=prod`. Steps and `.env.prod` values are in [`DOCKER_SETUP.md`](DOCKER_SETUP.md).

## Roadmap

The MVP plan is in [`docs/plan.md`](docs/plan.md). Ideas for later (receipt photos, unequal splits, live exchange rates, Khmer translation, Excel export and more) are in [`docs/ideas_backlog.md`](docs/ideas_backlog.md).

## License

MIT, see [`LICENSE`](LICENSE).
