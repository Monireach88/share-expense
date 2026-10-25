import json
from decimal import Decimal
from pathlib import Path

import pytest

from apps.settlement.engine import ExpenseInput, SettlementError, Transfer, settle, to_base

SHEETS = sorted((Path(__file__).parent / "fixtures" / "sheets").glob("*.json"))
D = Decimal


def load(path: Path) -> dict:
    data = json.loads(path.read_text())
    data["expenses"] = [
        ExpenseInput(e["payer"], e["beneficiaries"], D(e["amount"]), e["currency"], e["category"])
        for e in data["expenses"]
    ]
    data["rates"] = {k: D(v) for k, v in data["rates"].items()}
    return data


def run(data: dict):
    return settle(
        data["participants"],
        data["expenses"],
        base_currency=data["base_currency"],
        rates=data["rates"],
        sponsors=data["sponsors"],
    )


@pytest.mark.parametrize("path", SHEETS, ids=[p.stem for p in SHEETS])
def test_balances_match_original_spreadsheet(path):
    data = load(path)
    result = run(data)
    for person in result.people:
        expected = D(str(data["expected_balances"][person.participant]))
        assert abs(person.balance - expected) <= D("0.01"), person


@pytest.mark.parametrize("path", SHEETS, ids=[p.stem for p in SHEETS])
def test_balances_add_up_to_zero_and_transfers_settle_everyone(path):
    result = run(load(path))
    assert sum(p.balance for p in result.people) == 0
    remaining = {p.participant: p.balance for p in result.people}
    for t in result.transfers:
        remaining[t.sender] += t.amount
        remaining[t.receiver] -= t.amount
    assert all(v == 0 for v in remaining.values())
    assert len(result.transfers) <= len(result.people) - 1


def test_conversion_rounds_half_up_to_cents():
    assert to_base(D("74000"), "VND", "USD", {"VND": D("26200")}) == D("2.82")
    assert to_base(D("0.005"), "USD", "USD", {}) == D("0.01")


def test_equal_split_and_simple_transfer():
    result = settle(
        ["a", "b"], [ExpenseInput("a", ["a", "b"], D("10"), "USD")], base_currency="USD"
    )
    assert [p.balance for p in result.people] == [D("5.00"), D("-5.00")]
    assert result.transfers == [Transfer("b", "a", D("5.00"))]


def test_sponsored_share_moves_to_sponsor():
    # c's share is covered by a, so c owes nothing even though c ate.
    result = settle(
        ["a", "b", "c"],
        [ExpenseInput("b", ["a", "b", "c"], D("30"), "USD")],
        base_currency="USD",
        sponsors={"c": ["a"]},
    )
    balances = {p.participant: p.balance for p in result.people}
    assert balances == {"a": D("-20.00"), "b": D("20.00"), "c": D("0.00")}


def test_share_split_between_two_sponsors():
    result = settle(
        ["a", "b", "c"],
        [ExpenseInput("c", ["c"], D("10"), "USD")],
        base_currency="USD",
        sponsors={"c": ["a", "b"]},
    )
    balances = {p.participant: p.balance for p in result.people}
    assert balances == {"a": D("-5.00"), "b": D("-5.00"), "c": D("10.00")}


def test_paid_for_self_splits_a_balance_into_both_directions():
    # me pays a bus for all; maly pays a room for me alone and a snack for all.
    people = ["me", "maly", "a", "b"]
    result = settle(
        people,
        [
            ExpenseInput("me", people, D("500"), "USD"),
            ExpenseInput("maly", ["me"], D("500"), "USD"),
            ExpenseInput("maly", people, D("20"), "USD"),
        ],
        base_currency="USD",
    )
    me, maly = result.people[0], result.people[1]
    assert (me.paid - me.paid_for_self, me.responsible_for - me.paid_for_self) == (
        D("375.00"),
        D("505.00"),
    )
    assert (maly.paid - maly.paid_for_self, maly.responsible_for - maly.paid_for_self) == (
        D("515.00"),
        D("125.00"),
    )


def test_paying_for_the_person_you_cover_counts_as_paying_for_yourself():
    result = settle(
        ["a", "b", "c"],
        [ExpenseInput("a", ["a", "c"], D("10"), "USD")],
        base_currency="USD",
        sponsors={"c": ["a"]},
    )
    assert result.people[0].paid_for_self == D("10.00")


def test_three_way_split_rounds_without_losing_a_cent():
    result = settle(
        ["a", "b", "c"], [ExpenseInput("a", ["a", "b", "c"], D("10"), "USD")], base_currency="USD"
    )
    balances = sorted(p.balance for p in result.people)
    assert balances == [D("-3.34"), D("-3.33"), D("6.67")]


def test_names_that_contain_each_other_are_kept_apart():
    # The spreadsheet matched names as text, so "Aunt" also matched "Aunt-in-law".
    result = settle(
        ["Aunt", "Aunt-in-law"],
        [ExpenseInput("Aunt", ["Aunt-in-law"], D("8"), "USD")],
        base_currency="USD",
    )
    balances = {p.participant: p.balance for p in result.people}
    assert balances == {"Aunt": D("8.00"), "Aunt-in-law": D("-8.00")}


def test_category_totals():
    result = settle(
        ["a"],
        [
            ExpenseInput("a", ["a"], D("3"), "USD", "F&B"),
            ExpenseInput("a", ["a"], D("5"), "USD", "HOTEL"),
        ],
        base_currency="USD",
    )
    assert result.by_category == {"HOTEL": D("5.00"), "F&B": D("3.00")}
    assert result.total == D("8.00")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"expenses": [ExpenseInput("x", ["a"], D("1"), "USD")]}, "Unknown payer"),
        ({"expenses": [ExpenseInput("a", ["x"], D("1"), "USD")]}, "Unknown beneficiary"),
        ({"expenses": [ExpenseInput("a", [], D("1"), "USD")]}, "at least one beneficiary"),
        ({"expenses": [ExpenseInput("a", ["a"], D("1"), "VND")]}, "No exchange rate"),
        ({"expenses": [], "sponsors": {"a": ["x"]}}, "Unknown sponsor"),
        ({"expenses": [], "sponsors": {"a": ["b"], "b": ["c"]}}, "covered by someone else"),
    ],
)
def test_invalid_input_is_rejected(kwargs, message):
    with pytest.raises(SettlementError, match=message):
        settle(["a", "b", "c"], base_currency="USD", **kwargs)
