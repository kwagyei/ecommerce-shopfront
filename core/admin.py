from django import forms
from django.contrib import admin, messages
from django.db.models import F
from django.utils.html import format_html

from core.models import Category, Order, OrderItem, Product, StripeEvent


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "product_count"]
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ["name"]

    @admin.display(description="products")
    def product_count(self, category: Category) -> int:
        return category.products.count()


# -- products -------------------------------------------------------------------


class ProductAdminForm(forms.ModelForm):
    stock_adjustment = forms.IntegerField(
        required=False,
        help_text="Units to add (e.g. 10 for a delivery) or remove (e.g. -1 for a breakage).",
    )

    class Meta:
        model = Product
        fields = [
            "category",
            "name",
            "slug",
            "description",
            "price_minor",
            "stock",
            "image",
            "is_active",
        ]

    def clean_stock_adjustment(self) -> int:
        adjustment = self.cleaned_data.get("stock_adjustment") or 0
        if self.instance.pk and adjustment < 0:
            current = Product.objects.values_list("stock", flat=True).get(pk=self.instance.pk)
            if current + adjustment < 0:
                raise forms.ValidationError(f"Can't remove {-adjustment}: only {current} in stock.")
        return adjustment


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Stock on an existing product is changed by an adjustment, never overwritten.

    Orders decrement stock in the webhook. An absolute stock field would let a form
    opened before a sale write the old number back after it, undoing the sale. An
    adjustment is applied as stock = stock + n against whatever the row holds now.
    """

    form = ProductAdminForm
    list_display = ["name", "category", "price_display", "stock", "is_active"]
    list_filter = ["is_active", "category"]
    list_editable = ["is_active"]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ["category"]

    def get_fields(self, request, obj=None):
        fields = [
            "category",
            "name",
            "slug",
            "description",
            "price_minor",
            "image",
            "is_active",
        ]
        if obj is None:
            return [*fields[:5], "stock", *fields[5:]]
        return [*fields[:5], "stock", "stock_adjustment", *fields[5:], "created_at", "updated_at"]

    def get_readonly_fields(self, request, obj=None):
        return ["stock", "created_at", "updated_at"] if obj else []

    def save_model(self, request, obj, form, change):
        if not change:
            super().save_model(request, obj, form, change)
            return
        # Save only what the form changed, so the stock this request loaded is never
        # written back over a decrement that landed since.
        changed = [f for f in form.changed_data if f != "stock_adjustment"]
        if changed:
            obj.save(update_fields=[*changed, "updated_at"])
        adjustment = form.cleaned_data.get("stock_adjustment") or 0
        if adjustment:
            applied = Product.objects.filter(pk=obj.pk, stock__gte=-adjustment).update(
                stock=F("stock") + adjustment
            )
            if not applied:
                self.message_user(
                    request,
                    "Stock changed while you were editing; the adjustment would have "
                    "gone below zero and was not applied.",
                    messages.ERROR,
                )

    @admin.display(description="price", ordering="price_minor")
    def price_display(self, product: Product) -> str:
        return f"{product.price:.2f} kr"


# -- orders ---------------------------------------------------------------------


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    fields = ["product_name", "product", "unit_price", "quantity", "line_total"]
    readonly_fields = fields

    @admin.display(description="unit price")
    def unit_price(self, item: OrderItem) -> str:
        return f"{item.unit_price_minor / 100:.2f}"

    @admin.display(description="line total")
    def line_total(self, item: OrderItem) -> str:
        return f"{item.line_total_minor / 100:.2f}"


class StripeEventInline(admin.TabularInline):
    model = StripeEvent
    extra = 0
    can_delete = False
    fields = ["event_id", "type", "received_at"]
    readonly_fields = fields
    verbose_name_plural = "Stripe events behind this order"


STATUS_COLOURS = {
    Order.Status.PAID: "#1f3d2b",
    Order.Status.NEEDS_REFUND: "#b45309",
    Order.Status.SHIPPED: "#4b5563",
    Order.Status.REFUNDED: "#6b7280",
}


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Orders come from the Stripe webhook alone, so nothing here edits one by hand.

    Staff move them forward with two actions. Each is a single conditional UPDATE that
    only touches orders in the right starting state; anything else is skipped and
    counted, so a mis-click can't ship an order that is waiting for a refund.
    """

    list_display = ["pk", "created_at", "email", "total_display", "status_badge", "shipped_at"]
    list_filter = ["status", "created_at"]
    date_hierarchy = "created_at"
    search_fields = ["email", "stripe_checkout_session_id", "items__product_name"]
    readonly_fields = [
        "stripe_checkout_session_id",
        "email",
        "total_display",
        "status",
        "created_at",
        "shipped_at",
    ]
    fields = readonly_fields
    inlines = [OrderItemInline, StripeEventInline]
    actions = ["mark_shipped", "mark_refunded"]

    @admin.display(description="total", ordering="amount_total_minor")
    def total_display(self, order: Order) -> str:
        return f"{order.amount_total:.2f} {order.currency.upper()}"

    @admin.display(description="status", ordering="status")
    def status_badge(self, order: Order) -> str:
        return format_html(
            '<strong style="color: {}">{}</strong>',
            STATUS_COLOURS.get(order.status, "inherit"),
            order.get_status_display(),
        )

    @admin.action(description="Mark selected paid orders as shipped", permissions=["fulfil"])
    def mark_shipped(self, request, queryset):
        self._report(request, queryset, queryset.mark_shipped(), "marked as shipped", "paid")

    @admin.action(
        description="Mark as refunded (refund in the Stripe dashboard first)",
        permissions=["fulfil"],
    )
    def mark_refunded(self, request, queryset):
        self._report(
            request, queryset, queryset.mark_refunded(), "marked as refunded", "needs refund"
        )

    def _report(self, request, queryset, done: int, verb: str, required: str) -> None:
        total = queryset.count()
        noun = "order" if done == 1 else "orders"
        message = f"{done} {noun} {verb}."
        if total > done:
            message += f" {total - done} skipped: only {required} orders can change this way."
        self.message_user(request, message, messages.SUCCESS if done else messages.WARNING)

    def has_fulfil_permission(self, request) -> bool:
        return request.user.has_perm("core.change_order")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    """Every webhook delivery that passed signature verification, for auditing."""

    list_display = ["event_id", "type", "received_at", "order"]
    list_filter = ["type", "received_at"]
    date_hierarchy = "received_at"
    search_fields = ["event_id"]
    list_select_related = ["order"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
