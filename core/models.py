from decimal import Decimal

from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse


def validate_static_path(path: str) -> None:
    """The hashed static storage raises on a missing file, so a typo here would 500
    every page that shows the product. Catch it when the product is saved instead."""
    if path and not finders.find(path):
        raise ValidationError(f"No static file at static/{path}.")


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("catalog:category", args=[self.slug])


class ProductQuerySet(models.QuerySet):
    def active(self) -> "ProductQuerySet":
        return self.filter(is_active=True)

    def in_stock(self) -> "ProductQuerySet":
        return self.filter(stock__gt=0)


class Product(models.Model):
    """A thing for sale.

    Money is stored as an integer number of minor units (öre for SEK). Floats are
    never used for money: 0.1 + 0.2 != 0.3 in binary floating point, and a cent lost
    per order compounds. Everything downstream — cart totals, Stripe line items —
    works in these same minor units.
    """

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    price_minor = models.PositiveIntegerField(
        help_text="Price in minor units (öre). 19900 = 199.00 kr"
    )
    stock = models.PositiveIntegerField(default=0)
    # A path under static/, not an upload: free hosting has an ephemeral filesystem,
    # so uploaded media would vanish on every redeploy. See README.
    image = models.CharField(
        max_length=200,
        blank=True,
        validators=[validate_static_path],
        help_text="Path under static/, e.g. products/enamel-kettle.svg",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["is_active", "category"])]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("catalog:product", args=[self.slug])

    @property
    def price(self) -> Decimal:
        """Price as a two-place decimal, for display only.

        Never feed this back into arithmetic: totals are summed in minor units and
        converted once, at the edge, so no rounding error can accumulate.
        """
        return (Decimal(self.price_minor) / 100).quantize(Decimal("0.01"))

    @property
    def is_in_stock(self) -> bool:
        return self.stock > 0
