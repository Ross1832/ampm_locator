from django.shortcuts import render

from .models import UsefulInfo


def index(request):
    infos = UsefulInfo.objects.all().order_by("-created_at")
    page_numbers = range(1, (infos.count() // 10) + 2)  # Example pagination
    return render(request, "collector/info.html", {"infos": infos, "page_numbers": page_numbers})
