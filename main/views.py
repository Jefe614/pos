# views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from reportlab.pdfgen import canvas
from io import BytesIO
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from .models import Product, Sale, SaleItem, Customer, Category, Receipt
from .forms import ProductForm, CustomerForm, PaymentForm, CustomUserCreationForm
import json
from django.db.models import F
from django.views.decorators.csrf import csrf_exempt
import logging


logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)



@login_required
@login_required
def dashboard(request):
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Sales data calculations
    today_sales = Sale.objects.filter(created_at__date=today, completed=True).aggregate(
        total=Sum('total'), count=Count('id'))
    weekly_sales = Sale.objects.filter(created_at__date__gte=week_ago, completed=True).aggregate(
        total=Sum('total'), count=Count('id'))
    monthly_sales = Sale.objects.filter(created_at__date__gte=month_ago, completed=True).aggregate(
        total=Sum('total'), count=Count('id'))
    
    # Low stock products
    low_stock_products = Product.objects.filter(stock__lt=5).order_by('stock')[:5]
    low_stock_count = low_stock_products.count()
    
    # Recent sales with prefetch for efficiency
    recent_sales = Sale.objects.filter(completed=True).select_related('customer', 'cashier', 'receipt').order_by('-created_at')[:10]
    
    context = {
        'today_sales': today_sales.get('total') or Decimal('0.00'),
        'today_transactions': today_sales.get('count') or 0,
        'weekly_sales': weekly_sales.get('total') or Decimal('0.00'),
        'weekly_transactions': weekly_sales.get('count') or 0,
        'monthly_sales': monthly_sales.get('total') or Decimal('0.00'),
        'monthly_transactions': monthly_sales.get('count') or 0,
        'recent_sales': recent_sales,
        'low_stock': low_stock_products,
        'low_stock_count': low_stock_count,
    }
    return render(request, 'pos/dashboard.html', context)
@login_required
def pos(request):
    # Common setup for both GET and POST
    products = Product.objects.filter(stock__gt=0).select_related('category')
    categories = Category.objects.all()
    customers = Customer.objects.all()
    
    # Get or initialize cart from session
    cart = request.session.get('cart', {})
    
    # Calculate cart totals with proper decimal handling
    subtotal = sum(
        Decimal(str(item['price'])) * item['quantity'] 
        for item in cart.values()
    )
    tax = (subtotal * Decimal('0.10')).quantize(Decimal('0.00'))
    discount = Decimal(request.session.get('discount', '0.00'))
    total = (subtotal + tax - discount).quantize(Decimal('0.00'))

    if request.method == 'POST':
        try:
            # Extract and validate form data
            form_data = {
                'payment_method': request.POST.get('payment_method'),
                'customer_id': request.POST.get('customer') or None,
                'amount_paid': request.POST.get('amount_paid', '0'),
                'subtotal': request.POST.get('subtotal', '0'),
                'tax': request.POST.get('tax', '0'),
                'discount': request.POST.get('discount', '0'),
                'total': request.POST.get('total', '0'),
                'cart': request.POST.get('cart', '[]'),
            }

            logger.debug("Form data received: %s", form_data)

            # Validate required fields
            if not form_data['payment_method']:
                return JsonResponse({
                    'success': False, 
                    'error': 'Payment method required'
                }, status=400)

            # Convert and validate numeric fields
            try:
                numeric_fields = {
                    'amount_paid': Decimal(form_data['amount_paid']),
                    'client_subtotal': Decimal(form_data['subtotal']),
                    'client_tax': Decimal(form_data['tax']),
                    'client_discount': Decimal(form_data['discount']),
                    'client_total': Decimal(form_data['total']),
                }
            except (ValueError, InvalidOperation) as e:
                logger.error("Decimal conversion error: %s", str(e))
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid numeric format'
                }, status=400)

            # Parse and validate cart
            try:
                client_cart = json.loads(form_data['cart'])
                if not isinstance(client_cart, list):
                    raise ValueError("Cart must be an array")
            except (json.JSONDecodeError, ValueError) as e:
                logger.error("Invalid cart JSON: %s", str(e))
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid cart format'
                }, status=400)

            # Validate cart contents
            if not client_cart:
                return JsonResponse({
                    'success': False,
                    'error': 'Cart cannot be empty'
                }, status=400)

            # Validate cart items against session
            tolerance = Decimal('0.01')  # Allow 1 cent difference
            for item in client_cart:
                product_id = str(item.get('product_id'))
                if product_id not in cart:
                    return JsonResponse({
                        'success': False,
                        'error': f'Product {product_id} not in cart'
                    }, status=400)
                
                session_item = cart[product_id]
                session_total = Decimal(session_item['price']) * session_item['quantity']
                
                if (
                    item.get('quantity') != session_item['quantity'] or
                    abs(Decimal(str(item.get('price'))) - Decimal(session_item['price'])) > tolerance or
                    abs(Decimal(str(item.get('total'))) - session_total) > tolerance
                ):
                    return JsonResponse({
                        'success': False,
                        'error': f'Cart item {product_id} mismatch'
                    }, status=400)

            # Validate totals with tolerance
            if (
                abs(numeric_fields['client_subtotal'] - subtotal) > tolerance or
                abs(numeric_fields['client_tax'] - tax) > tolerance or
                abs(numeric_fields['client_discount'] - discount) > tolerance or
                abs(numeric_fields['client_total'] - total) > tolerance
            ):
                logger.error("Total mismatch: Client %s vs Server %s",
                    {k: numeric_fields[k] for k in ['client_subtotal', 'client_tax', 'client_discount', 'client_total']},
                    {'subtotal': subtotal, 'tax': tax, 'discount': discount, 'total': total}
                )
                return JsonResponse({
                    'success': False,
                    'error': 'Cart totals do not match',
                    'server_totals': {
                        'subtotal': str(subtotal),
                        'tax': str(tax),
                        'discount': str(discount),
                        'total': str(total),
                    }
                }, status=400)

            # Validate payment
            if form_data['payment_method'] == 'cash' and numeric_fields['amount_paid'] < total:
                return JsonResponse({
                    'success': False,
                    'error': f'Amount paid ({numeric_fields["amount_paid"]}) less than total ({total})'
                }, status=400)

            with transaction.atomic():
                # Create sale record
                sale = Sale.objects.create(
                    cashier=request.user,
                    customer_id=form_data['customer_id'],
                    payment_method=form_data['payment_method'],
                    subtotal=subtotal,
                    tax=tax,
                    discount=discount,
                    total=total,
                    amount_paid=numeric_fields['amount_paid'],
                    change=max(numeric_fields['amount_paid'] - total, Decimal('0')),
                    completed=True  # Ensure stock updates in SaleItem.save
                )

                # Create receipt
                receipt_number = f"REC-{sale.id:06d}"  # Example: REC-000001
                Receipt.objects.create(
                    sale=sale,
                    receipt_number=receipt_number,
                    printed=False
                )

                # Create sale items and update inventory
                for product_id, item in cart.items():
                    product = Product.objects.get(id=product_id)
                    SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        quantity=item['quantity'],
                        price=Decimal(item['price']),
                        total=Decimal(item['price']) * item['quantity']
                    )
                    product.stock = F('stock') - item['quantity']
                    product.save()

                # Clear cart
                request.session['cart'] = {}
                request.session['discount'] = '0.00'
                request.session.modified = True

                return JsonResponse({
                    'success': True,
                    'redirect_url': reverse('receipt', args=[sale.id])
                })

        except Exception as e:
            logger.exception("Sale processing error")
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)

    # GET request - render POS page
    context = {
        'products': products,
        'categories': categories,
        'customers': customers,
        'cart': cart,
        'subtotal': f"{subtotal:.2f}",
        'tax': f"{tax:.2f}",
        'discount': f"{discount:.2f}",
        'total': f"{total:.2f}",
    }
    return render(request, 'pos/pos.html', context)
# @login_required
@csrf_exempt 
@require_http_methods(["POST"])
def add_to_cart(request):
    try:
        data = json.loads(request.body)
        product_id = data.get('product_id')
        quantity = int(data.get('quantity', 1))
        update = data.get('update', False)

        if not product_id or quantity < 1:
            return JsonResponse({'error': 'Invalid product ID or quantity'}, status=400)

        product = get_object_or_404(Product, id=product_id)
        cart = request.session.get('cart', {})
        str_id = str(product_id)

        # Stock validation
        current_quantity = cart.get(str_id, {}).get('quantity', 0)
        new_quantity = quantity if update else current_quantity + quantity

        if new_quantity > product.stock:
            return JsonResponse({
                'error': f'Only {product.stock} available in stock'
            }, status=400)

        # Update cart
        cart[str_id] = {
            'name': product.name,
            'price': float(product.price),
            'quantity': new_quantity,
            'total': float(product.price * new_quantity),
            'barcode': product.barcode
        }

        request.session['cart'] = cart
        request.session.modified = True
        return JsonResponse({'success': True, 'cart_item_count': len(cart)})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@login_required
@require_http_methods(["POST"])
def remove_from_cart(request, product_id):
    cart = request.session.get('cart', {})
    if str(product_id) in cart:
        del cart[str(product_id)]
        request.session['cart'] = cart
    return JsonResponse({'success': True})

@login_required
@require_http_methods(["POST"])
def clear_cart(request):
    request.session['cart'] = {}
    request.session['discount'] = '0.00'
    return JsonResponse({'success': True})

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

from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib import colors

@login_required
def receipt(request, receipt_id):
    sale = get_object_or_404(
        Sale.objects.select_related('cashier', 'customer', 'receipt')
                   .prefetch_related('items__product'),
        id=receipt_id
    )
    
    if request.GET.get('format') == 'pdf':
        return generate_pdf_receipt(sale)
    
    context = {
        'sale': sale,
    }
    return render(request, 'pos/receipt.html', context)
def generate_pdf_receipt(sale):
    buffer = BytesIO()
    width, height = letter
    p = canvas.Canvas(buffer, pagesize=letter)
    
    # Set up styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=16,
        alignment=1,
        spaceAfter=12
    )
    header_style = ParagraphStyle(
        'Header',
        parent=styles['Normal'],
        fontSize=10,
        alignment=1
    )
    info_style = ParagraphStyle(
        'Info',
        parent=styles['Normal'],
        fontSize=9,
        leading=12
    )
    item_style = ParagraphStyle(
        'Item',
        parent=styles['Normal'],
        fontSize=9,
        leading=12
    )
    total_style = ParagraphStyle(
        'Total',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        textColor=colors.black,
        fontName='Helvetica-Bold'
    )
    
    # Store information
    p.setFont("Helvetica-Bold", 16)
    p.drawCentredString(width/2, height-50, "STORE NAME")
    p.setFont("Helvetica", 10)
    p.drawCentredString(width/2, height-70, "123 Main Street, City")
    p.drawCentredString(width/2, height-85, "Phone: (123) 456-7890")
    
    # Receipt header
    p.line(50, height-110, width-50, height-110)
    p.setFont("Helvetica-Bold", 12)
    p.drawCentredString(width/2, height-100, "SALES RECEIPT")
    
    # Receipt info
    cashier_initial = f"{sale.cashier.username[0]}." if sale.cashier.username else "N/A"
    info_data = [
        [f"<b>Receipt #:</b> {sale.receipt.receipt_number}", f"<b>Date:</b> {sale.created_at.strftime('%m/%d/%Y')}"],
        [f"<b>Time:</b> {sale.created_at.strftime('%I:%M %p')}", f"<b>Cashier:</b> {cashier_initial}"],
    ]
    
    if sale.customer:
        info_data.append([f"<b>Customer:</b> {sale.customer.name}", ""])
    
    info_table = Table(info_data, colWidths=[width/2-50, width/2-50])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    
    info_table.wrapOn(p, width, height)
    info_table.drawOn(p, 50, height-150)
    
    # Items table
    items = sale.items.all().order_by('id')
    item_data = [["ITEM", "QTY", "PRICE", "TOTAL"]]
    
    for item in items:
        item_data.append([
            item.product.name,
            str(item.quantity),
            f"${item.price:,.2f}",
            f"${item.total:,.2f}"
        ])
    
    items_table = Table(item_data, colWidths=[width*0.4, width*0.15, width*0.2, width*0.2])
    items_table.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (2,1), (-1,-1), 'RIGHT'),
        ('ALIGN', (0,1), (0,-1), 'LEFT'),
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('GRID', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BOX', (0,0), (-1,-1), 0.5, colors.lightgrey),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
    ]))
    
    items_table.wrapOn(p, width, height)
    items_table.drawOn(p, 50, height-250)
    
    # Totals
    totals_y = height-250 - (len(items) * 15) - 30
    
    total_data = [
        [Paragraph("<b>Subtotal:</b>", info_style), Paragraph(f"${sale.subtotal:,.2f}", info_style)],
        [Paragraph("<b>Tax (10%):</b>", info_style), Paragraph(f"${sale.tax:,.2f}", info_style)],
        [Paragraph("<b>Discount:</b>", info_style), Paragraph(f"${sale.discount:,.2f}", info_style)],
        [Paragraph("<b>TOTAL:</b>", total_style), Paragraph(f"${sale.total:,.2f}", total_style)],
        [Paragraph("<b>Payment Method:</b>", info_style), Paragraph(sale.get_payment_method_display(), info_style)],
        [Paragraph("<b>Amount Paid:</b>", info_style), Paragraph(f"${sale.amount_paid:,.2f}", info_style)],
        [Paragraph("<b>Change:</b>", info_style), Paragraph(f"${sale.change:,.2f}", info_style)],
    ]
    
    totals_table = Table(total_data, colWidths=[width*0.6, width*0.3])
    totals_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
    ]))
    
    totals_table.wrapOn(p, width, height)
    totals_table.drawOn(p, 50, totals_y)
    
    # Footer
    p.setFont("Helvetica", 9)
    p.drawCentredString(width/2, 100, "Thank you for shopping with us!")
    p.drawCentredString(width/2, 85, f"{sale.created_at.strftime('%m/%d/%Y %I:%M %p')} • Receipt #{sale.receipt.receipt_number}")
    
    if sale.customer:
        p.drawCentredString(width/2, 70, f"Customer: {sale.customer.name}")
    
    p.line(50, 60, width-50, 60)
    
    p.showPage()
    p.save()
    buffer.seek(0)
    
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{sale.receipt.receipt_number}.pdf"'
    return response
@login_required
def sales_report(request):
    date_from = request.GET.get('date_from', (timezone.now() - timedelta(days=30)).date())
    date_to = request.GET.get('date_to', timezone.now().date())
    
    sales = Sale.objects.filter(
        created_at__date__range=[date_from, date_to],
        completed=True
    ).values('created_at__date').annotate(
        total_sales=Sum('total'),
        transaction_count=Count('id')
    ).order_by('created_at__date')
    
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
    query = request.GET.get('search', '')
    category_id = request.GET.get('category')
    stock_status = request.GET.get('stock_status')
    
    products = Product.objects.all()
    
    if query:
        products = products.filter(Q(name__icontains=query) | Q(barcode__icontains=query))
    if category_id:
        products = products.filter(category_id=category_id)
    if stock_status == 'low':
        products = products.filter(stock__lt=5, stock__gt=0)
    elif stock_status == 'out':
        products = products.filter(stock=0)
    elif stock_status == 'in':
        products = products.filter(stock__gte=5)
    
    paginator = Paginator(products, 25)
    page = request.GET.get('page')
    # products = paginator.get_page(page)
    products = products.order_by('name')
    
    return render(request, 'pos/product_list.html', {
        'products': products,
        'categories': Category.objects.all()
    })

@login_required
def add_product(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('product_list')
    else:
        form = ProductForm()
    return render(request, 'pos/product_form.html', {'form': form})

@login_required
def edit_product(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            return redirect('product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'pos/product_form.html', {'form': form})

@login_required
def delete_product(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product.delete()
    return redirect('product_list')

@login_required
def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    return render(request, 'pos/product_detail.html', {'product': product})

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
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = CustomUserCreationForm()
    return render(request, 'pos/signup.html', {'form': form})


@login_required
@require_http_methods(["POST"])
def apply_discount(request):
    try:
        discount = Decimal(request.POST.get('discount', '0.00'))
        if discount < 0:
            return JsonResponse({'error': 'Discount cannot be negative'}, status=400)
        request.session['discount'] = str(discount)
        request.session.modified = True
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)