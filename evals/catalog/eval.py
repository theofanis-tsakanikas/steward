"""Claim 4 — the catalog is generated, idempotent and reconciled.

  A. clean estate, fresh mock: the sync is accepted; a second sync sends 0 commands; the reconciliation is
     empty (a dataset whose tables a log sink creates on first write is listed on its own); every asset of a
     type carries the same attribute set (the Import API cannot delete an attribute by omitting it)
  B. the mock refuses (the trap: a mock that accepts anything proves nothing): thirteen invalid jobs, each
     built by breaking one command of the valid catalog, each refused with its exact code, each leaving the
     catalog byte-for-byte as it was (one transaction, rolled back)
  C. drift in the catalog: a column deleted, a ghost table added, an owner changed and a description edited by
     hand — the reconciliation lists exactly those; the next sync repairs the edits and never deletes the
     ghost (doctrine 4: it is listed until a human retires it)
  D. a contract change: a new version of one contract changes only that dataset's assets, and the catalog keeps
     what the description said before, with when (doctrine 4)
  E. a sync that fails leaves the catalog STALE with the age of the last good sync, fails loudly, and the
     second failure past 24 hours says so (doctrine 1: fail open on documentation, with a deadline)
  F. a contract naming a group the directory does not know stops the build (doctrine 3: no default owner)

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
    check(
        "the changed owner and the edited description listed as differing",
        differing == sorted([(dom, ("responsibilities",)), (edited, ("attribute:Description",))]),
        str(differing),
    )
    for lst, code in (
        ("in_gcp_not_in_catalog", "RECONCILE_MISSING_IN_CATALOG"),
        ("in_catalog_not_in_gcp", "RECONCILE_MISSING_IN_GCP"),
        ("in_both_differing", "RECONCILE_DIFFERS"),
    ):
        if not rec[lst]:
            FAILURES.append(f"NOT_DETECTED {code} {lst}")

    repair = S.sync(cl, e, T1)
    again = S.sync(cl, e, T2)
    rec2 = S.reconcile(cl, e, T2)
    check(
        "the next sync repairs the three it owns (column, domain, description)",
        repair["changes_sent"] == 3,
        str(repair["changes_sent"]),
    )
    check("then sends nothing", again["changes_sent"] == 0, str(again["changes_sent"]))
    check(
        "the ghost is not deleted: it stays listed",
        rec2["in_catalog_not_in_gcp"] == [ghost] and not rec2["in_both_differing"],
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
    def import_job(self, commands, at):
        raise Rejection("UNKNOWN_ASSET_TYPE", 3, "simulated refusal")


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
    check("the catalog is exactly as it was", json.dumps(broken.state["assets"], sort_keys=True) == before, "")
    return {"first_failure": r1, "second_failure": r2}


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
