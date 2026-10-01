"""The contract model. One contract per BigQuery dataset; the single source of truth.

Doctrine 3 lives here: **a default is never invented.** Owner, steward, custodian, retention and its
legal basis, and every column's classification are required fields with no default. A contract
that omits one does not load — it is a failing build, not a plausible value.
"""

from __future__ import annotations

import re
from datetime import date as date_t
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PRINCIPAL = re.compile(r"^(user|group|serviceAccount):[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$")
RULE_ID = re.compile(r"^Q-[A-Z]{3}-\d{3}$")
# An instrument must be named: an article, a directive, a regulation or a law. Free prose is refused.
LEGAL = re.compile(r"Art\.|Directive|Regulation|\b[Ll]aw\b|obligation")

# The closed vocabulary of personal-data kinds a contract may declare. The first seven are the ones
# the value detector finds (core/classify.py); the rest are declared by stewards from meaning, not
# found by value — they make a column tagged but can never be evidenced by a scan.
DETECTABLE_KINDS = ("msisdn", "imsi", "imei", "email", "iban", "birth_date", "address")
DECLARED_ONLY_KINDS = ("customer_key", "person_name", "postcode", "location")
Kind = Literal[
    "msisdn",
    "imsi",
    "imei",
    "email",
    "iban",
    "birth_date",
    "address",
    "customer_key",
    "person_name",
    "postcode",
    "location",
]

NUMERIC_TYPES = frozenset({"INTEGER", "FLOAT", "NUMERIC"})


class Classification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    SPECIAL = "special"
    SENSITIVE_NETWORK = "sensitive-network"

    @property
    def tagged(self) -> bool:
        """Does a column of this class carry a BigQuery policy tag? Personal, special and
        network-sensitive data always does; public and internal never do."""
        return self in TAGGED


TAGGED = frozenset({Classification.PERSONAL, Classification.SPECIAL, Classification.SENSITIVE_NETWORK})


class Masking(StrEnum):
    """Per-role treatment of a tagged column. Each maps to one BigQuery data-masking rule, except
    `clear` (fine-grained reader) — and a role absent from the map is denied outright."""

    CLEAR = "clear"
    HASH = "hash"
    NULLIFY = "nullify"
    LAST_FOUR = "last_four"
    EMAIL_MASK = "email_mask"
    YEAR_ONLY = "year_only"
    DEFAULT = "default"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _principal(v: str) -> str:
    if not PRINCIPAL.match(v):
        raise ValueError(f"not a principal (user:|group:|serviceAccount:<email>): {v!r}")
    return v


Principal = Annotated[str, Field(min_length=3)]


class QualityRule(Strict):
    id: str
    kind: Literal["completeness", "validity", "uniqueness", "referential"]
    allowed: list[str] | None = None
    regex: str | None = None
    min: float | None = None
    max: float | None = None
    references: str | None = None  # dataset.table.column

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not RULE_ID.match(v):
            raise ValueError(f"rule id must look like Q-ABC-001, got {v!r}")
        return v

    @model_validator(mode="after")
    def _shape(self) -> QualityRule:
        has_validity = any(x is not None for x in (self.allowed, self.regex, self.min, self.max))
        if self.kind == "validity" and not has_validity:
            raise ValueError(f"{self.id}: a validity rule needs allowed, regex, min or max")
        if self.kind != "validity" and has_validity:
            raise ValueError(f"{self.id}: only validity rules take allowed/regex/min/max")
        if (self.kind == "referential") != (self.references is not None):
            raise ValueError(f"{self.id}: `references` is required for, and only for, referential rules")
        if self.regex is not None:
            re.compile(self.regex)
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"{self.id}: min > max")
        return self


class Freshness(Strict):
    id: str = Field(pattern=RULE_ID.pattern)
    column: str
    max_age_days: int = Field(gt=0)


class Column(Strict):
    type: Literal["STRING", "DATE", "TIMESTAMP", "INTEGER", "FLOAT", "NUMERIC", "BOOLEAN", "RECORD", "BYTES"]
    description: str = Field(min_length=3)
    classification: Classification
    kinds: list[Kind] = Field(default_factory=list)  # declared kinds of personal data; [] only for untagged columns
    masking: dict[str, Masking] = Field(default_factory=dict)
    quality: list[QualityRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Column:
        if self.classification.tagged and not self.masking:
            raise ValueError("a tagged column must declare masking for at least one role")
        if not self.classification.tagged and self.masking:
            raise ValueError(f"masking on a `{self.classification}` column has nothing to act on (no policy tag)")
        if self.classification.tagged and not self.kinds:
            raise ValueError("a tagged column must declare which kinds of personal data it holds")
        if not self.classification.tagged and self.kinds:
            raise ValueError(
                f"declares personal data ({', '.join(self.kinds)}) but is classified `{self.classification}` — it would carry no policy tag (doctrine 7)"
            )
        if self.type == "RECORD" and (self.masking or self.classification.tagged):
            raise ValueError("a RECORD is a container; classify its leaves")
        for rule in self.quality:
            if (rule.min is not None or rule.max is not None) and self.type not in NUMERIC_TYPES:
                raise ValueError(f"{rule.id}: min/max on a {self.type} column")
            if (rule.regex is not None or rule.allowed is not None) and self.type != "STRING":
                raise ValueError(f"{rule.id}: regex/allowed on a {self.type} column")
        return self


class TableRetention(Strict):
    """`partition`: compiled to partition expiration on `column`, which must be the table's partition
    column in the estate. `row`: BigQuery has no row expiry, so this compiles (T007) to a scheduled,
    idempotent DELETE over `column`; `rule` is the human sentence that DELETE must implement."""

    mode: Literal["partition", "row"]
    column: str
    period_days: int | None = Field(default=None, gt=0)  # a stricter table period; may not exceed the dataset's
    rule: str | None = None

    @model_validator(mode="after")
    def _rule(self) -> TableRetention:
        if self.mode == "row" and not self.rule:
            raise ValueError("row retention needs `rule`: the sentence the compiled DELETE implements")
        return self


class RowAccess(Strict):
    """Exactly one of: `column` (rows filtered per seat on this column) or `none` (every role with
    column access sees every row — a decision that must be written down with its reason)."""

    column: str | None = None
    none: str | None = Field(default=None, min_length=10)

    @model_validator(mode="after")
    def _one(self) -> RowAccess:
        if (self.column is None) == (self.none is None):
            raise ValueError("row_access needs exactly one of `column` or `none: <reason>`")
        return self


class Table(Strict):
    description: str = Field(min_length=3)
    primary_key: list[str] = Field(min_length=1)
    retention: TableRetention
    row_access: RowAccess  # required: "all rows" is a decision, never a default (doctrine 3)
    freshness: Freshness | None = None
    columns: dict[str, Column] = Field(min_length=1)


class Retention(Strict):
    period_days: int = Field(gt=0)
    legal_basis: str = Field(min_length=10)

    @field_validator("legal_basis")
    @classmethod
    def _cites(cls, v: str) -> str:
        if not LEGAL.search(v):
            raise ValueError("legal_basis must name an instrument (Art., Directive, Regulation, law or obligation)")
        return v


class Marketplace(Strict):
    listable: bool
    approvers: str
    max_grant_days: int = Field(gt=0, le=90)
    grantable_roles: list[str]

    @model_validator(mode="after")
    def _listed_iff_grantable(self) -> Marketplace:
        if self.listable != bool(self.grantable_roles):
            raise ValueError("a listed dataset grants at least one role; an unlisted one grants none")
        return self

    _p = field_validator("approvers")(classmethod(lambda cls, v: _principal(v)))


LOG_SINK_TABLE = re.compile(r"^cloudaudit_googleapis_com_[a-z_]+$")


class LogSink(Strict):
    """A dataset filled by a Cloud Logging sink: its tables and columns are Logging's (B15).

    Narrow on purpose — this must not become a key to doctrine 7. Only tables named the way Cloud
    Logging names audit-log tables are exempt from declaration, and the only personal data such a
    dataset may hold is principals' e-mail addresses."""

    source: str = Field(min_length=10)
    personal_kinds: list[Literal["email"]] = Field(min_length=1)


class Change(Strict):
    version: int = Field(ge=1)
    date: date_t
    change: str = Field(min_length=3)


class Contract(Strict):
    dataset: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    description: str = Field(min_length=3)
    owner: str
    steward: str
    custodian: str
    lawful_basis: str = Field(min_length=10)
    retention: Retention
    readers: list[str]  # roles with standing read access; [] is allowed and means "only via the marketplace"
    marketplace: Marketplace
    changelog: list[Change] = Field(min_length=1)
    log_sink: LogSink | None = None
    tables: dict[str, Table]

    @model_validator(mode="after")
    def _tables_or_sink(self) -> Contract:
        if self.log_sink is None and not self.tables:
            raise ValueError("a contract declares at least one table (or `log_sink` for a sink-filled dataset)")
        if self.log_sink is not None and self.tables:
            raise ValueError("a log-sink dataset's tables belong to Cloud Logging; declare none")
        return self

    _p = field_validator("owner", "steward", "custodian")(classmethod(lambda cls, v: _principal(v)))

    @field_validator("lawful_basis")
    @classmethod
    def _cites(cls, v: str) -> str:
        if not LEGAL.search(v):
            raise ValueError("lawful_basis must name an instrument (Art., Directive, Regulation, law or obligation)")
        return v

    @model_validator(mode="after")
    def _versioned(self) -> Contract:
        # Intra-file only: the changelog is complete and ordered. Whether a change against the
        # committed version bumped `version` is core/versioning.py (scripts/check_contract_versions.py).
        versions = [c.version for c in self.changelog]
        if versions != list(range(1, len(versions) + 1)):
            raise ValueError(f"changelog versions must be 1..n with no gaps or repeats, got {versions}")
        if versions[-1] != self.version:
            raise ValueError(f"version {self.version} has no changelog line (doctrine 4: a change is a new version)")
        return self

    def iter_columns(self):
        """Yield (fqn, table_name, column_path, Column) for every column, e.g. ('crm.customers.address.street', …)."""
        for tname, table in self.tables.items():
            for path, col in table.columns.items():
                yield f"{self.dataset}.{tname}.{path}", tname, path, col

    def table_retention_days(self, table: str) -> int:
        return self.tables[table].retention.period_days or self.retention.period_days


class Role(Strict):
    description: str = Field(min_length=3)
    scoped_by: str | None = None
    scopes: list[str] | None = None
    # A role whose seat on each dataset is that contract's own principal for this field.
    bound_from: Literal["steward", "custodian"] | None = None

    @model_validator(mode="after")
    def _scoped(self) -> Role:
        if (self.scoped_by is None) != (self.scopes is None):
            raise ValueError("scoped_by and scopes come together")
        if self.bound_from and self.scoped_by:
            raise ValueError("a role is either scoped or bound to a contract field, not both")
        return self


class Ceiling(Strict):
    clear_kinds: list[Kind]


class Roles(Strict):
    roles: dict[str, Role]
    ceilings: dict[str, Ceiling]
    seat_groups: dict[str, str]
    waiver_approvers: str
    directory: dict[str, list[str]]

    _p = field_validator("waiver_approvers")(classmethod(lambda cls, v: _principal(v)))

    @field_validator("directory")
    @classmethod
    def _members(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for g, ms in v.items():
            _principal(g)
            if not g.startswith("group:"):
                raise ValueError(f"directory keys are groups, got {g!r}")
            for m in ms:
                _principal(m)
                if m.startswith("group:"):
                    # Nested groups are refused rather than expanded: membership is then exactly what
                    # this file says, and "who is in this group" has one answer a reviewer can read.
                    raise ValueError(f"{g} contains group {m}: nested groups are not allowed")
        return v

    @model_validator(mode="after")
    def _seat_groups_cover_unbound_seats(self) -> Roles:
        seats = {s for r, role in self.roles.items() if not role.bound_from for s in self.seats(r)}
        if set(self.seat_groups) != seats:
            raise ValueError(f"seat_groups must name a group for exactly the seats {sorted(seats)}")
        missing = sorted(g for g in self.seat_groups.values() if g not in self.directory)
        if missing:
            raise ValueError(f"seat groups not in the directory: {missing}")
        return self

    @model_validator(mode="after")
    def _every_role_has_a_ceiling(self) -> Roles:
        missing = sorted(set(self.roles) - set(self.ceilings))
        extra = sorted(set(self.ceilings) - set(self.roles))
        if missing or extra:
            raise ValueError(f"ceilings must cover exactly the roles (missing {missing}, unknown {extra})")
        return self

    def seats(self, role: str) -> list[str]:
        """'analyst' → ['analyst@GR', 'analyst@IT', 'analyst@DE']; unscoped → ['fraud_investigator'].
        Bound roles have no seat of their own — use core.compile.seats_for(roles, role, contract)."""
        r = self.roles[role]
        if r.bound_from:
            raise ValueError(f"{role} is bound to each contract's {r.bound_from}; its seats depend on the contract")
        return [f"{role}@{s}" for s in r.scopes] if r.scopes else [role]

    def members(self, group: str) -> list[str]:
        return self.directory.get(group, [])

    def is_member(self, principal: str, group: str) -> bool:
        return principal == group or principal in self.members(group)

    def in_directory(self, principal: str) -> bool:
        return principal in self.directory or any(principal in ms for ms in self.directory.values())


MAX_WAIVER_DAYS = 90


class Waiver(Strict):
    """An exception with a deadline (doctrine 6). Approved by a named member of the waiver-approver
    group, who is neither the requester nor an owner of what is waived (doctrine 5)."""

    id: str = Field(pattern=r"^W-\d{3}$")
    finding: str
    target: str
    reason: str = Field(min_length=10)
    requested_by: str
    approved_by: str
    approved_on: date_t
    expires: date_t

    _p = field_validator("approved_by", "requested_by")(classmethod(lambda cls, v: _principal(v)))

    @model_validator(mode="after")
    def _window(self) -> Waiver:
        if self.expires <= self.approved_on:
            raise ValueError("expires must be after approved_on")
        if (self.expires - self.approved_on).days > MAX_WAIVER_DAYS:
            raise ValueError(
                f"a waiver may last at most {MAX_WAIVER_DAYS} days; longer is a policy change, not an exception"
            )
        return self


def parse_contract(doc: dict) -> Contract:
    return Contract.model_validate(doc)
