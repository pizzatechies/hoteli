from decimal import ROUND_CEILING, Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import permissions as P
from accounts.permissions import role_required
from bookings.forms import MpesaPromptForm, PaymentForm, VoidForm
from bookings.models import Payment
from bookings.services import BookingError, record_payment
from core.models import log_action

from . import services
from .forms import MenuCategoryForm, MenuItemForm, OrderForm
from .models import MenuCategory, MenuItem, Order, OrderItem


@role_required(*P.POS)
def home(request):
    today = timezone.localdate()
    open_orders = Order.objects.filter(status=Order.Status.OPEN).select_related("booking__room", "created_by")
    closed_today = Order.objects.filter(created_at__date=today).exclude(status=Order.Status.OPEN)
    sales = sum((o.total for o in closed_today if o.status != Order.Status.CANCELLED), Decimal("0"))
    return render(request, "pos/home.html", {
        "open_orders": open_orders, "closed_today": closed_today[:20], "sales_today": sales,
        "form": OrderForm(initial={"outlet": Order.Outlet.RESTAURANT}),
    })


@role_required(*P.POS)
@require_POST
def order_create(request):
    form = OrderForm(request.POST)
    if form.is_valid():
        order = form.save(commit=False)
        order.created_by = request.user
        if order.booking and not order.customer_name:
            order.customer_name = order.booking.guest.full_name
        order.save()
        return redirect("pos:order", pk=order.pk)
    messages.error(request, "Could not open the order: " + "; ".join(e for es in form.errors.values() for e in es))
    return redirect("pos:home")


@role_required(*P.POS)
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.select_related("booking__guest", "booking__room"), pk=pk)
    if request.method == "POST" and order.is_open:
        form = OrderForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            messages.success(request, "Order updated.")
            return redirect("pos:order", pk=pk)
    else:
        form = OrderForm(instance=order)
    categories = MenuCategory.objects.filter(is_active=True).prefetch_related("items")
    balance = order.balance
    phone = order.booking.guest.phone if order.booking_id else ""
    return render(request, "pos/order.html", {
        "order": order, "form": form, "categories": categories, "items": order.items.all(),
        "payments": order.payments.all(), "balance": balance,
        "payment_form": PaymentForm(initial={"amount": balance if balance > 0 else None,
                                             "method": Payment.Method.CASH}, auto_id="pay_%s"),
        "mpesa_form": MpesaPromptForm(auto_id="mpesa_%s", initial={
            "phone": phone,
            "amount": balance.quantize(Decimal("1"), rounding=ROUND_CEILING) if balance > 0 else None,
        }),
        "void_form": VoidForm(auto_id="void_%s"),
        "active_tx": request.GET.get("tx", ""),
        "can_void": request.user.has_role(*P.FINANCE),
    })


@role_required(*P.POS)
@require_POST
def order_add_item(request, pk):
    order = get_object_or_404(Order, pk=pk)
    item = get_object_or_404(MenuItem, pk=request.POST.get("item"))
    try:
        qty = max(int(request.POST.get("quantity", 1)), 1)
        services.add_item(order, item, qty, request.POST.get("notes", "")[:120])
    except (BookingError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("pos:order", pk=pk)


@role_required(*P.POS)
@require_POST
def order_update_item(request, pk, item_id):
    order = get_object_or_404(Order, pk=pk)
    line = get_object_or_404(OrderItem, pk=item_id, order=order)
    if not order.is_open:
        messages.error(request, "This order is closed.")
        return redirect("pos:order", pk=pk)
    try:
        qty = int(request.POST.get("quantity", line.quantity))
    except ValueError:
        qty = line.quantity
    if qty <= 0 or request.POST.get("remove"):
        line.delete()
    else:
        line.quantity = qty
        line.save(update_fields=["quantity"])
    return redirect("pos:order", pk=pk)


@role_required(*P.POS)
@require_POST
def order_charge_room(request, pk):
    order = get_object_or_404(Order, pk=pk)
    try:
        services.charge_to_room(order, request.user)
    except BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{order.number} charged to room {order.booking.room.number}.")
    return redirect("pos:order", pk=pk)


@role_required(*P.POS)
@require_POST
def order_pay(request, pk):
    from mpesa.services import record_manual_mpesa_payment

    order = get_object_or_404(Order, pk=pk)
    form = PaymentForm(request.POST)
    if not order.is_open:
        messages.error(request, "This order is already closed.")
    elif not form.is_valid():
        messages.error(request, "Payment not recorded: " + "; ".join(e for es in form.errors.values() for e in es))
    else:
        d = form.cleaned_data
        try:
            if d["method"] == Payment.Method.MPESA:
                record_manual_mpesa_payment(order=order, code=d["reference"], amount=d["amount"], user=request.user)
            else:
                record_payment(order=order, amount=d["amount"], method=d["method"], reference=d["reference"],
                               notes=d["notes"], user=request.user)
        except BookingError as exc:
            messages.error(request, str(exc))
        else:
            order.refresh_from_db()
            messages.success(request, "Payment recorded." + (" Order closed." if order.status == "PAID" else ""))
    return redirect("pos:order", pk=pk)


@role_required(*P.POS)
@require_POST
def order_cancel(request, pk):
    order = get_object_or_404(Order, pk=pk)
    try:
        services.cancel_order(order, request.user, request.POST.get("reason", "")[:120] or "No reason given")
    except BookingError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{order.number} cancelled.")
    return redirect("pos:order", pk=pk)


@role_required(*P.POS)
def order_bill(request, pk):
    order = get_object_or_404(Order.objects.select_related("booking__guest", "booking__room"), pk=pk)
    return render(request, "pos/bill.html", {"order": order, "items": order.items.all(),
                                             "payments": order.payments.filter(is_void=False),
                                             "printed_at": timezone.now()})


@role_required(*P.POS)
def order_list(request):
    qs = Order.objects.select_related("booking__room", "created_by")
    status = request.GET.get("status", "")
    outlet = request.GET.get("outlet", "")
    if status:
        qs = qs.filter(status=status)
    if outlet:
        qs = qs.filter(outlet=outlet)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "pos/order_list.html", {
        "page": page, "statuses": Order.Status.choices, "outlets": Order.Outlet.choices,
        "status": status, "outlet": outlet,
    })


@role_required(*P.MANAGEMENT, *P.POS)
def menu(request):
    categories = MenuCategory.objects.prefetch_related("items")
    return render(request, "pos/menu.html", {"categories": categories,
                                             "can_edit": request.user.has_role(*P.MANAGEMENT)})


@role_required(*P.MANAGEMENT)
def menu_item_form(request, pk=None):
    item = get_object_or_404(MenuItem, pk=pk) if pk else None
    form = MenuItemForm(request.POST or None, instance=item, initial={"category": request.GET.get("category")})
    if request.method == "POST" and form.is_valid():
        item = form.save()
        log_action(request.user, "menu.save", item)
        messages.success(request, f"{item.name} saved.")
        return redirect("pos:menu")
    return render(request, "rooms/form.html", {"form": form, "title": f"Edit {item.name}" if item else "Add menu item"})


@role_required(*P.MANAGEMENT)
def menu_category_form(request, pk=None):
    cat = get_object_or_404(MenuCategory, pk=pk) if pk else None
    form = MenuCategoryForm(request.POST or None, instance=cat)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Category saved.")
        return redirect("pos:menu")
    return render(request, "rooms/form.html", {"form": form, "title": "Edit category" if cat else "Add category"})
