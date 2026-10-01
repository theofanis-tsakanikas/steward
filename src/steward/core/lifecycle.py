"""Report lifecycle — an unused dashboard is notified, then archived; never deleted silently.

Input is a usage export (Looker System Activity in REAL mode; a labelled fixture otherwise, D3) with its
own `captured_at`, which is "now" here. No clock is read.

  active          viewed within NOTIFY_AFTER days
  notify-owner    not viewed for NOTIFY_AFTER days: the owner is told, with the archive date
  archive-due     notified at least GRACE days ago and still unviewed: archive (reversible), never delete
"""

from __future__ import annotations

from datetime import timedelta

from .marketplace import iso, ts

NOTIFY_AFTER = 90
GRACE = 14


def states(usage: dict) -> list[dict]:
    now = ts(usage["captured_at"])
    out = []
    for d in usage["dashboards"]:
        last = ts(d["last_viewed"]) if d.get("last_viewed") else None
        idle = (now - last).days if last else None
        notified = ts(d["notified_at"]) if d.get("notified_at") else None
        if notified and last and notified < last:
            notified = None  # a notice from an earlier idle spell; the dashboard was opened since
        if idle is not None and idle < NOTIFY_AFTER:
            state, action = "active", "none"
        elif notified and (now - notified).days >= GRACE:
            state, action = "archive-due", f"archive (reversible); owner {d['owner']} was notified {iso(notified)}"
        else:
            due = (notified or now) + timedelta(days=GRACE)
            state, action = "notify-owner", f"notify {d['owner']}: archived on {iso(due)} unless opened or renewed"
        out.append(
            {
                "dashboard": d["id"],
                "owner": d["owner"],
                "last_viewed": d.get("last_viewed"),
                "idle_days": idle,
                "state": state,
                "action": action,
                "delete": False,
            }
        )
    return out
