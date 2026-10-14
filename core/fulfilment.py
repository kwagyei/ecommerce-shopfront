"""Turning Stripe webhook events into orders, exactly once.

Three guarantees, each with tests in test_webhook.py:

1. **An event is processed at most once.** Its id is inserted into a unique column in
   the same transaction as the order. A replay fails the insert and changes nothing,
   even if two deliveries of the same event race each other.
2. **Nothing is half-done.** Recording the event, creating the order and decrementing
   stock commit together or not at all. If anything fails, the endpoint returns 500,
   Stripe retries, and the retry finds a clean slate.
3. **Stock never goes negative.** Product rows are locked (SELECT ... FOR UPDATE, in pk
   order so two orders can't deadlock) before stock is checked and decremented. A paid
   order that can't be filled is kept and flagged for a refund instead.
"""

import logging
from collections import Counter

from django.db import IntegrityError, transaction
from django.db.models import F

from core import payments
from core.models import Order, OrderItem, Product, StripeEvent

logger = logging.getLogger(__name__)

FULFILLING_EVENTS = {"checkout.session.completed"}


def handle_event(event) -> str:
    """Process a verified Stripe event. Returns what happened, for logging.

    Raises on failure (for example Stripe being unreachable), leaving nothing recorded.
    """
    if StripeEvent.objects.filter(event_id=event.id).exists():
        return "duplicate"

    # Network call outside the transaction, so no row locks are held while waiting on it.
    session = None
    if event.type in FULFILLING_EVENTS:
        session = payments.retrieve_checkout_session(event.data.object.id)

    with transaction.atomic():
        try:
            with transaction.atomic():
                record = StripeEvent.objects.create(event_id=event.id, type=event.type)
        except IntegrityError:
            # A concurrent delivery of this same event committed first.
            return "duplicate"

        if session is None:
            return "ignored"
        if not _is_from_this_shop(session):
            logger.warning("Checkout Session %s has no product ids; not ours", session.id)
            return "not ours"
        if session.payment_status != "paid":
            # Delayed payment methods complete later; this shop only takes cards.
            logger.warning("Checkout Session %s completed unpaid", session.id)
            return "unpaid"

        order, created = _order_for(session)
        record.order = order
        record.save(update_fields=["order"])
        return "fulfilled" if created else "duplicate session"


def _is_from_this_shop(session) -> bool:
    """Our checkout tags every line with a product id; anything else was created elsewhere."""
    items = session.line_items.data
    return bool(items) and all("product_id" in item.price.product.metadata for item in items)


def _order_for(session) -> tuple[Order, bool]:
    existing = Order.objects.filter(stripe_checkout_session_id=session.id).first()
    if existing:
        return existing, False

    lines = [
        (
            int(item.price.product.metadata["product_id"]),
            item.description,
            item.price.unit_amount,
            item.quantity,
        )
        for item in session.line_items.data
    ]
    try:
        with transaction.atomic():
            order = Order.objects.create(
                stripe_checkout_session_id=session.id,
                email=getattr(session.customer_details, "email", "") or "",
                amount_total_minor=session.amount_total,
                currency=session.currency,
            )
    except IntegrityError:
        # Another event for the same session created the order a moment ago.
        return Order.objects.get(stripe_checkout_session_id=session.id), False

    wanted = Counter()
    for product_id, _, _, quantity in lines:
        wanted[product_id] += quantity
    locked = {
        p.pk: p for p in Product.objects.select_for_update().filter(pk__in=wanted).order_by("pk")
    }

    OrderItem.objects.bulk_create(
        OrderItem(
            order=order,
            product=locked.get(product_id),
            product_name=name,
            unit_price_minor=unit_amount,
            quantity=quantity,
        )
        for product_id, name, unit_amount, quantity in lines
    )

    short = [pid for pid, qty in wanted.items() if pid not in locked or locked[pid].stock < qty]
    if short:
        # All or nothing: a partly filled order is harder to put right than a refund.
        order.status = Order.Status.NEEDS_REFUND
        order.save(update_fields=["status"])
        logger.warning("Order %s paid but short of stock for products %s", order.pk, short)
    else:
        for product_id, quantity in wanted.items():
            Product.objects.filter(pk=product_id).update(stock=F("stock") - quantity)
    return order, True
