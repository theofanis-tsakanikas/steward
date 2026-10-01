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
    if _strip(old) != _strip(new) and not nv > ov:
        out.append(Finding("VERSION_NOT_BUMPED", GATE, name, f"content changed but version stayed {ov} → {nv}"))
    if nv < ov:
        out.append(Finding("VERSION_DECREASED", GATE, name, f"version went {ov} → {nv}"))
    oc, nc = old.get("changelog", []), new.get("changelog", [])
    if nc[: len(oc)] != oc:
        out.append(Finding("CHANGELOG_REWRITTEN", GATE, name, "earlier changelog entries were edited or removed"))
    return out
