"""History (spec section 3): every change is recorded, the page, search, and Restore.

Same crew as the role tests: Ann owns the trip, Ben is an Editor, Cara and Dan are Members,
Eve is a Member with no traveler.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib import admin
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.expenses.models import Category, Expense
from apps.trips import history
from apps.trips.admin import HistoryEntryAdmin
from apps.trips.models import ExchangeRate, HistoryEntry, Trip
from tests.test_roles import Crew

pytestmark = pytest.mark.django_db


@pytest.fixture
def crew(db):
    return Crew()


def lines(crew) -> list[str]:
    """The History sentences of the trip, oldest first."""
    return [history.describe(e) for e in reversed(list(crew.trip.history.all()))]


def last_line(crew) -> str:
    return history.describe(crew.trip.history.first())


def delete(crew, who, expense):
    return crew.client(who).post(crew.url("expense_delete", expense.id))


def restore(crew, who, expense):
    return crew.client(who).post(crew.url("expense_restore", expense.id), follow=True)


# --- Gherkin scenarios of spec section 3 ---------------------------------------------------------


def test_every_expense_change_is_recorded_with_old_and_new_values(crew):
    crew.client("ben").post(crew.url("expense_create"), crew.form("dan", "40", "Dinner"))
    dinner = crew.trip.expenses.get(description="Dinner")
    crew.client("ben").post(crew.url("expense_edit", dinner.id), crew.form("dan", "4", "Dinner"))
    assert last_line(crew) == "Ben changed “Dinner”: amount 40.00 USD → 4.00 USD"
    page = crew.client("cara").get(crew.url("history")).content.decode()
    assert "Ben changed “Dinner”: amount 40.00 USD → 4.00 USD" in page


def test_history_cannot_be_changed(crew):
    crew.client("ann").post(crew.url("expense_create"), crew.form("ann"))
    entry = crew.trip.history.get()
    request = RequestFactory().get("/")
    request.user = crew.users["ann"]
    request.user.is_superuser = True
    model_admin = HistoryEntryAdmin(HistoryEntry, admin.site)
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request, entry)
    assert not model_admin.has_delete_permission(request, entry)
    with pytest.raises(TypeError):
        entry.save()
    with pytest.raises(TypeError):
        entry.delete()
    with pytest.raises(TypeError):
        crew.trip.history.all().update(actor_name="x")
    with pytest.raises(TypeError):
        crew.trip.history.all().delete()
    # No address accepts a change: the History page answers only GET.
    assert crew.client("ann").post(crew.url("history"), {"x": 1}).status_code in (200, 405)
    assert crew.trip.history.count() == 1


def test_a_member_restores_her_own_deleted_expense(crew):
    taxi = crew.expense("cara", "Taxi", "12")
    delete(crew, "cara", taxi)
    assert not crew.trip.expenses.filter(pk=taxi.pk).exists()
    page = crew.client("cara").get(crew.url("expense_edit", taxi.id)).content.decode()
    assert "Taxi" in page and "Restore expense" in page
    response = restore(crew, "cara", taxi)
    assert "Restored: Taxi" in response.content.decode()
    taxi.refresh_from_db()
    assert taxi.deleted_at is None and taxi.amount == Decimal("12")
    assert crew.trip.expenses.filter(pk=taxi.pk).exists()
    assert last_line(crew).startswith("Cara restored “Taxi”")


def test_a_member_cannot_restore_someone_elses_expense(crew):
    hotel = crew.expense("dan", "Hotel", "90")
    delete(crew, "ben", hotel)
    page = crew.client("cara").get(crew.url("expense_edit", hotel.id)).content.decode()
    assert "Hotel" in page and "Restore expense" not in page
    assert crew.client("cara").post(crew.url("expense_restore", hotel.id)).status_code == 403
    hotel.refresh_from_db()
    assert hotel.deleted_at is not None


def test_restore_is_refused_when_a_rate_is_missing(crew):
    rate = ExchangeRate.objects.create(trip=crew.trip, currency="VND", rate=Decimal("25000"))
    noodles = crew.expense("dan", "Noodles", "100000", currency="VND")
    delete(crew, "ben", noodles)
    rate.delete()
    response = restore(crew, "ben", noodles)
    assert "Not restored. Add these first: the VND rate." in response.content.decode()
    noodles.refresh_from_db()
    assert noodles.deleted_at is not None
    ExchangeRate.objects.create(trip=crew.trip, currency="VND", rate=Decimal("25000"))
    restore(crew, "ben", noodles)
    noodles.refresh_from_db()
    assert noodles.deleted_at is None


def test_search_finds_entries_by_type(crew):
    transport = crew.trip.categories.get(name="Transport")
    crew.client("ann").post(
        crew.url("expense_create"), {**crew.form("ann", "5", "Bus"), "category": transport.id}
    )
    crew.client("ann").post(crew.url("expense_create"), crew.form("ann", "9", "Pho"))
    page = crew.client("cara").get(crew.url("history"), {"q": "transport"}).content.decode()
    assert "Bus" in page and "Pho" not in page


def test_entries_survive_a_renamed_traveler(crew):
    crew.client("ann").post(crew.url("expense_create"), crew.form("dan", "60", "Dinner"))
    crew.client("ann").post(
        crew.url("participant_edit", crew.travelers["dan"].id), {"name": "Daniel"}
    )
    all_lines = lines(crew)
    assert "Ann added “Dinner”: 60.00 USD, paid by Dan" in all_lines[0]
    assert all_lines[1] == "Ann renamed traveler Dan → Daniel"
    assert "paid by Dan" in crew.client("cara").get(crew.url("history")).content.decode()


def test_history_opens_an_expense_on_a_settled_trip(crew):
    crew.client("ann").post(crew.url("expense_create"), crew.form("ann", "7", "Coffee"))
    coffee = crew.trip.expenses.get(description="Coffee")
    crew.client("ann").post(crew.url("trip_settle"))
    cara = crew.client("cara")
    page = cara.get(crew.url("history")).content.decode()
    assert crew.url("expense_edit", coffee.id) in page
    opened = cara.get(crew.url("expense_edit", coffee.id))
    assert opened.status_code == 200 and "Save" not in opened.content.decode()


# --- A write for every action in the table --------------------------------------------------------


def _expense_added(crew):
    crew.client("ann").post(crew.url("expense_create"), crew.form("ann"))


def _expense_changed(crew):
    taxi = crew.taxi
    crew.client("ben").post(crew.url("expense_edit", taxi.id), crew.form("dan", "25", "Taxi"))


def _expense_deleted(crew):
    delete(crew, "ben", crew.taxi)


def _expense_restored(crew):
    delete(crew, "ben", crew.taxi)
    restore(crew, "ben", crew.taxi)


def _traveler_added(crew):
    crew.client("ann").post(crew.url("participant_create"), {"name": "Fay"})


def _traveler_renamed(crew):
    crew.client("ann").post(crew.url("participant_edit", crew.travelers["dan"].id), {"name": "D"})


def _traveler_covered(crew):
    dan = crew.travelers["dan"]
    crew.client("ann").post(
        crew.url("participant_edit", dan.id),
        {"name": "Dan", "user": crew.users["dan"].id, "sponsors": [crew.travelers["ann"].id]},
    )


def _traveler_unlinked(crew):
    dan = crew.travelers["dan"]
    crew.client("ann").post(crew.url("participant_edit", dan.id), {"name": "Dan"})


def _traveler_linked(crew):
    crew.client("ann").post(
        crew.url("participant_edit", crew.travelers["dan"].id),
        {"name": "Dan", "user": crew.users["dan"].id},
    )
    eve = crew.users["eve"]
    crew.client("ann").post(crew.url("participant_create"), {"name": "Eve", "user": eve.id})


def _traveler_removed(crew):
    crew.client("ann").post(crew.url("participant_create"), {"name": "Fay"})
    fay = crew.trip.participants.get(name="Fay")
    crew.client("ann").post(crew.url("participant_delete", fay.id))


def _account_added(crew):
    crew.users["sam"].is_active = True
    crew.users["sam"].save()
    crew.client("ann").post(crew.url("member_add"), {"username": "sam"})


def _account_role(crew):
    crew.client("ann").post(crew.url("member_edit", crew.members["cara"].id), {"role": "editor"})


def _account_removed(crew):
    crew.client("ann").post(crew.url("member_remove", crew.members["cara"].id))


def _account_owner(crew):
    crew.client("ann").post(crew.url("member_transfer", crew.members["ben"].id))


def _rate_added(crew):
    crew.client("ann").post(crew.url("rate_save"), {"currency": "VND", "rate": "25000"})


def _rate_changed(crew):
    _rate_added(crew)
    crew.client("ann").post(crew.url("rate_save"), {"currency": "VND", "rate": "26000"})


def _rate_removed(crew):
    _rate_added(crew)
    rate = crew.trip.rates.get()
    crew.client("ann").post(crew.url("rate_delete", rate.id))


def _type_added(crew):
    crew.client("ben").post(crew.url("category_create"), {"name": "Tips", "emoji": "💵"})


def _type_renamed(crew):
    crew.client("ben").post(
        crew.url("category_edit", crew.food.id), {"name": "Meals", "emoji": "🍜"}
    )


def _type_removed(crew):
    other = crew.trip.categories.get(name="Translation")
    crew.client("ben").post(crew.url("category_delete", other.id))


def _trip_settled(crew):
    crew.client("ben").post(crew.url("trip_settle"))


def _trip_reopened(crew):
    _trip_settled(crew)
    crew.client("ben").post(crew.url("trip_reopen"))


def _trip_renamed(crew):
    crew.client("ann").post(
        crew.url("trip_settings"), {"name": "Better trip", "base_currency": "USD"}
    )


ACTIONS = [
    (_expense_added, "Ann added “Drinks”: 10.00 USD, paid by Ann"),
    (_expense_changed, "Ben changed “Taxi”: amount 20.00 USD → 25.00 USD"),
    (_expense_deleted, "Ben deleted “Taxi”: 20.00 USD, paid by Dan"),
    (_expense_restored, "Ben restored “Taxi”: 20.00 USD, paid by Dan"),
    (_traveler_added, "Ann added traveler Fay"),
    (_traveler_renamed, "Ann renamed traveler Dan → D"),
    (_traveler_covered, "Ann changed who covers Dan: nobody → Ann"),
    (_traveler_unlinked, "Ann unlinked traveler Dan from account Dan"),
    (_traveler_linked, "Ann linked traveler Eve to account Eve"),
    (_traveler_removed, "Ann removed traveler Fay"),
    (_account_added, "Ann added Sam's account"),
    (_account_role, "Ann changed Cara's role: Member → Editor"),
    (_account_removed, "Ann removed Cara's account"),
    (_account_owner, "Ann made Ben the Owner"),
    (_rate_added, "Ann added the VND rate: 1 USD = 25,000 VND"),
    (_rate_changed, "Ann changed the VND rate: 1 USD = 25,000 VND → 1 USD = 26,000 VND"),
    (_rate_removed, "Ann removed the VND rate: 1 USD = 25,000 VND"),
    (_type_added, "Ben added type Tips"),
    (_type_renamed, "Ben renamed type Food & drink → Meals"),
    (_type_removed, "Ben removed type Translation"),
    (_trip_settled, "Ben settled the trip"),
    (_trip_reopened, "Ben reopened the trip"),
    (_trip_renamed, "Ann renamed the trip: Crew trip → Better trip"),
]


@pytest.mark.parametrize("act,expected", ACTIONS, ids=[a.__name__ for a, _ in ACTIONS])
def test_every_action_writes_its_entry(crew, act, expected):
    act(crew)
    assert expected in lines(crew)


def test_account_removal_also_records_the_unlink(crew):
    crew.client("ann").post(crew.url("member_remove", crew.members["cara"].id))
    assert "Ann removed Cara's account" in lines(crew)
    assert "Ann unlinked traveler Cara from account Cara" in lines(crew)


def test_reordering_is_not_recorded(crew):
    other = crew.expense("dan", "Snack", "3")
    crew.client("ann").post(
        crew.url("expense_reorder"), {"day": "2026-06-01", "ids": [other.id, crew.taxi.id]}
    )
    assert crew.trip.history.count() == 0


def test_a_save_that_changes_nothing_writes_no_entry(crew):
    crew.client("ben").post(crew.url("expense_edit", crew.taxi.id), crew.form("dan", "20", "Taxi"))
    assert crew.trip.history.count() == 0


def test_an_entry_is_written_in_the_same_transaction_as_the_change(crew):
    # A refused change (settled trip) leaves neither a change nor an entry.
    crew.client("ann").post(crew.url("trip_settle"))
    before = crew.trip.history.count()
    crew.client("ann").post(crew.url("expense_create"), crew.form("ann"))
    delete(crew, "ann", crew.taxi)
    assert crew.trip.history.count() == before


def test_every_field_of_an_expense_change_is_listed(crew):
    taxi = crew.taxi
    transport = crew.trip.categories.get(name="Transport")
    crew.client("ben").post(
        crew.url("expense_edit", taxi.id),
        {
            "amount": "20",
            "currency": "USD",
            "description": "Cab",
            "payer": crew.travelers["ben"].id,
            "beneficiaries": [crew.travelers["ann"].id],
            "category": transport.id,
            "date": "2026-06-02",
        },
    )
    entry = crew.trip.history.get()
    assert set(entry.changes) == {"date", "payer", "for", "type", "description"}
    assert entry.changes["payer"]["old"] == "Dan" and entry.changes["payer"]["new"] == "Ben"
    assert entry.changes["for"]["new"] == "Ann"
    assert entry.changes["date"] == {"old": "1 Jun 2026", "new": "2 Jun 2026"}
    assert entry.values["payer"] == "Ben" and entry.values["type"] == "Transport"
    currency = crew.client("ann").post(crew.url("rate_save"), {"currency": "VND", "rate": "25000"})
    assert currency.status_code == 302
    crew.client("ben").post(
        crew.url("expense_edit", taxi.id),
        {
            "amount": "20",
            "currency": "VND",
            "description": "Cab",
            "payer": crew.travelers["ben"].id,
            "beneficiaries": [crew.travelers["ann"].id],
            "category": transport.id,
            "date": "2026-06-02",
        },
    )
    assert crew.trip.history.first().changes["currency"] == {"old": "USD", "new": "VND"}


# --- The page ------------------------------------------------------------------------------------


def test_the_page_is_open_to_every_member_and_closed_to_others(crew):
    for name in ("ann", "ben", "cara", "eve"):
        assert crew.client(name).get(crew.url("history")).status_code == 200
    assert crew.client("sam").get(crew.url("history")).status_code == 404


def test_the_header_shows_the_history_icon_to_everyone_and_settings_only_to_the_owner(crew):
    history_url = crew.url("history")
    settings_url = crew.url("trip_settings")
    for name in ("ann", "ben", "cara", "eve"):
        html = crew.client(name).get(crew.url("trip")).content.decode()
        assert f'href="{history_url}"' in html
        assert (f'href="{settings_url}"' in html) == (name == "ann")


def test_the_page_is_newest_first_and_groups_by_day(crew):
    crew.client("ann").post(crew.url("expense_create"), crew.form("ann", "1", "First"))
    crew.client("ann").post(crew.url("expense_create"), crew.form("ann", "2", "Second"))
    page = crew.client("cara").get(crew.url("history")).content.decode()
    assert page.index("Second") < page.index("First")
    assert page.count('class="day"') == 1 or page.count("<details") == 1


def test_ten_days_per_page_with_show_older(crew):
    now = timezone.now()
    for n in range(12):
        entry = history.record(crew.trip, crew.users["ann"], "added", "type", label=f"T{n}")
        HistoryEntry.objects.filter(pk=entry.pk)  # no update path: set the time through SQL below
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE trips_historyentry SET created_at = %s WHERE id = %s",
                [now - timedelta(days=n), entry.pk],
            )
    client = crew.client("cara")
    first = client.get(crew.url("history")).content.decode()
    assert first.count("<details") == 10
    assert "Show older" in first and "10 of 12 days shown" in first
    assert "T0" in first and "T9" in first and "T10" not in first
    second = client.get(crew.url("history"), {"page": 2}).content.decode()
    assert second.count("<details") == 2 and "T10" in second and "T11" in second
    assert "Show older" not in second


def test_search_runs_in_the_database_on_search_text(crew):
    crew.client("ann").post(crew.url("expense_create"), crew.form("dan", "5", "Bus"))
    crew.client("ann").post(crew.url("expense_create"), crew.form("ann", "5", "Pho"))
    with CaptureQueriesContext(connection) as queries:
        page = crew.client("cara").get(crew.url("history"), {"q": "DAN BUS"}).content.decode()
    assert any("search_text" in q["sql"] and "LIKE" in q["sql"].upper() for q in queries)
    assert "Bus" in page and "Pho" not in page
    # Case is ignored, and old and new values and the action word are searchable.
    crew.client("ben").post(crew.url("expense_edit", crew.taxi.id), crew.form("dan", "77", "Taxi"))
    found = crew.client("cara").get(crew.url("history"), {"q": "CHANGED 77"}).content.decode()
    assert "Taxi" in found and "Bus" not in found
    none = crew.client("cara").get(crew.url("history"), {"q": "zzz"}).content.decode()
    assert "Nothing in History matches" in none


def test_search_covers_account_names(crew):
    only_ann = {"beneficiaries": [crew.travelers["ann"].id]}
    crew.client("ann").post(
        crew.url("expense_create"), {**crew.form("ann", "5", "Bus"), **only_ann}
    )
    crew.client("ben").post(
        crew.url("expense_create"), {**crew.form("ann", "5", "Pho"), **only_ann}
    )
    page = crew.client("cara").get(crew.url("history"), {"q": "ben"}).content.decode()
    assert "Pho" in page and "Bus" not in page


def test_an_htmx_search_gets_the_list_and_the_input_has_the_htmx_attributes(crew):
    crew.client("ann").post(crew.url("expense_create"), crew.form("ann", "5", "Bus"))
    html = crew.client("cara").get(crew.url("history")).content.decode()
    assert 'hx-trigger="input changed delay:300ms, search"' in html and 'hx-select=".paged"' in html


# --- Restore -------------------------------------------------------------------------------------


def test_restored_values_equal_the_last_values_in_history(crew):
    dinner = crew.expense("dan", "Dinner", "60")
    crew.client("ben").post(crew.url("expense_edit", dinner.id), crew.form("dan", "55", "Dinner"))
    delete(crew, "ben", dinner)
    # Whatever the row holds now, restore brings back what History last shows.
    Expense.all_objects.filter(pk=dinner.pk).update(amount=Decimal("1"), description="Other")
    last = crew.trip.history.first().values
    restore(crew, "ben", dinner)
    dinner.refresh_from_db()
    assert history.expense_snapshot(history.fresh_expense(dinner.pk)) == last
    assert dinner.amount == Decimal("55") and dinner.description == "Dinner"


def test_restore_is_refused_when_the_type_was_removed_until_it_is_added_again(crew):
    transport = crew.trip.categories.get(name="Transport")
    taxi = crew.taxi
    Expense.all_objects.filter(pk=taxi.pk).update(category=transport)
    delete(crew, "ben", taxi)
    crew.client("ben").post(crew.url("category_delete", transport.id))
    response = restore(crew, "ben", taxi)
    assert "Not restored. Add these first: type Transport." in response.content.decode()
    taxi.refresh_from_db()
    assert taxi.deleted_at is not None
    Category.objects.create(trip=crew.trip, name="Transport", emoji="🚕")
    restore(crew, "ben", taxi)
    taxi.refresh_from_db()
    assert taxi.deleted_at is None and taxi.category.name == "Transport"


def test_restore_is_refused_when_a_for_traveler_was_removed(crew):
    crew.taxi.delete()  # Taxi lists Ben too, and a traveler in use cannot be removed.
    lunch = crew.expense("dan", "Lunch", "30")
    lunch.beneficiaries.set([crew.travelers["dan"], crew.travelers["ben"]])
    delete(crew, "ben", lunch)
    # With the expense deleted, Ben is free to be removed.
    crew.client("ann").post(crew.url("participant_delete", crew.travelers["ben"].id))
    assert not crew.trip.participants.filter(name="Ben").exists()
    response = restore(crew, "ann", lunch)
    assert "Not restored. Add these first: traveler Ben." in response.content.decode()
    lunch.refresh_from_db()
    assert lunch.deleted_at is not None


def test_an_expense_erased_with_its_payer_can_no_longer_be_restored(crew):
    crew.taxi.delete()
    lunch = crew.expense("ben", "Lunch", "30")
    delete(crew, "ann", lunch)
    crew.client("ann").post(crew.url("participant_delete", crew.travelers["ben"].id))
    assert not Expense.all_objects.filter(pk=lunch.pk).exists()
    page = crew.client("ann").get(crew.url("expense_edit", lunch.id))
    assert page.status_code == 200
    html = page.content.decode()
    assert (
        "Ben was removed from the trip, so this expense cannot be restored." in html
        and "Restore expense" not in html
    )
    assert "Lunch" in html and "Ben" in html
    assert crew.client("ann").post(crew.url("expense_restore", lunch.id)).status_code == 302
    assert crew.client("ann").get(crew.url("history")).status_code == 200


def test_restore_is_refused_on_a_settled_trip(crew):
    taxi = crew.taxi
    delete(crew, "ben", taxi)
    crew.client("ben").post(crew.url("trip_settle"))
    response = restore(crew, "ben", taxi)
    assert "This trip is settled" in response.content.decode()
    taxi.refresh_from_db()
    assert taxi.deleted_at is not None
    page = crew.client("ben").get(crew.url("expense_edit", taxi.id)).content.decode()
    assert "Restore expense" not in page


def test_tapping_restore_twice_restores_once(crew):
    taxi = crew.taxi
    delete(crew, "ben", taxi)
    restore(crew, "ben", taxi)
    restore(crew, "ben", taxi)
    assert [e.action for e in crew.trip.history.filter(object_type="expense")].count(
        "restored"
    ) == 1
    assert crew.trip.expenses.filter(pk=taxi.pk).count() == 1


def test_a_viewer_cannot_restore_and_sees_no_button(crew):
    taxi = crew.taxi
    delete(crew, "ben", taxi)
    eve = crew.client("eve")
    assert "Restore expense" not in eve.get(crew.url("expense_edit", taxi.id)).content.decode()
    assert eve.post(crew.url("expense_restore", taxi.id)).status_code == 403


def test_restore_only_accepts_post_and_other_trips_get_404(crew):
    taxi = crew.taxi
    delete(crew, "ben", taxi)
    assert crew.client("ben").get(crew.url("expense_restore", taxi.id)).status_code == 405
    assert crew.client("sam").post(crew.url("expense_restore", taxi.id)).status_code == 404


def test_a_deleted_expense_from_before_history_still_shows_and_restores(crew):
    Expense.all_objects.filter(pk=crew.taxi.pk).update(deleted_at=timezone.now())
    assert crew.trip.history.count() == 0
    page = crew.client("ben").get(crew.url("expense_edit", crew.taxi.id)).content.decode()
    assert "Taxi" in page and "Restore expense" in page
    restore(crew, "ben", crew.taxi)
    assert crew.trip.expenses.filter(pk=crew.taxi.pk).exists()


# --- Keeping entries -----------------------------------------------------------------------------


def test_entries_keep_the_actors_name_when_the_account_is_deleted(crew):
    crew.client("ben").post(crew.url("expense_create"), crew.form("ann", "5", "Bus"))
    crew.users["ben"].delete()
    entry = crew.trip.history.get()
    assert entry.actor is None and entry.actor_name == "Ben"
    assert "Ben added “Bus”" in history.describe(entry)


def test_deleting_the_trip_deletes_its_history(crew):
    crew.client("ann").post(crew.url("expense_create"), crew.form("ann"))
    assert HistoryEntry.objects.count() == 1
    crew.client("ann").post(crew.url("trip_delete"))
    assert not Trip.objects.filter(pk=crew.trip.pk).exists()
    assert HistoryEntry.objects.count() == 0


# --- Wording and links (UI review) ---------------------------------------------------------------


def test_the_trip_settings_line_uses_the_form_labels_and_readable_values(crew):
    crew.client("ann").post(
        crew.url("trip_settings"),
        {
            "name": "Crew trip",
            "country": "KH",
            "start_date": "2026-06-01",
            "end_date": "2026-06-05",
            "base_currency": "USD",
        },
    )
    crew.client("ann").post(
        crew.url("trip_settings"),
        {
            "name": "Crew trip",
            "country": "KH",
            "start_date": "2026-06-02",
            "end_date": "2026-06-05",
            "base_currency": "USD",
        },
    )
    assert last_line(crew) == "Ann changed the trip settings: start date 1 Jun 2026 → 2 Jun 2026"
    assert lines(crew)[0] == (
        "Ann changed the trip settings: country – → Cambodia; "
        "end date – → 5 Jun 2026; start date – → 1 Jun 2026"
    )


def test_split_between_says_everyone_when_the_list_is_all_travelers(crew):
    taxi = crew.taxi
    two = [crew.travelers["ann"].id, crew.travelers["cara"].id]
    crew.client("ben").post(
        crew.url("expense_edit", taxi.id), {**crew.form("dan", "20", "Taxi"), "beneficiaries": two}
    )
    crew.client("ben").post(crew.url("expense_edit", taxi.id), crew.form("dan", "20", "Taxi"))
    assert lines(crew) == [
        "Ben changed “Taxi”: split between Ann, Ben, Cara, Dan → Ann, Cara".replace(
            "Ann, Ben, Cara, Dan", "everyone"
        ),
        "Ben changed “Taxi”: split between Ann, Cara → everyone",
    ]


def test_the_deleted_page_reads_like_the_expense_page(crew):
    ExchangeRate.objects.create(trip=crew.trip, currency="VND", rate=Decimal("25000"))
    noodles = crew.expense("dan", "Noodles", "100000", currency="VND")
    delete(crew, "ben", noodles)
    html = crew.client("ben").get(crew.url("expense_edit", noodles.id)).content.decode()
    assert "Ben deleted this expense on" in html and "last values" not in html
    assert "🍜 Noodles" in html and "≈" in html
    assert "Everyone (4 travelers)" in html and "25,000 VND each" in html
    # Someone who may not restore sees who may, in the same words as the expense page.
    html = crew.client("cara").get(crew.url("expense_edit", noodles.id)).content.decode()
    assert "Only Dan, the Owner or an Editor can restore this expense." in html


def test_everyone_compares_travelers_not_counts(crew):
    lunch = crew.expense("dan", "Lunch", "30")
    lunch.beneficiaries.set(list(crew.travelers.values())[:3])
    delete(crew, "ben", lunch)
    crew.client("ann").post(crew.url("participant_create"), {"name": "Fay"})
    lunch.beneficiaries.set([])  # The row no longer matters: the page reads History.
    html = crew.client("ben").get(crew.url("expense_edit", lunch.id)).content.decode()
    assert "Everyone (" not in html


def test_history_links_carry_the_search_back_and_the_header_points_to_expenses(crew):
    crew.client("ann").post(crew.url("expense_create"), crew.form("ann", "5", "Bus"))
    bus = crew.trip.expenses.get(description="Bus")
    cara = crew.client("cara")
    html = cara.get(crew.url("history"), {"q": "bus"}).content.decode()
    assert "?next=" in html and "q%3Dbus" in html
    assert f'class="back" href="{crew.url("trip")}"' in html
    assert 'aria-current="page"' in html
    back = cara.get(crew.url("expense_edit", bus.id), {"next": crew.url("history") + "?q=bus"})
    assert f'href="{crew.url("history")}?q=bus"' in back.content.decode()
    delete(crew, "ann", bus)
    gone = cara.get(crew.url("expense_edit", bus.id), {"next": crew.url("history") + "?q=bus"})
    assert f'href="{crew.url("history")}?q=bus"' in gone.content.decode()
