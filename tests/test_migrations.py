from datetime import date

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_old_fixed_types_become_each_trips_own_types():
    executor = MigrationExecutor(connection)
    before = [("expenses", "0005_expense_position"), ("trips", "0003_trip_settled_at")]
    executor.migrate(before)
    old = executor.loader.project_state(before).apps
    trip = old.get_model("trips", "Trip").objects.create(name="Old trip", base_currency="USD")
    payer = old.get_model("trips", "Participant").objects.create(trip=trip, name="Person A")
    expense_model = old.get_model("expenses", "Expense")
    taxi = expense_model.objects.create(
        trip=trip,
        payer=payer,
        amount=5,
        currency="USD",
        date=date(2026, 6, 1),
        category="transport",
    )

    executor = MigrationExecutor(connection)
    executor.migrate([("expenses", "0006_custom_types")])
    new = executor.loader.project_state([("expenses", "0006_custom_types")]).apps
    categories = new.get_model("expenses", "Category").objects.filter(trip_id=trip.pk)
    assert categories.count() == 8
    assert new.get_model("expenses", "Expense").objects.get(pk=taxi.pk).category.name == "Transport"

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
