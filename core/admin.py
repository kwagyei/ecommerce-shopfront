from django.contrib import admin

from core.models import Category, Product


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
