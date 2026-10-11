from core.cart import Cart
from core.models import Category


def navigation(request):
    """Category nav and cart badge appear in the site header, so every page needs them.

    A context processor rather than a repeated line in each view: forgetting it is
    how the nav silently vanished from the product detail page. The cart count reads
    the session only, so it costs no query.
    """
    return {"categories": Category.objects.all(), "cart_count": len(Cart(request))}
