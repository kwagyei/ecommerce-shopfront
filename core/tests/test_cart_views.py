"""The cart through the HTTP surface: forms, redirects, messages and tamper resistance."""
import pytest
from django.urls import reverse

from core.models import Product
from core.tests.factories import make_product

pytestmark = pytest.mark.django_db


def add(client, product, quantity=1):
    return client.post(
        reverse("catalog:cart_add", args=[product.slug]), {"quantity": quantity}, follow=True
    )


def test_adding_a_product_puts_it_in_the_cart(client):
    product = make_product(stock=5)
    response = add(client, product, 2)
    assert response.status_code == 200
    assert b"Enamel kettle" in response.content
    assert b"added to your cart" in response.content


def test_the_header_shows_how_many_units_are_held(client):
    add(client, make_product(stock=9), 3)
    assert b'<span class="count">3</span>' in client.get(reverse("catalog:product_list")).content


def test_cart_shows_the_line_total_and_the_cart_total(client):
    product = make_product(price_minor=19999, stock=5)
    add(client, product, 2)
    content = client.get(reverse("catalog:cart")).content
    assert b"399.98 kr" in content


def test_adding_more_than_stock_clamps_and_says_so(client):
    product = make_product(stock=2)
    response = add(client, product, 10)
    assert b"Only 2" in response.content


def test_adding_an_out_of_stock_product_is_refused(client):
    product = make_product(stock=0)
    response = add(client, product, 1)
    assert b"out of stock" in response.content
    assert b"Your cart is empty" in client.get(reverse("catalog:cart")).content


def test_updating_quantity_changes_the_line(client):
    product = make_product(stock=5)
    add(client, product, 1)
    client.post(reverse("catalog:cart_update", args=[product.slug]), {"quantity": 4}, follow=True)
    assert b'value="4"' in client.get(reverse("catalog:cart")).content


def test_updating_to_zero_removes_the_line(client):
    product = make_product(stock=5)
    add(client, product, 2)
    response = client.post(
        reverse("catalog:cart_update", args=[product.slug]), {"quantity": 0}, follow=True
    )
    assert b"removed from your cart" in response.content
    assert b"Your cart is empty" in response.content


def test_removing_the_last_line_leaves_an_empty_cart_not_an_error(client):
    product = make_product(stock=5)
    add(client, product, 1)
    response = client.post(reverse("catalog:cart_remove", args=[product.slug]), follow=True)
    assert response.status_code == 200
    assert b"Your cart is empty" in response.content


def test_rubbish_quantities_do_not_crash_the_cart(client):
    product = make_product(stock=5)
    response = client.post(
        reverse("catalog:cart_add", args=[product.slug]), {"quantity": "; DROP TABLE"}, follow=True
    )
    assert response.status_code == 200
    assert b"added to your cart" in response.content  # fell back to a quantity of one


def test_cart_endpoints_reject_get(client):
    product = make_product(stock=5)
    for name in ["catalog:cart_add", "catalog:cart_update", "catalog:cart_remove"]:
        response = client.get(reverse(name, args=[product.slug]))
        assert response.status_code == 405, name


def test_cart_actions_require_a_csrf_token():
    """Without this, any site could add to a visitor's cart on their behalf."""
    from django.test import Client

    csrf_client = Client(enforce_csrf_checks=True)
    product = make_product(stock=5)
    response = csrf_client.post(reverse("catalog:cart_add", args=[product.slug]), {"quantity": 1})
    assert response.status_code == 403


def test_a_product_that_sells_out_while_in_the_cart_is_reported(client):
    product = make_product(stock=3)
    add(client, product, 3)
    Product.objects.filter(pk=product.pk).update(stock=0)
    response = client.get(reverse("catalog:cart"))
    assert b"sold out" in response.content
    assert b"Your cart is empty" in response.content


def test_carts_do_not_leak_between_sessions(client):
    from django.test import Client

    product = make_product(stock=5)
    add(client, product, 2)
    assert b"Your cart is empty" in Client().get(reverse("catalog:cart")).content


def test_browsing_does_not_create_a_session(client, django_assert_num_queries):
    """Regression: the cart used to call session.setdefault on construction, which
    marked the session dirty on every request and wrote a session row for every
    visitor — crawlers included — before anyone added anything."""
    from django.contrib.sessions.models import Session

    make_product(stock=5)
    client.get(reverse("catalog:product_list"))
    client.get(reverse("catalog:product", args=["enamel-kettle"]))
    assert Session.objects.count() == 0


def test_adding_to_the_cart_does_create_a_session(client):
    """The flip side: once there's something to remember, it must be persisted."""
    from django.contrib.sessions.models import Session

    add(client, make_product(stock=5), 1)
    assert Session.objects.count() == 1
