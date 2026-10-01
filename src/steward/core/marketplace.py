"""Claim 6 — access is requested, approved by a named human, and expires.

`decide()` turns the ledger into outcomes: a request becomes a grant only when its decision passes every
check below; anything else is refused with a named reason, and a request with no decision is denied
(doctrine 1). `gate()` then judges an IAM snapshot of the estate against those outcomes.

**No clock is read anywhere in this module.** "Now" is always data: the ledger's `as_of` when compiling,
the snapshot's `captured_at` when judging. A test that controlled the clock the code reads would be the
code agreeing with itself (claim 6's trap); tests/test_marketplace.py fails if this file ever calls
`now()` or `today()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .compile import seats_for
from .contract import Contract, Roles
from .findings import Finding

GATE = "marketplace"
VIEWER = "roles/bigquery.dataViewer"


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Outcome:
    request: dict
    status: str  # granted | refused | denied-no-decision
    reasons: list[Finding] = field(default_factory=list)
    decision: dict | None = None
    expires_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "request": self.request,
            "status": self.status,
            "decision": self.decision,
            "expires_at": self.expires_at,
            "reasons": [r.to_dict() for r in self.reasons],
        }


def _seat_role(seat: str) -> str:
    return seat.split("@")[0]


def decide(ledger: dict, contracts: list[Contract], roles: Roles) -> list[Outcome]:
    by_ds = {c.dataset: c for c in contracts}
    decisions: dict[str, list[dict]] = {}
    for d in ledger.get("decisions", []):
        decisions.setdefault(d["request"], []).append(d)
    out: list[Outcome] = []
    for req in ledger.get("requests", []):
        rid = req["id"]
        ds = by_ds.get(req["dataset"])
        ds_list = decisions.get(rid, [])
        if not ds_list:
            out.append(
                Outcome(
                    req,
                    "denied-no-decision",
                    [
                        Finding(
                            "NO_DECISION",
                            GATE,
                            rid,
                            "no human has decided; denied until one does (doctrine 1)",
                            severity="info",
                        )
                    ],
                )
            )
            continue
        if len(ds_list) > 1:
            out.append(
                Outcome(
                    req,
                    "refused",
                    [
                        Finding(
                            "DECISION_AMBIGUOUS",
                            GATE,
                            rid,
                            f"{len(ds_list)} decisions recorded; one request, one decision",
                        )
                    ],
                    ds_list[-1],
                )
            )
            continue
        dec = ds_list[0]
        f: list[Finding] = []
        approver, requester = dec["by"], req["requester"]
        if not requester.startswith("user:"):
            f.append(
                Finding(
                    "REQUESTER_NOT_HUMAN", GATE, rid, f"requested by {requester}; access is requested by a named person"
                )
            )
        if approver == requester:
            f.append(Finding("SELF_APPROVAL", GATE, rid, f"{approver} approved their own request (doctrine 5)"))
        if approver.startswith("serviceAccount:"):
            f.append(
                Finding(
                    "SERVICE_ACCOUNT_APPROVAL",
                    GATE,
                    rid,
                    f"approved by {approver}: no pipeline approves access (doctrine 5)",
                )
            )
        elif not approver.startswith("user:"):
            f.append(
                Finding(
                    "APPROVER_NOT_HUMAN",
                    GATE,
                    rid,
                    f"approved by {approver}: a decision is made by a named person, not a group",
                )
            )
        if ds is None:
            f.append(Finding("DATASET_UNKNOWN", GATE, rid, f"{req['dataset']} has no contract"))
        else:
            if approver.startswith("user:") and not roles.is_member(approver, ds.marketplace.approvers):
                f.append(
                    Finding(
                        "APPROVER_NOT_AUTHORISED",
                        GATE,
                        rid,
                        f"{approver} is not in {ds.marketplace.approvers}, the approvers {ds.dataset}'s contract names",
                    )
                )
            role = _seat_role(req["seat"])
            if role in ds.readers:
                f.append(
                    Finding(
                        "ROLE_NOT_GRANTABLE",
                        GATE,
                        rid,
                        f"{role} already reads {ds.dataset} standing; a grant would expire nothing",
                    )
                )
            elif role not in ds.marketplace.grantable_roles:
                f.append(
                    Finding(
                        "ROLE_NOT_GRANTABLE",
                        GATE,
                        rid,
                        f"{role} is not grantable on {ds.dataset} ({ds.marketplace.grantable_roles})",
                    )
                )
            if req["days"] > ds.marketplace.max_grant_days:
                f.append(
                    Finding(
                        "DURATION_EXCEEDS_MAX",
                        GATE,
                        rid,
                        f"{req['days']} days > {ds.marketplace.max_grant_days} allowed by {ds.dataset}'s contract",
                    )
                )
        if ts(dec["at"]) < ts(req["at"]):
            f.append(Finding("DECISION_BEFORE_REQUEST", GATE, rid, "decided before it was requested"))
        if dec["decision"] != "approve":
            out.append(
                Outcome(
                    req,
                    "refused",
                    [Finding("DENIED_BY_APPROVER", GATE, rid, f"denied by {approver}", severity="info")],
                    dec,
                )
            )
            continue
        if f:
            out.append(Outcome(req, "refused", f, dec))
            continue
        out.append(Outcome(req, "granted", [], dec, iso(ts(dec["at"]) + timedelta(days=req["days"]))))
    return out


def active_grants(outcomes: list[Outcome], as_of: str) -> list[Outcome]:
    """Grants still live at `as_of` (data, never a clock)."""
    t = ts(as_of)
    return [o for o in outcomes if o.status == "granted" and ts(o.expires_at) > t]


def condition_expression(expires_at: str) -> str:
    return f'request.time < timestamp("{expires_at}")'


def _expiry_from(expression: str | None) -> datetime | None:
    if not expression or "request.time < timestamp(" not in expression:
        return None
    return ts(expression.split('timestamp("', 1)[1].split('")', 1)[0])


def gate(snapshot: dict, outcomes: list[Outcome], contracts: list[Contract], roles: Roles) -> list[Finding]:
    """Judge an IAM snapshot. Now = snapshot['captured_at'] — the moment the evidence was taken."""
    now = ts(snapshot["captured_at"])
    by_ds = {c.dataset: c for c in contracts}
    granted = {(o.request["seat"], o.request["dataset"], o.expires_at): o for o in outcomes if o.status == "granted"}
    out: list[Finding] = []
    for b in snapshot["bindings"]:
        if b["role"] != VIEWER:
            continue
        ds, seat = b["dataset"], b["seat"]
        c = by_ds.get(ds)
        if c is None:
            continue
        target = f"{ds}:{seat}"
        standing = seat in {s for r in c.readers for s in seats_for(roles, r, c)}
        expiry = _expiry_from((b.get("condition") or {}).get("expression"))
        if expiry is None:
            if not standing:
                out.append(
                    Finding(
                        "GRANT_WITHOUT_EXPIRY",
                        GATE,
                        target,
                        "dataViewer with no expiry condition for a seat that is not a standing reader — every grant expires",
                    )
                )
            continue
        if expiry <= now:
            out.append(
                Finding(
                    "GRANT_EXPIRED_PRESENT",
                    GATE,
                    target,
                    f"expired {iso(expiry)}, still bound at capture {snapshot['captured_at']} — remove it",
                )
            )
        if (seat, ds, iso(expiry)) not in granted:
            out.append(
                Finding(
                    "GRANT_UNAPPROVED", GATE, target, f"bound until {iso(expiry)} with no approved request behind it"
                )
            )
    return out
