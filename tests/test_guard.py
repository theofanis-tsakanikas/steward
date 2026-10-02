"""The budget guard and the reaper decide in logic.py, with no Google library: so they are tested here."""

from __future__ import annotations

import base64
import importlib.util
import json
import re
from datetime import date

from steward import io

spec = importlib.util.spec_from_file_location("guard_logic", io.REPO / "infra" / "bootstrap" / "guard" / "logic.py")
logic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logic)

TODAY = date(2026, 10, 7)


def event(body: dict) -> dict:
    return {"message": {"data": base64.b64encode(json.dumps(body).encode()).decode()}}


def test_a_budget_message_is_decoded():
    assert logic.decode_budget_message(event({"costAmount": 31.5}))["costAmount"] == 31.5


def test_the_guard_stops_at_the_stop_level_and_not_before():
    assert not logic.spend_reached({"costAmount": 29.99}, 45)
    assert not logic.spend_reached({"costAmount": 44.99}, 45)
    assert logic.spend_reached({"costAmount": 45}, 45)
    assert logic.spend_reached({"costAmount": 80}, 45)


def test_a_notification_that_cannot_be_read_is_treated_as_an_alert():
    # doctrine 1: the safe state is "stop spending" — including where the failure is in the decoding
    for bad in (
        {},
        {"costAmount": None},
        {"costAmount": "plenty"},
        {"costAmount": float("nan")},
        {"costAmount": "NaN"},
    ):
        assert logic.spend_reached(bad, 45)
    assert logic.spend_reached({"costAmount": float("inf")}, 45)
    for not_an_object in (None, [], "text", 7):
        assert logic.spend_reached(not_an_object, 45)


def test_a_message_that_cannot_be_decoded_is_none_and_never_an_exception():
    good = base64.b64encode(b'{"costAmount": 1}').decode()
    bad_inputs = [
        {},
        {"message": {}},
        {"message": {"data": "!!not base64!!"}},
        {"message": {"data": base64.b64encode(b"{not json").decode()}},
        {"message": {"data": base64.b64encode(b"[1, 2]").decode()}},  # JSON, but not an object
        {"message": {"data": base64.b64encode(b"\xff\xfe").decode()}},  # not UTF-8
        {"message": {"data": 12}},
        None,
    ]
    for bad in bad_inputs:
        assert logic.decode_budget_message(bad) is None, bad
        assert logic.spend_reached(logic.decode_budget_message(bad), 45)  # ...and None means stop
    assert logic.decode_budget_message({"message": {"data": good}}) == {"costAmount": 1}


def test_a_stop_level_that_cannot_be_read_stops_everything():
    assert logic.parse_stop_at("45") == 45.0
    for bad in (None, "", "soon", "nan", "inf"):
        assert logic.parse_stop_at(bad) == 0.0


def test_the_reaper_deletes_only_steward_datasets_past_their_date():
    mine = {"project": "steward"}
    assert logic.expired({**mine, "expires-at": "2026-10-06"}, TODAY)
    assert not logic.expired({**mine, "expires-at": "2026-10-07"}, TODAY)  # the last day is still a day
    assert not logic.expired({**mine, "expires-at": "2026-10-08"}, TODAY)


def test_the_reaper_never_deletes_on_a_guess():
    assert not logic.expired(None, TODAY)
    assert not logic.expired({}, TODAY)
    assert not logic.expired({"project": "steward"}, TODAY)  # no date
    assert not logic.expired({"project": "steward", "expires-at": "soon"}, TODAY)
    assert not logic.expired({"project": "steward", "expires-at": "2026-13-45"}, TODAY)  # not a date
    assert not logic.expired({"project": "someone-else", "expires-at": "2020-01-01"}, TODAY)  # not ours


def _default(name: str, text: str) -> str:
    block = text[text.index(f'variable "{name}"') :]
    return re.search(r"default\s*=\s*(.+)", block).group(1).strip()


def test_the_guard_and_the_terraform_agree_on_the_stop_level():
    root = io.REPO / "infra" / "bootstrap"
    tf, variables = (root / "guard.tf").read_text(), (root / "variables.tf").read_text()
    assert re.search(r"GUARD_STOP_AT\s*=\s*tostring\(var\.stop_at\)", tf)  # one source for the stop level
    stop, total = float(_default("stop_at", variables)), float(_default("budget_total", variables))
    assert 0 < stop < total  # headroom: budget data lags, a stop at the ceiling is already over it
    assert json.loads(_default("alert_at", variables)) == [30, 50]  # CLAUDE.md: alerts at 30 and 50
    assert total <= 50


def test_the_deployer_and_the_destroyer_are_different_identities_and_only_the_deployer_is_switched_off():
    root = io.REPO / "infra" / "bootstrap"
    guard = (root / "guard.tf").read_text()
    assert "google_service_account.deployer.name" in guard.split("guard_may_disable_deployer")[1].split("}")[0]
    assert "google_service_account.destroyer" not in guard  # the way to take the estate down stays open


def test_a_free_trial_budget_measures_gross_usage_not_net_of_credits():
    # On a Free Trial the credit pays everything, so net spend is zero forever and a net budget never alerts.
    root = io.REPO / "infra" / "bootstrap"
    assert _default("budget_counts_credits", (root / "variables.tf").read_text()) == "false"
    budget = (root / "budget.tf").read_text()
    assert re.search(
        r'credit_types_treatment\s*=\s*var\.budget_counts_credits \? "INCLUDE_ALL_CREDITS" : "EXCLUDE_ALL_CREDITS"',
        budget,
    )
