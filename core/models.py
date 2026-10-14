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


class Order(models.Model):
    """A paid Checkout Session. Created only by the Stripe webhook, never by a page view.

    Unique on the session id: Stripe can describe one payment in more than one event,
    and however many arrive, one payment is one order.
    """

    class Status(models.TextChoices):
        PAID = "paid", "Paid"
        NEEDS_REFUND = "needs_refund", "Needs refund (not enough stock)"
        SHIPPED = "shipped", "Shipped"

    stripe_checkout_session_id = models.CharField(max_length=255, unique=True)
    email = models.EmailField(blank=True)
    amount_total_minor = models.PositiveIntegerField(help_text="What Stripe charged, in öre.")
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PAID)
    created_at = models.DateTimeField(auto_now_add=True)
    shipped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self) -> str:
        return f"Order {self.pk} ({self.get_status_display()})"

    @property
    def amount_total(self) -> Decimal:
        return (Decimal(self.amount_total_minor) / 100).quantize(Decimal("0.01"))


class OrderItem(models.Model):
    """One paid line. Name and price are copied at purchase time, so editing or deleting
    the product later never rewrites what a customer was charged."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    product_name = models.CharField(max_length=140)
    unit_price_minor = models.PositiveIntegerField()
    quantity = models.PositiveIntegerField()

    def __str__(self) -> str:
        return f"{self.quantity} × {self.product_name}"

    @property
    def line_total_minor(self) -> int:
        return self.unit_price_minor * self.quantity


class StripeEvent(models.Model):
    """Every webhook event received, keyed by Stripe's event id.

    The unique constraint is the idempotency guarantee: a replayed event fails to
    insert, so it can never be processed twice, even when two deliveries race.
    """

    event_id = models.CharField(max_length=255, unique=True)
    type = models.CharField(max_length=100)
    received_at = models.DateTimeField(auto_now_add=True)
    order = models.ForeignKey(
        Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )

    class Meta:
        ordering = ["-received_at"]

    def __str__(self) -> str:
        return f"{self.type} ({self.event_id})"
