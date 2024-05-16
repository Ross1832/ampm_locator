from django.contrib import admin

from .models import UsefulInfo


@admin.register(UsefulInfo)
class UsefulInfoAdmin(admin.ModelAdmin):
    list_display = ("title", "description", "created_at")
    search_fields = ("title", "description")
