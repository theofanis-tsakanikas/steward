"""Doctrine 4: a correction never erases what was previously stated.

Compares a contract with its previously committed version (both as plain dicts). A changed contract
must carry a higher `version`, and the previous changelog must survive unchanged as a prefix.
"""

from __future__ import annotations

from .findings import Finding

GATE = "contract-versions"


def _strip(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in ("version", "changelog")}


def compare(name: str, old: dict | None, new: dict | None) -> list[Finding]:
    if old is None or new is None:
        if old is not None and new is None:
            return [
                Finding(
                    "CONTRACT_DELETED",
                    GATE,
                    name,
                    "a contract was removed; retire it with a final version instead (its history must survive)",
                )
            ]
        return []
    if old == new:
        return []
    out = []
    ov, nv = old.get("version", 0), new.get("version", 0)
    if not isinstance(ov, int) or not isinstance(nv, int):
        return [Finding("VERSION_INVALID", GATE, name, f"version must be an integer, got {ov!r} → {nv!r}")]
    if _strip(old) != _strip(new) and not nv > ov:
        out.append(Finding("VERSION_NOT_BUMPED", GATE, name, f"content changed but version stayed {ov} → {nv}"))
    if nv < ov:
        out.append(Finding("VERSION_DECREASED", GATE, name, f"version went {ov} → {nv}"))
    oc, nc = old.get("changelog", []), new.get("changelog", [])
    if nc[: len(oc)] != oc:
        out.append(Finding("CHANGELOG_REWRITTEN", GATE, name, "earlier changelog entries were edited or removed"))
    return out


_ROLES_META = ("version", "changes")


def compare_roles(old: dict | None, new: dict) -> list[Finding]:
    """_roles.yaml is a governance file: who is in which group, who approves, what each role may see in
    clear. Any change to it since the base commit is a new version whose `changes` entry names a requester
    and an approver; the approver must have been, **in the base commit's directory**, a member of the base
    commit's approver group, and must not be the requester. A ceiling kind added must be listed in that
    entry's `ceilings_added`. Earlier entries are append-only. No base file → fail closed.

    The base is read as raw data, never through today's model: the file's shape may have evolved since
    (the first versioned _roles.yaml is compared with an unversioned one)."""
    from .contract import Roles

    where = "_roles.yaml"
    if not old:
        return [
            Finding(
                "ROLES_BASE_MISSING",
                GATE,
                where,
                "no _roles.yaml in the base commit: a roles change cannot be verified against anything",
            )
        ]
    out: list[Finding] = []
    roles = Roles.model_validate(new)
    base_version = old.get("version", 0)
    base_directory = old.get("directory") or {}
    base_group = old.get("waiver_approvers", "")
    old_changes = [dict(c, date=str(c.get("date"))) for c in (old.get("changes") or [])]
    kept = [c.model_dump(mode="json") for c in roles.changes][: len(old_changes)]
    if kept != old_changes:
        out.append(
            Finding(
                "ROLES_HISTORY_REWRITTEN", GATE, f"{where}:changes", "earlier versions' entries were edited or removed"
            )
        )
    strip = ("version", "changes")
    content_changed = {k: v for k, v in old.items() if k not in strip} != {
        k: v for k, v in new.items() if k not in strip
    }
    added = [ch for ch in roles.changes if ch.version > base_version]
    if content_changed and not added:
        out.append(
            Finding(
                "ROLES_CHANGE_UNAPPROVED",
                GATE,
                where,
                f"content changed but version stayed {base_version}: a roles change is a new version with an approval",
            )
        )
    approvers = {m.casefold() for m in base_directory.get(base_group, [])}
    base_people = {m.casefold() for ms in base_directory.values() for m in ms}
    for ch in added:
        tgt = f"{where}:changes.v{ch.version}"
        if not ch.approved_by.startswith("user:") or ch.approved_by.casefold() not in approvers:
            out.append(
                Finding(
                    "ROLES_CHANGE_UNAPPROVED",
                    GATE,
                    tgt,
                    f"approved by {ch.approved_by}, who was not in {base_group} in the base commit",
                )
            )
        if ch.approved_by.casefold() == ch.requested_by.casefold():
            out.append(
                Finding("ROLES_CHANGE_UNAPPROVED", GATE, tgt, "requester approved their own change (doctrine 5)")
            )
        if ch.requested_by.casefold() not in base_people:
            out.append(
                Finding(
                    "ROLES_CHANGE_UNAPPROVED",
                    GATE,
                    tgt,
                    f"requested by {ch.requested_by}, who is not in the base commit's directory",
                )
            )
    listed = {(c.role, k) for ch in added for c in ch.ceilings_added for k in c.kinds}
    old_ceil = {r: set((c or {}).get("clear_kinds", [])) for r, c in (old.get("ceilings") or {}).items()}
    for role, ceil in roles.ceilings.items():
        for kind in sorted(set(ceil.clear_kinds) - old_ceil.get(role, set())):
            if (role, kind) not in listed:
                out.append(
                    Finding(
                        "CEILING_RAISED",
                        GATE,
                        f"{where}:ceilings.{role}",
                        f"{kind} added to {role}'s clear_kinds without being listed in this change's ceilings_added",
                    )
                )
    return out
