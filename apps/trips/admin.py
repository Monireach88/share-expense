from django.contrib import admin

from .models import HistoryEntry


@admin.register(HistoryEntry)
class HistoryEntryAdmin(admin.ModelAdmin):
    """History shown read-only: nobody adds, changes or deletes an entry, not even in the admin."""

    list_display = ("created_at", "trip", "actor_name", "action", "object_type", "object_label")
    list_filter = ("object_type", "action")
    search_fields = ("search_text",)
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
