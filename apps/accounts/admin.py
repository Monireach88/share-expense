from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _

from apps.trips.models import TripMember

from .models import User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    list_display = ("username", "first_name", "is_active", "closed", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser")
    ordering = ("is_active", "-date_joined")
    actions = ["approve", "restore"]
    readonly_fields = ("closed_at",)
    fieldsets = (*UserAdmin.fieldsets, (_("Closed"), {"fields": ("closed_at",)}))

    @admin.display(boolean=True, description=_("closed"), ordering="closed_at")
    def closed(self, user) -> bool:
        return user.closed_at is not None

    def get_deleted_objects(self, objs, request):
        """Refuse to delete an account that owns a trip, so a trip never loses its owner.

        The delete page and the "delete selected" action both ask this method; a non-empty
        ``protected`` list makes Django show the reason and offer no Delete button.
        """
        to_delete, model_count, perms_needed, protected = super().get_deleted_objects(objs, request)
        owned = TripMember.objects.filter(
            user__in=list(objs), role=TripMember.Role.OWNER
        ).select_related("trip", "user")
        protected = list(protected) + [
            _("Trip “%(trip)s”, owned by %(user)s: make someone else its Owner first.")
            % {"trip": m.trip.name, "user": m.user.username}
            for m in owned
        ]
        return to_delete, model_count, perms_needed, protected

    @admin.action(description=_("Approve selected sign-up requests"))
    def approve(self, request, queryset):
        """Closed accounts are skipped: only "restore" opens them again."""
        count = queryset.filter(is_active=False, closed_at__isnull=True).update(is_active=True)
        self.message_user(
            request, _("%(count)d account(s) approved.") % {"count": count}, messages.SUCCESS
        )

    @admin.action(description=_("Restore selected closed accounts"))
    def restore(self, request, queryset):
        count = queryset.filter(closed_at__isnull=False).update(closed_at=None, is_active=True)
        self.message_user(
            request, _("%(count)d account(s) restored.") % {"count": count}, messages.SUCCESS
        )
