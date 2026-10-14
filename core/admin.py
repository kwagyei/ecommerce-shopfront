from django.contrib import admin

from core.models import Category, Order, OrderItem, Product, StripeEvent


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "product_count"]
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ["name"]

    @admin.display(description="products")
    def product_count(self, category: Category) -> int:
        return category.products.count()


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "price_display", "stock", "is_active"]
    list_filter = ["is_active", "category"]
    list_editable = ["stock", "is_active"]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ["created_at", "updated_at"]
    list_select_related = ["category"]

    @admin.display(description="price", ordering="price_minor")
    def price_display(self, product: Product) -> str:
        return f"{product.price:.2f} kr"


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ["product", "product_name", "unit_price_minor", "quantity"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Read-only for now: orders are created by the Stripe webhook alone. Status filters
    and the mark-as-shipped action arrive in milestone 5."""

    list_display = ["pk", "created_at", "email", "total_display", "status"]
    list_filter = ["status"]
    search_fields = ["email", "stripe_checkout_session_id"]
    inlines = [OrderItemInline]

    @admin.display(description="total", ordering="amount_total_minor")
    def total_display(self, order: Order) -> str:
        return f"{order.amount_total:.2f} {order.currency.upper()}"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ["event_id", "type", "received_at", "order"]
    list_filter = ["type"]
    search_fields = ["event_id"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
