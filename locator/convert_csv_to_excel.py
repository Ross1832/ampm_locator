import csv
import datetime
import io

import pandas as pd
from django.core.files.storage import FileSystemStorage
from django.http import HttpResponse
from django.shortcuts import render

# Mapping of German month names to numbers
month_mapping = {
    "Jan": "01", "Feb": "02", "Mär": "03", "Apr": "04", "Mai": "05", "Jun": "06",
    "Jul": "07", "Aug": "08", "Sep": "09", "Okt": "10", "Nov": "11", "Dez": "12"
}


def convert_date(date_str):
    try:
        day, month, year = date_str.split('-')
        month_number = month_mapping[month]
        return f"{day}.{month_number}.20{year}"
    except Exception:
        try:
            if " " in date_str:
                date_str = date_str.split(" ")[0]
            date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            return date_obj.strftime("%d.%m.%Y")
        except Exception:
            return date_str


def process_ebay_csv(file_content):
    lines = file_content.splitlines()
    relevant_lines = lines[1:]
    reader = csv.DictReader(relevant_lines, delimiter=';', quotechar='"')

    headers = reader.fieldnames
    print("Headers:", headers)

    normalized_headers = {header.strip().lower(): header.strip() for header in headers if header.strip()}
    print("Normalized Headers:", normalized_headers)

    required_headers = ['verkauft am', 'bestellnummer', 'name des käufers', 'bestandseinheit', 'anzahl']
    for header in required_headers:
        if header not in normalized_headers:
            raise KeyError(f"Required header '{header}' not found in CSV file headers: {headers}")

    data = []
    for row in reader:
        date_str = row[normalized_headers['verkauft am']].strip() if row[normalized_headers['verkauft am']] else ''
        date = convert_date(date_str)
        order_number = row[normalized_headers['bestellnummer']].strip() if row[normalized_headers['bestellnummer']] else ''
        customer_name = row[normalized_headers['name des käufers']].strip() if row[normalized_headers['name des käufers']] else ''
        item = row[normalized_headers['bestandseinheit']].strip() if row[normalized_headers['bestandseinheit']] else ''
        quantity = row[normalized_headers['anzahl']].strip() if row[normalized_headers['anzahl']] else ''

        data.append({
            'store_name': 'Ebay',
            'date': date,
            'order_number': order_number,
            'customer_name': customer_name,
            'item': item,
            'quantity': quantity
        })

    return data


def process_shopify_csv(file_content):
    lines = file_content.splitlines()
    reader = csv.DictReader(lines)

    headers = reader.fieldnames
    print("Headers:", headers)

    normalized_headers = {header.strip().lower(): header.strip() for header in headers if header.strip()}
    print("Normalized Headers:", normalized_headers)

    required_headers = ['created at', 'name', 'billing name', 'lineitem sku', 'lineitem quantity']
    for header in required_headers:
        if header not in normalized_headers:
            raise KeyError(f"Required header '{header}' not found in CSV file headers: {headers}")

    data = []
    for row in reader:
        date_str = row[normalized_headers['created at']].strip() if row[normalized_headers['created at']] else ''
        date = convert_date(date_str)
        order_number = row[normalized_headers['name']].strip() if row[normalized_headers['name']] else ''
        customer_name = row[normalized_headers['billing name']].strip() if row[normalized_headers['billing name']] else ''
        item = row[normalized_headers['lineitem sku']].strip() if row[normalized_headers['lineitem sku']] else ''
        quantity = row[normalized_headers['lineitem quantity']].strip() if row[normalized_headers['lineitem quantity']] else ''

        data.append({
            'store_name': 'Shopify',
            'date': date,
            'order_number': order_number,
            'customer_name': customer_name,
            'item': item,
            'quantity': quantity
        })

    return data


def upload_and_download(request):
    ebay_excel_file_url = None
    shopify_excel_file_url = None
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES.get('csv_file')
        fs = FileSystemStorage()
        filename = fs.save(csv_file.name, csv_file)
        uploaded_file_url = fs.url(filename)

        with fs.open(filename) as csvfile:
            file_content = csvfile.read().decode('utf-8-sig')

            if 'process_ebay' in request.POST:
                data = process_ebay_csv(file_content)
                store_name = 'ebay'
            elif 'process_shopify' in request.POST:
                data = process_shopify_csv(file_content)
                store_name = 'shopify'
            else:
                raise ValueError("Invalid form submission")

        df = pd.DataFrame(data)
        excel_buffer = io.BytesIO()
        df.to_excel(excel_buffer, index=False)
        excel_buffer.seek(0)

        excel_filename = f'orders_{store_name}_{datetime.date.today()}.xlsx'
        with fs.open(excel_filename, 'wb') as f:
            f.write(excel_buffer.getvalue())

        if store_name == 'ebay':
            ebay_excel_file_url = fs.url(excel_filename)
        elif store_name == 'shopify':
            shopify_excel_file_url = fs.url(excel_filename)

    return render(request, 'locator/upload_and_download.html', {
        'ebay_excel_file_url': ebay_excel_file_url,
        'shopify_excel_file_url': shopify_excel_file_url
    })
