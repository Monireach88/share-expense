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


@pytest.mark.django_db(transaction=True)
def test_the_shared_invite_link_is_cleared_and_dropped_on_existing_data():
    """Spec section 6.4: old links, remembered links and removal marks go; trips and accounts
    stay, and accounts still waiting for approval keep waiting."""
    before = [("trips", "0006_invite_link"), ("accounts", "0002_username_rules")]
    executor = MigrationExecutor(connection)
    executor.migrate(before)
    old = executor.loader.project_state(before).apps
    user_model = old.get_model("accounts", "User")
    owner = user_model.objects.create(username="person_a", password="x")
    waiting = user_model.objects.create(
        username="person_b", password="x", is_active=False, invite_token="abc"
    )
    trip = old.get_model("trips", "Trip").objects.create(name="Old trip", invite_token="tok")
    old.get_model("trips", "RemovedAccount").objects.create(trip=trip, user=waiting)

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    from django.contrib.auth import get_user_model

    from apps.trips.models import Invite, Trip

    assert Trip.objects.get(pk=trip.pk).name == "Old trip"
    users = get_user_model().objects
    assert users.get(pk=owner.pk).closed_at is None
    assert not users.get(pk=waiting.pk).is_active and users.get(pk=waiting.pk).closed_at is None
    assert not Invite.objects.exists()
    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
        columns = [
            c.name for c in connection.introspection.get_table_description(cursor, "trips_trip")
        ]
    assert "trips_removedaccount" not in tables and "invite_token" not in columns
