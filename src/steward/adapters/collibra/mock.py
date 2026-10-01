"""A Collibra that refuses what Collibra would refuse — and what Steward's operating model forbids.

A mock that accepts anything proves nothing (claim 4's trap). This one validates every Import API command
against the documented shape (docs/COLLIBRA.md, guide read 2026-10-01) and against catalog/collibra.yaml, and
rejects the WHOLE job on the first invalid command and commits nothing (`continueOnError=false`: one
transaction, rolled back on error):

  MALFORMED_COMMAND           missing resourceType / identifier, identifier of the wrong shape
  UNKNOWN_RESOURCE_TYPE       not Community / Domain / Asset
  UNKNOWN_FIELD               a top-level field the command type does not have
  DOMAIN_MISSING              a domain in a community, or an asset in a domain, that does not exist
  UNKNOWN_DOMAIN_TYPE / WRONG_DOMAIN_TYPE
  UNKNOWN_ASSET_TYPE          an asset type the operating model does not have
  UNKNOWN_STATUS / UNKNOWN_ATTRIBUTE / MALFORMED_ATTRIBUTE / MISSING_REQUIRED_ATTRIBUTE
  UNKNOWN_RELATION            a relation key that is not `<Source>:<role>:<role>:<Target>:<TARGET|SOURCE>` of
                              a relation type the model has (ids and PUBLIC_ID forms are not used by Steward)
  RELATION_TYPE_MISMATCH      the anchor or the related asset is not of the type the relation joins
  DANGLING_RELATION           a relation to an asset that exists neither in the catalog nor earlier in the job
  MALFORMED_RESPONSIBILITY    anything but {role: [{"user"|"userGroup": {"id": ...}}]}
  UNKNOWN_ROLE / UNKNOWN_PRINCIPAL   a role, or a user group id, the directory does not have
  RESPONSIBILITIES_NOT_ENABLED       responsibilities on an asset while the instance setting is off (the default)

State is a JSON file. Doctrine 4: whatever a field said before it was replaced is kept, with when. Every sync
(also the ones that sent nothing) is recorded under `runs` with its mode.

Semantics taken from the guide: commands are `MERGE` upserts keyed by identifier; with the default
`attributesAction=REPLACE` the attributes a command lists are replaced and the others are left alone;
with the default `relationsAction=REPLACE` the list for each relation type given is the complete final set for
the anchor asset (an empty list deletes). Not confirmed against a live instance: that is T024.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from steward.core.catalog import key

MODE = "MOCK"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ALLOWED = {
    "Community": {"resourceType", "identifier", "name", "description", "parent", "responsibilities"},
    "Domain": {"resourceType", "identifier", "name", "description", "type", "community", "responsibilities"},
    "Asset": {
        "resourceType", "identifier", "name", "displayName", "type", "status", "domain", "attributes",
        "relations", "tags", "responsibilities",
    },
}  # fmt: skip


@dataclass
class Rejection(Exception):
    code: str
    command: int
    message: str

    def __str__(self) -> str:
        return f"{self.code} (command {self.command}): {self.message}"


@dataclass
class MockCollibra:
    model: dict
    state: dict = field(
        default_factory=lambda: {"communities": {}, "domains": {}, "assets": {}, "history": [], "runs": []}
    )
    path: Path | None = None
    mode: str = MODE

    @classmethod
    def open(cls, model_path: Path, state_path: Path | None = None) -> MockCollibra:
        model = yaml.safe_load(model_path.read_text())
        m = cls(model, path=state_path)
        if state_path and state_path.exists():
            m.state = json.loads(state_path.read_text())
            m.state.setdefault("runs", [])
        return m

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.state, indent=1, sort_keys=True) + "\n")

    # ── read side, in the commands' own terms ─────────────────────────────────────────────────────
    def current(self) -> dict[tuple, dict]:
        out: dict[tuple, dict] = {}
        for k, c in self.state["communities"].items():
            out[("Community", k)] = c
        for bucket in ("domains", "assets"):
            for k, d in self.state[bucket].items():
                out[tuple(json.loads(k))] = d
        return out

    def record_run(self, report: dict) -> None:
        self.state["runs"].append({k: v for k, v in report.items() if k != "stale"} | {"mode": self.mode})

    def last_good_sync(self) -> str | None:
        good = [r["run_at"] for r in self.state["runs"] if r.get("status") == "ok"]
        return max(good) if good else None

    # ── write side: validate everything, then apply atomically ────────────────────────────────────
    def import_job(self, commands: list[dict], at: str) -> dict:
        staged = copy.deepcopy(self.state)
        created = updated = 0
        for i, cmd in enumerate(commands):
            outcome = self._apply(staged, i, cmd, at)
            created += outcome == "created"
            updated += outcome == "updated"
        self.state = staged
        return {"mode": self.mode, "commands": len(commands), "created": created, "updated": updated}

    def _apply(self, st: dict, i: int, cmd: dict, at: str) -> str:
        rt = cmd.get("resourceType")
        if rt not in ALLOWED:
            raise Rejection("UNKNOWN_RESOURCE_TYPE", i, f"resourceType {rt!r}")
        for f in cmd:
            if f not in ALLOWED[rt]:
                raise Rejection("UNKNOWN_FIELD", i, f"a {rt} command has no field {f!r}")
        ident = cmd.get("identifier")
        if not isinstance(ident, dict) or not isinstance(ident.get("name"), str) or not ident["name"]:
            raise Rejection("MALFORMED_COMMAND", i, "identifier.name is required")
        self._responsibilities(i, rt, cmd)

        if rt == "Community":
            k = ident["name"]
            return self._store(st["communities"], k, cmd, st, at, merge=False)

        if rt == "Domain":
            comm = (ident.get("community") or {}).get("name")
            if comm not in st["communities"]:
                raise Rejection("DOMAIN_MISSING", i, f"community {comm!r} does not exist")
            dtype = (cmd.get("type") or {}).get("name")
            if dtype not in self.model["domain_types"]:
                raise Rejection("UNKNOWN_DOMAIN_TYPE", i, f"{dtype!r} is not a domain type of this operating model")
            return self._store(st["domains"], json.dumps(list(key(cmd))), cmd, st, at, merge=False)

        # Asset
        dom = ident.get("domain") or {}
        dk = json.dumps(["Domain", (dom.get("community") or {}).get("name"), dom.get("name")])
        if dk not in st["domains"]:
            raise Rejection("DOMAIN_MISSING", i, f"domain {dom.get('name')!r} does not exist")
        typ = (cmd.get("type") or {}).get("name")
        spec = self.model["asset_types"].get(typ)
        if spec is None:
            raise Rejection("UNKNOWN_ASSET_TYPE", i, f"{typ!r} is not an asset type of this operating model")
        dtype = st["domains"][dk]["type"]["name"]
        if dtype != spec["domain_type"]:
            raise Rejection(
                "WRONG_DOMAIN_TYPE", i, f"a {typ} belongs in a {spec['domain_type']} domain, not a {dtype} domain"
            )
        status = (cmd.get("status") or {}).get("name")
        if status not in self.model["statuses"]:
            raise Rejection("UNKNOWN_STATUS", i, f"{status!r}")
        for a, vals in (cmd.get("attributes") or {}).items():
            if a not in self.model["attribute_types"]:
                raise Rejection("UNKNOWN_ATTRIBUTE", i, f"{a!r} is not an attribute type of this operating model")
            ok = (
                isinstance(vals, list)
                and vals
                and all(isinstance(v, dict) and isinstance(v.get("value"), str) for v in vals)
            )
            if not ok:
                raise Rejection("MALFORMED_ATTRIBUTE", i, f"{a!r} must be a non-empty list of {{'value': <string>}}")
        k = json.dumps(list(key(cmd)))
        prev = st["assets"].get(k)
        have = {**(prev["attributes"] if prev else {}), **(cmd.get("attributes") or {})}
        missing = [r for r in spec["required_attributes"] if r not in have]
        if missing:
            raise Rejection("MISSING_REQUIRED_ATTRIBUTE", i, f"{typ} {ident['name']!r} lacks {missing}")
        for rel_key, targets in (cmd.get("relations") or {}).items():
            self._relation(st, i, ident["name"], typ, rel_key, targets)
        return self._store(st["assets"], k, cmd, st, at, merge=True)

    def _responsibilities(self, i: int, rt: str, cmd: dict) -> None:
        resp = cmd.get("responsibilities")
        if resp is None:
            return
        if rt == "Asset" and not self.model.get("asset_responsibilities", False):
            raise Rejection(
                "RESPONSIBILITIES_NOT_ENABLED",
                i,
                "Asset responsibilities support is off (the default): declare them on the domain",
            )
        directory = set(self.model["user_groups"].values())
        if not isinstance(resp, dict):
            raise Rejection("MALFORMED_RESPONSIBILITY", i, "responsibilities must be an object role -> list")
        for role, holders in resp.items():
            if role not in self.model["responsibility_roles"]:
                raise Rejection("UNKNOWN_ROLE", i, f"{role!r}")
            if not isinstance(holders, list) or not holders:
                raise Rejection("MALFORMED_RESPONSIBILITY", i, f"{role!r}: a non-empty list of users or user groups")
            for h in holders:
                kind = next(iter(h)) if isinstance(h, dict) and len(h) == 1 else None
                ref = h[kind] if kind in ("user", "userGroup") else None
                if not (
                    isinstance(ref, dict)
                    and set(ref) == {"id"}
                    and isinstance(ref["id"], str)
                    and UUID.match(ref["id"])
                ):
                    raise Rejection(
                        "MALFORMED_RESPONSIBILITY",
                        i,
                        f"{role!r}: {h!r} — the Import API names a user or userGroup by id",
                    )
                if kind == "userGroup" and ref["id"] not in directory:
                    raise Rejection("UNKNOWN_PRINCIPAL", i, f"user group {ref['id']} is not in the directory")
                if kind == "user":
                    raise Rejection("UNKNOWN_PRINCIPAL", i, "Steward assigns groups, never individuals")

    def _relation(self, st: dict, i: int, name: str, typ: str, rel_key: str, targets: list) -> None:
        parts = rel_key.split(":")
        if len(parts) != 5 or parts[4] not in ("TARGET", "SOURCE"):
            raise Rejection(
                "UNKNOWN_RELATION",
                i,
                f"{rel_key!r}: expected '<Source>:<source role>:<target role>:<Target>:<TARGET|SOURCE>'",
            )
        src, srole, trole, tgt, direction = parts
        if not any(
            (r["source"], r["source_role"], r["target_role"], r["target"]) == (src, srole, trole, tgt)
            for r in self.model["relation_types"]
        ):
            raise Rejection(
                "UNKNOWN_RELATION", i, f"{':'.join(parts[:4])!r} is not a relation type of this operating model"
            )
        anchor_type, other_type = (src, tgt) if direction == "TARGET" else (tgt, src)
        if typ != anchor_type:
            raise Rejection(
                "RELATION_TYPE_MISMATCH", i, f"a {typ} cannot be the anchor of {rel_key!r} (expects a {anchor_type})"
            )
        if not isinstance(targets, list):
            raise Rejection("UNKNOWN_RELATION", i, f"{rel_key!r}: a list of asset identifiers (an empty list deletes)")
        for t in targets:
            tk = json.dumps(["Asset", t["domain"]["community"]["name"], t["domain"]["name"], t["name"]])
            found = st["assets"].get(tk)
            if found is None:
                raise Rejection("DANGLING_RELATION", i, f"{name!r} → {t['name']!r}, which does not exist")
            if found["type"]["name"] != other_type:
                raise Rejection("RELATION_TYPE_MISMATCH", i, f"{rel_key!r} cannot point at a {found['type']['name']}")

    def _store(self, bucket: dict, k: str, cmd: dict, st: dict, at: str, merge: bool) -> str:
        prev = bucket.get(k)
        new = copy.deepcopy(cmd)
        if prev and merge:
            new["attributes"] = {**prev.get("attributes", {}), **cmd.get("attributes", {})}
            if prev.get("relations") or cmd.get("relations"):
                new["relations"] = {**prev.get("relations", {}), **cmd.get("relations", {})}
        elif prev:  # communities and domains: fields not sent stay as they were
            new = {**prev, **new}
        if prev == new:
            return "unchanged"
        # doctrine 4: keep what a field said before it was replaced
        if prev:
            name = cmd["identifier"]["name"]
            for fld in sorted(set(prev) | set(new)):
                if fld in ("attributes", "identifier"):
                    continue
                if prev.get(fld) != new.get(fld):
                    st["history"].append({"resource": name, "field": fld, "was": prev.get(fld), "replaced_at": at})
            for a in sorted(set(prev.get("attributes", {})) | set(new.get("attributes", {}))):
                before, after = prev.get("attributes", {}).get(a), new.get("attributes", {}).get(a)
                if a != "Last Changed" and before not in (None, after):
                    st["history"].append(
                        {"resource": name, "field": f"attribute:{a}", "was": before[0]["value"], "replaced_at": at}
                    )
        bucket[k] = new
        return "updated" if prev else "created"
