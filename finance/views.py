from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts import permissions as P
from accounts.permissions import role_required
from core.forms import DateRangeForm
from core.models import log_action

from .forms import ExpenseForm
from .models import Expense
from .reports import profit_and_loss


def _range(request):
    today = timezone.localdate()
    form = DateRangeForm(request.GET or None, initial={"start": today.replace(day=1), "end": today})
    if form.is_bound and form.is_valid():
        return form, form.cleaned_data["start"], form.cleaned_data["end"]
    return DateRangeForm(initial={"start": today.replace(day=1), "end": today}), today.replace(day=1), today


@role_required(*P.FINANCE)
def expense_list(request):
    form, start, end = _range(request)
    qs = Expense.objects.filter(date__range=(start, end)).select_related("recorded_by")
    category = request.GET.get("category", "")
    if category:
        qs = qs.filter(category=category)
    by_category = qs.values("category").annotate(total=Sum("amount")).order_by("-total")
    labels = dict(Expense.Category.choices)
    return render(request, "finance/expense_list.html", {
        "form": form, "start": start, "end": end, "category": category, "categories": Expense.Category.choices,
        "page": Paginator(qs, 40).get_page(request.GET.get("page")),
        "total": qs.aggregate(t=Sum("amount"))["t"] or 0,
        "by_category": [(labels[r["category"]], r["total"]) for r in by_category],
        "new_form": ExpenseForm(initial={"date": timezone.localdate()}),
    })


@role_required(*P.FINANCE)
def expense_form(request, pk=None):
    expense = get_object_or_404(Expense, pk=pk) if pk else None
    form = ExpenseForm(request.POST or None, instance=expense)
    if request.method == "POST":
        if request.POST.get("delete") and expense:
            log_action(request.user, "expense.delete", expense, f"Deleted expense {expense}")
            expense.delete()
            messages.success(request, "Expense deleted.")
            return redirect("finance:expenses")
        if form.is_valid():
            expense = form.save(commit=False)
            if not expense.pk:
                expense.recorded_by = request.user
            expense.save()
            log_action(request.user, "expense.save", expense, f"Expense {expense.description} {expense.amount}")
            messages.success(request, "Expense saved.")
            return redirect("finance:expenses")
    return render(request, "rooms/form.html", {"form": form, "title": "Edit expense" if expense else "Record an expense",
                                               "can_delete": bool(expense)})


@role_required(*P.REPORTS)
def profit_loss(request):
    form, start, end = _range(request)
    return render(request, "finance/profit_loss.html", {"form": form, "start": start, "end": end,
                                                        "pl": profit_and_loss(start, end)})
