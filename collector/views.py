from django.core.checks import Info
from django.core.paginator import Paginator
from django.shortcuts import render

from .models import UsefulInfo


def info_list(request):
    infos = Info.objects.all().order_by('title')  # Default ordering

    # Pagination
    paginator = Paginator(infos, 10)  # Show 10 infos per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'infos': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'page_obj': page_obj,
        'paginator': paginator,
    }
    return render(request, 'info.html', context)