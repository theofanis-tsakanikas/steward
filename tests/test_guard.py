"""The budget guard and the reaper decide in logic.py, with no Google library: so they are tested here."""

from __future__ import annotations

import base64
import importlib.util
import json
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


def test_the_guard_stops_at_the_last_level_and_not_before():
    assert not logic.spend_reached({"costAmount": 29.99}, 50)
    assert not logic.spend_reached({"costAmount": 49.99}, 50)
    assert logic.spend_reached({"costAmount": 50}, 50)
    assert logic.spend_reached({"costAmount": 80}, 50)


def test_a_notification_that_cannot_be_read_is_treated_as_an_alert():
    # doctrine 1: the safe state is "stop spending"
    for bad in ({}, {"costAmount": None}, {"costAmount": "plenty"}):
        assert logic.spend_reached(bad, 50)


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


def test_the_guard_and_the_terraform_agree_on_the_stop_level():
    tf = (io.REPO / "infra" / "bootstrap" / "guard.tf").read_text()
    assert "GUARD_STOP_AT  = tostring(max(var.alert_at...))" in tf  # the last alert level is the stop level
    variables = (io.REPO / "infra" / "bootstrap" / "variables.tf").read_text()
    assert "default     = [30, 50]" in variables  # CLAUDE.md: alerts at 30 and 50
