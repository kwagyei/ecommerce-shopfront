# shopfront

A small Django store with Stripe test-mode checkout and an admin panel.

**Status:** Milestone 2 — catalog and a working cart. Checkout next.

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
python manage.py seed          # twelve demo products across three categories
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
| 1 | Catalog: products, categories, admin, seed data | ✅ |
| 2 | Session cart: add, update, remove, server-side totals | ✅ |
| 3 | Stripe Checkout session | |
| 4 | Webhook: signature verification, idempotent fulfilment, stock decrement | |
| 5 | Admin: order management, shipping actions, event audit | |
| 6 | Demo polish: screenshots, seeded data, test-card instructions | |

## Design decisions

**Money is stored as integer minor units** (öre), never floats. `0.1 + 0.2 != 0.3` in
binary floating point, and a rounding error per line item compounds across a cart. Totals
are summed in minor units and converted to a decimal once, for display only.

**Product images are static files, not uploads.** Free hosting has an ephemeral
filesystem — anything uploaded disappears on the next redeploy. The `Product.image` field
holds a path under `static/`, so images survive deploys and cost nothing to serve. Real
uploads would need object storage, which would mean a paid account.

**The session stores product ids and quantities, nothing else.** Prices are read from
the database every time the cart is rendered. A session cookie is client-visible data, so
a price held there would be a discount waiting to be forged — and reading live means an
admin price change reaches carts that already hold the product.

**The cart reconciles against the catalog before it is shown.** A cart can sit in a
session for weeks, during which a product can be withdrawn, deleted or sold out. Rather
than failing at checkout, the cart clamps quantities to available stock, drops what can no
longer be sold, and says what it changed.

**Browsing creates no session.** The cart deliberately does not touch the session until
something is added. An earlier version called `session.setdefault` on construction, which
marked the session dirty on every request and wrote a session row for every visitor,
crawlers included. There's a regression test for it.

**Plain forms, not HTMX.** The cart works with JavaScript disabled and depends on no
third-party script at runtime. HTMX can be layered on later as enhancement; starting with
it would have meant a CDN dependency for a demo that doesn't need one.

**Withdrawn products return 404, not 403.** A 403 confirms the product exists; a 404
doesn't leak that an item was ever listed.

**The category nav comes from a context processor.** It was built per-view at first and
promptly went missing from the product detail page. There's a regression test for it now.

## Deliberately out of scope

User accounts, reviews, wishlists, coupons, search, multi-currency, shipping
calculations, and email receipts (Stripe sends those). Guest checkout only.

## Stack

Django 5 · PostgreSQL (Neon) · Stripe Checkout · Whitenoise · Gunicorn · pytest · ruff

## Licence

MIT — see [LICENSE](LICENSE).
