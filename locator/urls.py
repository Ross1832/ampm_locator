from django.urls import path

from .views import (
    CompleteOrderView,
    HoldOrderView,
    OrderListView,
    collect_items,
    fetch_model_numbers,
    finalize_items,
    select_model,
    set_item,
    update_order_status,
    upload_orders,
)

urlpatterns = [
    path("locator/", set_item, name="set_item"),
    path("select-model/", select_model, name="select-model"),
    path("fetch-model-numbers/", fetch_model_numbers, name="fetch-model-numbers"),
    path("finalize-items/", finalize_items, name="finalize-items"),
    ########
    path(
        "orders/", OrderListView.as_view(), name="order_list"
    ),  # URL for the orders list view
    path("update-order-status/", update_order_status, name="update_order_status"),
    # URL for updating order status via AJAX
    path(
        "collect-items/", collect_items, name="collect_items"
    ),  # URL for collecting items via AJAX
    path(
        "complete-order/<int:pk>/", CompleteOrderView.as_view(), name="complete_order"
    ),
    # URL for marking an order as complete
    path("hold-order/<int:pk>/", HoldOrderView.as_view(), name="hold_order"),
    #######
    path("upload/", upload_orders, name="upload_orders"),
]
