"""The guard's decisions, pure: no Google library, so they are tested offline (tests/test_guard.py).

Two decisions only:
  * has the project's spend reached the level at which the deploy path must stop?
  * has a dataset passed the date written on it?
Anything not understood is a "no action" for the reaper (it must never delete on a guess) and a "yes" for the
guard (an alert that cannot be read is treated as an alert: the safe state is "stop spending").
"""

from __future__ import annotations

import base64
import json
import re
from datetime import date

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def decode_budget_message(cloud_event_data: dict) -> dict:
    """A budget notification arrives as a Pub/Sub message whose data is base64-encoded JSON."""
    raw = cloud_event_data["message"]["data"]
    return json.loads(base64.b64decode(raw).decode("utf-8"))


def spend_reached(message: dict, stop_at: float) -> bool:
    """True when the notification says cost >= stop_at, or when it cannot be read."""
    try:
        return float(message["costAmount"]) >= stop_at
    except (KeyError, TypeError, ValueError):
        return True


def expired(labels: dict | None, today: date) -> bool:
    """A dataset is expired when it is Steward's (project=steward) and its expires-at is strictly before today.

    No label, an unparseable label, or someone else's dataset: not expired."""
    labels = labels or {}
    if labels.get("project") != "steward":
        return False
    value = labels.get("expires-at", "")
    if not ISO_DATE.match(value):
        return False
    try:
        return date.fromisoformat(value) < today
    except ValueError:
        return False
