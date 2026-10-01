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


def compare_roles(old: dict | None, new: dict) -> list[Finding]:
    """Doctrine 5 for ceilings: any kind added to a role's `clear_kinds` since the base commit needs a
    `ceiling_changes` entry approved by a named member of the waiver-approver group who did not ask for
    it. A ceiling raised in the same PR that uses it is otherwise a key to doctrine 7 in effect."""
    from .contract import Roles

    if not old:
        return []
    out: list[Finding] = []
    roles = Roles.model_validate(new)
    old_ceil = {r: set(c.get("clear_kinds", [])) for r, c in (old.get("ceilings") or {}).items()}
    approved = {(ch.role, k): ch for ch in roles.ceiling_changes for k in ch.kinds_added}
    for role, ceil in roles.ceilings.items():
        for kind in sorted(set(ceil.clear_kinds) - old_ceil.get(role, set())):
            ch = approved.get((role, kind))
            where = f"_roles.yaml:ceilings.{role}"
            if ch is None:
                out.append(
                    Finding(
                        "CEILING_RAISED",
                        GATE,
                        where,
                        f"{kind} added to {role}'s clear_kinds with no approved ceiling_changes entry",
                    )
                )
                continue
            if not ch.approved_by.startswith("user:") or not roles.is_member(ch.approved_by, roles.waiver_approvers):
                out.append(
                    Finding(
                        "CEILING_RAISED",
                        GATE,
                        where,
                        f"{kind} for {role}: approved by {ch.approved_by}, not a member of {roles.waiver_approvers}",
                    )
                )
            elif ch.approved_by.casefold() == ch.requested_by.casefold():
                out.append(
                    Finding(
                        "CEILING_RAISED",
                        GATE,
                        where,
                        f"{kind} for {role}: requester approved their own raise (doctrine 5)",
                    )
                )
    old_changes = old.get("ceiling_changes") or []
    if [c for c in (new.get("ceiling_changes") or [])][: len(old_changes)] != old_changes:
        out.append(
            Finding(
                "CHANGELOG_REWRITTEN",
                GATE,
                "_roles.yaml:ceiling_changes",
                "earlier ceiling approvals were edited or removed",
            )
        )
    return out
