from django.contrib import admin
from django.urls import include, path
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import AdminLoginForm
from apps.trips.offline import favicon, service_worker, web_manifest

# Keep Django's own admin look (responsive, dark mode, updated with Django); only name it.
admin.site.site_header = _("Share Expense admin")
admin.site.site_title = _("Share Expense admin")
admin.site.login_form = AdminLoginForm

urlpatterns = [
    path("sw.js", service_worker, name="service_worker"),
    path("manifest.webmanifest", web_manifest, name="web_manifest"),
    path("favicon.ico", favicon, name="favicon"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.trips.urls")),
]
