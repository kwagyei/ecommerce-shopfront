"""The cart, stored in the session.

Two rules drive the design:

1. **Only product ids and quantities live in the session.** Prices are read from the
   database every time the cart is rendered, so a price change in the admin is
   reflected immediately in everyone's cart and no cart can pay a stale price. The
   database session backend keeps the data server-side, but the cart doesn't rely on
   that: under a signed-cookie session engine, a stored price would be client data.
2. **Arithmetic stays in integer minor units.** Totals are summed as whole öre and
   converted to a decimal once, for display.
"""

from dataclasses import dataclass
from decimal import Decimal

from core.models import Product

SESSION_KEY = "cart"
MAX_QUANTITY_PER_LINE = 99


@dataclass(frozen=True)
class CartLine:
    product: Product
    quantity: int

    @property
    def total_minor(self) -> int:
        return self.product.price_minor * self.quantity

    @property
    def total(self) -> Decimal:
        return (Decimal(self.total_minor) / 100).quantize(Decimal("0.01"))


class Cart:
    """A session-backed cart. Keys are string product ids, because sessions are JSON."""

    def __init__(self, request):
        self.session = request.session
        # Read, never setdefault. Mutating the session here would mark it dirty on
        # every request, so Django would create and write a session row for every
        # visitor who merely looked at a page — including crawlers. Writes happen
        # in _save(), only when the cart actually changes.
        self._items: dict[str, int] = dict(self.session.get(SESSION_KEY) or {})

    # -- mutation -----------------------------------------------------------

    def add(self, product: Product, quantity: int = 1) -> int:
        """Add to the existing quantity. Returns the quantity actually held."""
        return self.set_quantity(product, self._items.get(str(product.pk), 0) + quantity)

    def set_quantity(self, product: Product, quantity: int) -> int:
        """Set an absolute quantity, clamped to what can actually be sold.

        Clamping rather than rejecting keeps the cart usable: asking for 50 of a
        product with 3 in stock leaves 3 in the cart, not an error page.
        """
        quantity = min(quantity, product.stock, MAX_QUANTITY_PER_LINE)
        if quantity <= 0:
            self.remove(product)
            return 0
        self._items[str(product.pk)] = quantity
        self._save()
        return quantity

    def remove(self, product: Product) -> bool:
        """Returns whether the product was in the cart."""
        if self._items.pop(str(product.pk), None) is None:
            return False
        self._save()
        return True

    def clear(self) -> None:
        self.session[SESSION_KEY] = self._items = {}
        self._save()

    def reconcile(self) -> list[str]:
        """Bring the cart back in line with the catalog, reporting what changed.

        A cart can sit in a session for weeks. In that time a product can be withdrawn,
        deleted, or sold down below the quantity held. Called when the cart is shown and
        again before checkout, so the customer never reaches payment holding something
        that cannot be sold.
        """
        notes: list[str] = []
        products = {str(p.pk): p for p in self._fetch_products()}

        for product_id, quantity in list(self._items.items()):
            product = products.get(product_id)
            if product is None:
                del self._items[product_id]
                notes.append("An item is no longer available and was removed from your cart.")
            elif product.stock == 0:
                del self._items[product_id]
                notes.append(f"{product.name} sold out and was removed from your cart.")
            elif quantity > product.stock:
                self._items[product_id] = product.stock
                notes.append(f"Only {product.stock} of {product.name} left; your cart was updated.")

        if notes:
            self._save()
        return notes

    # -- reading ------------------------------------------------------------

    def quantity_of(self, product: Product) -> int:
        return self._items.get(str(product.pk), 0)

    def lines(self) -> list[CartLine]:
        """One query for the whole cart, regardless of how many lines it holds."""
        products = {str(p.pk): p for p in self._fetch_products()}
        return [
            CartLine(product=products[pid], quantity=qty)
            for pid, qty in self._items.items()
            if pid in products
        ]

    @property
    def total_minor(self) -> int:
        return sum(line.total_minor for line in self.lines())

    @property
    def total(self) -> Decimal:
        return (Decimal(self.total_minor) / 100).quantize(Decimal("0.01"))

    def __len__(self) -> int:
        """Number of units in the cart, which is what the header badge shows."""
        return sum(self._items.values())

    def __bool__(self) -> bool:
        return bool(self._items)

    def _fetch_products(self):
        ids = [pid for pid in self._items if pid.isdigit()]
        return Product.objects.active().select_related("category").filter(pk__in=ids)

    def _save(self) -> None:
        self.session[SESSION_KEY] = self._items
        self.session.modified = True
