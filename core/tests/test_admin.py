"""The admin as staff use it: orders are read-only apart from guarded status changes,
and stock is adjusted by a delta so a stale form can't undo a sale."""

import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from core.models import Order, Product, StripeEvent
from core.tests.factories import default_category, make_order, make_product

pytestmark = pytest.mark.django_db

ORDERS = reverse("admin:core_order_changelist")


def run_action(client, action: str, *orders):
    return client.post(
        ORDERS,
        {"action": action, "_selected_action": [o.pk for o in orders]},
        follow=True,
    )


# -- order status changes -------------------------------------------------------


def test_mark_shipped_moves_paid_orders_and_stamps_the_time(admin_client):
    order = make_order()
    response = run_action(admin_client, "mark_shipped", order)
    order.refresh_from_db()
    assert order.status == Order.Status.SHIPPED
    assert order.shipped_at is not None
    assert b"1 order marked as shipped" in response.content


def test_mark_shipped_never_ships_an_order_that_needs_a_refund(admin_client):
    """Shipping stock the shop doesn't have would turn one problem into two."""
    paid = make_order(session_id="cs_a")
    short = make_order(status="needs_refund", session_id="cs_b")
    shipped = make_order(status="shipped", session_id="cs_c")

    response = run_action(admin_client, "mark_shipped", paid, short, shipped)

    short.refresh_from_db()
    assert short.status == Order.Status.NEEDS_REFUND
    assert short.shipped_at is None
    assert b"1 order marked as shipped" in response.content
    assert b"2 skipped" in response.content


def test_mark_refunded_only_closes_orders_that_need_a_refund(admin_client):
    paid = make_order(session_id="cs_a")
    short = make_order(status="needs_refund", session_id="cs_b")

    run_action(admin_client, "mark_refunded", paid, short)

    paid.refresh_from_db()
    short.refresh_from_db()
    assert (paid.status, short.status) == (Order.Status.PAID, Order.Status.REFUNDED)


def test_view_only_staff_can_see_orders_but_not_change_their_status(client):
    clerk = User.objects.create_user("clerk", password="x", is_staff=True)
    clerk.user_permissions.add(Permission.objects.get(codename="view_order"))
    client.force_login(clerk)
    order = make_order()

    page = client.get(ORDERS)
    assert page.status_code == 200
    assert b"mark_shipped" not in page.content

    run_action(client, "mark_shipped", order)
    order.refresh_from_db()
    assert order.status == Order.Status.PAID


def test_orders_cannot_be_added_or_edited_by_hand(admin_client):
    order = make_order()
    assert admin_client.get(reverse("admin:core_order_add")).status_code == 403
    admin_client.post(
        reverse("admin:core_order_change", args=[order.pk]), {"amount_total_minor": 1}
    )
    order.refresh_from_db()
    assert order.amount_total_minor == 44900


def test_orders_can_be_filtered_by_status(admin_client):
    make_order(email="paid@example.com", session_id="cs_a")
    make_order(status="needs_refund", email="short@example.com", session_id="cs_b")
    content = admin_client.get(ORDERS, {"status__exact": "needs_refund"}).content
    assert b"short@example.com" in content
    assert b"paid@example.com" not in content


def test_an_order_page_shows_its_items_and_the_stripe_events_behind_it(admin_client):
    order = make_order()
    order.items.create(product_name="Enamel kettle", unit_price_minor=44900, quantity=1)
    StripeEvent.objects.create(event_id="evt_123", type="checkout.session.completed", order=order)
    content = admin_client.get(reverse("admin:core_order_change", args=[order.pk])).content
    assert b"Enamel kettle" in content
    assert b"evt_123" in content


def test_the_stripe_event_log_is_read_only(admin_client):
    event = StripeEvent.objects.create(event_id="evt_123", type="checkout.session.completed")
    assert admin_client.get(reverse("admin:core_stripeevent_changelist")).status_code == 200
    assert admin_client.get(reverse("admin:core_stripeevent_add")).status_code == 403
    admin_client.post(reverse("admin:core_stripeevent_change", args=[event.pk]), {"type": "forged"})
    event.refresh_from_db()
    assert event.type == "checkout.session.completed"


# -- stock adjustment -----------------------------------------------------------


def product_form(product: Product, **overrides) -> dict:
    data = {
        "category": product.category_id,
        "name": product.name,
        "slug": product.slug,
        "description": product.description,
        "price_minor": product.price_minor,
        "image": product.image,
        "is_active": "on" if product.is_active else "",
        "stock_adjustment": "",
    }
    return {**data, **overrides}


def test_a_stale_product_form_cannot_undo_a_sale(admin_client):
    """Regression: stock was edited as an absolute number. Open the form at 5, let an
    order take 2, save the form, and stock went back to 5. Adjustments are relative."""
    product = make_product(stock=5)
    stale = product_form(product, stock_adjustment="2")
    Product.objects.filter(pk=product.pk).update(stock=3)  # the webhook sells 2

    admin_client.post(reverse("admin:core_product_change", args=[product.pk]), stale)

    product.refresh_from_db()
    assert product.stock == 5  # 3 left after the sale, plus the 2 received


def test_saving_a_stale_form_without_an_adjustment_leaves_stock_alone(admin_client):
    product = make_product(stock=5)
    stale = product_form(product, name="Renamed kettle")
    Product.objects.filter(pk=product.pk).update(stock=3)

    admin_client.post(reverse("admin:core_product_change", args=[product.pk]), stale)

    product.refresh_from_db()
    assert (product.name, product.stock) == ("Renamed kettle", 3)


def test_an_absolute_stock_value_in_the_form_is_ignored(admin_client):
    product = make_product(stock=5)
    admin_client.post(
        reverse("admin:core_product_change", args=[product.pk]),
        product_form(product, stock="99"),
    )
    product.refresh_from_db()
    assert product.stock == 5


def test_an_adjustment_that_would_go_below_zero_is_refused(admin_client):
    product = make_product(stock=3)
    response = admin_client.post(
        reverse("admin:core_product_change", args=[product.pk]),
        product_form(product, stock_adjustment="-5"),
    )
    assert b"only 3 in stock" in response.content
    product.refresh_from_db()
    assert product.stock == 3


def test_a_new_product_takes_its_starting_stock_directly(admin_client):
    admin_client.post(
        reverse("admin:core_product_add"),
        {
            "category": default_category().pk,
            "name": "Oak spoon",
            "slug": "oak-spoon",
            "description": "",
            "price_minor": 9900,
            "image": "",
            "is_active": "on",
            "stock": "7",
        },
    )
    assert Product.objects.get(slug="oak-spoon").stock == 7


def test_the_product_list_no_longer_edits_stock_inline(admin_client):
    make_product(stock=5)
    content = admin_client.get(reverse("admin:core_product_changelist")).content
    assert b'name="form-0-stock"' not in content
