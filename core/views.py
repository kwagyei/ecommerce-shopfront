import logging

import stripe
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core import fulfilment, payments
from core.cart import Cart
from core.models import Category, Product

logger = logging.getLogger(__name__)

# The id of the Checkout Session this browser started, so the success page only acts
# on its own payment and not on any session id pasted into the URL.
CHECKOUT_SESSION_KEY = "checkout_session_id"


def product_list(request):
    products = Product.objects.active().select_related("category")
    return render(request, "catalog/product_list.html", {"products": products, "current": None})


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    products = Product.objects.active().filter(category=category).select_related("category")
    return render(request, "catalog/product_list.html", {"products": products, "current": category})


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
        messages.warning(request, f"You already have all {before} of {product.name} in your cart.")
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


@require_POST
def checkout(request):
    """Turn the cart into a Stripe Checkout Session and send the customer to pay.

    Fulfilment does not happen here or on the success page: a customer can close the
    tab after paying. Orders are created by the webhook (milestone 4), which Stripe
    retries until it lands.
    """
    cart = Cart(request)
    notes = cart.reconcile()
    if notes:
        # Stock or availability moved since the cart was shown. Let the customer see
        # what they'd actually be paying for before sending them to Stripe.
        for note in notes:
            messages.warning(request, note)
        return redirect("catalog:cart")
    if not cart:
        return redirect("catalog:cart")
    if not payments.is_configured():
        messages.error(request, "Checkout isn't available right now. Your cart is saved.")
        return redirect("catalog:cart")

    try:
        session = payments.create_checkout_session(
            cart.lines(),
            success_url=request.build_absolute_uri(reverse("catalog:checkout_success")),
            cancel_url=request.build_absolute_uri(reverse("catalog:checkout_cancel")),
        )
    except stripe.StripeError:
        logger.exception("Could not create a Stripe Checkout Session")
        messages.error(
            request, "We couldn't reach the payment provider. Your cart is saved; try again."
        )
        return redirect("catalog:cart")

    request.session[CHECKOUT_SESSION_KEY] = session.id
    # 303 so the browser follows with a GET, as Stripe recommends.
    return HttpResponseRedirect(session.url, status=303)


def checkout_success(request):
    """Shown after payment. Clears the cart, but only for the session this browser started."""
    started = request.session.get(CHECKOUT_SESSION_KEY)
    if started and request.GET.get("session_id") == started:
        Cart(request).clear()
        del request.session[CHECKOUT_SESSION_KEY]
    return render(request, "checkout/success.html")


def checkout_cancel(request):
    messages.info(request, "Checkout cancelled. Your cart is as you left it.")
    return redirect("catalog:cart")


@csrf_exempt  # Stripe can't send a CSRF token; the signature check below replaces it.
@require_POST
def stripe_webhook(request):
    """Stripe calls this after a payment. 2xx tells Stripe to stop retrying, so a 2xx
    only goes out once the event is safely recorded (or known to be a duplicate)."""
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret:
        logger.error("STRIPE_WEBHOOK_SECRET is not set; refusing webhook")
        return HttpResponse(status=500)
    try:
        event = stripe.Webhook.construct_event(
            request.body, request.headers.get("Stripe-Signature"), secret
        )
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)

    try:
        outcome = fulfilment.handle_event(event)
    except stripe.StripeError:
        logger.exception("Could not process Stripe event %s; Stripe will retry", event.id)
        return HttpResponse(status=500)
    logger.info("Stripe event %s (%s): %s", event.id, event.type, outcome)
    return HttpResponse(status=200)


def healthz(request):
    """Liveness probe: cheap, no database access, used by the host to check the app is up."""
    return JsonResponse({"status": "ok"})


def _quantity_from(request, default: int) -> int:
    """Form input is untrusted: anything unparseable falls back to the default."""
    try:
        return int(request.POST.get("quantity", default))
    except (TypeError, ValueError):
        return default
