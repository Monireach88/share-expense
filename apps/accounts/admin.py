from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "is_active", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser")
    ordering = ("is_active", "-date_joined")
    actions = ["approve"]

    @admin.action(description=_("Approve selected sign-up requests"))
    def approve(self, request, queryset):
        count = queryset.filter(is_active=False).update(is_active=True)
        self.message_user(
            request, _("%(count)d account(s) approved.") % {"count": count}, messages.SUCCESS
        )
