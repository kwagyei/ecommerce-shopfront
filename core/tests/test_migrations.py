"""The data migration that moved the seeded catalogue from drawings to photographs."""

import importlib

import pytest
from django.apps import apps

from core.models import Product
from core.tests.factories import make_product

pytestmark = pytest.mark.django_db

photos = importlib.import_module("core.migrations.0005_product_photos")


def test_seeded_drawings_become_photographs():
    make_product(slug="enamel-kettle", image="products/enamel-kettle.svg")

    photos.to_photos(apps, None)

    assert Product.objects.get(slug="enamel-kettle").image == "products/enamel-kettle.jpg"


def test_an_image_changed_in_the_admin_is_left_alone():
    """Only rows still on their original drawing move; a hand-picked image is a decision."""
    make_product(slug="enamel-kettle", image="products/brass-lamp.svg")
    make_product(slug="not-seeded", name="Other", image="products/head-torch.svg")

    photos.to_photos(apps, None)

    assert Product.objects.get(slug="enamel-kettle").image == "products/brass-lamp.svg"
    assert Product.objects.get(slug="not-seeded").image == "products/head-torch.svg"


def test_the_migration_reverses():
    make_product(slug="wool-blanket", name="Wool blanket", image="products/wool-blanket.svg")

    photos.to_photos(apps, None)
    photos.to_drawings(apps, None)

    assert Product.objects.get(slug="wool-blanket").image == "products/wool-blanket.svg"
