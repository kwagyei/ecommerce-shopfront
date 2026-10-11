from django.urls import path

from core import views

app_name = "catalog"

urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("category/<slug:slug>/", views.category_detail, name="category"),
    path("product/<slug:slug>/", views.product_detail, name="product"),
]
