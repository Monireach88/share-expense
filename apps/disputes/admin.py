from django.contrib import admin

from .models import Dispute, DisputeMessage, Notification


class DisputeMessageInline(admin.TabularInline):
    model = DisputeMessage
    extra = 0
    readonly_fields = ("author_name", "text", "created_at")
    fields = readonly_fields
    can_delete = False


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    """Shown read-only: disputes change only through the trip pages, where History records them."""

    list_display = ("created_at", "trip", "opened_by_name", "state")
    list_filter = ("state",)
    inlines = [DisputeMessageInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "trip", "kind", "read_at")
    list_filter = ("kind",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
