import pytest
from django.urls import reverse

from core.tests.factories import make_category, make_product

pytestmark = pytest.mark.django_db


def test_list_shows_active_products_only(client):
    category = make_category()
    make_product(category=category, slug="live", name="Enamel kettle")
    make_product(category=category, slug="withdrawn", name="Withdrawn thing", is_active=False)

    response = client.get(reverse("catalog:product_list"))
    assert response.status_code == 200
    assert b"Enamel kettle" in response.content
    assert b"Withdrawn thing" not in response.content


def test_list_shows_the_price_in_major_units(client):
    make_product(price_minor=44900)
    assert b"449.00 kr" in client.get(reverse("catalog:product_list")).content


def test_category_page_shows_only_that_category(client):
    kitchen = make_category(name="Kitchen", slug="kitchen")
    desk = make_category(name="Desk", slug="desk")
    make_product(category=kitchen, slug="kettle", name="Enamel kettle")
    make_product(category=desk, slug="lamp", name="Brass lamp")

    response = client.get(reverse("catalog:category", args=["kitchen"]))
    assert b"Enamel kettle" in response.content
    assert b"Brass lamp" not in response.content


def test_unknown_category_is_a_404(client):
    assert client.get(reverse("catalog:category", args=["nope"])).status_code == 404


def test_product_detail_renders(client):
    make_product(slug="enamel-kettle", description="A kettle.")
    response = client.get(reverse("catalog:product", args=["enamel-kettle"]))
    assert response.status_code == 200
    assert b"Enamel kettle" in response.content
    assert b"A kettle." in response.content


def test_withdrawn_product_detail_is_a_404_not_a_403(client):
    """A withdrawn product shouldn't confirm it ever existed."""
    make_product(slug="withdrawn", is_active=False)
    assert client.get(reverse("catalog:product", args=["withdrawn"])).status_code == 404


def test_out_of_stock_products_are_listed_but_marked(client):
    make_product(slug="sold-out", name="Stoneware mug", stock=0)
    response = client.get(reverse("catalog:product", args=["sold-out"]))
    assert b"Out of stock" in response.content


def test_catalog_page_does_not_scale_queries_with_product_count(client, django_assert_num_queries):
    """Guards against an N+1: the category name is rendered for every card."""
    category = make_category()
    for i in range(10):
        make_product(category=category, slug=f"product-{i}", name=f"Product {i}")
    with django_assert_num_queries(2):  # products (joined) + the nav's categories
        client.get(reverse("catalog:product_list"))


def test_every_page_shows_the_category_nav(client):
    """Regression: the nav was missing on product detail when each view built it itself."""
    make_category(name="Kitchen", slug="kitchen")
    make_product(slug="enamel-kettle")
    for url in [
        reverse("catalog:product_list"),
        reverse("catalog:category", args=["kitchen"]),
        reverse("catalog:product", args=["enamel-kettle"]),
    ]:
        assert b'href="/category/kitchen/"' in client.get(url).content, url


def test_every_page_says_checkout_is_in_test_mode_and_names_the_test_card(client):
    """The demo is public: a visitor must never think a real payment is being taken."""
    make_category(name="Kitchen", slug="kitchen")
    make_product(slug="enamel-kettle")
    for url in [
        reverse("catalog:product_list"),
        reverse("catalog:category", args=["kitchen"]),
        reverse("catalog:product", args=["enamel-kettle"]),
        reverse("catalog:cart"),
        reverse("catalog:checkout_success"),
    ]:
        content = client.get(url).content
        assert b"Stripe test mode" in content, url
        assert b"4242 4242 4242 4242" in content, url


def test_home_features_the_first_product_in_stock(client):
    """The hero offers something a visitor can actually buy, so a sold-out product
    that sorts first by name is skipped."""
    make_product(slug="anvil", name="Anvil", stock=0)
    make_product(slug="bellows", name="Bellows", stock=2)

    response = client.get(reverse("catalog:product_list"))
    assert response.context["featured"].slug == "bellows"


def test_home_has_no_featured_product_when_everything_is_sold_out(client):
    make_product(slug="anvil", name="Anvil", stock=0)

    response = client.get(reverse("catalog:product_list"))
    assert response.status_code == 200
    assert response.context["featured"] is None
    assert b'class="offer"' not in response.content


def test_home_shelves_products_under_their_category(client):
    kitchen = make_category(name="Kitchen", slug="kitchen")
    desk = make_category(name="Desk", slug="desk")
    make_product(category=kitchen, slug="kettle", name="Enamel kettle")
    make_product(category=desk, slug="lamp", name="Brass lamp")

    content = client.get(reverse("catalog:product_list")).content.decode()
    # Shelves sort by category name, so Desk comes first; each holds only its own products.
    desk_shelf, kitchen_shelf = content.split('id="shelf-desk"')[1].split('id="shelf-kitchen"')
    assert "Brass lamp" in desk_shelf and "Enamel kettle" not in desk_shelf
    kitchen_shelf = kitchen_shelf.split("</section>")[0]
    assert "Enamel kettle" in kitchen_shelf and "Brass lamp" not in kitchen_shelf
