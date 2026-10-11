from django.urls import path

from core import views

app_name = "catalog"

urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("category/<slug:slug>/", views.category_detail, name="category"),
    path("product/<slug:slug>/", views.product_detail, name="product"),
    path("cart/", views.cart_detail, name="cart"),
    path("cart/add/<slug:slug>/", views.cart_add, name="cart_add"),
    path("cart/update/<slug:slug>/", views.cart_update, name="cart_update"),
    path("cart/remove/<slug:slug>/", views.cart_remove, name="cart_remove"),
]
