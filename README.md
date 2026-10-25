# Share Expense

A simple, mobile-first web app for sharing costs on a group trip. One or two people record each expense as it happens; at the end, everyone sees how much they spent and **who must pay whom**.

It was built to replace a spreadsheet, and it gives the same numbers as that spreadsheet.

## Features

- **Trips** with a base currency (for example USD) and one fixed exchange rate for each other currency (for example 1 USD = 26,200 VND).
- **Participants are just names.** Grandma does not need an account to be part of a trip.
- **Sponsors:** a participant can be covered by one or more other people (a child by a parent). Their share moves to the sponsors, split equally.
- **Expenses:** date, payer, beneficiaries (everyone by default), type, description, amount and currency. The amount is split equally among the beneficiaries. Deleted expenses are kept in the database but left out of the totals.
- **Balances:** one list of each person's balance (paid minus share, with the shares they cover), each payer row showing whom to pay so the trip settles with the fewest payments, and a "Why?" view that splits your own balance into what you paid for others and what others paid for you.
- **Trip dashboard** (top of the Expenses tab): your balance, what the trip cost you, today's spending, the trip total, and spending by type and by day.
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
3. The user can now log in. The trip owner adds them to a trip on the trip's **People** page.

## Self-hosting

Production runs the app, Postgres and a [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) from one compose file, so the server opens no ports and Cloudflare provides HTTPS: `make up ENV=prod`. Steps and `.env.prod` values are in [`DOCKER_SETUP.md`](DOCKER_SETUP.md).

## Roadmap

The MVP plan is in [`docs/plan.md`](docs/plan.md). Ideas for later (receipt photos, unequal splits, live exchange rates, Khmer translation, Excel export and more) are in [`docs/ideas_backlog.md`](docs/ideas_backlog.md).

## License

MIT, see [`LICENSE`](LICENSE).
