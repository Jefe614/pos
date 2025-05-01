# barcode_views.py

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
import json

@login_required
@require_http_methods(["POST"])
def update_cart_item(request):
    """Update the quantity of an item in the cart"""
    product_id = request.POST.get('product_id')
    quantity = int(request.POST.get('quantity', 1))
    update = request.POST.get('update') == 'true'
    
    if not product_id:
        return JsonResponse({'success': False, 'error': 'Product ID is required'})
    
    cart = request.session.get('cart', {})
    
    if product_id not in cart:
        return JsonResponse({'success': False, 'error': 'Product not in cart'})
    
    if update:
        # Update the quantity directly
        cart[product_id]['quantity'] = quantity
    else:
        # Add to existing quantity
        cart[product_id]['quantity'] += quantity
    
    # Recalculate total
    cart[product_id]['total'] = cart[product_id]['quantity'] * cart[product_id]['price']
    
    # Update session
    request.session['cart'] = cart
    
    # Calculate totals
    subtotal = sum(item['total'] for item in cart.values())
    tax = subtotal * 0.1  # 10% tax
    total = subtotal + tax
    
    return JsonResponse({
        'success': True,
        'item': cart[product_id],
        'cart_total': sum(item['quantity'] for item in cart.values()),
        'subtotal': subtotal,
        'tax': tax,
        'total': total
    })

@login_required
@require_http_methods(["POST"])
def quick_add_product(request):
    """Quickly add a new product and return its details"""
    from .models import Product, Category
    
    try:
        # Get form data
        name = request.POST.get('name')
        price = request.POST.get('price')
        barcode = request.POST.get('barcode')
        stock = request.POST.get('stock', 1)
        category_id = request.POST.get('category')
        
        # Validate required fields
        if not name or not price:
            return JsonResponse({'success': False, 'error': 'Name and price are required'})
        
        # Get category if provided
        category = None
        if category_id:
            try:
                category = Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                pass
        
        # Generate barcode if not provided
        if not barcode:
            barcode = f"PRD{Product.objects.count() + 1:06d}"
        
        # Create new product
        product = Product.objects.create(
            name=name,
            price=price,
            barcode=barcode,
            stock=stock,
            category=category
        )
        
        return JsonResponse({
            'success': True,
            'product_id': product.id,
            'name': product.name,
            'price': str(product.price),
            'barcode': product.barcode
        })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_http_methods(["POST"])
def apply_discount(request):
    """Apply discount to the current cart"""
    try:
        data = json.loads(request.body)
        discount = float(data.get('discount', 0))
        
        # Store discount in session
        request.session['discount'] = discount
        
        # Calculate totals
        cart = request.session.get('cart', {})
        subtotal = sum(item['total'] for item in cart.values())
        tax = subtotal * 0.1  # 10% tax
        total = subtotal + tax - discount
        
        # Make sure total is not negative
        if total < 0:
            total = 0
        
        return JsonResponse({
            'success': True,
            'subtotal': subtotal,
            'tax': tax,
            'discount': discount,
            'total': total
        })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})