from django.apps import AppConfig
from django.db.models.signals import post_save


class ExpensesConfig(AppConfig):
    name = "apps.expenses"

    def ready(self):
        from apps.trips.models import Trip

        post_save.connect(_new_trip_gets_default_types, sender=Trip, dispatch_uid="default_types")


def _new_trip_gets_default_types(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        from .models import add_default_categories

        add_default_categories(instance)
