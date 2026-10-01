"""Claim 6 — access is requested, approved by a named human, and expires.

`decide()` turns the ledger into outcomes: a request becomes a grant — to the person who asked, never
to their whole seat — only when its decision passes every check below; anything else is refused with a
named reason, and a request with no decision is denied (doctrine 1). `gate()` judges an IAM snapshot of
the estate against those outcomes.

**No clock is read.** "Now" is data: the ledger's `as_of` when compiling, the snapshot's `captured_at`
when judging. scripts/check_core_purity.py refuses any clock in the core (CORE_CLOCK).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .compile import seats_for
from .contract import Contract, Roles
from .findings import Finding

GATE = "marketplace"
VIEWER = "roles/bigquery.dataViewer"
EDITOR = "roles/bigquery.dataEditor"
_CONDITION = re.compile(r'^request\.time < timestamp\("(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"\)$')


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(principal: str) -> str:
    """IAM principals compare case-insensitively and without stray whitespace."""
    return principal.strip().casefold()


def _utc(v: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", v):
        raise ValueError(f"timestamps are UTC, written YYYY-MM-DDTHH:MM:SSZ: {v!r}")
    ts(v)
    return v


# ── the ledger, strictly typed ────────────────────────────────────────────────────────────────────


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Request(_M):
    id: str = Field(pattern=r"^R-\d{3}$")
    requester: str
    seat: str
    dataset: str
    days: int = Field(gt=0)
    at: str
    justification: str = Field(min_length=10)

    @field_validator("at")
    @classmethod
    def _t(cls, v: str) -> str:
        return _utc(v)

    @field_validator("requester")
    @classmethod
    def _p(cls, v: str) -> str:
        if not re.fullmatch(r"(user|group|serviceAccount):[^@\s]+@[^@\s]+", v.strip()):
            raise ValueError(f"not an IAM principal (lower-case prefix): {v!r}")
        return v


class Decision(_M):
    request: str
    decision: Literal["approve", "deny"]
    by: str
    at: str

    @field_validator("at")
    @classmethod
    def _t(cls, v: str) -> str:
        return _utc(v)

    @field_validator("by")
    @classmethod
    def _p(cls, v: str) -> str:
        if not re.fullmatch(r"(user|group|serviceAccount):[^@\s]+@[^@\s]+", v.strip()):
            raise ValueError(f"not an IAM principal (lower-case prefix): {v!r}")
        return v


class Ledger(_M):
    as_of: str
    requests: list[Request]
    decisions: list[Decision]

    @field_validator("as_of")
    @classmethod
    def _t(cls, v: str) -> str:
        return _utc(v)

    @model_validator(mode="after")
    def _refs(self) -> Ledger:
        ids = [r.id for r in self.requests]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate request ids {dupes}")
        unknown = sorted({d.request for d in self.decisions} - set(ids))
        if unknown:
            raise ValueError(f"decisions for unknown requests {unknown}")
        return self


def load_ledger(doc: dict) -> tuple[Ledger | None, list[Finding]]:
    try:
        return Ledger.model_validate(doc), []
    except ValidationError as e:
        return None, [
            Finding("LEDGER_INVALID", GATE, ".".join(map(str, err["loc"])) or "ledger", err["msg"])
            for err in e.errors()
        ]


# ── decisions ─────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Outcome:
    request: dict
    status: str  # granted | refused | denied-no-decision
    reasons: list[Finding] = field(default_factory=list)
    decision: dict | None = None
    expires_at: str | None = None

    @property
    def member(self) -> str:
        """The grant goes to the person who asked."""
        return self.request["requester"]

    def to_dict(self) -> dict:
        return {
            "request": self.request,
            "status": self.status,
            "decision": self.decision,
            "expires_at": self.expires_at,
            "member": self.member if self.status == "granted" else None,
            "reasons": [r.to_dict() for r in self.reasons],
        }


def _role(seat: str) -> str:
    return seat.split("@")[0]


def decide(ledger: dict | Ledger, contracts: list[Contract], roles: Roles) -> list[Outcome]:
    lg = ledger if isinstance(ledger, Ledger) else Ledger.model_validate(ledger)
    by_ds = {c.dataset: c for c in contracts}
    decisions: dict[str, list[Decision]] = {}
    for d in lg.decisions:
        decisions.setdefault(d.request, []).append(d)
    out: list[Outcome] = []
    for r in lg.requests:
        req = r.model_dump()
        rid = r.id
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
                    ds_list[-1].model_dump(),
                )
            )
            continue
        dec = ds_list[0]
        f: list[Finding] = []
        approver, requester = norm(dec.by), norm(r.requester)
        ds = by_ds.get(r.dataset)
        # who asked
        if not requester.startswith("user:"):
            f.append(
                Finding(
                    "REQUESTER_NOT_HUMAN",
                    GATE,
                    rid,
                    f"requested by {r.requester}; access is requested by a named person",
                )
            )
        elif not any(requester == norm(m) for ms in roles.directory.values() for m in ms):
            f.append(Finding("REQUESTER_UNKNOWN", GATE, rid, f"{r.requester} is not in the directory"))
        group = roles.seat_groups.get(r.seat)
        if group is None:
            f.append(Finding("SEAT_NOT_REQUESTABLE", GATE, rid, f"{r.seat} is not a requestable seat"))
        elif not any(requester == norm(m) for m in roles.members(group)):
            f.append(
                Finding(
                    "REQUESTER_NOT_IN_SEAT",
                    GATE,
                    rid,
                    f"{r.requester} is not in {group}, so cannot ask for {r.seat}'s access",
                )
            )
        # who decided
        if approver == requester:
            f.append(Finding("SELF_APPROVAL", GATE, rid, f"{dec.by} approved their own request (doctrine 5)"))
        if approver.startswith("serviceaccount:"):
            f.append(
                Finding(
                    "SERVICE_ACCOUNT_APPROVAL",
                    GATE,
                    rid,
                    f"approved by {dec.by}: no pipeline approves access (doctrine 5)",
                )
            )
        elif not approver.startswith("user:"):
            f.append(
                Finding(
                    "APPROVER_NOT_HUMAN",
                    GATE,
                    rid,
                    f"approved by {dec.by}: a decision is made by a named person, not a group",
                )
            )
        # what was asked
        if ds is None:
            f.append(Finding("DATASET_UNKNOWN", GATE, rid, f"{r.dataset} has no contract"))
        else:
            if approver.startswith("user:") and not any(
                approver == norm(m) for m in roles.members(ds.marketplace.approvers)
            ):
                f.append(
                    Finding(
                        "APPROVER_NOT_AUTHORISED",
                        GATE,
                        rid,
                        f"{dec.by} is not in {ds.marketplace.approvers}, the approvers {ds.dataset}'s contract names",
                    )
                )
            role = _role(r.seat)
            if not ds.marketplace.listable:
                f.append(
                    Finding(
                        "DATASET_NOT_LISTED",
                        GATE,
                        rid,
                        f"{ds.dataset} is not listed in the marketplace; it is reached by standing readers only",
                    )
                )
            elif role in ds.readers:
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
            if r.days > ds.marketplace.max_grant_days:
                f.append(
                    Finding(
                        "DURATION_EXCEEDS_MAX",
                        GATE,
                        rid,
                        f"{r.days} days > {ds.marketplace.max_grant_days} allowed by {ds.dataset}'s contract",
                    )
                )
            if ts(dec.at) - ts(r.at) > timedelta(days=ds.marketplace.max_grant_days):
                f.append(
                    Finding(
                        "DECISION_STALE",
                        GATE,
                        rid,
                        f"decided {(ts(dec.at) - ts(r.at)).days} days after the request; re-request",
                    )
                )
        if ts(dec.at) < ts(r.at):
            f.append(Finding("DECISION_BEFORE_REQUEST", GATE, rid, "decided before it was requested"))
        if dec.decision != "approve":
            out.append(
                Outcome(
                    req,
                    "refused",
                    [Finding("DENIED_BY_APPROVER", GATE, rid, f"denied by {dec.by}", severity="info")],
                    dec.model_dump(),
                )
            )
            continue
        if f:
            out.append(Outcome(req, "refused", f, dec.model_dump()))
            continue
        out.append(Outcome(req, "granted", [], dec.model_dump(), iso(ts(dec.at) + timedelta(days=r.days))))
    return out


def active_grants(outcomes: list[Outcome], as_of: str) -> list[Outcome]:
    """Grants still live at `as_of` (data, never a clock)."""
    t = ts(as_of)
    return [o for o in outcomes if o.status == "granted" and ts(o.expires_at) > t]


def condition_expression(expires_at: str) -> str:
    return f'request.time < timestamp("{expires_at}")'


# ── judging an IAM snapshot ───────────────────────────────────────────────────────────────────────


def gate(snapshot: dict, outcomes: list[Outcome], contracts: list[Contract], roles: Roles) -> list[Finding]:
    """Judge every BigQuery role binding on every dataset. Now = snapshot['captured_at'] — the moment the
    evidence was taken. Anything not explained by a contract or an approved, live grant is blocking."""
    now = ts(snapshot["captured_at"])
    by_ds = {c.dataset: c for c in contracts}
    granted = {(norm(o.member), o.request["dataset"], o.expires_at) for o in outcomes if o.status == "granted"}
    out: list[Finding] = []
    for b in snapshot["bindings"]:
        ds, member, role = b["dataset"], b["member"], b["role"]
        target = f"{ds}:{member}"
        c = by_ds.get(ds)
        if c is None:
            out.append(Finding("GRANT_ON_UNCONTRACTED", GATE, target, f"{role} on {ds}, which no contract declares"))
            continue
        standing_viewers = {s for r in c.readers for s in seats_for(roles, r, c)}
        cond = (b.get("condition") or {}).get("expression")
        writer = snapshot.get("sink_writer_identity")
        if role == EDITOR and not cond and (member == c.custodian or (c.log_sink and writer and member == writer)):
            continue  # B12 custodian; B15 this project's sink writer identity, as captured with the snapshot
        if role != VIEWER:
            out.append(
                Finding("GRANT_ROLE_UNEXPECTED", GATE, target, f"{role} is granted by no contract and no request")
            )
            continue
        if not cond:
            if member not in standing_viewers:
                out.append(
                    Finding(
                        "GRANT_WITHOUT_EXPIRY",
                        GATE,
                        target,
                        "dataViewer with no expiry condition for a member that is not a standing reader — every grant expires",
                    )
                )
            continue
        m = _CONDITION.match(cond.strip())
        if not m:
            out.append(
                Finding(
                    "GRANT_CONDITION_UNRECOGNISED",
                    GATE,
                    target,
                    f'condition {cond!r} is not exactly `request.time < timestamp("…Z")`; it cannot be shown to expire',
                )
            )
            continue
        try:
            expiry = ts(m.group(1))
        except ValueError:
            out.append(
                Finding(
                    "GRANT_CONDITION_UNRECOGNISED", GATE, target, f"condition date {m.group(1)!r} is not a real date"
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
        if (norm(member), ds, iso(expiry)) not in granted:
            out.append(
                Finding(
                    "GRANT_UNAPPROVED", GATE, target, f"bound until {iso(expiry)} with no approved request behind it"
                )
            )
    return out
