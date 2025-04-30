from django.contrib import admin
from .models import Product, Customer, Sale, Receipt, SaleItem, Category

admin.site.register(Product)
admin.site.register(Customer)
admin.site.register(Sale)
admin.site.register(Receipt)
admin.site.register(SaleItem)
admin.site.register(Category)

# Register your models here.
