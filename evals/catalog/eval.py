"""Claim 4 — the catalog is generated, idempotent and reconciled.

  A. clean estate, fresh mock: the sync is accepted; a second sync sends 0 commands; the reconciliation is
     empty (a dataset whose tables a log sink creates on first write is listed on its own); every asset of a
     type carries the same attribute set (the Import API cannot delete an attribute by omitting it)
  B. the mock refuses (the trap: a mock that accepts anything proves nothing): twenty invalid jobs, each
     built by breaking one command of the valid catalog, each refused with its exact code, each leaving the
     catalog byte-for-byte as it was (one transaction, rolled back)
  C. drift in the catalog: a column deleted, a ghost table added, an owner changed, a description edited, a
     status changed, a relation removed, a foreign attribute added and a retired dashboard left behind — the
     reconciliation lists exactly those; the next sync repairs what it owns, never deletes the ghost or the
     retired dashboard (doctrine 4: listed until a human retires them) and never resends what it cannot remove
  D. a contract change: a new version of one contract changes only that dataset's assets, and the catalog keeps
     what the description said before, with when (doctrine 4)
  E. a sync that fails leaves the catalog STALE with the age of the last good sync, fails loudly, and the
     second failure past 24 hours says so (doctrine 1: fail open on documentation, with a deadline)
  F. a contract naming a group the directory does not know stops the build (doctrine 3: no default owner)
  G. what the sync must leave alone or say: a steward's acceptance of a glossary term survives the next sync; an
     owner that outlives its contract is listed and not resent forever; a column the scan did not cover says
     "not scanned", never "nothing found"; the log-sink exception expires (doctrine 6)

Honest limits: the mock enforces the Import API as DOCUMENTED (docs/COLLIBRA.md, read 2026-10-01), not as a
live instance behaves; whether a real Collibra accepts these commands is T024. Everything here is mode=MOCK.
"""

from __future__ import annotations

import copy
import json
import sys

from steward import catalog_sync as S
from steward import io, pipeline
from steward.adapters.collibra.mock import MockCollibra, Rejection
from steward.core import catalog as C

T0, T1, T2 = "2026-10-01T09:00:00Z", "2026-10-01T09:05:00Z", "2026-10-03T12:00:00Z"
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(f"MISMATCH {name}: {detail}")


def fresh() -> MockCollibra:
    return MockCollibra(S.model())


def snapshot(cl: MockCollibra) -> str:
    return json.dumps(cl.state, sort_keys=True)


# ── A ──────────────────────────────────────────────────────────────────────────────────────────────
def scenario_a(e) -> dict:
    print("A. clean estate")
    cl = fresh()
    r1 = S.sync(cl, e, T0)
    r2 = S.sync(cl, e, T1)
    rec = S.reconcile(cl, e, T1)
    check("first sync accepted", r1["status"] == "ok", r1.get("error", ""))
    check(
        "first sync created every command",
        r1["created"] == r1["desired_commands"],
        f"{r1['created']} of {r1['desired_commands']}",
    )
    check("second sync sends 0 commands", r2["changes_sent"] == 0 and r2["created"] == r2["updated"] == 0, str(r2))
    clean = not (
        rec["in_gcp_not_in_catalog"]
        or rec["in_catalog_not_in_gcp"]
        or rec["in_both_differing"]
        or rec["generated_not_in_catalog"]
    )
    check("reconciliation empty after a sync", clean, json.dumps(rec)[:300])
    check(
        "log-sink dataset listed on its own, not as drift",
        rec["pending_first_write"] == [f"{S.PROJECT}.audit"],
        str(rec["pending_first_write"]),
    )
    check("every output carries the mode", r1["mode"] == r2["mode"] == rec["mode"] == "MOCK", "")
    by_type: dict[str, set] = {}
    count: dict[str, int] = {}
    for k, v in cl.current().items():
        if k[0] == "Asset":
            t = v["type"]["name"]
            by_type.setdefault(t, set()).add(frozenset(set(v["attributes"]) - C.VOLATILE))
            count[t] = count.get(t, 0) + 1
    uneven = {t: len(s) for t, s in by_type.items() if len(s) != 1}
    check("one attribute set per asset type", not uneven, str(uneven))
    print(f"     {r1['created']} commands: " + ", ".join(f"{t} ×{n}" for t, n in sorted(count.items())))
    return {"first": r1, "second": r2, "reconciliation": rec, "assets_by_type": count}


# ── B ──────────────────────────────────────────────────────────────────────────────────────────────
def _first(cmds, typ):
    return next(i for i, c in enumerate(cmds) if c["resourceType"] == "Asset" and c["type"]["name"] == typ)


def _owned_domain(c):
    return next(i for i, x in enumerate(c) if x["resourceType"] == "Domain" and "responsibilities" in x)


def _bad_cases(good: list[dict]) -> list[tuple[str, str, list[dict]]]:
    def variant(fn) -> list[dict]:
        c = copy.deepcopy(good)
        fn(c)
        return c

    col, tbl = _first(good, "Column"), _first(good, "Table")
    some_group = next(iter(S.model()["user_groups"].values()))

    def unknown_type(c):
        c[col]["type"]["name"] = "Data Element"

    def drop_desc(c):
        del c[tbl]["attributes"]["Description"]

    def dangling(c):
        c[col]["relations"][C.IS_PART_OF_TABLE][0]["name"] = f"{S.PROJECT}.crm.no_such_table"

    def shorthand(c):  # the form the first draft used: not the documented fully qualified name
        c[col]["relations"] = {"is part of:TARGET": c[col]["relations"][C.IS_PART_OF_TABLE]}

    def mismatch(c):  # a Table anchoring a Column->Table relation
        c[tbl]["relations"][C.IS_PART_OF_TABLE] = c[tbl]["relations"][C.IS_PART_OF_SCHEMA]

    def by_name(c):
        c[_owned_domain(c)]["responsibilities"] = {"Owner": [{"group": {"name": "crm-owners"}}]}

    def unknown_group(c):
        c[_owned_domain(c)]["responsibilities"]["Owner"] = [
            {"userGroup": {"id": "00000000-0000-0000-0000-000000000000"}}
        ]

    def on_asset(c):
        c[tbl]["responsibilities"] = {"Owner": [{"userGroup": {"id": some_group}}]}

    def wrong_domain(c):
        c[col]["identifier"]["domain"] = {"name": C.GLOSSARY, "community": c[col]["identifier"]["domain"]["community"]}

    def unknown_attr(c):
        c[tbl]["attributes"]["Cost Centre"] = [{"value": "x"}]

    def unknown_status(c):
        c[tbl]["status"] = {"name": "Approved"}

    def asset_before_domain(c):
        i = next(i for i, x in enumerate(c) if x["resourceType"] == "Domain")
        c.insert(i, c.pop(tbl))

    def unknown_role(c):
        r = c[_owned_domain(c)]["responsibilities"]
        r["Business Steward"] = r.pop("Steward")

    rep_i = _first(good, "Report")

    def wrong_anchor(
        c,
    ):  # the Report anchors Table->Schema; the target IS a Schema, so only the anchor check can refuse
        schema = next(x for x in c if x["resourceType"] == "Asset" and x["type"]["name"] == "Schema")
        c[rep_i]["relations"] = {C.IS_PART_OF_SCHEMA: [schema["identifier"]]}

    def extra_ident_key(c):
        c[tbl]["identifier"]["externalId"] = "x"

    def type_by_id(c):
        c[tbl]["type"] = {"id": "00000000-0000-0000-0000-000000031007"}

    def two_values(c):
        c[tbl]["attributes"]["Description"] = [{"value": "a"}, {"value": "b"}]

    def empty_value(c):
        c[tbl]["attributes"]["Description"] = [{"value": ""}]

    def duplicate_target(c):
        t = c[rep_i]["relations"][C.USES_COLUMN]
        t.append(copy.deepcopy(t[0]))

    def target_no_domain(c):
        c[rep_i]["relations"][C.USES_COLUMN][0] = {"name": "halverra-data.crm.customers.msisdn"}

    return [
        ("an asset type the model does not have", "UNKNOWN_ASSET_TYPE", variant(unknown_type)),
        ("a required attribute missing", "MISSING_REQUIRED_ATTRIBUTE", variant(drop_desc)),
        ("a relation to an asset that does not exist", "DANGLING_RELATION", variant(dangling)),
        ("a relation key in the shorthand, not the documented form", "UNKNOWN_RELATION", variant(shorthand)),
        ("a relation anchored on the wrong asset type", "RELATION_TYPE_MISMATCH", variant(mismatch)),
        ("a responsibility naming a group instead of its id", "MALFORMED_RESPONSIBILITY", variant(by_name)),
        ("a user group id the directory does not have", "UNKNOWN_PRINCIPAL", variant(unknown_group)),
        ("responsibilities on an asset (setting off by default)", "RESPONSIBILITIES_NOT_ENABLED", variant(on_asset)),
        ("a column placed in a glossary domain", "WRONG_DOMAIN_TYPE", variant(wrong_domain)),
        ("an attribute type the model does not have", "UNKNOWN_ATTRIBUTE", variant(unknown_attr)),
        ("a status the model does not have", "UNKNOWN_STATUS", variant(unknown_status)),
        ("an asset sent before its domain", "DOMAIN_MISSING", variant(asset_before_domain)),
        ("a role the model does not have", "UNKNOWN_ROLE", variant(unknown_role)),
        ("a report anchoring a table's relation (target type right)", "RELATION_TYPE_MISMATCH", variant(wrong_anchor)),
        ("an extra key in an identifier", "MALFORMED_COMMAND", variant(extra_ident_key)),
        ("a type addressed by id, a form Steward does not emit", "MALFORMED_COMMAND", variant(type_by_id)),
        ("an attribute with two values", "MALFORMED_ATTRIBUTE", variant(two_values)),
        ("an attribute with an empty value", "MALFORMED_ATTRIBUTE", variant(empty_value)),
        ("a relation target listed twice", "MALFORMED_COMMAND", variant(duplicate_target)),
        (
            "a relation target with no domain (a KeyError, not a refusal)",
            "MALFORMED_COMMAND",
            variant(target_no_domain),
        ),
    ]


def scenario_b(e) -> list[dict]:
    print("B. the mock refuses")
    good = S.desired(e)
    try:
        fresh().import_job(good, T0)
        check("the unbroken job is accepted (each case below breaks one command of it)", True)
    except Rejection as r:
        check("the unbroken job is accepted (each case below breaks one command of it)", False, str(r))
    rows = []
    for name, code, cmds in _bad_cases(good):
        cl = fresh()
        before = snapshot(cl)
        try:
            cl.import_job(cmds, T0)
            got = "ACCEPTED"
        except Rejection as r:
            got = r.code
        untouched = snapshot(cl) == before
        check(
            f"{name} → {code}",
            got == code and untouched,
            f"got {got}" + ("" if untouched else ", and the catalog changed"),
        )
        if got != code:
            FAILURES.append(f"NOT_DETECTED {code} {name}")
        rows.append({"case": name, "expected": code, "got": got, "catalog_untouched": untouched})
    return rows


# ── C ──────────────────────────────────────────────────────────────────────────────────────────────
def scenario_c(e) -> dict:
    print("C. drift in the catalog")
    cl = fresh()
    S.sync(cl, e, T0)
    proj, comm = S.PROJECT, S.model()["community"]
    dom = C.physical_domain("crm")
    deleted = f"{proj}.crm.customers.country"
    del cl.state["assets"][json.dumps(["Asset", comm, dom, deleted])]
    ghost = f"{proj}.crm.ghost_table"
    cl.import_job(
        [
            C._asset(
                ghost,
                dom,
                comm,
                "Table",
                "Accepted",
                {"Description": "added by hand", "Contract Version": "1"},
                relations={C.IS_PART_OF_SCHEMA: [C._ident(f"{proj}.crm", dom, comm)]},
                display="ghost_table",
            )
        ],
        T0,
    )
    other_group = S.model()["user_groups"]["group:finance-owners@halverra.example"]
    cl.state["domains"][json.dumps(["Domain", comm, dom])]["responsibilities"]["Owner"] = [
        {"userGroup": {"id": other_group}}
    ]
    edited = f"{proj}.crm.customers"
    cl.state["assets"][json.dumps(["Asset", comm, dom, edited])]["attributes"]["Description"] = [
        {"value": "edited in the catalog UI"}
    ]

    tickets = f"{proj}.crm.support_tickets"
    cl.state["assets"][json.dumps(["Asset", comm, dom, tickets])]["status"] = {"name": "Under Review"}
    rpt = next(k for k, v in cl.current().items() if k[0] == "Asset" and v["type"]["name"] == "Report")
    cl.state["assets"][json.dumps(list(rpt))]["relations"][C.USES_COLUMN] = []
    foreign_col = f"{proj}.crm.customers.email"
    cl.state["assets"][json.dumps(["Asset", comm, dom, foreign_col])]["attributes"]["Comment"] = [{"value": "by hand"}]
    reports = C.REPORTS
    retired = "looker:retired_dashboard"
    cl.import_job(
        [
            C._asset(
                retired,
                reports,
                comm,
                "Report",
                "Accepted",
                {"Description": "a dashboard deleted from LookML", "Lifecycle State": "active"},
                relations={C.USES_COLUMN: [C._ident(f"{proj}.crm.customers.msisdn", dom, comm)]},
            )
        ],
        T0,
    )

    rec = S.reconcile(cl, e, T1)
    differing = sorted((d["resource"].split(" / ")[-1], tuple(d["differs"])) for d in rec["in_both_differing"])
    check(
        "deleted column listed as in GCP, not in catalog",
        rec["in_gcp_not_in_catalog"] == [deleted],
        str(rec["in_gcp_not_in_catalog"]),
    )
    check(
        "ghost table listed as in catalog, not in GCP",
        rec["in_catalog_not_in_gcp"] == [ghost],
        str(rec["in_catalog_not_in_gcp"]),
    )
    want_differing = sorted(
        [
            (dom, ("responsibilities",)),
            (edited, ("attribute:Description",)),
            (tickets, ("status",)),
            (rpt[3], ("relations",)),
            (foreign_col, ("attribute:Comment",)),
        ]
    )
    check(
        "owner, description, status, relation and foreign attribute listed as differing",
        differing == want_differing,
        str(differing),
    )
    check(
        "a dashboard the estate no longer implies is listed, not left advertising its columns",
        rec["in_catalog_not_generated"] == [f"{comm} / {reports} / {retired}"],
        str(rec["in_catalog_not_generated"]),
    )
    for lst, code in (
        ("in_gcp_not_in_catalog", "RECONCILE_MISSING_IN_CATALOG"),
        ("in_catalog_not_in_gcp", "RECONCILE_MISSING_IN_GCP"),
        ("in_both_differing", "RECONCILE_DIFFERS"),
        ("in_catalog_not_generated", "RECONCILE_STALE_GENERATED"),
    ):
        if not rec[lst]:
            FAILURES.append(f"NOT_DETECTED {code} {lst}")

    repair = S.sync(cl, e, T1)
    again = S.sync(cl, e, T2)
    rec2 = S.reconcile(cl, e, T2)
    check(
        "the next sync repairs the five it owns (column, domain, description, status, relation)",
        repair["changes_sent"] == 5,
        str(repair["changes_sent"]),
    )
    check(
        "then sends nothing — including for what it cannot remove",
        again["changes_sent"] == 0,
        str(again["changes_sent"]),
    )
    check(
        "the ghost, the retired dashboard and the foreign attribute stay listed, nothing else does",
        rec2["in_catalog_not_in_gcp"] == [ghost]
        and rec2["in_catalog_not_generated"] == [f"{comm} / {reports} / {retired}"]
        and [(d["resource"].split(" / ")[-1], d["differs"]) for d in rec2["in_both_differing"]]
        == [(foreign_col, ["attribute:Comment"])],
        str(rec2),
    )
    return {"reconciliation_before_repair": rec, "repair_commands": repair["changes_sent"], "after": rec2}


# ── D ──────────────────────────────────────────────────────────────────────────────────────────────
def scenario_d(base) -> dict:
    print("D. a contract change is a new version; the catalog keeps the old words")
    cl = fresh()
    S.sync(cl, base, T0)
    docs = copy.deepcopy(io.contract_docs())
    old = docs["finance"]["tables"]["billing"]["description"]
    nxt = docs["finance"]["version"] + 1
    docs["finance"]["version"] = nxt
    docs["finance"]["changelog"].append({"version": nxt, "date": "2026-10-01", "change": "reworded billing (eval)"})
    docs["finance"]["tables"]["billing"]["description"] = old + " (reworded)"
    new = pipeline.load(contract_docs=docs)
    check(
        "the new version loads (an invalid one would degrade to `restricted`)",
        "finance" not in new.broken,
        str(new.broken),
    )
    changed = C.diff(S.desired(new), cl.current(), T1)
    names = sorted(c["identifier"]["name"] for c in changed)
    # the schema and the tables carry the contract version; columns, other datasets and the domain do not change
    expected = sorted([f"{S.PROJECT}.finance", f"{S.PROJECT}.finance.billing"])
    check("exactly the finance schema and the reworded table change", names == expected, str(names))
    r = S.sync(cl, new, T1)
    check("the sync sends exactly those", r["changes_sent"] == len(changed), f"{r['changes_sent']} vs {len(changed)}")
    res = f"{S.PROJECT}.finance.billing"
    kept = [h for h in cl.state["history"] if h["field"] == "attribute:Description" and h["resource"] == res]
    check(
        "the previous description is kept, with when",
        len(kept) == 1 and kept[0]["was"] == old and kept[0]["replaced_at"] == T1,
        str(kept),
    )
    ver = [h for h in cl.state["history"] if h["field"] == "attribute:Contract Version" and h["resource"] == res]
    check("the previous contract version is kept", len(ver) == 1, str(ver))
    return {"changed": names, "history_entries": len(cl.state["history"])}


# ── E ──────────────────────────────────────────────────────────────────────────────────────────────
class Refusing(MockCollibra):
    """Refuses any real job but still accepts the one-command stale marker (the instance is up, the job is bad)."""

    def import_job(self, commands, at):
        if len(commands) > 1:
            raise Rejection("UNKNOWN_ASSET_TYPE", 3, "simulated refusal")
        return super().import_job(commands, at)


class Down(MockCollibra):
    """The instance is unreachable: nothing, not even the marker, can be written."""

    def import_job(self, commands, at):
        raise ConnectionError("simulated outage")


def scenario_e(e) -> dict:
    print("E. a failing sync is loud and marks the catalog stale")
    cl = fresh()
    S.sync(cl, e, T0)
    broken = Refusing(cl.model, state=copy.deepcopy(cl.state))
    docs = copy.deepcopy(io.contract_docs())  # something to send, so the refusal is reached
    docs["crm"]["version"] += 1
    docs["crm"]["description"] += " (changed)"
    changed = pipeline.load(contract_docs=docs)
    before = json.dumps(broken.state["assets"], sort_keys=True)
    r1 = S.sync(broken, changed, T1)
    r2 = S.sync(broken, changed, T2)
    check(
        "failure reported as failed, not swallowed",
        r1["status"] == "failed" and "UNKNOWN_ASSET_TYPE" in r1["error"],
        str(r1),
    )
    check("stale marker names the last good sync", bool(r1["stale"]) and T0 in r1["stale"], str(r1["stale"]))
    check(
        "past 24 h the marker says so", bool(r2["stale"]) and "past the 24 h deadline" in r2["stale"], str(r2["stale"])
    )
    runs = broken.state["runs"]
    check(
        "the failed runs are in the run log, with the mode",
        [x["status"] for x in runs] == ["ok", "failed", "failed"] and all(x["mode"] == "MOCK" for x in runs),
        str(runs),
    )
    check(
        "the catalog's assets are exactly as they were",
        json.dumps(broken.state["assets"], sort_keys=True) == before,
        "",
    )
    comm = broken.current()[("Community", S.model()["community"])]["description"]
    check(
        "the catalog itself shows the stale marker", r1.get("marker_written") and "STALE" in comm and T0 in comm, comm
    )
    recovered = MockCollibra(broken.model, state=broken.state)
    healed = S.sync(recovered, changed, T2)
    healed_desc = recovered.current()[("Community", S.model()["community"])]["description"]
    check(
        "the next good sync writes the plain text back",
        healed["status"] == "ok" and "STALE" not in healed_desc,
        healed_desc,
    )
    down = Down(cl.model, state=copy.deepcopy(cl.state))
    r3 = S.sync(down, changed, T1)
    check(
        "an unreachable instance: failed, stale, marker not written, run still logged",
        r3["status"] == "failed"
        and r3["stale"]
        and r3["marker_written"] is False
        and down.state["runs"][-1]["status"] == "failed",
        str(r3),
    )
    # a build failure (a group with no id) is a failed run with a record, not a traceback with none
    nogroup = fresh()
    S.sync(nogroup, e, T0)
    docs2 = copy.deepcopy(io.contract_docs())
    docs2["crm"]["owner"] = "group:nobody@halverra.example"
    docs2["crm"]["version"] += 1
    docs2["crm"]["changelog"].append({"version": docs2["crm"]["version"], "date": "2026-10-01", "change": "eval"})
    r4 = S.sync(nogroup, pipeline.load(contract_docs=docs2), T1)
    check(
        "an owner with no catalog id: a failed, logged run that names the group",
        r4["status"] == "failed"
        and r4["error"].startswith("OWNER_GROUP_UNKNOWN")
        and "nobody" in r4["error"]
        and nogroup.state["runs"][-1]["status"] == "failed",
        str(r4),
    )
    return {"first_failure": r1, "second_failure": r2, "unreachable": r3, "no_owner_id": r4}


# ── F ──────────────────────────────────────────────────────────────────────────────────────────────
def scenario_f(e) -> None:
    print("F. no default owner")
    groups = {k: v for k, v in S.model()["user_groups"].items() if k != "group:crm-owners@halverra.example"}
    try:
        S.desired(e, "MOCK", groups)
        got = "BUILT"
    except ValueError as exc:
        got = "ValueError" if "crm-owners" in str(exc) else f"wrong error: {exc}"
    check("a contract group with no user group id stops the build", got == "ValueError", got)
    if got == "BUILT":
        FAILURES.append("NOT_DETECTED OWNER_GROUP_UNKNOWN crm-owners")


def scenario_g(e) -> dict:
    print("G. what the sync leaves alone, or says")
    comm = S.model()["community"]
    cl = fresh()
    S.sync(cl, e, T0)
    term = next(k for k, v in cl.current().items() if k[0] == "Asset" and v["type"]["name"] == "Business Term")
    check(
        "a drafted glossary term is not born Accepted",
        cl.current()[term]["status"]["name"] in ("Candidate", "Under Review"),
        "",
    )
    cl.state["assets"][json.dumps(list(term))]["status"] = {"name": "Accepted"}  # a steward's decision, in the catalog
    after = S.sync(cl, e, T1)
    rec = S.reconcile(cl, e, T1)
    check(
        "a steward's acceptance survives the next sync and is not drift",
        after["changes_sent"] == 0
        and cl.current()[term]["status"]["name"] == "Accepted"
        and not rec["in_both_differing"],
        f"sent {after['changes_sent']}, differing {rec['in_both_differing']}",
    )

    docs = copy.deepcopy(io.contract_docs())
    docs.pop("crm")
    no_crm = pipeline.load(contract_docs=docs)
    S.sync(cl, no_crm, T1)
    again = S.sync(cl, no_crm, T2)
    left = [d for d in S.reconcile(cl, no_crm, T2)["in_both_differing"] if "crm" in d["resource"]]
    check(
        "a contract removed: its owner stays listed (the Import API cannot remove it) and is not resent forever",
        again["changes_sent"] == 0 and [d["differs"] for d in left] == [["responsibilities"]],
        f"sent {again['changes_sent']}, left {left}",
    )

    h = copy.deepcopy(io.harvest())
    h["crm.customers"]["fields"].append({"name": "ref_3", "type": "STRING", "mode": "NULLABLE"})
    e_h = pipeline.load(harvest=h)
    cl2 = fresh()
    S.sync(cl2, e_h, T0)
    col = cl2.current()[("Asset", comm, C.physical_domain("crm"), f"{S.PROJECT}.crm.customers.ref_3")]
    said = col["attributes"]["Proposed Description"][0]["value"]
    check("a column the scan never saw says so, never 'nothing found'", said.startswith("Not scanned"), said)
    check(
        "…and is held at restricted until a contract declares it",
        col["attributes"]["Personal Data Classification"][0]["value"].startswith("restricted"),
        "",
    )

    live = S.reconcile(cl2, e_h, "2026-10-30T00:00:00Z")
    lapsed = S.reconcile(cl2, e_h, "2026-11-02T00:00:00Z")
    check(
        "the log-sink exception holds before its date", live["pending_first_write"] == [f"{S.PROJECT}.audit"], str(live)
    )
    check(
        "…and after it the dataset is drift again (doctrine 6)",
        not lapsed["pending_first_write"] and lapsed["in_catalog_not_in_gcp"] == [f"{S.PROJECT}.audit"],
        str(lapsed),
    )
    return {"acceptance_kept": True, "not_scanned": said, "pending_expiry": lapsed["in_catalog_not_in_gcp"]}


def evaluate() -> dict:
    FAILURES.clear()
    e = pipeline.load()
    out: dict = {"mode": "MOCK", "scenarios": {}}
    out["scenarios"]["A_clean"] = scenario_a(e)
    out["scenarios"]["B_refusals"] = scenario_b(e)
    out["scenarios"]["C_drift"] = scenario_c(e)
    out["scenarios"]["D_contract_change"] = scenario_d(e)
    out["scenarios"]["E_failure"] = scenario_e(e)
    scenario_f(e)
    out["scenarios"]["G_leave_alone_or_say"] = scenario_g(e)
    out["failures"] = list(FAILURES)
    return out


def main() -> int:
    r = evaluate()
    for f in r["failures"]:
        print(f)
    ok = not r["failures"]
    print(
        "ok claim 4 (mode MOCK): generated, validated by a mock that refuses, idempotent, reconciled; hand edits found and repaired"
        if ok
        else "FAIL claim 4"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
