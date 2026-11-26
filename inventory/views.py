from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts import permissions as P
from accounts.permissions import role_required
from core.models import log_action

from . import services
from .forms import AdjustForm, ReceiveForm, StockItemForm
from .models import StockItem, StockMovement

STOCK_ROLES = (*P.MANAGEMENT, *P.FINANCE, *P.POS)


@role_required(*STOCK_ROLES)
def stock_list(request):
    items = StockItem.objects.all()
    area = request.GET.get("area", "")
    if area:
        items = items.filter(area=area)
    if request.GET.get("low"):
        items = [i for i in items if i.is_low]
    items = list(items)
    return render(request, "inventory/list.html", {
        "items": items, "areas": StockItem.Area.choices, "area": area, "low_only": bool(request.GET.get("low")),
        "total_value": sum((i.value for i in items if i.is_active), Decimal("0")),
        "low_count": len(services.low_stock()),
        "receive_form": ReceiveForm(), "adjust_form": AdjustForm(),
        "can_manage": request.user.has_role(*P.MANAGEMENT),
    })


@role_required(*P.MANAGEMENT)
def item_form(request, pk=None):
    item = get_object_or_404(StockItem, pk=pk) if pk else None
    form = StockItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        item = form.save()
        log_action(request.user, "stock.item", item, f"Saved stock item {item}")
        messages.success(request, f"{item.name} saved. Link it to menu items under Menu so sales deduct stock.")
        return redirect("inventory:list")
    return render(request, "rooms/form.html", {"form": form, "title": f"Edit {item}" if item else "New stock item"})


@role_required(*STOCK_ROLES)
def item_detail(request, pk):
    item = get_object_or_404(StockItem, pk=pk)
    return render(request, "inventory/detail.html", {
        "item": item, "page": Paginator(item.movements.select_related("user", "order"), 40).get_page(request.GET.get("page")),
        "menu_items": item.menu_items.all(), "receive_form": ReceiveForm(initial={"unit_cost": item.unit_cost,
                                                                                 "supplier": item.supplier}),
        "adjust_form": AdjustForm(),
    })


@role_required(*STOCK_ROLES)
@require_POST
def receive(request, pk):
    item = get_object_or_404(StockItem, pk=pk)
    form = ReceiveForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        services.receive(item, d["quantity"], d["unit_cost"], user=request.user, supplier=d["supplier"],
                         record_expense=d["record_expense"], method=d["method"], reference=d["reference"])
        messages.success(request, f"Received {d['quantity']:g} {item.unit} of {item.name}.")
    else:
        messages.error(request, "Enter the quantity and cost per unit.")
    return redirect(request.POST.get("next") or "inventory:list")


@role_required(*STOCK_ROLES)
@require_POST
def adjust(request, pk):
    item = get_object_or_404(StockItem, pk=pk)
    form = AdjustForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        if d["action"] == "count":
            services.count(item, d["quantity"], user=request.user, note=d["note"])
        else:
            kind = StockMovement.Kind.WASTE if d["action"] == "waste" else StockMovement.Kind.USE
            services.move(item, kind, -d["quantity"], user=request.user, note=d["note"])
        item.refresh_from_db()
        messages.success(request, f"{item.name}: now {item.quantity:g} {item.unit}.")
    else:
        messages.error(request, "Enter a quantity.")
    return redirect(request.POST.get("next") or "inventory:list")
