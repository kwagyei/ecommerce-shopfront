"""Unit tests for the cart itself, independent of any view."""

from decimal import Decimal

import pytest

from core.cart import MAX_QUANTITY_PER_LINE, Cart
from core.models import Product
from core.tests.factories import make_product

pytestmark = pytest.mark.django_db


@pytest.fixture
def cart(rf):
    """A cart over a real session, without going through a view."""
    from django.contrib.sessions.middleware import SessionMiddleware

    request = rf.get("/")
    SessionMiddleware(lambda r: None).process_request(request)
    return Cart(request)


def test_a_new_cart_is_empty(cart):
    assert len(cart) == 0
    assert cart.lines() == []
    assert cart.total_minor == 0
    assert bool(cart) is False


def test_adding_accumulates_quantity(cart):
    product = make_product(stock=10)
    cart.add(product, 2)
    cart.add(product, 3)
    assert len(cart) == 5


def test_quantity_is_clamped_to_available_stock(cart):
    product = make_product(stock=3)
    assert cart.add(product, 50) == 3
    assert len(cart) == 3


def test_quantity_is_clamped_to_the_per_line_maximum(cart):
    product = make_product(stock=10_000)
    assert cart.add(product, 500) == MAX_QUANTITY_PER_LINE


def test_setting_quantity_to_zero_removes_the_line(cart):
    product = make_product(stock=5)
    cart.add(product, 2)
    cart.set_quantity(product, 0)
    assert cart.lines() == []


def test_negative_quantities_remove_rather_than_go_negative(cart):
    product = make_product(stock=5)
    cart.add(product, 2)
    assert cart.set_quantity(product, -5) == 0
    assert len(cart) == 0


def test_totals_are_summed_in_minor_units(cart):
    """199.99 and 449.00 are exactly the amounts floating point would get wrong."""
    cheap = make_product(slug="cheap", price_minor=19999, stock=10)
    pricey = make_product(slug="pricey", price_minor=44900, stock=10)
    cart.add(cheap, 2)
    cart.add(pricey, 1)
    assert cart.total_minor == 84898
    assert cart.total == Decimal("848.98")


def test_price_is_read_from_the_database_not_the_session(cart):
    """A price change in the admin must reach carts that already hold the product."""
    product = make_product(price_minor=10000, stock=5)
    cart.add(product, 1)
    Product.objects.filter(pk=product.pk).update(price_minor=12500)
    assert cart.total == Decimal("125.00")


def test_a_tampered_session_cannot_invent_products(cart):
    cart._items["999999"] = 5
    cart._items["not-a-number"] = 3
    assert cart.lines() == []
    assert cart.total_minor == 0


def test_withdrawn_products_disappear_from_the_cart(cart):
    product = make_product(stock=5)
    cart.add(product, 1)
    Product.objects.filter(pk=product.pk).update(is_active=False)
    assert cart.lines() == []


def test_reconcile_clamps_a_line_that_outgrew_its_stock(cart):
    product = make_product(stock=5)
    cart.add(product, 5)
    Product.objects.filter(pk=product.pk).update(stock=2)
    notes = cart.reconcile()
    assert len(cart) == 2
    assert any("Only 2" in note for note in notes)


def test_reconcile_drops_a_product_that_sold_out(cart):
    product = make_product(stock=5)
    cart.add(product, 3)
    Product.objects.filter(pk=product.pk).update(stock=0)
    notes = cart.reconcile()
    assert cart.lines() == []
    assert any("sold out" in note for note in notes)


def test_reconcile_drops_a_product_that_was_deleted(cart):
    product = make_product(stock=5)
    cart.add(product, 1)
    Product.objects.filter(pk=product.pk).delete()
    notes = cart.reconcile()
    assert cart.lines() == []
    assert any("no longer available" in note for note in notes)


def test_reconcile_says_nothing_when_nothing_changed(cart):
    cart.add(make_product(stock=5), 2)
    assert cart.reconcile() == []


def test_clear_empties_the_cart(cart):
    cart.add(make_product(stock=5), 2)
    cart.clear()
    assert len(cart) == 0


def test_reading_the_cart_costs_one_query_whatever_its_size(cart, django_assert_num_queries):
    for i in range(8):
        cart.add(make_product(slug=f"product-{i}", stock=5), 1)
    with django_assert_num_queries(1):
        cart.lines()
