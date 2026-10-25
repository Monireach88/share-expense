from django.contrib import admin
from django.urls import include, path
from django.utils.translation import gettext_lazy as _

# Keep Django's own admin look (responsive, dark mode, updated with Django); only name it.
admin.site.site_header = _("Share Expense admin")
admin.site.site_title = _("Share Expense admin")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.trips.urls")),
]
