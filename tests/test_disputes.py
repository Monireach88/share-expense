"""Notifications (spec section 4) and disputes (section 5).

Same crew as the role tests: Ann owns the trip, Ben is an Editor, Cara and Dan are Members, Eve is
a Member with no traveler. "Taxi" is Dan's expense, recorded by Ben, for Ann, Ben, Cara and Dan.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.disputes.models import Dispute, DisputeMessage, Notification
from apps.trips import actions, history
from apps.trips.models import Trip
from tests.test_roles import Crew

pytestmark = pytest.mark.django_db


@pytest.fixture
def crew(db):
    return Crew()


def open_dispute(crew, who, expense, reason="This is wrong"):
    return crew.client(who).post(crew.url("dispute_open", expense.id), {"reason": reason})


def write(crew, who, dispute, text="A message"):
    return crew.client(who).post(crew.url("dispute_write", dispute.id), {"text": text})


def resolve(crew, who, dispute):
    return crew.client(who).post(crew.url("dispute_resolve", dispute.id))


def close(crew, who, dispute, reason="Checked the receipt"):
    return crew.client(who).post(crew.url("dispute_close", dispute.id), {"reason": reason})


def notified(crew, kind=None) -> set[str]:
    """The accounts that got a notification (of this kind), then forget them all."""
    items = Notification.objects.filter(trip=crew.trip)
    if kind:
        items = items.filter(kind=kind)
    names = {n.user.username for n in items.select_related("user")}
    Notification.objects.all().delete()
    return names


def lines(crew) -> list[str]:
    return [history.describe(e) for e in reversed(list(crew.trip.history.all()))]


def page(crew, who, expense) -> str:
    return crew.client(who).get(crew.url("expense_edit", expense.id)).content.decode()


def expense_by(crew, who, payer, description, people, amount="60"):
    """An expense recorded through the form by ``who``, so History has its "added" entry."""
    form = {**crew.form(payer, amount, description), "beneficiaries": []}
    form["beneficiaries"] = [crew.travelers[p].id for p in people]
    response = crew.client(who).post(crew.url("expense_create"), form)
    assert response.status_code == 302, response.content[:300]
    return crew.trip.expenses.get(description=description)


# --- Gherkin scenarios of spec section 5 ---------------------------------------------------------


def test_the_full_dispute_flow(crew):
    dinner = expense_by(crew, "dan", "dan", "Dinner", ["dan", "cara", "ben"])
    open_dispute(crew, "cara", dinner, "I did not eat dinner")
    dispute = Dispute.objects.get()
    assert notified(crew) == {"dan"}

    # Dan removes Cara from "For" and saves: he stays on the expense page to write "Fixed".
    form = {
        **crew.form("dan", "60", "Dinner"),
        "beneficiaries": [crew.travelers["dan"].id, crew.travelers["ben"].id],
    }
    response = crew.client("dan").post(crew.url("expense_edit", dinner.id), form)
    assert response.status_code == 302
    assert response["Location"] == crew.url("expense_edit", dinner.id) + "#disputes"
    assert "Sorry, fixed" not in page(crew, "dan", dinner)
    write(crew, "dan", dispute, "Sorry, fixed")
    assert notified(crew) == {"cara"}

    assert resolve(crew, "cara", dispute).status_code == 302
    dispute.refresh_from_db()
    assert dispute.state == Dispute.State.RESOLVED
    assert notified(crew) == {"dan"}
    assert lines(crew)[-4:] == [
        "Cara opened a dispute on “Dinner”: I did not eat dinner",
        "Dan changed “Dinner”: split between Ben, Cara, Dan → Ben, Dan",
        "Dan wrote in the dispute on “Dinner”: Sorry, fixed",
        "Cara resolved the dispute on “Dinner”",
    ]


def test_only_the_opener_can_resolve(crew):
    open_dispute(crew, "cara", crew.taxi)
    dispute = Dispute.objects.get()
    resolve_url = crew.url("dispute_resolve", dispute.id)
    assert resolve_url not in page(crew, "dan", crew.taxi)
    assert resolve_url in page(crew, "cara", crew.taxi)
    assert resolve(crew, "dan", dispute).status_code == 403
    assert resolve(crew, "ann", dispute).status_code == 403
    dispute.refresh_from_db()
    assert dispute.is_open


def test_a_traveler_disputes_a_payment_moved_away_from_him(crew):
    hotel = expense_by(crew, "ben", "dan", "Hotel", ["ben", "cara"])
    form = {
        **crew.form("ben", "60", "Hotel"),
        "beneficiaries": [crew.travelers["ben"].id, crew.travelers["cara"].id],
    }
    crew.client("ben").post(crew.url("expense_edit", hotel.id), form)
    hotel.refresh_from_db()
    assert hotel.payer == crew.travelers["ben"]
    assert crew.url("dispute_open", hotel.id) in page(crew, "dan", hotel)
    open_dispute(crew, "dan", hotel)
    assert Dispute.objects.filter(expense=hotel, opened_by=crew.users["dan"]).exists()


def test_an_open_dispute_blocks_settling(crew):
    open_dispute(crew, "cara", crew.taxi)
    ben = crew.client("ben")
    balances = ben.get(crew.url("summary")).content.decode()
    assert "1 open dispute blocks settling" in balances
    assert "Mark as settled" not in balances
    assert crew.url("trip") + "?disputed=1" in balances
    response = ben.post(crew.url("trip_settle"))
    assert response.status_code == 400
    assert response.content.decode() == "The trip cannot be settled: 1 open dispute."
    crew.trip.refresh_from_db()
    assert not crew.trip.is_settled


def test_the_owner_closes_a_stuck_dispute(crew):
    open_dispute(crew, "cara", crew.taxi)
    notified(crew)
    dispute = Dispute.objects.get()
    close(crew, "ann", dispute, "Photo shows Cara at dinner")
    dispute.refresh_from_db()
    assert dispute.state == Dispute.State.CLOSED
    assert dispute.close_reason == "Photo shows Cara at dinner"
    assert "cara" in notified(crew)
    assert (
        lines(crew)[-1]
        == "Ann, the Owner, closed Cara’s dispute on “Taxi”: Photo shows Cara at dinner"
    )
    assert "Photo shows Cara at dinner" in page(crew, "cara", crew.taxi)


def test_the_owner_closes_a_dispute_about_her_own_expense_in_the_open(crew):
    hotel = crew.expense("ann", "Hotel", "90")
    open_dispute(crew, "cara", hotel)
    notified(crew)
    close(crew, "ann", Dispute.objects.get())
    assert notified(crew) == {"ben", "cara", "dan", "eve"}


def test_a_viewer_cannot_open_a_dispute(crew):
    assert crew.url("dispute_open", crew.taxi.id) not in page(crew, "eve", crew.taxi)
    assert "Dispute" not in page(crew, "eve", crew.taxi)
    assert open_dispute(crew, "eve", crew.taxi).status_code == 403
    assert not Dispute.objects.exists()


# --- Who may open a dispute (§5.1) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("who", "allowed"),
    [("dan", True), ("cara", True), ("ben", True), ("ann", True), ("eve", False)],
    ids=["payer", "in-for", "editor-in-for", "owner-in-for", "viewer"],
)
def test_who_may_open_a_dispute(crew, who, allowed):
    response = open_dispute(crew, who, crew.taxi)
    assert Dispute.objects.exists() == allowed
    if not allowed:
        assert response.status_code == 403


def test_a_traveler_never_on_the_expense_cannot_open_one(crew):
    lunch = expense_by(crew, "ben", "ben", "Lunch", ["ben"])
    assert crew.url("dispute_open", lunch.id) not in page(crew, "cara", lunch)
    assert open_dispute(crew, "cara", lunch).status_code == 403
    assert not Dispute.objects.exists()


def test_a_traveler_removed_from_for_can_still_open_one(crew):
    lunch = expense_by(crew, "ben", "ben", "Lunch", ["ben", "cara"])
    form = {**crew.form("ben", "60", "Lunch"), "beneficiaries": [crew.travelers["ben"].id]}
    crew.client("ben").post(crew.url("expense_edit", lunch.id), form)
    assert open_dispute(crew, "cara", lunch).status_code == 302
    assert Dispute.objects.filter(expense=lunch).exists()


def test_no_dispute_on_a_settled_trip(crew):
    actions.settle(crew.trip, by=crew.members["ann"])
    assert crew.url("dispute_open", crew.taxi.id) not in page(crew, "cara", crew.taxi)
    response = crew.client("cara").post(
        crew.url("dispute_open", crew.taxi.id), {"reason": "x"}, follow=True
    )
    assert "This trip is settled" in response.content.decode()
    assert not Dispute.objects.exists()


def test_one_open_dispute_per_expense_per_account(crew):
    open_dispute(crew, "cara", crew.taxi)
    assert crew.url("dispute_open", crew.taxi.id) not in page(crew, "cara", crew.taxi)
    response = crew.client("cara").post(
        crew.url("dispute_open", crew.taxi.id), {"reason": "again"}, follow=True
    )
    assert "You already have an open dispute on this expense." in response.content.decode()
    assert Dispute.objects.count() == 1
    # Another account may open its own, and after resolving Cara may open a new one.
    open_dispute(crew, "dan", crew.taxi)
    resolve(crew, "cara", Dispute.objects.get(opened_by=crew.users["cara"]))
    open_dispute(crew, "cara", crew.taxi)
    assert Dispute.objects.filter(opened_by=crew.users["cara"]).count() == 2


def test_a_dispute_needs_a_reason(crew):
    open_dispute(crew, "cara", crew.taxi, "  ")
    assert not Dispute.objects.exists()


def test_a_dispute_is_opened_on_a_deleted_expense_from_its_page(crew):
    crew.client("dan").post(crew.url("expense_delete", crew.taxi.id))
    deleted_page = page(crew, "cara", crew.taxi)
    assert crew.url("dispute_open", crew.taxi.id) in deleted_page
    open_dispute(crew, "cara", crew.taxi, "Why deleted?")
    deleted_page = page(crew, "cara", crew.taxi)
    assert "Why deleted?" in deleted_page
    assert crew.url("dispute_resolve", Dispute.objects.get().id) in deleted_page


# --- Who is notified (§5.2) --------------------------------------------------------------------


def test_opened_notifies_the_creator_and_the_payers_account(crew):
    open_dispute(crew, "cara", crew.taxi)  # Ben recorded it, Dan paid.
    assert notified(crew, Notification.Kind.DISPUTE_OPENED) == {"ben", "dan"}


def test_opened_skips_accounts_no_longer_on_the_trip(crew):
    actions.remove_member(crew.members["ben"], by=crew.members["ann"])
    open_dispute(crew, "cara", crew.taxi)
    assert notified(crew) == {"dan"}


def test_the_owner_is_notified_when_nobody_but_the_opener_would_be(crew):
    lunch = expense_by(crew, "cara", "cara", "Lunch", ["cara", "dan"])
    open_dispute(crew, "cara", lunch)  # Cara recorded and paid it herself.
    assert notified(crew) == {"ann"}
    write(crew, "cara", Dispute.objects.get())
    assert notified(crew) == {"ann"}


def test_messages_notify_everyone_in_the_dispute_except_the_writer(crew):
    open_dispute(crew, "cara", crew.taxi)
    dispute = Dispute.objects.get()
    notified(crew)
    write(crew, "dan", dispute)
    assert notified(crew) == {"cara", "ben"}  # The Owner has not written yet.
    write(crew, "ann", dispute)
    assert notified(crew) == {"cara", "ben", "dan"}
    write(crew, "ben", dispute)
    assert notified(crew) == {"cara", "dan", "ann"}  # Now the Owner is in the dispute.
    resolve(crew, "cara", dispute)
    assert notified(crew, Notification.Kind.DISPUTE_RESOLVED) == {"ben", "dan", "ann"}


def test_closed_notifies_the_people_in_the_dispute_except_the_owner(crew):
    open_dispute(crew, "cara", crew.taxi)
    notified(crew)
    close(crew, "ann", Dispute.objects.get())
    assert notified(crew, Notification.Kind.DISPUTE_CLOSED) == {"cara", "ben", "dan"}


# --- Who may write, resolve and close (§5.2, §5.3) ---------------------------------------------


@pytest.mark.parametrize(
    ("who", "allowed"),
    [("cara", True), ("ben", True), ("dan", True), ("ann", True), ("eve", False)],
    ids=["opener", "creator", "payer", "owner", "viewer"],
)
def test_who_may_write_in_a_dispute(crew, who, allowed):
    open_dispute(crew, "cara", crew.taxi)
    dispute = Dispute.objects.get()
    response = write(crew, who, dispute, "Hello")
    assert DisputeMessage.objects.exists() == allowed
    if not allowed:
        assert response.status_code == 403
        assert crew.url("dispute_write", dispute.id) not in page(crew, who, crew.taxi)


def test_an_editor_writes_in_any_dispute_and_then_is_in_it(crew):
    lunch = crew.expense("dan", "Lunch", "30")
    lunch.created_by = crew.users["dan"]
    lunch.save()
    open_dispute(crew, "cara", lunch)
    dispute = Dispute.objects.get()
    assert notified(crew) == {"dan"}  # Ben neither recorded nor paid it.
    assert crew.url("dispute_write", dispute.id) in page(crew, "ben", lunch)
    write(crew, "ben", dispute, "Fixed")
    assert DisputeMessage.objects.get().author == crew.users["ben"]
    assert notified(crew) == {"cara", "dan"}
    write(crew, "dan", dispute)
    assert notified(crew) == {"cara", "ben"}  # Ben has written, so he is in the dispute now.
    resolve(crew, "cara", dispute)
    assert notified(crew) == {"dan", "ben"}


def test_the_opener_keeps_her_rights_after_becoming_a_viewer(crew):
    open_dispute(crew, "cara", crew.taxi)
    dispute = Dispute.objects.get()
    crew.trip.participants.filter(pk=crew.travelers["cara"].pk).update(user=None)
    write(crew, "cara", dispute, "Still here")
    assert DisputeMessage.objects.get().text == "Still here"
    assert resolve(crew, "cara", dispute).status_code == 302
    dispute.refresh_from_db()
    assert dispute.state == Dispute.State.RESOLVED


def test_only_the_owner_closes_and_needs_a_reason(crew):
    open_dispute(crew, "cara", crew.taxi)
    dispute = Dispute.objects.get()
    for who in ("ben", "cara", "dan"):
        assert close(crew, who, dispute).status_code == 403
    response = crew.client("ann").post(
        crew.url("dispute_close", dispute.id), {"reason": " "}, follow=True
    )
    assert "Write the reason for closing this dispute." in response.content.decode()
    dispute.refresh_from_db()
    assert dispute.is_open
    assert crew.url("dispute_close", dispute.id) in page(crew, "ann", crew.taxi)
    assert crew.url("dispute_close", dispute.id) not in page(crew, "ben", crew.taxi)


@pytest.mark.parametrize("end", ["resolved", "closed"])
def test_resolved_and_closed_disputes_take_no_messages_and_do_not_reopen(crew, end):
    open_dispute(crew, "cara", crew.taxi)
    dispute = Dispute.objects.get()
    if end == "resolved":
        resolve(crew, "cara", dispute)
    else:
        close(crew, "ann", dispute)
    response = crew.client("cara").post(
        crew.url("dispute_write", dispute.id), {"text": "More"}, follow=True
    )
    assert f"This dispute is {end}, so it takes no new messages." in response.content.decode()
    assert not DisputeMessage.objects.exists()
    resolve(crew, "cara", dispute)
    close(crew, "ann", dispute)
    dispute.refresh_from_db()
    assert dispute.state == end
    assert crew.url("dispute_write", dispute.id) not in page(crew, "cara", crew.taxi)


# --- The screen (§5.4) and settling (§5.5) -----------------------------------------------------


def test_the_expense_card_shows_disputed_and_the_list_filters_disputed_expenses(crew):
    crew.expense("ben", "Museum", "15")
    open_dispute(crew, "cara", crew.taxi)
    expenses = crew.client("ann").get(crew.url("trip")).content.decode()
    assert expenses.count("Disputed") == 1
    filtered = crew.client("ann").get(crew.url("trip") + "?disputed=1").content.decode()
    assert "Taxi" in filtered
    assert "Museum" not in filtered
    resolve(crew, "cara", Dispute.objects.get())
    assert "Disputed" not in crew.client("ann").get(crew.url("trip")).content.decode()


def test_the_editor_form_shows_the_disputes_section(crew):
    open_dispute(crew, "cara", crew.taxi, "Too much")
    form_page = page(crew, "ben", crew.taxi)
    assert "Save changes" in form_page
    assert "Too much" in form_page
    assert crew.url("dispute_write", Dispute.objects.get().id) in form_page


def test_saving_without_a_dispute_returns_to_the_list(crew):
    response = crew.client("ben").post(
        crew.url("expense_edit", crew.taxi.id), crew.form("dan", "25", "Taxi")
    )
    assert response["Location"] == crew.url("trip")


def test_settling_works_again_once_disputes_end(crew):
    open_dispute(crew, "cara", crew.taxi)
    resolve(crew, "cara", Dispute.objects.get())
    assert crew.client("ben").post(crew.url("trip_settle")).status_code == 302
    crew.trip.refresh_from_db()
    assert crew.trip.is_settled


# --- History of dispute events -----------------------------------------------------------------


def test_every_dispute_event_writes_a_history_entry(crew):
    open_dispute(crew, "cara", crew.taxi, "Not my taxi")
    dispute = Dispute.objects.get()
    write(crew, "dan", dispute, "It was")
    close(crew, "ann", dispute, "Receipt checked")
    assert lines(crew) == [
        "Cara opened a dispute on “Taxi”: Not my taxi",
        "Dan wrote in the dispute on “Taxi”: It was",
        "Ann, the Owner, closed Cara’s dispute on “Taxi”: Receipt checked",
    ]
    entries = crew.trip.history.filter(object_type="dispute")
    assert {e.values["expense_id"] for e in entries} == {str(crew.taxi.id)}
    history_page = crew.client("eve").get(crew.url("history")).content.decode()
    assert crew.url("expense_edit", crew.taxi.id) in history_page
    found = crew.client("eve").get(crew.url("history") + "?q=receipt").content.decode()
    assert "Receipt checked" in found


# --- Removing a traveler, type or rate while a dispute exists (§3) ------------------------------


def test_removing_a_traveler_is_refused_while_a_dispute_exists_on_her_expense(crew):
    open_dispute(crew, "cara", crew.taxi)
    crew.client("dan").post(crew.url("expense_delete", crew.taxi.id))  # Taxi no longer counts.
    ann = crew.client("ann")
    url = crew.url("participant_delete", crew.travelers["dan"].id)
    assert "has a dispute" in ann.get(url).content.decode()
    ann.post(url)
    assert crew.trip.participants.filter(name="Dan").exists()
    assert Dispute.objects.exists()


def test_removing_a_type_is_refused_while_a_dispute_exists(crew):
    open_dispute(crew, "cara", crew.taxi)
    crew.client("dan").post(crew.url("expense_delete", crew.taxi.id))
    response = crew.client("ann").post(crew.url("category_delete", crew.food.id))
    assert response.status_code == 409
    assert "has a dispute" in response.json()["error"]
    assert crew.trip.categories.filter(pk=crew.food.pk).exists()


def test_removing_a_rate_is_refused_while_a_dispute_exists(crew):
    crew.trip.rates.create(currency="KHR", rate=Decimal("4000"))
    fare = crew.expense("dan", "Tuktuk", "8000", currency="KHR")
    open_dispute(crew, "cara", fare)
    crew.client("dan").post(crew.url("expense_delete", fare.id))
    rate = crew.trip.rates.get()
    ann = crew.client("ann")
    assert "has a dispute" in ann.get(crew.url("rate_delete", rate.id)).content.decode()
    ann.post(crew.url("rate_delete", rate.id))
    assert crew.trip.rates.exists()


def test_deleting_the_trip_deletes_its_disputes(crew):
    open_dispute(crew, "cara", crew.taxi)
    crew.client("ann").post(crew.url("trip_delete"))
    assert not Trip.objects.exists()
    assert not Dispute.objects.exists()


# --- Notifications (section 4) -----------------------------------------------------------------


def test_settling_and_reopening_notify_every_account_but_the_one_who_did_it(crew):
    ben = crew.client("ben")
    ben.post(crew.url("trip_settle"))
    assert notified(crew, Notification.Kind.SETTLED) == {"ann", "cara", "dan", "eve"}
    ben.post(crew.url("trip_reopen"))
    assert notified(crew, Notification.Kind.REOPENED) == {"ann", "cara", "dan", "eve"}


def test_a_settle_notification_links_to_its_history_entry(crew):
    crew.client("ben").post(crew.url("trip_settle"))
    item = Notification.objects.get(user=crew.users["cara"])
    entry = crew.trip.history.get(action="settled")
    assert item.link == f"{crew.url('history')}#entry-{entry.pk}"
    assert f'id="entry-{entry.pk}"' in crew.client("cara").get(crew.url("history")).content.decode()


def test_the_bell_counts_unread_items_and_the_list_marks_them_read(crew):
    open_dispute(crew, "cara", crew.taxi, "Not mine")
    dan = crew.client("dan")
    for address in (crew.url("trip"), "/"):
        assert 'class="bell-count" aria-hidden="true">1<' in dan.get(address).content.decode()
    listing = dan.get("/notifications/").content.decode()
    assert "Cara opened a dispute on “Taxi”: Not mine" in listing
    assert "Crew trip" in listing
    assert crew.url("expense_edit", crew.taxi.id) + "#disputes" in listing
    assert Notification.objects.get(user=crew.users["dan"]).read_at is not None
    assert "bell-count" not in dan.get(crew.url("trip")).content.decode()


def test_the_list_is_newest_first(crew):
    crew.client("ben").post(crew.url("trip_settle"))
    crew.client("ben").post(crew.url("trip_reopen"))
    listing = crew.client("cara").get("/notifications/").content.decode()
    assert listing.index("Ben reopened the trip") < listing.index("Ben settled the trip")


def test_a_removed_account_gets_no_new_items_and_its_old_ones_are_hidden(crew):
    open_dispute(crew, "cara", crew.taxi)
    assert Notification.objects.filter(user=crew.users["dan"]).exists()
    resolve(crew, "cara", Dispute.objects.get())
    actions.remove_member(crew.members["dan"], by=crew.members["ann"])
    dan = crew.client("dan")
    assert "Cara opened" not in dan.get("/notifications/").content.decode()
    assert "bell-count" not in dan.get("/").content.decode()
    crew.client("ben").post(crew.url("trip_settle"))
    assert not Notification.objects.filter(user=crew.users["dan"], kind="settled").exists()


def test_an_account_sees_only_its_own_notifications(crew):
    open_dispute(crew, "cara", crew.taxi, "Secret reason")
    assert "Secret reason" not in crew.client("eve").get("/notifications/").content.decode()


def test_the_disputed_filter_links_deleted_expenses_with_an_open_dispute(crew):
    open_dispute(crew, "cara", crew.taxi)
    crew.client("dan").post(crew.url("expense_delete", crew.taxi.id))
    filtered = crew.client("ben").get(crew.url("trip") + "?disputed=1").content.decode()
    assert "Deleted expenses with an open dispute:" in filtered
    assert crew.url("expense_edit", crew.taxi.id) + "#disputes" in filtered


def test_the_dispute_heading_names_the_account_and_the_traveler_at_opening(crew):
    crew.users["cara"].first_name = "Friend"
    crew.users["cara"].save()
    open_dispute(crew, "cara", crew.taxi)
    assert "Dispute by Friend (Cara)" in page(crew, "ann", crew.taxi)
    crew.trip.participants.filter(pk=crew.travelers["cara"].pk).update(user=None)
    assert "Dispute by Friend (Cara)" in page(crew, "ann", crew.taxi)
    open_dispute(crew, "dan", crew.taxi)
    assert "Dispute by Dan<" in page(crew, "ann", crew.taxi)


def test_the_closed_notification_names_the_opener_and_the_reason(crew):
    open_dispute(crew, "cara", crew.taxi)
    close(crew, "ann", Dispute.objects.get(), "Receipt checked")
    listing = crew.client("cara").get("/notifications/").content.decode()
    assert "Ann, the Owner, closed Cara’s dispute on “Taxi”. Reason: Receipt checked" in listing


def test_balances_counts_open_disputes_in_words(crew):
    open_dispute(crew, "cara", crew.taxi)
    open_dispute(crew, "dan", crew.taxi)
    balances = crew.client("ann").get(crew.url("summary")).content.decode()
    assert "2 open disputes block settling" in balances


def test_the_dispute_section_wording(crew):
    assert "Disputes</h2>" not in page(crew, "cara", crew.taxi)
    assert "Dispute this expense" in page(crew, "cara", crew.taxi)
    open_dispute(crew, "cara", crew.taxi)
    dispute = Dispute.objects.get()
    owner_page = page(crew, "ann", crew.taxi)
    assert "Disputes</h2>" in owner_page
    assert "Close dispute" in owner_page and "Confirm closing" in owner_page
    assert "Mark as resolved" in page(crew, "cara", crew.taxi)
    local = timezone.localtime(dispute.created_at)
    assert f"{local:%-d %b %Y} at {local:%H:%M}" in owner_page
    resolve(crew, "cara", dispute)
    dispute.refresh_from_db()
    done = timezone.localtime(dispute.closed_at)
    assert f"Cara marked this dispute resolved on {done:%-d %b %Y} at {done:%H:%M}." in page(
        crew, "ann", crew.taxi
    )
