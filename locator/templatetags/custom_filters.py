# custom_filters.py

from django import template

register = template.Library()


@register.filter
def get_status_display(status_code, status_dict):
    return status_dict.get(status_code, "Unknown Status")
