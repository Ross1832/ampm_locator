import json
import logging
import uuid
import os
import io
from django.http import HttpResponse
from .utils import extract_text_from_pdf, parse_orders
from django.core.files.storage import FileSystemStorage
from django.conf import settings
import pandas as pd
from django.db.models import Q, Sum
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import ListView
from django.core.files.storage import default_storage

from .forms import ItemForm, UpdateFileForm, UploadFileForm
from .models import Item, Order, OrderItem
from .utils import handle_update_file, handle_uploaded_file, process_excel_data

logger = logging.getLogger(__name__)


def set_item(request):
    form = ItemForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        number = form.cleaned_data["number"]
        model_prefix = form.cleaned_data["model_prefix"]
        line = form.cleaned_data["line"]
        place = form.cleaned_data["place"]

        try:
            item = Item.objects.get(number=number, model_prefix=model_prefix)
            item.line = line
            item.place = place
            item.save()
            message = f"Item {model_prefix}{number} updated successfully!"
        except Item.DoesNotExist:
            item = Item(
                number=number,
                model_prefix=model_prefix,
                line=line,
                place=place
            )
            item.save()
            message = f"Item {model_prefix}{number} added successfully!"

        return redirect("set_item")
    else:
        items = Item.objects.all().order_by("-updated_at")[:5]
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
    item_choices = Item.MODEL_CHOICES
    return render(request, "locator/select_model.html", {'item_choices': item_choices})


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
            if items_data.get(f"{item.model_prefix}{item.number}", 0) > 0
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


def upload_orders(request):#upload orders
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


def upload_items(request): #upload items
    if request.method == 'POST':
        if 'upload' in request.POST:
            form = UploadFileForm(request.POST, request.FILES)
            update_form = UpdateFileForm()
            if form.is_valid():
                results = handle_uploaded_file(request.FILES['file'])
                return render(request, 'locator/upload_items.html', {'form': form, 'update_form': update_form, 'results': results})
        elif 'update' in request.POST:
            form = UploadFileForm()
            update_form = UpdateFileForm(request.POST, request.FILES)
            if update_form.is_valid():
                results = handle_update_file(request.FILES['file'])
                return render(request, 'locator/upload_items.html', {'form': form, 'update_form': update_form, 'results': results})
    else:
        form = UploadFileForm()
        update_form = UpdateFileForm()
    return render(request, 'locator/upload_items.html', {'form': form, 'update_form': update_form})




#pdf_all
@csrf_exempt  # Use this decorator if you decide not to handle CSRF tokens in the form
def upload_pdfs(request):
    if request.method == 'POST' and request.FILES.getlist('pdf_files'):
        pdf_files = request.FILES.getlist('pdf_files')
        fs = FileSystemStorage(location=settings.MEDIA_ROOT)

        all_data = []

        for pdf_file in pdf_files:
            # Generate a unique filename to prevent conflicts
            unique_filename = f"{uuid.uuid4().hex}_{pdf_file.name}"
            filename = fs.save(unique_filename, pdf_file)
            uploaded_file_path = fs.path(filename)

            # Process the PDF file
            text = extract_text_from_pdf(uploaded_file_path)
            data = parse_orders(text)
            all_data.extend(data)

            # Delete the uploaded PDF after processing
            fs.delete(filename)

        # Create a DataFrame from the combined data
        df = pd.DataFrame(all_data, columns=['Order number', 'Order date', 'Buyer name', 'SKU', 'Quantity', 'Delivery service'])

        # Save the Excel file to an in-memory stream
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False)
        output.seek(0)

        # Prepare response to download the file
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename=orders_{uuid.uuid4().hex}.xlsx'

        return response

    # If GET request or no files uploaded, render the upload page
    html_form = '''
    <!DOCTYPE html>
    <html>
    <body>
    <h2>Upload PDFs</h2>
    <form action="" method="post" enctype="multipart/form-data">
        <!-- {% csrf_token %} -->
        <input type="file" name="pdf_files" multiple required>
        <input type="submit" value="Upload">
    </form>
    </body>
    </html>
    '''
    return HttpResponse(html_form)


def aggregate_skus(request):
    if request.method == 'POST':
        excel_files = request.FILES.getlist('excel_files')
        if not excel_files:
            return HttpResponse("No files uploaded")

        dfs = []
        for uploaded_file in excel_files:
            # Save uploaded file temporarily
            temp_file_path = os.path.join(settings.MEDIA_ROOT, uploaded_file.name)
            with default_storage.open(temp_file_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
            # Read Excel file into DataFrame
            df = pd.read_excel(temp_file_path)
            dfs.append(df)
            # Remove temporary file
            default_storage.delete(temp_file_path)

        # Concatenate all dataframes
        df_all = pd.concat(dfs, ignore_index=True)

        # Ensure 'Quantity' is numeric
        df_all['Quantity'] = pd.to_numeric(df_all['Quantity'], errors='coerce')

        # Group by 'SKU' and sum 'Quantity'
        result = df_all.groupby('SKU', as_index=False)['Quantity'].sum()

        # Sort the result by 'SKU' in ascending order
        result = result.sort_values(by='SKU')

        # Generate a unique filename
        output_filename = f'aggregated_quantities_{uuid.uuid4()}.xlsx'
        output_file_path = os.path.join(settings.MEDIA_ROOT, output_filename)

        # Output to Excel
        result.to_excel(output_file_path, index=False)

        # Build file URL
        aggregated_file_url = settings.MEDIA_URL + output_filename

        return render(request, 'upload_and_download.html', {
            'aggregated_file_url': aggregated_file_url
        })
    else:
        return render(request, 'upload_and_download.html')
