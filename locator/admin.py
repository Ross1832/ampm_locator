from django.contrib import admin

from .models import Item, Order, OrderItem

admin.site.register(Item)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 1


class OrderAdmin(admin.ModelAdmin):
    inlines = [OrderItemInline]

    def items_with_quantities(self, obj):
        items = (
            obj.orderitem_set.all()
        )
        return ", ".join([f"{item.item} ({item.quantity})" for item in items])

    items_with_quantities.short_description = (
        "Items (Quantity)"
    )

    list_display = (
        "store_name",
        "date",
        "order_number",
        "items_with_quantities",
        "customer_name",
        "status",
    )
    search_fields = ["order_number", "customer_name", "store_name"]


admin.site.register(Order, OrderAdmin)


class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "item", "quantity")
    search_fields = ["order__order_number", "item__model_prefix"]


admin.site.register(OrderItem, OrderItemAdmin)
