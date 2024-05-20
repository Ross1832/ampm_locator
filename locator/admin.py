from django.contrib import admin

from .models import Item, Order, OrderItem


class ItemAdmin(admin.ModelAdmin):
    list_display = ('item', 'quantity', 'updated_at')
    search_fields = ('model_prefix', 'number', 'quantity')
    list_filter = ('model_prefix',)
    ordering = ('-updated_at', 'quantity')
    list_per_page = 30

    def item(self, obj):
        return f"{obj.model_prefix}{obj.number}"

    item.short_description = 'Item'


admin.site.register(Item, ItemAdmin)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1


class OrderAdmin(admin.ModelAdmin):
    inlines = [OrderItemInline]

    def items_with_quantities(self, obj):
        items = obj.orderitem_set.all()
        return ", ".join([f"{item.item.model_prefix}{item.item.number} ({item.quantity})" for item in items])

    items_with_quantities.short_description = "Items (Quantity)"

    list_display = (
        "store_name",
        "date",
        "order_number",
        "items_with_quantities",
        "customer_name",
        "status",
        "created_at",
        "updated_at",
    )

    search_fields = ["order_number", "customer_name", "store_name"]
    list_filter = ["status", "store_name", "date"]
    ordering = ["-date"]
    list_editable = ["status"]
    list_display_links = ["order_number"]


admin.site.register(Order, OrderAdmin)


class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "item_display", "quantity")
    search_fields = ["order__order_number", "item__model_prefix", "item__number"]

    def item_display(self, obj):
        return f"{obj.item.model_prefix}{obj.item.number}"

    item_display.short_description = 'Item'



