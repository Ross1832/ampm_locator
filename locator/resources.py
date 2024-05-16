import logging

from import_export import fields, resources
from import_export.results import RowResult
from import_export.widgets import ForeignKeyWidget

from .models import Item, Order

logger = logging.getLogger(__name__)


class OrderResource(resources.ModelResource):
    store_name = fields.Field(attribute="store_name", column_name="store_name")
    date = fields.Field(attribute="date", column_name="date")
    order_number = fields.Field(attribute="order_number", column_name="order_number")
    customer_name = fields.Field(attribute="customer_name", column_name="customer_name")
    item = fields.Field(
        attribute="item", column_name="item", widget=ForeignKeyWidget(Item, "number")
    )
    quantity = fields.Field(attribute="quantity", column_name="quantity")
    status = fields.Field(attribute="status", column_name="status", default="INP")
    notes = fields.Field(attribute="notes", column_name="notes", default="")

    class Meta:
        model = Order
        import_id_fields = ["order_number"]
        skip_unchanged = True
        report_skipped = True
        exclude = ("id",)

    def before_import_row(self, row, **kwargs):
        try:
            item_number = row["item"].strip()  # Обеспечиваем удаление лишних пробелов
            item = Item.objects.get(number=item_number)
            row["item"] = item
        except Item.DoesNotExist:
            logger.error(f"Item with number '{item_number}' not found")
            row["item"] = None
            raise ValueError(f"Item with number '{item_number}' not found")

    def after_save_instance(self, instance, using_transactions, dry_run):
        if not dry_run:
            logger.info(f"Saved order: {instance.order_number}")

    def import_row(self, row, instance_loader, **kwargs):
        try:
            return super().import_row(row, instance_loader, **kwargs)
        except ValueError as e:
            logger.error(f"Error importing row {row}: {str(e)}")
            return {"import_type": RowResult.IMPORT_TYPE_ERROR, "errors": [(e, row)]}
