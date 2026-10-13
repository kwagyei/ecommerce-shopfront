from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.cart import Cart
from core.models import Category, Product


def product_list(request):
    products = Product.objects.active().select_related("category")
    return render(request, "catalog/product_list.html", {"products": products, "current": None})


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    products = Product.objects.active().filter(category=category).select_related("category")
    return render(
        request, "catalog/product_list.html", {"products": products, "current": category}
    )


def product_detail(request, slug):
    """Inactive products 404 rather than 403: a withdrawn product shouldn't confirm it exists."""
    product = get_object_or_404(Product.objects.active().select_related("category"), slug=slug)
    return render(request, "catalog/product_detail.html", {"product": product})


def cart_detail(request):
    cart = Cart(request)
    for note in cart.reconcile():
        messages.warning(request, note)
    return render(request, "cart/detail.html", {"cart": cart})


@require_POST
def cart_add(request, slug):
    """POST only, so a crawler following links can never fill a cart."""
    product = get_object_or_404(Product.objects.active(), slug=slug)
    requested = _quantity_from(request, default=1)

    if requested < 1:
        # The form's min="1" stops this in a browser; a hand-made POST gets no effect.
        messages.error(request, "Choose a quantity of at least 1.")
        return redirect(product.get_absolute_url())
    if product.stock == 0:
        messages.error(request, f"{product.name} is out of stock.")
        return redirect(product.get_absolute_url())

    cart = Cart(request)
    before = cart.quantity_of(product)
    added = cart.add(product, requested) - before
    if added == 0:
        messages.warning(
            request, f"You already have all {before} of {product.name} in your cart."
        )
    elif added < requested:
        more = " more" if before else ""
        messages.warning(request, f"Only {added}{more} of {product.name} could be added.")
    else:
        messages.success(request, f"{product.name} added to your cart.")
    return redirect("catalog:cart")


@require_POST
def cart_update(request, slug):
    product = get_object_or_404(Product.objects.active(), slug=slug)
    cart = Cart(request)
    requested = _quantity_from(request, default=0)
    held = cart.set_quantity(product, requested)
    if held == 0:
        messages.info(request, f"{product.name} removed from your cart.")
    elif held < requested:
        messages.warning(request, f"Only {held} of {product.name} are available.")
    return redirect("catalog:cart")


@require_POST
def cart_remove(request, slug):
    """Works for withdrawn products too, so a customer can clear one out of their cart.

    Only names the product when it was actually in this cart. Otherwise the response is
    the same as for a slug that never existed, so withdrawn products stay unconfirmed.
    """
    product = Product.objects.filter(slug=slug).first()
    if product is not None and Cart(request).remove(product):
        messages.info(request, f"{product.name} removed from your cart.")
    return redirect("catalog:cart")


def healthz(request):
    """Liveness probe: cheap, no database access, used by the host to check the app is up."""
    return JsonResponse({"status": "ok"})


def _quantity_from(request, default: int) -> int:
    """Form input is untrusted: anything unparseable falls back to the default."""
    try:
        return int(request.POST.get("quantity", default))
    except (TypeError, ValueError):
        return default
