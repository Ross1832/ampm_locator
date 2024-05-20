import logging

import pandas as pd
from dateutil import parser

from .models import Item, Order, OrderItem

logger = logging.getLogger(__name__)


def handle_uploaded_file(file):
    df = pd.read_excel(file, engine='openpyxl')

    results = []
    for idx, row in df.iterrows():
        item_str = row['item']
        quantity = row['quantity']

        model_prefix = item_str[:3]
        number = item_str[3:]

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
                'item': item_str,
                'status': 'Created',
                'quantity': quantity
            })
        else:
            item.quantity = quantity
            item.save()
            results.append({
                'row': idx + 2,
                'item': item_str,
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

        model_prefix = item_str[:3]
        number = item_str[3:]

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
                'item': item_str,
                'status': 'Updated',
                'quantity': item.quantity
            })
            logger.debug(f"Row {idx + 2}: Incremented item {item_str} by {quantity}, new quantity {item.quantity}")

    return results


def process_excel_data(data): #standart uplaod functionality
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


