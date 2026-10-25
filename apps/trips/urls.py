from django.urls import path

from apps.accounts.views import health
from apps.expenses import views as expense_views

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", health, name="health"),
    path("trips/new/", views.trip_create, name="trip_create"),
    path("trips/<uuid:trip_id>/", expense_views.expense_list, name="trip"),
    path("trips/<uuid:trip_id>/expenses/new/", expense_views.expense_create, name="expense_create"),
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
    path("trips/<uuid:trip_id>/summary/", views.summary, name="summary"),
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
