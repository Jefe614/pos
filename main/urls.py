from django.urls import path
from . import views
from django.contrib.auth import views as auth_views



urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('pos/', views.pos, name='pos'),
    path('pos/add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('pos/remove-from-cart/<int:product_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('pos/clear-cart/', views.clear_cart, name='clear_cart'),
    path('pos/product-by-barcode/', views.product_by_barcode, name='product_by_barcode'),
    path('receipt/<int:receipt_id>/', views.receipt, name='receipt'),
    path('pos/apply-discount/', views.apply_discount, name='apply_discount'),
    
    
    # Reports
    path('reports/sales/', views.sales_report, name='sales_report'),
    
    # Products
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.add_product, name='add_product'),
    path('products/<int:pk>/edit/', views.edit_product, name='edit_product'),
    path('products/delete/<int:product_id>/', views.delete_product, name='delete_product'),
    path('products/<int:product_id>/', views.product_detail, name='product_detail'),



    
    # Customers
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/add/', views.add_customer, name='add_customer'),
    path('login/', auth_views.LoginView.as_view(template_name='pos/login.html'), name='login'),
    # path('accounts/login/', auth_views.LoginView.as_view(template_name='pos/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('signup/', views.signup, name='signup'),
    
]