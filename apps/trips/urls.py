from django.urls import path

from apps.accounts.views import health
from apps.disputes import views as dispute_views
from apps.expenses import views as expense_views

from . import history_views, invite_views, views

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", health, name="health"),
    path("trips/new/", views.trip_create, name="trip_create"),
    path("trips/<uuid:trip_id>/", expense_views.expense_list, name="trip"),
    path("trips/<uuid:trip_id>/expenses/new/", expense_views.expense_create, name="expense_create"),
    path(
        "trips/<uuid:trip_id>/expenses/ai-fill/",
        expense_views.expense_ai_fill,
        name="expense_ai_fill",
    ),
    path(
        "trips/<uuid:trip_id>/expenses/suggest/",
        expense_views.description_suggestion,
        name="description_suggestion",
    ),
    path(
        "trips/<uuid:trip_id>/expenses/reorder/",
        expense_views.expense_reorder,
        name="expense_reorder",
    ),
    path(
        "trips/<uuid:trip_id>/expenses/<uuid:expense_id>/",
        expense_views.expense_edit,
        name="expense_edit",
    ),
    path(
        "trips/<uuid:trip_id>/expenses/<uuid:expense_id>/delete/",
        expense_views.expense_delete,
        name="expense_delete",
    ),
    path("trips/<uuid:trip_id>/types/", expense_views.category_create, name="category_create"),
    path(
        "trips/<uuid:trip_id>/types/<int:category_id>/",
        expense_views.category_edit,
        name="category_edit",
    ),
    path(
        "trips/<uuid:trip_id>/types/<int:category_id>/delete/",
        expense_views.category_delete,
        name="category_delete",
    ),
    path(
        "trips/<uuid:trip_id>/expenses/<uuid:expense_id>/restore/",
        expense_views.expense_restore,
        name="expense_restore",
    ),
    path(
        "trips/<uuid:trip_id>/expenses/<uuid:expense_id>/disputes/",
        dispute_views.dispute_open,
        name="dispute_open",
    ),
    path(
        "trips/<uuid:trip_id>/disputes/<int:dispute_id>/messages/",
        dispute_views.dispute_write,
        name="dispute_write",
    ),
    path(
        "trips/<uuid:trip_id>/disputes/<int:dispute_id>/resolve/",
        dispute_views.dispute_resolve,
        name="dispute_resolve",
    ),
    path(
        "trips/<uuid:trip_id>/disputes/<int:dispute_id>/close/",
        dispute_views.dispute_close,
        name="dispute_close",
    ),
    path("notifications/", dispute_views.notification_list, name="notifications"),
    path("trips/<uuid:trip_id>/history/", history_views.history_page, name="history"),
    path("trips/<uuid:trip_id>/summary/", views.summary, name="summary"),
    path("trips/<uuid:trip_id>/settle/", views.trip_settle, name="trip_settle"),
    path("trips/<uuid:trip_id>/reopen/", views.trip_reopen, name="trip_reopen"),
    path("trips/<uuid:trip_id>/report/", expense_views.report, name="report"),
    path(
        "trips/<uuid:trip_id>/report/export.<str:fmt>",
        expense_views.report_export,
        name="report_export",
    ),
    path("trips/<uuid:trip_id>/people/", views.people, name="people"),
    path("trips/<uuid:trip_id>/people/new/", views.participant_create, name="participant_create"),
    path(
        "trips/<uuid:trip_id>/people/<uuid:participant_id>/",
        views.participant_edit,
        name="participant_edit",
    ),
    path(
        "trips/<uuid:trip_id>/people/<uuid:participant_id>/delete/",
        views.participant_delete,
        name="participant_delete",
    ),
    path("trips/<uuid:trip_id>/invites/new/", views.invite_new, name="invite_new"),
    path(
        "trips/<uuid:trip_id>/invites/<int:invite_id>/copy/",
        views.invite_copy,
        name="invite_copy",
    ),
    path(
        "trips/<uuid:trip_id>/invites/<int:invite_id>/resend/",
        views.invite_resend,
        name="invite_resend",
    ),
    path(
        "trips/<uuid:trip_id>/invites/<int:invite_id>/cancel/",
        views.invite_cancel,
        name="invite_cancel",
    ),
    path("trips/<uuid:trip_id>/leave/", views.trip_leave, name="trip_leave"),
    path("invite/<str:token>/", invite_views.invite_page, name="invite"),
    # The removed shared invite link: old addresses say that it no longer works.
    path("join/<str:token>/", invite_views.old_join_link, name="join"),
    path("trips/<uuid:trip_id>/members/<int:member_id>/", views.member_edit, name="member_edit"),
    path(
        "trips/<uuid:trip_id>/members/<int:member_id>/owner/",
        views.member_transfer,
        name="member_transfer",
    ),
    path(
        "trips/<uuid:trip_id>/members/<int:member_id>/remove/",
        views.member_remove,
        name="member_remove",
    ),
    path("trips/<uuid:trip_id>/settings/", views.trip_settings, name="trip_settings"),
    path("trips/<uuid:trip_id>/settings/rates/", views.rate_save, name="rate_save"),
    path(
        "trips/<uuid:trip_id>/settings/rates/<int:rate_id>/delete/",
        views.rate_delete,
        name="rate_delete",
    ),
    path("trips/<uuid:trip_id>/delete/", views.trip_delete, name="trip_delete"),
]
