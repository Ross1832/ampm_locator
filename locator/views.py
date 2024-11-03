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
import pdfplumber
from .forms import ItemForm, UpdateFileForm, UploadFileForm
from .models import Item, Order, OrderItem
from .utils import handle_update_file, handle_uploaded_file, process_excel_data
import re
from django.core.files.base import ContentFile
from django.views.decorators.csrf import csrf_protect


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
@csrf_exempt # Use this decorator if you decide not to handle CSRF tokens in the form
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

        return render(request, 'locator/upload_and_download.html', {
            'aggregated_file_url': aggregated_file_url
        })
    else:
        return render(request, 'locator/upload_and_download.html')


#### home24

def upload_pdfs_home24(request):
    if request.method == 'POST' and request.FILES.getlist('pdf_files_home24'):
        pdf_files = request.FILES.getlist('pdf_files_home24')
        all_orders = []

        for pdf_file in pdf_files:
            # Save the uploaded file temporarily
            temp_pdf_path = default_storage.save('temp/' + pdf_file.name, ContentFile(pdf_file.read()))
            # Process the PDF file
            text = ''
            with pdfplumber.open(default_storage.path(temp_pdf_path)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + '\n'
            # Delete the temporary file
            default_storage.delete(temp_pdf_path)

            # Extract orders from text
            def extract_orders_from_text(text):
                orders = []
                # Define order separators for different languages
                order_separators = [
                    'Lieferschein',        # German
                    'Bon de livraison',    # French
                    'Leveringsbon'         # Dutch
                ]
                # Create a regex pattern for order separators
                order_separator_regex = r'(?i)(?:' + '|'.join(map(re.escape, order_separators)) + ')'
                # Split text into individual orders
                order_texts = re.split(order_separator_regex, text)
                for order_text in order_texts[1:]:  # Skip text before the first order separator
                    order = {}

                    # Helper function to get field value based on patterns
                    def get_field_value(text, patterns):
                        for pattern in patterns:
                            match = re.search(pattern, text, re.I)
                            if match:
                                return match.group(1).strip()
                        return None

                    # Define patterns for each field in different languages
                    order_number_patterns = [
                        r'Bestellnummer:\s*([A-Za-z0-9-]+)',          # German
                        r'Numéro de commande\s*:\s*([A-Za-z0-9-]+)',  # French
                        r'Bestelnummer:\s*([A-Za-z0-9-]+)',           # Dutch
                    ]
                    order_date_patterns = [
                        r'Bestelldatum:\s*([\d./-]+)',           # German
                        r'Date de commande\s*:\s*([\d./-]+)',    # French
                        r'Besteldatum:\s*([\d./-]+)',            # Dutch
                    ]
                    buyer_name_patterns = [
                        r'Name des Kunden:\s*(.*)',        # German
                        r'Nom de l\'acheteur\s*:\s*(.*)',  # French
                        r'Klantnaam:\s*(.*)',              # Dutch
                    ]
                    delivery_service_patterns = [
                        r'Versandmethode:\s*(.*)',         # German
                        r'Mode de livraison\s*:\s*(.*)',   # French
                        r'Verzendmethode:\s*(.*)',         # Dutch
                    ]
                    sku_patterns = [
                        r'Shop-Referenz:\s*(.*)',          # German
                        r'Référence vendeur\s*:\s*(.*)',   # French
                        r'Referentie shop:\s*(.*)',        # Dutch
                    ]
                    quantity_markers = [
                        r'Anzahl',      # German
                        r'Menge',       # German
                        r'Qté',         # French
                        r'Aant\.',      # Dutch
                    ]

                    # Extract Order Number
                    order_number = get_field_value(order_text, order_number_patterns)
                    if order_number:
                        order['Order number'] = order_number
                    else:
                        continue  # Skip if no order number found

                    # Extract Order Date
                    order_date = get_field_value(order_text, order_date_patterns)
                    if order_date:
                        order['Order date'] = order_date.strip()

                    # Extract Buyer's Name
                    buyer_name = get_field_value(order_text, buyer_name_patterns)
                    if buyer_name:
                        order["Buyer's name"] = buyer_name.strip()

                    # Extract Delivery Service
                    delivery_service = get_field_value(order_text, delivery_service_patterns)
                    if delivery_service:
                        order['Delivery service'] = delivery_service.strip()

                    # Extract SKU
                    sku = get_field_value(order_text, sku_patterns)
                    if sku:
                        order['SKU'] = sku.strip()
                    else:
                        order['SKU'] = ''

                    # Extract Quantity
                    quantity = '1'  # Default quantity
                    lines = order_text.split('\n')
                    for i, line in enumerate(lines):
                        for marker in quantity_markers:
                            if re.match(r'(?i)^' + marker + r'\s*$', line.strip()):
                                # Next non-empty line is the quantity
                                for next_line in lines[i + 1:]:
                                    next_line = next_line.strip()
                                    if next_line:
                                        if next_line.isdigit():
                                            quantity = next_line
                                        else:
                                            # Check if quantity is in the same line
                                            match = re.search(r'(\d+)', line)
                                            if match:
                                                quantity = match.group(1)
                                        break
                                break
                        else:
                            continue
                        break
                    order['Quantity'] = quantity

                    orders.append(order)
                return orders

            orders = extract_orders_from_text(text)
            if not orders:
                print(f"No orders found in {pdf_file.name}")
            all_orders.extend(orders)
        if not all_orders:
            return HttpResponse('No orders were extracted. Please check the PDF files and the extraction logic.')

        # Create DataFrame and write to Excel
        df = pd.DataFrame(all_orders)
        # Reorder columns as specified
        df = df[['Order number', 'Order date', "Buyer's name", 'SKU', 'Quantity', 'Delivery service']]

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
        response['Content-Disposition'] = f'attachment; filename=home24_orders_{uuid.uuid4().hex}.xlsx'

        return response
    else:
        # If GET request or no files uploaded, redirect back to the main upload page
        return redirect('upload_and_download')  # Ensure 'upload_and_download' is the correct URL name




### mano
def upload_pdfs_mano(request):
    if request.method == 'POST' and request.FILES.getlist('pdf_files_mano'):
        pdf_files = request.FILES.getlist('pdf_files_mano')
        all_orders = []

        for pdf_file in pdf_files:
            # Save the uploaded file temporarily
            temp_pdf_path = default_storage.save('temp/' + pdf_file.name, ContentFile(pdf_file.read()))
            pdf_full_path = default_storage.path(temp_pdf_path)
            print(f"Processing file: {pdf_full_path}")

            # Extract text from PDF
            def extract_text_from_pdf(pdf_path):
                text = ''
                with pdfplumber.open(pdf_path) as pdf:
                    for page_num, page in enumerate(pdf.pages, start=1):
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + '\n'
                        else:
                            print(f"No text found on page {page_num} of {pdf_path}")
                return text

            # Parse orders from text
            def parse_orders(text):
                # Use regex to split on the splitting phrase, ignoring extra whitespace
                orders = re.split(r'Vielen Dank für Ihre Bestellung beim Verkäufer AM\.PM Europe GmbH\s*', text)
                # Remove the first element if it's empty
                if not orders[0].strip():
                    orders = orders[1:]
                parsed_orders = []
                for order_text in orders:
                    order_data = parse_order(order_text)
                    if order_data:
                        parsed_orders.extend(order_data)
                return parsed_orders

            # Parse individual order
            def parse_order(order_text):
                order_data = []
                lines = [line.strip() for line in order_text.strip().split('\n')]
                if not lines:
                    return order_data
                # Extract order number
                order_number = lines[0]
                print(f"Processing Order Number: {order_number}")
                # Combine lines into a single string
                order_text_combined = ' '.join(lines)
                # Extract order date and delivery service
                date_delivery_pattern = r'Bestelldatum Lieferzeit Träger\s*(\d{2}\.\d{2}\.\d{2}, \d{2}:\d{2})\s*(\d+\s*Tage)?\s*([\w\(\)]+)'
                date_delivery_match = re.search(date_delivery_pattern, order_text_combined)
                if date_delivery_match:
                    order_date = date_delivery_match.group(1)
                    delivery_time = date_delivery_match.group(2) or ''
                    delivery_service = date_delivery_match.group(3) or ''
                else:
                    order_date = ''
                    delivery_service = ''
                print(f"Order Date: {order_date}, Delivery Service: {delivery_service}")
                # Extract buyer's name
                buyer_name = ''
                # Find the line containing 'Kunden-Details'
                idx = -1
                for i, line in enumerate(lines):
                    if 'Kunden-Details' in line:
                        idx = i
                        break
                if idx == -1:
                    buyer_name = ''
                else:
                    # Start from the line after 'Kunden-Details'
                    i = idx + 1
                    while i < len(lines):
                        line = lines[i]
                        # Skip lines that are labels or empty
                        if line.strip() == '' or any(keyword in line for keyword in [
                            'Unternehmen', 'Lieferanschrift', 'Mehrwertsteuersatz',
                            'Haftung für Rechnungen', 'Ausstehende', 'Hausnr.', 'Straße +', 'nungsstellung', 'Hausnr.'
                        ]):
                            i += 1
                            continue
                        # If line contains phone number and name
                        phone_name_match = re.match(r'\+[\d]+\s+(.+)', line)
                        if phone_name_match:
                            name_part = phone_name_match.group(1).strip()
                            # Remove duplicate words
                            name_words = name_part.split()
                            seen = set()
                            unique_name_words = []
                            for word in name_words:
                                if word not in seen:
                                    seen.add(word)
                                    unique_name_words.append(word)
                            buyer_name = ' '.join(unique_name_words)
                            break
                        # If line starts with a name followed by a phone number
                        name_phone_match = re.match(r'(.+?)\s+\+[\d]+', line)
                        if name_phone_match:
                            buyer_name = name_phone_match.group(1).strip()
                            break
                        # If line is just a phone number, skip it
                        if re.match(r'\+[\d]+$', line):
                            i += 1
                            continue
                        # Assume the line is the buyer's name
                        buyer_name = line.strip()
                        break
                        i += 1
                print(f"Buyer's Name: {buyer_name}")
                # Extract items
                item_pattern = r'Referenz SKU Menge\s*([\s\S]+?)VAT Excl VAT'
                item_match = re.search(item_pattern, order_text)
                if item_match:
                    items_text = item_match.group(1)
                    # Find all SKUs and Quantities
                    sku_quantity_pattern = r'\b([A-Z0-9]+)\b\s+(\d+)\b'
                    matches = re.findall(sku_quantity_pattern, items_text)
                    for sku, quantity in matches:
                        order_data.append({
                            'Order number': order_number,
                            'Order date': order_date,
                            'Buyer\'s name': buyer_name,
                            'SKU': sku,
                            'Quantity': quantity,
                            'Delivery service': delivery_service
                        })
                        print(f"Extracted Item: SKU={sku}, Quantity={quantity}")
                else:
                    print("No items found in this order.")
                return order_data

            # Begin processing the PDF file
            text = extract_text_from_pdf(pdf_full_path)
            # Delete the temporary file
            default_storage.delete(temp_pdf_path)

            if not text.strip():
                print(f"No text extracted from {pdf_full_path}.")
                continue
            orders = parse_orders(text)
            if not orders:
                print(f"No orders found in {pdf_file.name}.")
            else:
                all_orders.extend(orders)

        if not all_orders:
            return HttpResponse('No orders extracted from the uploaded PDFs.')

        # Create DataFrame and save to Excel
        df = pd.DataFrame(all_orders)

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
        response['Content-Disposition'] = f'attachment; filename=mano_orders_{uuid.uuid4().hex}.xlsx'

        return response
    else:
        # If GET request or no files uploaded, render the upload page
        html_form = '''
        <!DOCTYPE html>
        <html>
        <body>
        <h2>Upload PDFs for Mano</h2>
        <form action="" method="post" enctype="multipart/form-data">
            <!-- {% csrf_token %} -->
            <input type="file" name="pdf_files_mano" multiple required>
            <input type="submit" value="Upload">
        </form>
        </body>
        </html>
        '''
        return HttpResponse(html_form)



#ampm
def upload_pdfs_new_functionality(request):
    if request.method == 'POST' and request.FILES.getlist('pdf_files_new'):
        pdf_files = request.FILES.getlist('pdf_files_new')
        data_list = []

        for pdf_file in pdf_files:
            # Save the uploaded file temporarily
            temp_pdf_path = default_storage.save('temp/' + pdf_file.name, ContentFile(pdf_file.read()))
            pdf_full_path = default_storage.path(temp_pdf_path)
            print(f"Processing file: {pdf_full_path}")

            # Extract text from PDF
            with pdfplumber.open(pdf_full_path) as pdf:
                text = ''
                # Extract text from all pages
                for page_num, page in enumerate(pdf.pages, start=1):
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + '\n'
                    else:
                        text += f'[Page {page_num} has no extractable text]\n'

            # Extract data using the function
            def extract_data_from_text(text):
                lines = text.split('\n')
                order_number = ''
                order_date = ''
                buyer_name = ''
                sku = ''
                quantity = ''
                # Process lines
                for i, line in enumerate(lines):
                    line = line.strip()
                    # Extract order number
                    if 'BESTELLNUMMER' in line:
                        match = re.search(r'BESTELLNUMMER\s*:\s*(#?\S+)', line)
                        if match:
                            order_number = match.group(1).strip()
                        continue
                    # Extract order date
                    if 'BESTELLDATUM' in line:
                        match = re.search(r'BESTELLDATUM\s*:\s*([\d\.]+\s*[\d:]+)', line)
                        if match:
                            order_date = match.group(1).strip()
                        continue
                    # Extract buyer's name
                    if 'VERSANDDETAILS' in line:
                        # The next line contains buyer's name repeated
                        if i + 1 < len(lines):
                            buyer_line = lines[i + 1].strip()
                            buyer_name_parts = buyer_line.split()
                            if len(buyer_name_parts) >= 2:
                                buyer_name = ' '.join(buyer_name_parts[:2])
                            else:
                                buyer_name = buyer_line
                        continue
                    # Extract SKU and Quantity
                    if 'TITEL' in line and 'ARTIKELNUMMER' in line:
                        # Process the lines after this header
                        for j in range(i + 1, len(lines)):
                            data_line = lines[j].strip()
                            if not data_line:
                                continue
                            # Check if line contains SKU
                            if re.match(r'^[A-Z0-9.-]{5,}$', data_line):
                                sku = data_line
                                # Now look for quantity
                                quantity_found = False
                                for k in range(j, j + 5):
                                    if k >= len(lines):
                                        break
                                    line_to_check = lines[k].strip()
                                    if not line_to_check:
                                        continue
                                    # Look for pattern: number before percentage sign
                                    qty_match = re.search(r'\b(\d+)\b\s*\d+%.*', line_to_check)
                                    if qty_match:
                                        quantity = qty_match.group(1)
                                        quantity_found = True
                                        break
                                if not quantity_found:
                                    quantity = ''
                                break
                        continue
                return {
                    'Order number': order_number,
                    'Order date': order_date,
                    'Buyer\'s name': buyer_name,
                    'SKU': sku,
                    'Quantity': quantity,
                    'Delivery service': 'Unknown'
                }

            data = extract_data_from_text(text)
            data_list.append(data)

            # Delete the temporary file
            default_storage.delete(temp_pdf_path)

        if not data_list:
            return HttpResponse('No data extracted from the uploaded PDFs.')

        # Create DataFrame and save to Excel
        df = pd.DataFrame(data_list)

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
        response['Content-Disposition'] = f'attachment; filename=ampm_orders_{uuid.uuid4().hex}.xlsx'

        return response
    else:
        # If GET request or no files uploaded, render the upload page
        html_form = '''
        <!DOCTYPE html>
        <html>
        <body>
        <h2>Upload PDFs for AMPM</h2>
        <form action="" method="post" enctype="multipart/form-data">
            <!-- {% csrf_token %} -->
            <input type="file" name="pdf_files_new" multiple required>
            <input type="submit" value="Upload">
        </form>
        </body>
        </html>
        '''
        return HttpResponse(html_form)


def upload_and_download(request):
    if request.method == 'POST':
        if 'home24_submit' in request.POST and request.FILES.getlist('pdf_files_home24'):
            # Handle Home24 form submission
            return upload_pdfs_home24(request)
        elif 'mano_submit' in request.POST and request.FILES.getlist('pdf_files_mano'):
            # Handle Mano form submission
            return upload_pdfs_mano(request)
        elif 'ampm_submit' in request.POST and request.FILES.getlist('pdf_files_new'):
            # Handle AMPM form submission
            return upload_pdfs_new_functionality(request)
        elif 'existing_submit' in request.POST and request.FILES.getlist('pdf_files'):
            # Handle existing functionality
            return upload_pdfs(request)
        # ... handle other forms ...
    else:
        # Render your upload and download template
        return render(request, 'locator/upload_and_download.html')