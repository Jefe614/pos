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
from reportlab.graphics.shapes import Drawing


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['barcode', 'name', 'category', 'price', 'cost', 'stock', 'image']
        widgets = {
            'price': forms.NumberInput(attrs={'step': '0.01'}),
            'cost': forms.NumberInput(attrs={'step': '0.01'}),
        }

    def clean_barcode(self):
        barcode = self.cleaned_data.get('barcode')
        if barcode:
            qs = Product.objects.filter(barcode=barcode)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("This barcode already exists.")
        return barcode

    def generate_barcode_image(self, barcode):
        barcode_obj = code128.Code128(barcode, barWidth=0.5, barHeight=40)
        drawing = Drawing(200, 50)
        drawing.add(barcode_obj)

        image_data = renderPM.drawToPIL(drawing)
        buffer = BytesIO()
        image_data.save(buffer, format='PNG')

        barcode_filename = f'product_{barcode}.png'
        barcode_file = ContentFile(buffer.getvalue())
        file_path = default_storage.save(f'barcodes/{barcode_filename}', barcode_file)
        return file_path

    def save(self, commit=True):
        product = super().save(commit=False)
        
        if not product.barcode:
            # Save temporarily to generate ID
            temp_save = not commit
            product.save()  # Generates ID
            product.barcode = f"PRD{product.id:06d}"

            # Generate and save the barcode image
            barcode_image_path = self.generate_barcode_image(product.barcode)
            product.barcode_image = barcode_image_path
        
        if commit:
            product.save()
            self.save_m2m()  # To ensure m2m relationships are saved
        
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