from django.shortcuts import render

from .models import UsefulInfo


def index(request):
    infos = UsefulInfo.objects.all().order_by(
        "-created_at"
    )
    return render(request, "collector/info.html", {"infos": infos})
