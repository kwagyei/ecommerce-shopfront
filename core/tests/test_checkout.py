"""Checkout: the cart becomes a Stripe Checkout Session. Stripe itself is faked; no test
reaches the network (conftest.py fails any that tries)."""

from types import SimpleNamespace

import pytest
import stripe
from django.urls import reverse

from core import payments
from core.models import Product
from core.tests.factories import make_product

pytestmark = pytest.mark.django_db


class FakeStripe:
    """Records what would have been sent to Stripe and returns a plausible session."""

    def __init__(self, error: Exception | None = None):
        self.calls: list[dict] = []
        self.error = error
        self.v1 = SimpleNamespace(checkout=SimpleNamespace(sessions=self))

    def create(self, params):
        self.calls.append(params)
        if self.error:
            raise self.error
        return SimpleNamespace(
            id="cs_test_123", url="https://checkout.stripe.com/c/pay/cs_test_123"
        )


@pytest.fixture
def fake_stripe(monkeypatch, settings):
    settings.STRIPE_SECRET_KEY = "sk_test_fake"
    fake = FakeStripe()
    monkeypatch.setattr(payments, "stripe_client", lambda: fake)
    return fake


def add(client, product, quantity=1):
    client.post(reverse("catalog:cart_add", args=[product.slug]), {"quantity": quantity})


def checkout(client, **kwargs):
    return client.post(reverse("catalog:checkout"), **kwargs)


def test_checkout_sends_the_customer_to_stripe(client, fake_stripe):
    add(client, make_product(stock=5), 2)
    response = checkout(client)
    assert response.status_code == 303
    assert response["Location"] == "https://checkout.stripe.com/c/pay/cs_test_123"


def test_line_items_use_database_prices_in_minor_units(client, fake_stripe):
    """The amount charged comes from the catalog, never from anything the browser sent."""
    product = make_product(price_minor=44900, stock=5)
    add(client, product, 2)
    checkout(client, data={"price_minor": 1, "unit_amount": 1})

    [params] = fake_stripe.calls
    assert params["mode"] == "payment"
    [item] = params["line_items"]
    assert item["quantity"] == 2
    assert item["price_data"]["currency"] == "sek"
    assert item["price_data"]["unit_amount"] == 44900
    assert item["price_data"]["product_data"]["name"] == "Enamel kettle"


def test_line_items_carry_the_product_id_for_the_webhook(client, fake_stripe):
    product = make_product(stock=5)
    add(client, product)
    checkout(client)
    [item] = fake_stripe.calls[0]["line_items"]
    assert item["price_data"]["product_data"]["metadata"] == {"product_id": str(product.pk)}


def test_return_urls_are_absolute_and_carry_the_session_id_placeholder(client, fake_stripe):
    add(client, make_product(stock=5))
    checkout(client)
    params = fake_stripe.calls[0]
    assert params["success_url"] == (
        "http://testserver/checkout/success/?session_id={CHECKOUT_SESSION_ID}"
    )
    assert params["cancel_url"] == "http://testserver/checkout/cancel/"


def test_an_empty_cart_never_reaches_stripe(client, fake_stripe):
    response = checkout(client, follow=True)
    assert fake_stripe.calls == []
    assert b"Your cart is empty" in response.content


def test_a_cart_that_changed_goes_back_for_review_instead_of_to_payment(client, fake_stripe):
    """The customer must see what they're paying for. If stock moved since the cart was
    last shown, they review the corrected cart rather than paying for a surprise."""
    product = make_product(stock=5)
    add(client, product, 4)
    Product.objects.filter(pk=product.pk).update(stock=2)

    response = checkout(client, follow=True)

    assert fake_stripe.calls == []
    assert b"Only 2 of Enamel kettle left" in response.content


def test_a_withdrawn_product_is_removed_before_payment(client, fake_stripe):
    kept = make_product(stock=5)
    withdrawn = make_product(slug="lamp", name="Lamp", stock=5)
    add(client, kept)
    add(client, withdrawn)
    Product.objects.filter(pk=withdrawn.pk).update(is_active=False)

    checkout(client)  # reconciles and bounces to the cart
    checkout(client)  # now goes through with what's left

    [params] = fake_stripe.calls
    assert [i["price_data"]["product_data"]["name"] for i in params["line_items"]] == [
        "Enamel kettle"
    ]


def test_a_stripe_failure_keeps_the_cart_and_says_so(client, monkeypatch, settings):
    settings.STRIPE_SECRET_KEY = "sk_test_fake"
    fake = FakeStripe(error=stripe.APIConnectionError("network down"))
    monkeypatch.setattr(payments, "stripe_client", lambda: fake)
    add(client, make_product(stock=5), 2)

    response = checkout(client, follow=True)

    assert b"couldn&#x27;t reach the payment provider" in response.content
    assert b'<span class="count">2</span>' in response.content


def test_checkout_without_stripe_keys_is_disabled_not_broken(client, settings):
    settings.STRIPE_SECRET_KEY = ""
    add(client, make_product(stock=5))
    response = checkout(client, follow=True)
    assert response.status_code == 200
    assert b"Checkout isn&#x27;t available" in response.content


def test_checkout_rejects_get(client):
    assert client.get(reverse("catalog:checkout")).status_code == 405


def test_checkout_requires_a_csrf_token(fake_stripe):
    from django.test import Client

    csrf_client = Client(enforce_csrf_checks=True)
    assert csrf_client.post(reverse("catalog:checkout")).status_code == 403
    assert fake_stripe.calls == []


def test_returning_from_a_paid_checkout_clears_the_cart(client, fake_stripe):
    add(client, make_product(stock=5), 2)
    checkout(client)
    response = client.get(reverse("catalog:checkout_success"), {"session_id": "cs_test_123"})
    assert b"Thank you" in response.content
    assert b"Your cart is empty" in client.get(reverse("catalog:cart")).content


def test_a_success_url_for_someone_elses_session_does_not_clear_the_cart(client, fake_stripe):
    """The success URL is guessable, so it only acts on the session this browser started."""
    add(client, make_product(stock=5), 2)
    checkout(client)
    client.get(reverse("catalog:checkout_success"), {"session_id": "cs_test_other"})
    assert b'<span class="count">2</span>' in client.get(reverse("catalog:cart")).content


def test_the_success_page_does_not_create_a_session_for_strangers(client):
    from django.contrib.sessions.models import Session

    client.get(reverse("catalog:checkout_success"), {"session_id": "cs_test_123"})
    assert Session.objects.count() == 0


def test_cancelling_returns_to_an_unchanged_cart(client, fake_stripe):
    add(client, make_product(stock=5), 2)
    checkout(client)
    response = client.get(reverse("catalog:checkout_cancel"), follow=True)
    assert b"Checkout cancelled" in response.content
    assert b'<span class="count">2</span>' in response.content


def test_the_cart_offers_checkout_and_names_the_test_card(client):
    add(client, make_product(stock=5))
    content = client.get(reverse("catalog:cart")).content
    assert reverse("catalog:checkout").encode() in content
    assert b"4242 4242 4242 4242" in content
