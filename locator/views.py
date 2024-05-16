import json

import pandas as pd
from dateutil import parser
from django.db.models import Q, Sum
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from .forms import ItemForm, UploadFileForm
from .models import Item, Order, OrderItem


def set_item(request):
    form = ItemForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item, created = Item.objects.update_or_create(
            number=form.cleaned_data["number"], defaults=form.cleaned_data
        )
        message = (
            f"Item {form.cleaned_data['model_prefix']}{form.cleaned_data['number']} "
            f"{'added' if created else 'updated'} successfully!"
        )
        return redirect("set_item")
    else:
        items = Item.objects.all().order_by("-id")[:5]  # Fetch only the last 5 items
        context = {"form": form, "items": items}
        if request.method == "POST":
            context["errors"] = form.errors
        return render(request, "locator/set_item.html", context)


def fetch_model_numbers(request):
    model_prefix = request.GET.get("model_prefix")
    if model_prefix:
        numbers = list(
            Item.objects.filter(model_prefix=model_prefix)
            .values_list("number", flat=True)
            .distinct()
        )
        return JsonResponse({"numbers": numbers})
    else:
        error_message = "Model prefix not specified"
        return JsonResponse({"error": error_message}, status=400)


####################


def select_model(request):
    return render(request, "locator/select_model.html")


@csrf_exempt
def finalize_items(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=400)

    try:
        data = json.loads(request.body.decode("utf-8"))
        items_data = data.get("items", {})
        if not items_data:
            return JsonResponse({"error": "No items data received"}, status=400)

        prefixes = [key[:3] for key in items_data.keys()]
        numbers = [key[3:] for key in items_data.keys() if len(key) > 3]

        items_query = Item.objects.filter(model_prefix__in=prefixes, number__in=numbers)
        results = [
            {
                "model": f"{item.model_prefix}{item.number}",
                "quantity": items_data.get(f"{item.model_prefix}{item.number}", 0),
                "line": item.line,
                "place": item.place,
            }
            for item in items_query
        ]

        return JsonResponse({"items": results})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


############################################
class OrderListView(ListView):
    model = Order
    template_name = "locator/order_list.html"
    context_object_name = "orders"

    def get_queryset(self):
        queryset = super().get_queryset()
        store = self.request.GET.get("store")
        status = self.request.GET.get("status")
        search_query = self.request.GET.get("search")

        if store:
            queryset = queryset.filter(store_name=store)
        if status:
            queryset = queryset.filter(status=status)
        if search_query:
            queryset = queryset.filter(
                Q(customer_name__icontains=search_query)
                | Q(order_number__icontains=search_query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        status_choices = dict(Order.STATUS_CHOICES)
        context["distinct_statuses"] = Order.objects.values_list(
            "status", flat=True
        ).distinct()
        context["status_descriptions"] = {
            status: status_choices.get(status, "")
            for status in context["distinct_statuses"]
        }
        context["distinct_stores"] = (
            Order.objects.order_by("store_name")
            .values_list("store_name", flat=True)
            .distinct()
        )
        print("Distinct Stores: ", list(context["distinct_stores"]))
        for order in context["orders"]:
            order.items_with_quantities = order.items.annotate(
                total_quantity=Sum("orderitem__quantity")
            ).values("model_prefix", "number", "total_quantity")
        return context


class CompleteOrderView(View):
    def post(self, request, pk):
        order = Order.objects.get(pk=pk)
        order.status = "COM"
        order.save()
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))


class HoldOrderView(View):
    def post(self, request, pk):
        note = request.POST.get("note")
        order = Order.objects.get(pk=pk)
        order.status = "ONH"
        order.notes = note
        order.save()
        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))


def collect_items(request):
    store_name = request.GET.get("store")
    status = request.GET.get("status")
    search_query = request.GET.get("search")

    queryset = OrderItem.objects.select_related("item", "order")

    if store_name:
        queryset = queryset.filter(order__store_name=store_name)
    if status:
        queryset = queryset.filter(order__status=status)
    if search_query:
        queryset = queryset.filter(
            Q(order__customer_name__icontains=search_query)
            | Q(order__order_number__icontains=search_query)
        )

    items = (
        queryset.values(
            "item__model_prefix", "item__number", "item__line", "item__place"
        )
        .annotate(total_quantity=Sum("quantity"))
        .order_by("item__line", "item__place")
    )

    # Prepare the data for JSON response
    items_list = [
        {
            "model": item["item__model_prefix"] + item["item__number"],
            "quantity": item["total_quantity"],
            "line": item["item__line"],
            "place": item["item__place"],
        }
        for item in items
    ]

    return JsonResponse({"items": items_list})


@require_POST
@csrf_exempt
def update_order_status(request):
    order_id = request.POST.get("order_id")
    new_status = request.POST.get("status")
    note = request.POST.get("note", "")

    try:
        order = Order.objects.get(pk=order_id)
        order.status = new_status
        if new_status == "ONH":
            order.notes = note
        order.save()
        return JsonResponse(
            {"success": True, "message": "Order status updated successfully"}
        )
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "message": "Order not found"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)})


############################################


def upload_orders(request):
    context = {
        "new_orders": [],
        "duplicate_orders": [],
        "error_orders": [],
        "form": UploadFileForm(),
    }

    if request.method == "POST":
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            excel_file = request.FILES["file"]
            data = pd.read_excel(excel_file, dtype={"order_number": str})
            results = process_excel_data(data)
            context.update(results)
            return render(request, "locator/upload.html", context)
    else:
        form = UploadFileForm()

    return render(request, "locator/upload.html", context)


def process_excel_data(data):
    results = {
        "new_orders": [],
        "duplicate_orders": [],
        "error_orders": [],
        "order_details": [],
    }
    required_columns = [
        "store_name",
        "date",
        "order_number",
        "customer_name",
        "item",
        "quantity",
    ]

    for index, row in data.iterrows():
        order_info = {
            col: str(row[col]).strip() if pd.notna(row[col]) else None
            for col in required_columns
        }

        missing_fields = [
            field for field in required_columns if pd.isna(row.get(field))
        ]
        if missing_fields:
            results["error_orders"].append(
                (
                    order_info["order_number"],
                    f"Row {index + 2}: Missing fields: {missing_fields}",
                )
            )
            continue

        try:
            date = (
                parser.parse(order_info["date"], dayfirst=True).date()
                if order_info["date"]
                else None
            )
        except ValueError as e:
            results["error_orders"].append(
                (order_info["order_number"], f"Row {index + 2}: Invalid date format")
            )
            continue

        order_number = order_info["order_number"]

        if Order.objects.filter(order_number=order_number).exists():
            results["duplicate_orders"].append(order_number)
            continue

        try:
            item = Item.objects.get(
                model_prefix=order_info["item"][:3] if order_info["item"] else "",
                number=order_info["item"][3:] if order_info["item"] else "",
            )
        except Item.DoesNotExist:
            results["error_orders"].append(
                (order_number, f"Row {index + 2}: Item does not exist")
            )
            continue

        try:
            order = Order.objects.create(
                store_name=order_info["store_name"],
                date=date,
                order_number=order_number,
                customer_name=order_info["customer_name"],
                status="INP",
            )
            OrderItem.objects.create(
                order=order, item=item, quantity=order_info["quantity"]
            )
            results["new_orders"].append(order_number)
            results["order_details"].append(
                {
                    "store_name": order_info["store_name"],
                    "date": order_info["date"],
                    "order_number": order_number,
                    "customer_name": order_info["customer_name"],
                    "item": order_info["item"],
                    "quantity": order_info["quantity"],
                    "status": "Created",
                }
            )
        except Exception as e:
            results["error_orders"].append((order_number, f"Row {index + 2}: {str(e)}"))
            results["order_details"].append(
                {
                    "store_name": order_info["store_name"],
                    "date": order_info["date"],
                    "order_number": order_number,
                    "customer_name": order_info["customer_name"],
                    "item": order_info["item"],
                    "quantity": order_info["quantity"],
                    "status": "Error",
                }
            )

    return results
