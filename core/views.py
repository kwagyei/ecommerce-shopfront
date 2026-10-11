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

    if product.stock == 0:
        messages.error(request, f"{product.name} is out of stock.")
        return redirect(product.get_absolute_url())

    held = Cart(request).add(product, requested)
    if held < requested:
        messages.warning(request, f"Only {held} of {product.name} could be added.")
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
    product = get_object_or_404(Product, slug=slug)
    Cart(request).remove(product)
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
