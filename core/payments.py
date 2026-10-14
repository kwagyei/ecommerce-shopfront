"""Everything that talks to Stripe lives here, so views stay about HTTP and tests can
swap one function for a fake.

Checkout uses Stripe's hosted page: the server creates a Checkout Session and redirects
to it, so card details never touch this app and no Stripe JavaScript is needed.
"""

import stripe
from django.conf import settings

from core.cart import CartLine

CURRENCY = "sek"


def is_configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def stripe_client() -> stripe.StripeClient:
    return stripe.StripeClient(settings.STRIPE_SECRET_KEY)


def line_items(lines: list[CartLine]) -> list[dict]:
    """Amounts come from the catalog in minor units, which is also what Stripe expects.

    Each item carries its product id so the webhook can map a paid line back to the
    product whose stock it must decrement.
    """
    return [
        {
            "quantity": line.quantity,
            "price_data": {
                "currency": CURRENCY,
                "unit_amount": line.product.price_minor,
                "product_data": {
                    "name": line.product.name,
                    "metadata": {"product_id": str(line.product.pk)},
                },
            },
        }
        for line in lines
    ]


def create_checkout_session(lines: list[CartLine], success_url: str, cancel_url: str):
    return stripe_client().v1.checkout.sessions.create(
        params={
            "mode": "payment",
            "line_items": line_items(lines),
            # Stripe substitutes the real id on redirect; the braces must reach it unencoded.
            "success_url": f"{success_url}?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": cancel_url,
        }
    )


def retrieve_checkout_session(session_id: str):
    """The session as Stripe holds it now, with each line's product metadata expanded.

    Fetched rather than read from the event body so fulfilment always works from what
    Stripe actually charged, with the line items the event payload doesn't include.
    """
    return stripe_client().v1.checkout.sessions.retrieve(
        session_id, params={"expand": ["line_items.data.price.product"]}
    )
