from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

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


def healthz(request):
    """Liveness probe: cheap, no database access, used by the host to check the app is up."""
    return JsonResponse({"status": "ok"})
