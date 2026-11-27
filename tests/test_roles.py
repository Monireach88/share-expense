"""Trip roles (spec §2 and §2.1): Owner, Editor, Member, and a Member with no traveler (Viewer).

The crew: Ann owns the trip; Ben is an Editor; Cara and Dan are Members; Eve is a Member with no
traveler; Sam is not on the trip. Every one except Eve and Sam has a traveler of the same name.
"""

import json
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.expenses import suggest
from apps.expenses.models import Expense
from apps.trips import actions
from apps.trips.models import Participant, Trip, TripMember

pytestmark = pytest.mark.django_db

ROLES = {
    "ann": TripMember.Role.OWNER,
    "ben": TripMember.Role.EDITOR,
    "cara": TripMember.Role.MEMBER,
    "dan": TripMember.Role.MEMBER,
    "eve": TripMember.Role.MEMBER,
}


class Crew:
    """The trip, its people and one expense of Dan's, plus a logged-in client per account."""

    def __init__(self):
        # No password: hashing one costs about half a second, and these accounts never type one.
        self.users = {
            name: get_user_model().objects.create_user(name, password=None, first_name=name.title())
            for name in [*ROLES, "sam"]
        }
        self.trip = Trip.objects.create(name="Crew trip", created_by=self.users["ann"])
        self.members = {
            name: TripMember.objects.create(trip=self.trip, user=self.users[name], role=role)
            for name, role in ROLES.items()
        }
        self.travelers = {
            name: Participant.objects.create(
                trip=self.trip, name=name.title(), user=self.users[name]
            )
            for name in ("ann", "ben", "cara", "dan")
        }
        self.food = self.trip.categories.get(name="Food & drink")
        self.taxi = self.expense("dan", "Taxi", "20")

    def client(self, name) -> Client:
        client = Client()
        client.force_login(self.users[name])
        return client

    def expense(self, payer, description, amount, currency="USD") -> Expense:
        expense = Expense.objects.create(
            trip=self.trip,
            payer=self.travelers[payer],
            amount=Decimal(amount),
            currency=currency,
            date=date(2026, 6, 1),
            category=self.food,
            description=description,
            created_by=self.users["ben"],
        )
        expense.beneficiaries.set(self.travelers.values())
        return expense

    def form(self, payer, amount="10", description="Drinks") -> dict:
        return {
            "amount": amount,
            "currency": "USD",
            "description": description,
            "payer": self.travelers[payer].id,
            "beneficiaries": [p.id for p in self.travelers.values()],
            "category": self.food.id,
            "date": "2026-06-01",
        }

    def url(self, name, *args) -> str:
        return reverse(name, args=[self.trip.id, *args])


@pytest.fixture
def crew(db):
    return Crew()


# --- Gherkin scenarios of spec §2 -----------------------------------------------------------


def test_a_member_adds_an_expense_paid_by_herself_for_others(crew):
    response = crew.client("cara").post(crew.url("expense_create"), crew.form("cara"))
    assert response.status_code == 302
    drinks = crew.trip.expenses.get(description="Drinks")
    assert drinks.payer == crew.travelers["cara"]
    assert drinks.beneficiaries.count() == 4


def test_a_member_cannot_record_another_traveler_as_payer(crew):
    cara = crew.client("cara")
    response = cara.post(crew.url("expense_create"), crew.form("dan"))
    assert response.status_code == 403
    assert not crew.trip.expenses.filter(description="Drinks").exists()
    # Not on her own expense either: the payer cannot move to someone else.
    lunch = crew.expense("cara", "Lunch", "30")
    response = cara.post(crew.url("expense_edit", lunch.id), crew.form("dan", "30", "Lunch"))
    assert response.status_code == 403
    lunch.refresh_from_db()
    assert lunch.payer == crew.travelers["cara"]


def test_a_members_form_shows_the_payer_fixed_to_her_own_traveler(crew):
    page = crew.client("cara").get(crew.url("expense_create"))
    assert list(page.context["form"].fields["payer"].queryset) == [crew.travelers["cara"]]
    assert "Your account can add and change only expenses paid by Cara." in page.content.decode()
    # Owner and Editors choose any payer.
    page = crew.client("ben").get(crew.url("expense_create"))
    assert page.context["form"].fields["payer"].queryset.count() == 4


def test_a_member_sees_someone_elses_expense_read_only(crew):
    cara = crew.client("cara")
    page = cara.get(crew.url("expense_edit", crew.taxi.id))
    assert page.status_code == 200
    assert page.templates[0].name == "expenses/detail.html"
    html = page.content.decode()
    assert "Taxi" in html and "Dan" in html and "20.00" in html
    assert "Only Dan, the Owner or an Editor can change this expense." in html
    assert "Everyone (4 travelers)" in html and "4 travelers · 5.00 USD each" in html
    assert "Added by Ben on" in html
    assert "Save changes" not in html and "Delete this expense" not in html
    assert 'name="amount"' not in html
    # The server refuses a change or a delete as well.
    assert cara.post(crew.url("expense_edit", crew.taxi.id), crew.form("cara")).status_code == 403
    assert cara.post(crew.url("expense_delete", crew.taxi.id)).status_code == 403
    crew.taxi.refresh_from_db()
    assert crew.taxi.amount == Decimal("20") and crew.taxi.deleted_at is None


def test_a_member_edits_an_expense_someone_else_recorded_with_her_as_payer(crew):
    lunch = crew.expense("cara", "Lunch", "30")  # Recorded by Ben.
    cara = crew.client("cara")
    assert "Save changes" in cara.get(crew.url("expense_edit", lunch.id)).content.decode()
    response = cara.post(crew.url("expense_edit", lunch.id), crew.form("cara", "35", "Lunch"))
    assert response.status_code == 302
    lunch.refresh_from_db()
    assert lunch.amount == Decimal("35")
    # And may delete it.
    assert cara.post(crew.url("expense_delete", lunch.id)).status_code == 302
    assert not crew.trip.expenses.filter(pk=lunch.pk).exists()


def test_a_viewer_cannot_add_expenses(crew):
    eve = crew.client("eve")
    page = eve.get(crew.url("trip")).content.decode()
    assert crew.url("expense_create") not in page
    assert eve.get(crew.url("expense_create")).status_code == 403
    assert eve.post(crew.url("expense_create"), crew.form("ann")).status_code == 403
    assert not crew.trip.expenses.filter(description="Drinks").exists()
    # She still sees every expense, read-only.
    assert "Save changes" not in eve.get(crew.url("expense_edit", crew.taxi.id)).content.decode()


def test_an_editor_settles_the_trip(crew):
    ben = crew.client("ben")
    assert "Mark as settled" in ben.get(crew.url("summary")).content.decode()
    assert ben.post(crew.url("trip_settle")).status_code == 302
    crew.trip.refresh_from_db()
    assert crew.trip.is_settled
    assert "Reopen trip" in ben.get(crew.url("summary")).content.decode()
    assert ben.post(crew.url("trip_reopen")).status_code == 302
    crew.trip.refresh_from_db()
    assert not crew.trip.is_settled


def test_a_member_cannot_settle(crew):
    cara = crew.client("cara")
    assert "Mark as settled" not in cara.get(crew.url("summary")).content.decode()
    assert cara.post(crew.url("trip_settle")).status_code == 403
    crew.trip.refresh_from_db()
    assert not crew.trip.is_settled


def test_ownership_transfer(crew):
    ann = crew.client("ann")
    ben_member = crew.members["ben"]
    confirm = ann.get(crew.url("member_transfer", ben_member.id)).content.decode()
    assert "Make Ben the Owner?" in confirm
    assert "only Ben can make you the Owner again" in confirm
    assert ann.post(crew.url("member_transfer", ben_member.id)).status_code == 302
    roles = dict(crew.trip.memberships.values_list("user__username", "role"))
    assert roles["ben"] == TripMember.Role.OWNER and roles["ann"] == TripMember.Role.EDITOR
    # The new owner has the Owner's pages; the old one does not.
    assert crew.client("ben").get(crew.url("trip_settings")).status_code == 200
    assert ann.get(crew.url("trip_settings")).status_code == 403


def test_removing_an_account_unlinks_its_traveler(crew):
    ann = crew.client("ann")
    response = ann.post(crew.url("member_remove", crew.members["cara"].id))
    assert response.status_code == 302
    assert crew.client("cara").get(crew.url("trip")).status_code == 404
    crew.travelers["cara"].refresh_from_db()
    assert crew.travelers["cara"].user is None


def test_one_account_cannot_be_linked_to_two_travelers(crew):
    response = crew.client("ann").post(
        crew.url("participant_edit", crew.travelers["dan"].id),
        {"name": "Dan", "user": crew.users["cara"].id},
    )
    assert response.status_code == 200
    assert "This account is already linked to Cara." in response.content.decode()
    crew.travelers["dan"].refresh_from_db()
    assert crew.travelers["dan"].user == crew.users["dan"]


def test_a_settled_trip_still_allows_account_changes(crew):
    ann = crew.client("ann")
    ann.post(crew.url("trip_settle"))
    response = ann.post(crew.url("member_edit", crew.members["cara"].id), {"role": "editor"})
    assert response.status_code == 302
    crew.members["cara"].refresh_from_db()
    assert crew.members["cara"].role == TripMember.Role.EDITOR
    response = ann.post(crew.url("expense_create"), crew.form("ann"), follow=True)
    assert "This trip is settled" in response.content.decode()
    assert not crew.trip.expenses.filter(description="Drinks").exists()


# --- Further rules of §2 --------------------------------------------------------------------


def test_types_members_add_but_only_owner_and_editors_rename_or_remove(crew):
    cara = crew.client("cara")
    created = cara.post(crew.url("category_create"), {"name": "Tips", "emoji": "💵"})
    assert created.status_code == 201
    tips = created.json()["id"]
    assert (
        cara.post(crew.url("category_edit", tips), {"name": "X", "emoji": "💵"}).status_code == 403
    )
    assert cara.post(crew.url("category_delete", tips)).status_code == 403
    ben = crew.client("ben")
    assert (
        ben.post(crew.url("category_edit", tips), {"name": "Tip", "emoji": "💵"}).status_code == 200
    )
    assert ben.post(crew.url("category_delete", tips)).status_code == 204
    # The Member's form offers no rename or remove (no edit addresses for the script).
    html = cara.get(crew.url("expense_create")).content.decode()
    assert "data-create=" in html and "data-edit=" not in html
    assert "data-edit=" in ben.get(crew.url("expense_create")).content.decode()


def test_only_owner_and_editors_reorder(crew):
    second = crew.expense("dan", "Bus", "5")
    data = {"day": "2026-06-01", "ids": [crew.taxi.id, second.id]}
    assert crew.client("cara").post(crew.url("expense_reorder"), data).status_code == 403
    assert "data-reorder" not in crew.client("cara").get(crew.url("trip")).content.decode()
    assert crew.client("ben").post(crew.url("expense_reorder"), data).status_code == 204
    assert "data-reorder" in crew.client("ben").get(crew.url("trip")).content.decode()


def test_unlinking_a_members_traveler_makes_her_a_viewer(crew):
    crew.client("ann").post(
        crew.url("participant_edit", crew.travelers["cara"].id), {"name": "Cara", "user": ""}
    )
    assert (
        crew.client("cara").post(crew.url("expense_create"), crew.form("cara")).status_code == 403
    )
    accounts = crew.client("ann").get(crew.url("people")).content.decode().split(">Accounts<")[1]
    cara_row = accounts[accounts.index(">Cara") :].split("</li>", 1)[0]
    assert "Viewer" in cara_row


def test_editors_and_the_owner_keep_their_rights_without_a_traveler(crew):
    crew.travelers["ben"].user = None
    crew.travelers["ben"].save()
    ben = crew.client("ben")
    assert ben.post(crew.url("expense_create"), crew.form("dan")).status_code == 302
    assert (
        ben.post(crew.url("expense_edit", crew.taxi.id), crew.form("dan", "21")).status_code == 302
    )


def test_the_owner_cannot_change_her_own_role_or_remove_herself(crew):
    ann = crew.client("ann")
    own = crew.members["ann"]
    assert ann.get(crew.url("member_edit", own.id)).status_code == 404
    assert ann.post(crew.url("member_edit", own.id), {"role": "member"}).status_code == 404
    assert ann.post(crew.url("member_transfer", own.id)).status_code == 404
    ann.post(crew.url("member_remove", own.id))
    own.refresh_from_db()
    assert own.is_owner
    with pytest.raises(actions.ActionRefused):
        actions.change_role(own, TripMember.Role.MEMBER, by=own)
    # The Accounts list offers the other accounts only.
    people = ann.get(crew.url("people")).content.decode()
    assert crew.url("member_edit", own.id) not in people
    assert crew.url("member_edit", crew.members["cara"].id) in people


def test_only_the_owner_changes_roles(crew):
    ben = crew.client("ben")
    assert (
        ben.post(crew.url("member_edit", crew.members["cara"].id), {"role": "editor"}).status_code
        == 403
    )
    crew.members["cara"].refresh_from_db()
    assert crew.members["cara"].role == TripMember.Role.MEMBER
    # A role other than Member or Editor is not offered.
    ann = crew.client("ann")
    response = ann.post(crew.url("member_edit", crew.members["cara"].id), {"role": "owner"})
    assert response.status_code == 200
    crew.members["cara"].refresh_from_db()
    assert crew.members["cara"].role == TripMember.Role.MEMBER


def test_ownership_goes_only_to_an_approved_account(crew):
    eve = crew.users["eve"]
    eve.is_active = False
    eve.save()
    ann = crew.client("ann")
    page = ann.get(crew.url("member_transfer", crew.members["eve"].id)).content.decode()
    assert "This account is not approved yet." in page
    ann.post(crew.url("member_transfer", crew.members["eve"].id))
    crew.members["ann"].refresh_from_db()
    assert crew.members["ann"].is_owner


def test_a_settled_trip_allows_the_name_transfer_and_linking(crew):
    ann = crew.client("ann")
    ann.post(crew.url("trip_settle"))
    ann.post(crew.url("trip_settings"), {"name": "Renamed", "base_currency": "USD"})
    crew.trip.refresh_from_db()
    assert crew.trip.name == "Renamed"
    crew.client("ann").post(
        crew.url("participant_edit", crew.travelers["cara"].id), {"name": "X", "user": ""}
    )
    crew.travelers["cara"].refresh_from_db()
    assert crew.travelers["cara"].user is None and crew.travelers["cara"].name == "Cara"
    ann.post(crew.url("member_transfer", crew.members["ben"].id))
    crew.members["ben"].refresh_from_db()
    assert crew.members["ben"].is_owner


def test_settling_is_refused_when_balances_have_an_error(crew):
    crew.expense("dan", "Pho", "50000", currency="VND")  # No VND rate: Balances show an error.
    response = crew.client("ben").post(crew.url("trip_settle"))
    assert response.status_code == 400
    assert "cannot be settled" in response.content.decode()
    crew.trip.refresh_from_db()
    assert not crew.trip.is_settled


def test_settling_and_expense_changes_lock_the_trip_row(crew):
    ben = crew.client("ben")
    for request in (
        lambda: ben.post(crew.url("trip_settle")),
        lambda: ben.post(crew.url("trip_reopen")),
        lambda: ben.post(crew.url("expense_create"), crew.form("dan")),
        lambda: ben.post(crew.url("expense_edit", crew.taxi.id), crew.form("dan", "22", "Taxi")),
        lambda: ben.post(crew.url("expense_delete", crew.taxi.id)),
    ):
        with CaptureQueriesContext(connection) as queries:
            assert request().status_code == 302
        assert any("FOR UPDATE" in q["sql"] and '"trips_trip"' in q["sql"] for q in queries), (
            queries.captured_queries
        )


def test_the_admin_refuses_to_delete_a_trip_owner(crew):
    admin = get_user_model().objects.create_user(
        "admin", password=None, is_staff=True, is_superuser=True
    )
    client = Client()
    client.force_login(admin)
    url = reverse("admin:accounts_user_delete", args=[crew.users["ann"].id])
    page = client.get(url).content.decode()
    assert "Crew trip" in page and "make someone else its Owner first" in page
    client.post(url, {"post": "yes"})
    assert get_user_model().objects.filter(pk=crew.users["ann"].pk).exists()
    # The same through the "delete selected" action.
    client.post(
        reverse("admin:accounts_user_changelist"),
        {"action": "delete_selected", "_selected_action": [crew.users["ann"].id], "post": "yes"},
    )
    assert get_user_model().objects.filter(pk=crew.users["ann"].pk).exists()
    # An account that owns no trip can still be deleted.
    client.post(reverse("admin:accounts_user_delete", args=[crew.users["sam"].id]), {"post": "yes"})
    assert not get_user_model().objects.filter(pk=crew.users["sam"].pk).exists()


# --- Database rules ---------------------------------------------------------------------------


def test_the_database_allows_one_owner_per_trip(crew):
    with pytest.raises(IntegrityError), transaction.atomic():
        TripMember.objects.filter(pk=crew.members["ben"].pk).update(role=TripMember.Role.OWNER)
    # Other trips have their own owner.
    other = Trip.objects.create(name="Other trip")
    TripMember.objects.create(trip=other, user=crew.users["ben"], role=TripMember.Role.OWNER)


def test_the_database_allows_one_traveler_per_account_in_a_trip(crew):
    with pytest.raises(IntegrityError), transaction.atomic():
        Participant.objects.create(trip=crew.trip, name="Cara 2", user=crew.users["cara"])
    # Travelers without an account are many; the same account may travel in another trip.
    Participant.objects.create(trip=crew.trip, name="Kid 1")
    Participant.objects.create(trip=crew.trip, name="Kid 2")
    other = Trip.objects.create(name="Other trip")
    Participant.objects.create(trip=other, name="Cara", user=crew.users["cara"])


# --- Add with AI for a Member -----------------------------------------------------------------


@pytest.fixture
def ai_reply(settings, monkeypatch):
    settings.DEEPSEEK_API_KEY = "test-key"
    reply = {}
    monkeypatch.setattr(suggest, "chat", lambda messages, **kw: json.dumps(reply))
    return reply


def ai_fill(client, crew):
    return client.post(crew.url("expense_ai_fill"), {"text": "Some sentence about drinks"})


AI_ANSWER = dict(is_expense=True, amount="10", currency="USD", beneficiaries=[], everyone=True,
                 type="Food & drink", description="Drinks", date=None)  # fmt: skip


def test_ai_fill_for_a_member_names_another_payer_so_who_paid_is_missing(crew, ai_reply):
    ai_reply.update(AI_ANSWER, payer="Dan")
    data = ai_fill(crew.client("cara"), crew).json()
    assert "payer" not in data["fields"]
    assert "who paid" in data["missing"]
    # Owner and Editors get the payer the sentence names.
    data = ai_fill(crew.client("ben"), crew).json()
    assert data["fields"]["payer"] == str(crew.travelers["dan"].id)


@pytest.mark.parametrize("named", ["Cara", None])
def test_ai_fill_for_a_member_always_uses_her_own_traveler(crew, ai_reply, named):
    ai_reply.update(AI_ANSWER, payer=named)
    data = ai_fill(crew.client("cara"), crew).json()
    assert data["fields"]["payer"] == str(crew.travelers["cara"].id)
    assert not any(m.startswith("who paid") for m in data["missing"])


def test_viewers_get_no_ai_fill_and_no_suggestion(crew, ai_reply):
    ai_reply.update(AI_ANSWER, payer="Ann")
    eve = crew.client("eve")
    assert ai_fill(eve, crew).status_code == 403
    assert eve.post(crew.url("description_suggestion"), {"text": "tuktuk"}).status_code == 403


# --- Every trip view, for every role ---------------------------------------------------------

OK, NO, HIDDEN = "ok", 403, 404
EVERYONE = {"ann": OK, "ben": OK, "cara": OK, "eve": OK, "sam": HIDDEN}
ADDERS = {"ann": OK, "ben": OK, "cara": OK, "eve": NO, "sam": HIDDEN}
MANAGERS = {"ann": OK, "ben": OK, "cara": NO, "eve": NO, "sam": HIDDEN}
OWNER = {"ann": OK, "ben": NO, "cara": NO, "eve": NO, "sam": HIDDEN}

# (view, method, address arguments, form data, who may use it). "taxi" is Dan's expense, so
# Cara (a Member) may only look at it.
VIEWS = [
    ("trip", "get", [], None, EVERYONE),
    ("summary", "get", [], None, EVERYONE),
    ("report", "get", [], None, EVERYONE),
    ("report_export", "get", ["csv"], None, EVERYONE),
    ("people", "get", [], None, EVERYONE),
    ("expense_edit", "get", ["taxi"], None, EVERYONE),
    ("expense_create", "get", [], None, ADDERS),
    ("expense_create", "post", [], "own", ADDERS),
    ("category_create", "post", [], {"name": "Tips", "emoji": "💵"}, ADDERS),
    ("expense_ai_fill", "post", [], {"text": "Drinks for everyone"}, ADDERS),
    ("description_suggestion", "post", [], {"text": "tuktuk"}, ADDERS),
    ("expense_edit", "post", ["taxi"], "dan", MANAGERS),
    ("expense_delete", "get", ["taxi"], None, MANAGERS),
    ("expense_delete", "post", ["taxi"], None, MANAGERS),
    ("expense_reorder", "post", [], {"day": "2026-06-01", "ids": ["taxi"]}, MANAGERS),
    ("category_edit", "post", ["unused_type"], {"name": "Meals", "emoji": "🍜"}, MANAGERS),
    ("category_delete", "post", ["unused_type"], None, MANAGERS),
    ("trip_settle", "post", [], None, MANAGERS),
    ("trip_reopen", "post", [], None, MANAGERS),
    ("trip_settings", "get", [], None, OWNER),
    ("trip_settings", "post", [], {"name": "New name", "base_currency": "USD"}, OWNER),
    ("rate_save", "post", [], {"currency": "VND", "rate": "26000"}, OWNER),
    ("rate_delete", "get", ["rate"], None, OWNER),
    ("rate_delete", "post", ["rate"], None, OWNER),
    ("trip_delete", "get", [], None, OWNER),
    ("trip_delete", "post", [], None, OWNER),
    ("participant_create", "get", [], None, OWNER),
    ("participant_create", "post", [], {"name": "Kid"}, OWNER),
    ("participant_edit", "get", ["dan_p"], None, OWNER),
    ("participant_edit", "post", ["dan_p"], {"name": "Daniel"}, OWNER),
    ("participant_delete", "get", ["dan_p"], None, OWNER),
    ("participant_delete", "post", ["dan_p"], None, OWNER),
    ("member_add", "get", [], None, OWNER),
    ("member_add", "post", [], {"username": "sam"}, OWNER),
    ("member_edit", "get", ["cara_m"], None, OWNER),
    ("member_edit", "post", ["cara_m"], {"role": "editor"}, OWNER),
    ("member_transfer", "get", ["dan_m"], None, OWNER),
    ("member_transfer", "post", ["dan_m"], None, OWNER),
    ("member_remove", "post", ["dan_m"], None, OWNER),
]


@pytest.mark.parametrize("who", list(EVERYONE))
@pytest.mark.parametrize(
    ("view", "method", "args", "data", "expected"),
    VIEWS,
    ids=[f"{v[1]}-{v[0]}" for v in VIEWS],
)
def test_every_trip_view_answers_each_role(crew, ai_reply, who, view, method, args, data, expected):
    ai_reply.update(AI_ANSWER, payer=None)
    crew.trip.rates.create(currency="KHR", rate=Decimal("4000"))
    named = {
        "taxi": crew.taxi.id,
        "unused_type": crew.trip.categories.get(name="Transport").id,
        "rate": crew.trip.rates.get().id,
        "dan_p": Participant.objects.create(trip=crew.trip, name="Unused").id,
        "cara_m": crew.members["cara"].id,
        "dan_m": crew.members["dan"].id,
    }
    url = crew.url(view, *(named.get(a, a) for a in args))
    if data == "own":  # Each account records an expense its own traveler paid.
        data = crew.form(who if who in crew.travelers else "ann")
    elif data == "dan":
        data = crew.form("dan", "25", "Taxi")
    elif data and "ids" in data:
        data = {**data, "ids": [named[i] for i in data["ids"]]}
    response = getattr(crew.client(who), method)(url, data or {})
    if expected[who] == OK:
        assert response.status_code < 400, response.content[:300]
    else:
        assert response.status_code == expected[who]


def test_read_only_notices_and_split_name_the_right_people(crew):
    cara = crew.client("cara")
    # A payer whose account name differs from the traveler name shows both.
    dan = crew.users["dan"]
    dan.first_name = "Daniel"
    dan.save()
    html = cara.get(crew.url("expense_edit", crew.taxi.id)).content.decode()
    assert "Only Daniel (Dan), the Owner or an Editor can change this expense." in html
    # A payer with no account: only the Owner or an Editor.
    kid = Participant.objects.create(trip=crew.trip, name="Kid")
    snack = Expense.objects.create(
        trip=crew.trip, payer=kid, amount=Decimal("9"), currency="USD",
        date=date(2026, 6, 1), category=crew.food,
    )  # fmt: skip
    snack.beneficiaries.set([kid, crew.travelers["ann"]])
    html = cara.get(crew.url("expense_edit", snack.id)).content.decode()
    assert "Only the Owner or an Editor can change this expense." in html
    assert '<span class="name">Ann</span>, <span class="name">Kid</span>' in html
    assert "2 travelers · 4.50 USD each" in html
    assert "Added on " in html and "Added by" not in html  # No recorded creator.
    # A Viewer is told why.
    html = crew.client("eve").get(crew.url("expense_edit", snack.id)).content.decode()
    assert "Your account is not linked to a traveler" in html


def test_account_page_wording(crew):
    ann = crew.client("ann")
    page = ann.get(crew.url("member_edit", crew.members["cara"].id)).content.decode()
    assert "Traveler: Cara" in page and "cara ·" not in page  # Username equals the name.
    assert "A Member can change only the expenses that Cara paid." in page
    assert "Make Cara the Owner" in page
    assert "no longer linked to Cara." in page
    page = ann.get(crew.url("member_edit", crew.members["eve"].id)).content.decode()
    assert "so as a Member it can only view the trip" in page
    assert "no longer linked" not in page
    response = ann.post(
        crew.url("member_edit", crew.members["cara"].id), {"role": "editor"}, follow=True
    )
    assert "Cara is now an Editor." in response.content.decode()
    response = ann.post(
        crew.url("member_edit", crew.members["cara"].id), {"role": "member"}, follow=True
    )
    assert "Cara is now a Member." in response.content.decode()
    accounts = ann.get(crew.url("people")).content.decode().split(">Accounts<")[1]
    assert "traveler Cara" not in accounts
