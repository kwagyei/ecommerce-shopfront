from decimal import Decimal

import pytest
from django.db import IntegrityError

from core.models import Product
from core.tests.factories import make_category, make_product

pytestmark = pytest.mark.django_db


def test_price_converts_minor_units_to_a_decimal():
    product = make_product(price_minor=44900)
    assert product.price == Decimal("449.00")
    assert isinstance(product.price, Decimal), "money must never become a float"


def test_price_keeps_exact_cents():
    """19999 öre is 199.99 kr exactly — the case floating point would round badly."""
    assert make_product(price_minor=19999).price == Decimal("199.99")


def test_zero_price_is_allowed_but_negative_is_not():
    assert make_product(slug="free-thing", price_minor=0).price == Decimal("0")
    with pytest.raises(IntegrityError):
        make_product(slug="negative", price_minor=-1)


def test_slug_must_be_unique():
    make_product(slug="duplicate")
    with pytest.raises(IntegrityError):
        make_product(slug="duplicate", name="Something else")


def test_is_in_stock_follows_the_stock_count():
    assert make_product(slug="has-stock", stock=1).is_in_stock is True
    assert make_product(slug="no-stock", stock=0).is_in_stock is False


def test_active_queryset_excludes_withdrawn_products():
    category = make_category()
    make_product(category=category, slug="live", is_active=True)
    make_product(category=category, slug="withdrawn", is_active=False)
    assert [p.slug for p in Product.objects.active()] == ["live"]


def test_in_stock_queryset_excludes_sold_out_products():
    category = make_category()
    make_product(category=category, slug="available", stock=2)
    make_product(category=category, slug="sold-out", stock=0)
    assert [p.slug for p in Product.objects.in_stock()] == ["available"]


def test_string_representations_are_the_names():
    product = make_product()
    assert str(product) == "Enamel kettle"
    assert str(product.category) == "Kitchen"
