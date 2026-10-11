"""Small helpers so tests read as what they're testing, not as object construction."""
from core.models import Category, Product


def make_category(**kwargs) -> Category:
    defaults = {"name": "Kitchen", "slug": "kitchen"}
    return Category.objects.create(**{**defaults, **kwargs})


def default_category() -> Category:
    """Reused rather than recreated, so a test making two products doesn't trip
    the unique constraint on Category.slug and fail for the wrong reason."""
    category, _ = Category.objects.get_or_create(slug="kitchen", defaults={"name": "Kitchen"})
    return category


def make_product(category: Category | None = None, **kwargs) -> Product:
    defaults = {
        "name": "Enamel kettle",
        "slug": "enamel-kettle",
        "price_minor": 44900,
        "stock": 3,
        "description": "A kettle.",
        "is_active": True,
    }
    return Product.objects.create(category=category or default_category(), **{**defaults, **kwargs})
