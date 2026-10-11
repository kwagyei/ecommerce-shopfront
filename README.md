# shopfront

A small Django store with Stripe test-mode checkout and an admin panel.

**Status:** Milestone 0 — skeleton deployed, CI green. No catalog yet.

## Why this exists

Most portfolio stores stop at a product grid and a fake checkout. This one is built
around the part real payment systems get wrong: **webhook handling that stays correct
when Stripe delivers the same event twice.** See [Milestones](#milestones).

Payments run in **Stripe test mode only**. The app never handles card details — checkout
happens on Stripe's hosted page.

## Running it locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # defaults are fine for local work
python manage.py migrate
python manage.py runserver
```

The app uses SQLite locally and Postgres wherever `DATABASE_URL` is set.

### Tests and linting

```bash
pytest
ruff check .
```

Both run in CI on every pull request, along with Django's `check --deploy`.

## Milestones

| # | Scope | Status |
|---|---|---|
| 0 | Skeleton, CI, deployment, health check | ✅ |
| 1 | Catalog: products, categories, admin, seed data | |
| 2 | Session cart: add, update, remove, server-side totals | |
| 3 | Stripe Checkout session | |
| 4 | Webhook: signature verification, idempotent fulfilment, stock decrement | |
| 5 | Admin: order management, shipping actions, event audit | |
| 6 | Demo polish: screenshots, seeded data, test-card instructions | |

## Deliberately out of scope

User accounts, reviews, wishlists, coupons, search, multi-currency, shipping
calculations, and email receipts (Stripe sends those). Guest checkout only.

## Stack

Django 5 · PostgreSQL (Neon) · Stripe Checkout · Whitenoise · Gunicorn · pytest · ruff

## Licence

MIT — see [LICENSE](LICENSE).
