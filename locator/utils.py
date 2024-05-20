import logging

import pandas as pd
from dateutil import parser
from django.utils import timezone
from .models import Item, Order, OrderItem

logger = logging.getLogger(__name__)


def handle_uploaded_file(file):
    df = pd.read_excel(file, engine='openpyxl')

    results = []
    for idx, row in df.iterrows():
        item_str = row['item']
        quantity = row['quantity']

        # Extract the item code
        item_code = item_str.split()[0]
        model_prefix = item_code[:3]
        number = item_code[3:]

        if model_prefix not in dict(Item.MODEL_CHOICES):
            results.append({
                'row': idx + 2,
                'item': item_str,
                'status': 'Failed',
                'reason': f"Invalid model prefix: {model_prefix}"
            })
            continue

        item = Item.objects.filter(model_prefix=model_prefix, number=number).first()
        if not item:
            Item.objects.create(
                model_prefix=model_prefix,
                number=number,
                line=None,
                place=None,
                quantity=quantity
            )
            results.append({
                'row': idx + 2,
                'item': item_code,
                'status': 'Created',
                'quantity': quantity
            })
        else:
            item.quantity = quantity
            item.save()
            results.append({
                'row': idx + 2,
                'item': item_code,
                'status': 'Set new quantity',
                'quantity': quantity
            })

    return results


def handle_update_file(file):
    df = pd.read_excel(file, engine='openpyxl')

    results = []
    for idx, row in df.iterrows():
        item_str = row['item']
        quantity = row['quantity']

        # Extract the item code
        item_code = item_str.split()[0]
        model_prefix = item_code[:3]
        number = item_code[3:]

        if model_prefix not in dict(Item.MODEL_CHOICES):
            results.append({
                'row': idx + 2,
                'item': item_str,
                'status': 'Failed',
                'reason': f"Invalid model prefix: {model_prefix}"
            })
            logger.debug(f"Row {idx + 2}: Invalid model prefix: {model_prefix}")
            continue

        item = Item.objects.filter(model_prefix=model_prefix, number=number).first()
        if not item:
            results.append({
                'row': idx + 2,
                'item': item_str,
                'status': 'Failed',
                'reason': 'Item does not exist'
            })
            logger.debug(f"Row {idx + 2}: Item {item_str} does not exist")
        else:
            item.quantity += quantity
            item.save()
            results.append({
                'row': idx + 2,
                'item': item_code,
                'status': 'Updated',
                'quantity': item.quantity
            })
            logger.debug(f"Row {idx + 2}: Incremented item {item_code} by {quantity}, new quantity {item.quantity}")

    return results


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

        items = order_info["item"].split(",")
        quantities = order_info["quantity"].split(",")

        if len(items) != len(quantities):
            results["error_orders"].append(
                (order_number, f"Row {index + 2}: Mismatch between items and quantities")
            )
            continue

        # Validate all items before creating the order
        all_items_exist = True
        for item_code in items:
            try:
                Item.objects.get(
                    model_prefix=item_code[:3] if item_code else "",
                    number=item_code[3:] if item_code else "",
                )
            except Item.DoesNotExist:
                results["error_orders"].append(
                    (order_number, f"Row {index + 2}: Item {item_code} does not exist")
                )
                all_items_exist = False
                break

        if not all_items_exist:
            continue

        try:
            order = Order.objects.create(
                store_name=order_info["store_name"],
                date=date,
                order_number=order_number,
                customer_name=order_info["customer_name"],
                status="INP",
                created_at=timezone.now(),
                updated_at=timezone.now()
            )

            for item_code, qty in zip(items, quantities):
                item = Item.objects.get(
                    model_prefix=item_code[:3] if item_code else "",
                    number=item_code[3:] if item_code else "",
                )
                OrderItem.objects.create(
                    order=order, item=item, quantity=int(qty.strip())
                )
                results["order_details"].append(
                    {
                        "store_name": order_info["store_name"],
                        "date": order_info["date"],
                        "order_number": order_number,
                        "customer_name": order_info["customer_name"],
                        "item": item_code.strip(),
                        "quantity": qty.strip(),
                        "status": "Created",
                    }
                )

            results["new_orders"].append(order_number)

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
