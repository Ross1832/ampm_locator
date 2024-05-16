from django.db import models


class Item(models.Model):
    MODEL_CHOICES = [
        ("FTA", "FTA"),
        ("FBA", "FBA"),
        ("FXA", "FXA"),
        ("FGA", "FGA"),
        ("FNA", "FNA"),
        ("AIB", "AIB"),
        ("AGA", "AGA"),
    ]
    model_prefix = models.CharField(max_length=3, choices=MODEL_CHOICES)
    number = models.CharField(max_length=10)
    line = models.PositiveIntegerField(null=True)
    place = models.PositiveIntegerField(null=True)
    quantity = models.IntegerField(default=1)

    class Meta:
        ordering = ["line", "place"]

    def __str__(self):
        return f"{self.model_prefix}{self.number}"


class Order(models.Model):
    STATUS_CHOICES = [
        ("DEL", "Delivered"),
        ("INP", "In Progress"),
        ("ONH", "On Hold"),
        ("CAN", "Cancelled"),
        ("COM", "Completed"),
    ]

    store_name = models.CharField(max_length=255)
    date = models.DateField()
    order_number = models.CharField(max_length=20, unique=True)
    customer_name = models.CharField(max_length=255)
    items = models.ManyToManyField(Item, through="OrderItem")
    status = models.CharField(max_length=3, choices=STATUS_CHOICES, default="INP")
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Order {self.order_number} from {self.store_name} - {self.get_status_display()}"

    def get_items_display(self):
        return ", ".join([str(item) for item in self.items.all()])

    get_items_display.short_description = "Items"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    quantity = models.IntegerField()

    def __str__(self):
        return f"Order: {self.order.order_number}, Item: {self.item}, Quantity: {self.quantity}"
