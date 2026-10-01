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
import math
import re
from datetime import date

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def decode_budget_message(cloud_event_data) -> dict | None:
    """A budget notification arrives as a Pub/Sub message whose data is base64-encoded JSON. Anything else
    (no message, bad base64, bad JSON, JSON that is not an object) is None: unreadable, never an exception."""
    try:
        raw = cloud_event_data["message"]["data"]
        message = json.loads(base64.b64decode(raw, validate=True).decode("utf-8"))
    except Exception:
        return None
    return message if isinstance(message, dict) else None


def parse_stop_at(raw) -> float:
    """The stop level from the environment. One that cannot be read, or is not a finite number, is 0: stop."""
    try:
        level = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return level if math.isfinite(level) else 0.0


def spend_reached(message, stop_at: float) -> bool:
    """True when the notification says cost >= stop_at, or when it cannot be read: not an object, no cost,
    a cost that is not a number, NaN or infinite (NaN compares False with everything, so it is tested first)."""
    if not isinstance(message, dict):
        return True
    try:
        cost = float(message["costAmount"])
    except (KeyError, TypeError, ValueError):
        return True
    if not math.isfinite(cost):
        return True
    return cost >= stop_at


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
