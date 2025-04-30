from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from reportlab.pdfgen import canvas
from django.db.models import Count
from io import BytesIO
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from .models import Product, Sale, SaleItem, Customer, Category, Receipt, InventoryLog
from .forms import CustomUserCreationForm, ProductForm, CustomerForm, SaleForm, PaymentForm
from django.core.paginator import Paginator
from django.db.models import Q
from django.db.models.functions import TruncDay


@login_required
def dashboard(request):
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Today's sales
    today_sales_data = Sale.objects.filter(created_at__date=today, completed=True).aggregate(
        total=Sum('total'),
        count=Count('id')
    )

    # Weekly sales
    weekly_sales_data = Sale.objects.filter(created_at__date__gte=week_ago, completed=True).aggregate(
        total=Sum('total'),
        count=Count('id')
    )
    
    # Monthly sales
    monthly_sales_data = Sale.objects.filter(created_at__date__gte=month_ago, completed=True).aggregate(
        total=Sum('total'),
        count=Count('id')
    )
    
    # Recent sales (last 10)
    recent_sales = Sale.objects.filter(completed=True).select_related(
        'customer', 'receipt'
    ).order_by('-created_at')[:10]
    
    # Low stock products
    low_stock = Product.objects.filter(stock__lt=5).order_by('stock')[:5]
    
    context = {
        'today_sales': today_sales_data.get('total') or 0,
        'today_transactions': today_sales_data.get('count') or 0,
        'weekly_sales': weekly_sales_data.get('total') or 0,
        'weekly_transactions': weekly_sales_data.get('count') or 0,
        'monthly_sales': monthly_sales_data.get('total') or 0,
        'monthly_transactions': monthly_sales_data.get('count') or 0,
        'low_stock': low_stock,
        'low_stock_count': low_stock.count(),
        'recent_sales': recent_sales,
    }
    return render(request, 'pos/dashboard.html', context)

@login_required
def pos(request):
    products = Product.objects.filter(stock__gt=0).select_related('category')
    customers = Customer.objects.all()
    
    if request.method == 'POST':
        form = SaleForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                sale = form.save(commit=False)
                sale.cashier = request.user
                sale.save()
                
                # Process cart items from session
                cart = request.session.get('cart', {})
                for product_id, item in cart.items():
                    product = Product.objects.get(id=product_id)
                    SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        quantity=item['quantity'],
                        price=item['price'],
                        total=item['total']
                    )
                
                # Generate receipt
                receipt = Receipt.objects.create(
                    sale=sale,
                    receipt_number=f"RCPT-{sale.id:06d}"
                )
                
                # Clear cart
                request.session['cart'] = {}
                
                return redirect('receipt', receipt_id=receipt.id)
    else:
        form = SaleForm()
    
    context = {
        'products': products,
        'customers': customers,
        'form': form,
    }
    return render(request, 'pos/pos.html', context)

@login_required
@require_http_methods(["POST"])
def add_to_cart(request):
    product_id = request.POST.get('product_id')
    quantity = int(request.POST.get('quantity', 1))
    
    product = get_object_or_404(Product, id=product_id)
    
    cart = request.session.get('cart', {})
    
    if product_id in cart:
        cart[product_id]['quantity'] += quantity
        cart[product_id]['total'] = cart[product_id]['quantity'] * product.price
    else:
        cart[product_id] = {
            'name': product.name,
            'price': float(product.price),
            'quantity': quantity,
            'total': float(product.price * quantity),
            'barcode': product.barcode
        }
    
    request.session['cart'] = cart
    
    return JsonResponse({
        'success': True,
        'cart_total': sum(item['quantity'] for item in cart.values()),
        'cart_subtotal': sum(item['total'] for item in cart.values())
    })

@login_required
def remove_from_cart(request, product_id):
    cart = request.session.get('cart', {})
    
    if str(product_id) in cart:
        del cart[str(product_id)]
        request.session['cart'] = cart
    
    return redirect('pos')

@login_required
def clear_cart(request):
    request.session['cart'] = {}
    return redirect('pos')

@login_required
def product_by_barcode(request):
    barcode = request.GET.get('barcode')
    product = Product.objects.filter(barcode=barcode).first()
    
    if product:
        return JsonResponse({
            'id': product.id,
            'name': product.name,
            'price': str(product.price),
            'barcode': product.barcode,
            'stock': product.stock
        })
    return JsonResponse({'error': 'Product not found'}, status=404)

@login_required
def receipt(request, receipt_id):
    receipt = get_object_or_404(Receipt, id=receipt_id)
    sale = receipt.sale
    
    # Mark as printed
    if not receipt.printed:
        receipt.printed = True
        receipt.save()
    
    if request.GET.get('format') == 'pdf':
        return generate_pdf_receipt(receipt)
    
    context = {
        'receipt': receipt,
        'sale': sale,
        'items': sale.items.all()
    }
    return render(request, 'pos/receipt.html', context)

def generate_pdf_receipt(receipt):
    buffer = BytesIO()
    p = canvas.Canvas(buffer)
    
    # Draw receipt content
    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, 800, "SIMPLE POS RECEIPT")
    p.setFont("Helvetica", 12)
    p.drawString(100, 780, f"Receipt #: {receipt.receipt_number}")
    p.drawString(100, 760, f"Date: {receipt.created_at.strftime('%Y-%m-%d %H:%M')}")
    p.drawString(100, 740, f"Cashier: {receipt.sale.cashier.get_full_name()}")
    
    # Draw items table
    y = 700
    p.drawString(100, y, "Item")
    p.drawString(300, y, "Qty")
    p.drawString(350, y, "Price")
    p.drawString(450, y, "Total")
    
    y -= 20
    for item in receipt.sale.items.all():
        p.drawString(100, y, item.product.name)
        p.drawString(300, y, str(item.quantity))
        p.drawString(350, y, f"${item.price:.2f}")
        p.drawString(450, y, f"${item.total:.2f}")
        y -= 20
    
    # Draw totals
    y -= 30
    p.drawString(350, y, "Subtotal:")
    p.drawString(450, y, f"${receipt.sale.subtotal:.2f}")
    
    y -= 20
    p.drawString(350, y, "Tax:")
    p.drawString(450, y, f"${receipt.sale.tax:.2f}")
    
    y -= 20
    p.drawString(350, y, "Discount:")
    p.drawString(450, y, f"${receipt.sale.discount:.2f}")
    
    y -= 20
    p.setFont("Helvetica-Bold", 14)
    p.drawString(350, y, "Total:")
    p.drawString(450, y, f"${receipt.sale.total:.2f}")
    
    p.setFont("Helvetica", 10)
    p.drawString(100, 100, "Thank you for your business!")
    
    p.showPage()
    p.save()
    
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{receipt.receipt_number}.pdf"'
    return response

@login_required
def sales_report(request):
    date_from = request.GET.get('date_from', timezone.now().date() - timedelta(days=30))
    date_to = request.GET.get('date_to', timezone.now().date())
    
    sales = Sale.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
        completed=True
    ).annotate(
        day=TruncDay('created_at')
    ).values('day').annotate(
        total_sales=Sum('total'),
        cash_sales=Sum('total', filter=Q(payment_method='cash')),
        card_sales=Sum('total', filter=Q(payment_method='card')),
        mobile_sales=Sum('total', filter=Q(payment_method='mobile')),
        transaction_count=Count('id')
    ).order_by('day')
    
    context = {
        'sales': sales,
        'date_from': date_from,
        'date_to': date_to,
        'total': sum(sale['total_sales'] for sale in sales),
        'transaction_count': sum(sale['transaction_count'] for sale in sales)
    }
    return render(request, 'pos/sales_report.html', context)

@login_required
def product_list(request):
    products = Product.objects.all().select_related('category')
    return render(request, 'pos/product_list.html', {'products': products})

@login_required
def add_product(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            
            # Generate barcode if not provided
            if not product.barcode:
                product.barcode = f"PRD{Product.objects.count() + 1:06d}"
            
            product.save()
            return redirect('product_list')
    else:
        form = ProductForm()
    
    return render(request, 'pos/product_form.html', {'form': form})

@login_required
def customer_list(request):
    customers = Customer.objects.all()
    return render(request, 'pos/customer_list.html', {'customers': customers})

@login_required
def add_customer(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('customer_list')
    else:
        form = CustomerForm()
    
    return render(request, 'pos/customer_form.html', {'form': form})

def signup(request):
    if request.user.is_authenticated:
        return redirect('/')
    
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('/')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'pos/signup.html', {'form': form})


def product_list(request):
    products = Product.objects.all().select_related('category')
    categories = Category.objects.all()
    
    # Search
    search_query = request.GET.get('search')
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) | 
            Q(barcode__icontains=search_query)
        )
    
    # Category filter
    category_filter = request.GET.get('category')
    if category_filter:
        products = products.filter(category_id=category_filter)
    
    # Stock status filter
    stock_filter = request.GET.get('stock_status')
    if stock_filter == 'low':
        products = products.filter(stock__lt=5, stock__gt=0)
    elif stock_filter == 'out':
        products = products.filter(stock=0)
    elif stock_filter == 'in':
        products = products.filter(stock__gte=5)
    
    # Pagination
    paginator = Paginator(products, 25)  # Show 25 products per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'products': page_obj,
        'categories': categories,
    }
    return render(request, 'pos/product_list.html', context)


def edit_product(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            return redirect('product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'pos/edit_product.html', {'form': form})


def delete_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product.delete()
    return redirect('product_list')


def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    return render(request, 'pos/product_detail.html', {'product': product})