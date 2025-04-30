from django import forms
from .models import Product, Customer, Sale
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from reportlab.graphics.barcode import code128
from reportlab.lib.pagesizes import letter
from reportlab.graphics import renderPM
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from io import BytesIO

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['barcode', 'name', 'category', 'price', 'cost', 'stock', 'image']
        widgets = {
            'price': forms.NumberInput(attrs={'step': '0.01'}),
            'cost': forms.NumberInput(attrs={'step': '0.01'}),
        }

    def generate_barcode_image(self, barcode):
        # Create a barcode using code128
        barcode_obj = code128.Code128(barcode, barWidth=0.5, barHeight=40)

        # Render the barcode into a PNG image
        buffer = BytesIO()
        renderPM.drawToFile(barcode_obj, buffer, fmt='PNG')

        # Save the image to the file system
        barcode_filename = f'product_{barcode}.png'
        barcode_file = ContentFile(buffer.getvalue())
        file_path = default_storage.save(f'barcodes/{barcode_filename}', barcode_file)
        return file_path

    def save(self, commit=True):
        product = super().save(commit=False)
        
        if not product.barcode:
            product.save()  # Save to generate an ID
            product.barcode = f"PRD{product.id:06d}"
            
            # Generate and save the barcode image
            barcode_image_path = self.generate_barcode_image(product.barcode)
            product.barcode_image = barcode_image_path  # Assuming you have a barcode_image field in your model
            
            if commit:
                product.save()
        
        return product

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'phone', 'email', 'address']

class SaleForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ['customer', 'payment_method', 'subtotal', 'tax', 'discount', 'amount_paid']
        widgets = {
            'subtotal': forms.HiddenInput(),
            'tax': forms.HiddenInput(),
            'discount': forms.HiddenInput(),
            'amount_paid': forms.HiddenInput(),
        }

class PaymentForm(forms.Form):
    payment_method = forms.ChoiceField(choices=Sale.PAYMENT_METHODS, widget=forms.RadioSelect)
    amount_paid = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    customer = forms.ModelChoiceField(queryset=Customer.objects.all(), required=False)


class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    
    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user