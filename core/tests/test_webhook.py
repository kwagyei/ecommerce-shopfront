"""The Stripe webhook: the only place orders are created.

Stripe delivers events at least once and retries until it gets a 2xx, so the same
event can arrive twice, and two events can describe the same payment. Every test here
signs its payload with the real Stripe scheme, so signature verification is exercised
for real; only the follow-up fetch of the Checkout Session is faked.
"""

import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
import stripe
from django.urls import reverse

from core import payments
from core.models import Order, Product, StripeEvent
from core.tests.factories import make_product

pytestmark = pytest.mark.django_db

SECRET = "whsec_test_secret"


def sign(payload: bytes, secret: str = SECRET, timestamp: int | None = None) -> str:
    """Stripe's signature scheme: HMAC-SHA256 of "<timestamp>.<payload>"."""
    timestamp = timestamp or int(time.time())
    signed = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def event_payload(event_id="evt_1", session_id="cs_test_1", type_="checkout.session.completed"):
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": type_,
            "data": {"object": {"id": session_id, "object": "checkout.session"}},
        }
    ).encode()


def deliver(client, payload: bytes, signature: str | None = None):
    headers = {} if signature == "" else {"HTTP_STRIPE_SIGNATURE": signature or sign(payload)}
    return client.post(
        reverse("stripe_webhook"), data=payload, content_type="application/json", **headers
    )


def paid_session(session_id, lines, payment_status="paid", email="buyer@example.com"):
    """What Stripe returns for a completed session with line items expanded."""
    return SimpleNamespace(
        id=session_id,
        payment_status=payment_status,
        amount_total=sum(p.price_minor * q for p, q in lines),
        currency="sek",
        customer_details=SimpleNamespace(email=email),
        line_items=SimpleNamespace(
            data=[
                SimpleNamespace(
                    description=p.name,
                    quantity=q,
                    price=SimpleNamespace(
                        unit_amount=p.price_minor,
                        product=SimpleNamespace(metadata={"product_id": str(p.pk)}),
                    ),
                )
                for p, q in lines
            ]
        ),
    )


@pytest.fixture
def stripe_sessions(monkeypatch, settings):
    """Session id -> session, standing in for the Stripe API. Counts fetches."""
    settings.STRIPE_WEBHOOK_SECRET = SECRET
    sessions: dict = {}
    sessions["_fetches"] = 0

    def retrieve(session_id):
        sessions["_fetches"] += 1
        return sessions[session_id]

    monkeypatch.setattr(payments, "retrieve_checkout_session", retrieve)
    return sessions


# -- idempotency: the reason this milestone exists ---------------------------


def test_a_replayed_event_creates_exactly_one_order(client, stripe_sessions):
    """Written first. Stripe may deliver the same event twice; the second delivery must
    be acknowledged without creating a second order or decrementing stock again."""
    kettle = make_product(stock=5)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 2)])
    payload = event_payload()

    first = deliver(client, payload)
    second = deliver(client, payload)

    assert (first.status_code, second.status_code) == (200, 200)
    assert Order.objects.count() == 1
    assert StripeEvent.objects.count() == 1
    kettle.refresh_from_db()
    assert kettle.stock == 3


def test_a_replay_does_not_even_refetch_the_session(client, stripe_sessions):
    kettle = make_product(stock=5)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 1)])
    payload = event_payload()
    deliver(client, payload)
    deliver(client, payload)
    assert stripe_sessions["_fetches"] == 1


def test_two_different_events_for_one_payment_create_one_order(client, stripe_sessions):
    """Distinct event ids can describe the same Checkout Session, so the order is unique
    on the session id too, not only on the event id."""
    kettle = make_product(stock=5)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 1)])

    deliver(client, event_payload(event_id="evt_1"))
    deliver(client, event_payload(event_id="evt_2"))

    assert Order.objects.count() == 1
    assert StripeEvent.objects.count() == 2
    kettle.refresh_from_db()
    assert kettle.stock == 4


def test_a_failure_mid_fulfilment_leaves_nothing_behind_so_the_retry_works(
    client, stripe_sessions, monkeypatch
):
    """If recording the event committed before the order did, a crash in between would
    make Stripe's retry look like a duplicate and the order would be lost for good."""
    kettle = make_product(stock=5)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 1)])
    real_retrieve = payments.retrieve_checkout_session

    def flaky(session_id):
        raise stripe.APIConnectionError("network down")

    monkeypatch.setattr(payments, "retrieve_checkout_session", flaky)
    assert deliver(client, event_payload()).status_code == 500
    assert StripeEvent.objects.count() == 0

    monkeypatch.setattr(payments, "retrieve_checkout_session", real_retrieve)
    assert deliver(client, event_payload()).status_code == 200
    assert Order.objects.count() == 1


# -- signature verification -------------------------------------------------


def test_an_unsigned_request_is_rejected(client, stripe_sessions):
    make_product(stock=5)
    assert deliver(client, event_payload(), signature="").status_code == 400
    assert StripeEvent.objects.count() == 0


def test_a_request_signed_with_another_secret_is_rejected(client, stripe_sessions):
    payload = event_payload()
    response = deliver(client, payload, signature=sign(payload, secret="whsec_attacker"))
    assert response.status_code == 400
    assert Order.objects.count() == 0


def test_a_tampered_payload_is_rejected(client, stripe_sessions):
    signature = sign(event_payload(session_id="cs_test_1"))
    response = deliver(client, event_payload(session_id="cs_test_forged"), signature=signature)
    assert response.status_code == 400


def test_an_old_signature_is_rejected_so_captured_requests_cannot_be_replayed(
    client, stripe_sessions
):
    payload = event_payload()
    stale = sign(payload, timestamp=int(time.time()) - 3600)
    assert deliver(client, payload, signature=stale).status_code == 400


def test_without_a_signing_secret_the_endpoint_refuses_rather_than_trusting(client, settings):
    settings.STRIPE_WEBHOOK_SECRET = ""
    payload = event_payload()
    assert deliver(client, payload, signature=sign(payload)).status_code == 500
    assert StripeEvent.objects.count() == 0


def test_the_webhook_needs_no_csrf_token_because_the_signature_is_the_check(stripe_sessions):
    from django.test import Client

    kettle = make_product(stock=5)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 1)])
    response = deliver(Client(enforce_csrf_checks=True), event_payload())
    assert response.status_code == 200


def test_the_webhook_rejects_get(client):
    assert client.get(reverse("stripe_webhook")).status_code == 405


# -- the order itself -------------------------------------------------------


def test_the_order_records_what_was_paid(client, stripe_sessions):
    kettle = make_product(stock=5, price_minor=44900)
    lamp = make_product(slug="lamp", name="Brass lamp", stock=2, price_minor=119900)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 2), (lamp, 1)])

    deliver(client, event_payload())

    order = Order.objects.get()
    assert order.stripe_checkout_session_id == "cs_test_1"
    assert order.email == "buyer@example.com"
    assert order.amount_total_minor == 2 * 44900 + 119900
    assert order.currency == "sek"
    assert order.status == Order.Status.PAID
    assert {(i.product_name, i.unit_price_minor, i.quantity) for i in order.items.all()} == {
        ("Enamel kettle", 44900, 2),
        ("Brass lamp", 119900, 1),
    }
    assert StripeEvent.objects.get().order == order


def test_order_lines_keep_the_price_paid_after_the_catalog_changes(client, stripe_sessions):
    kettle = make_product(stock=5, price_minor=44900)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 1)])
    deliver(client, event_payload())

    Product.objects.filter(pk=kettle.pk).update(price_minor=1, name="Renamed")

    item = Order.objects.get().items.get()
    assert (item.product_name, item.unit_price_minor) == ("Enamel kettle", 44900)


def test_stock_is_decremented_for_every_line(client, stripe_sessions):
    kettle = make_product(stock=5)
    lamp = make_product(slug="lamp", name="Brass lamp", stock=2)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 2), (lamp, 2)])
    deliver(client, event_payload())
    kettle.refresh_from_db()
    lamp.refresh_from_db()
    assert (kettle.stock, lamp.stock) == (3, 0)


def test_a_payment_for_stock_that_sold_out_meanwhile_is_flagged_not_oversold(
    client, stripe_sessions
):
    """Stock isn't reserved during checkout, so two customers can both pay for the last
    unit. The second order is kept (the money was taken) but flagged for a refund, and
    stock never goes negative."""
    kettle = make_product(stock=1)
    lamp = make_product(slug="lamp", name="Brass lamp", stock=5)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 1)])
    stripe_sessions["cs_test_2"] = paid_session("cs_test_2", [(kettle, 1), (lamp, 1)])

    deliver(client, event_payload(event_id="evt_1", session_id="cs_test_1"))
    response = deliver(client, event_payload(event_id="evt_2", session_id="cs_test_2"))

    assert response.status_code == 200
    second = Order.objects.get(stripe_checkout_session_id="cs_test_2")
    assert second.status == Order.Status.NEEDS_REFUND
    kettle.refresh_from_db()
    lamp.refresh_from_db()
    assert (kettle.stock, lamp.stock) == (0, 5), "all or nothing: no partial decrement"


def test_a_product_deleted_since_checkout_flags_the_order(client, stripe_sessions):
    kettle = make_product(stock=5)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 1)])
    kettle.delete()
    deliver(client, event_payload())
    order = Order.objects.get()
    assert order.status == Order.Status.NEEDS_REFUND
    assert order.items.get().product is None


def test_an_unpaid_session_creates_no_order(client, stripe_sessions):
    kettle = make_product(stock=5)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 1)], "unpaid")
    assert deliver(client, event_payload()).status_code == 200
    assert Order.objects.count() == 0
    kettle.refresh_from_db()
    assert kettle.stock == 5


def test_other_event_types_are_recorded_but_change_nothing(client, stripe_sessions):
    response = deliver(client, event_payload(type_="payment_intent.created"))
    assert response.status_code == 200
    assert StripeEvent.objects.get().type == "payment_intent.created"
    assert Order.objects.count() == 0
    assert stripe_sessions["_fetches"] == 0


def test_a_paid_session_from_outside_this_shop_is_recorded_and_ignored(client, stripe_sessions):
    """Sessions created elsewhere on the account (or by `stripe trigger`) carry no
    product_id. Crashing on them would make Stripe retry the event for days."""
    foreign = paid_session("cs_test_1", [])
    foreign.line_items.data = [
        SimpleNamespace(
            description="T-shirt",
            quantity=1,
            price=SimpleNamespace(unit_amount=2000, product=SimpleNamespace(metadata={})),
        )
    ]
    stripe_sessions["cs_test_1"] = foreign

    assert deliver(client, event_payload()).status_code == 200
    assert Order.objects.count() == 0
    assert StripeEvent.objects.count() == 1


def test_staff_can_see_webhook_orders_in_the_admin(admin_client, client, stripe_sessions):
    kettle = make_product(stock=5)
    stripe_sessions["cs_test_1"] = paid_session("cs_test_1", [(kettle, 2)])
    deliver(client, event_payload())
    order = Order.objects.get()

    assert admin_client.get(reverse("admin:core_order_changelist")).status_code == 200
    page = admin_client.get(reverse("admin:core_order_change", args=[order.pk]))
    assert b"Enamel kettle" in page.content
    assert admin_client.get(reverse("admin:core_order_add")).status_code == 403
