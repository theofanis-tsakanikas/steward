"""The contract model. One contract per BigQuery dataset; the single source of truth.

Doctrine 3 lives here: **a default is never invented.** Owner, steward, custodian, retention and its
legal basis, and every column's classification are required fields with no default. A contract
that omits one does not load — it is a failing build, not a plausible value.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PRINCIPAL = re.compile(r"^(user|group|serviceAccount):[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$")
RULE_ID = re.compile(r"^Q-[A-Z]{3}-\d{3}$")


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
        return self


class Freshness(Strict):
    id: str
    column: str
    max_age_days: int = Field(gt=0)


class Column(Strict):
    type: Literal["STRING", "DATE", "TIMESTAMP", "INTEGER", "FLOAT", "NUMERIC", "BOOLEAN", "RECORD", "BYTES"]
    description: str = Field(min_length=3)
    classification: Classification
    kinds: list[str] = Field(default_factory=list)  # declared kinds of personal data (msisdn, iban, …)
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
        if self.type == "RECORD" and (self.masking or self.classification.tagged):
            raise ValueError("a RECORD is a container; classify its leaves")
        return self


class TableRetention(Strict):
    mode: Literal["partition", "row"]
    column: str
    period_days: int | None = Field(default=None, gt=0)  # overrides the dataset period (must not exceed it)
    rule: str | None = None


class RowAccess(Strict):
    column: str


class Table(Strict):
    description: str = Field(min_length=3)
    primary_key: list[str] = Field(min_length=1)
    retention: TableRetention
    row_access: RowAccess | None = None
    freshness: Freshness | None = None
    columns: dict[str, Column] = Field(min_length=1)


class Retention(Strict):
    period_days: int = Field(gt=0)
    legal_basis: str = Field(min_length=10)


class Marketplace(Strict):
    listable: bool
    approvers: str
    max_grant_days: int = Field(gt=0, le=90)
    grantable_roles: list[str] = Field(min_length=1)

    _p = field_validator("approvers")(classmethod(lambda cls, v: _principal(v)))


class Change(Strict):
    version: int
    date: str
    change: str


class Contract(Strict):
    dataset: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    description: str = Field(min_length=3)
    owner: str
    steward: str
    custodian: str
    lawful_basis: str = Field(min_length=10)
    retention: Retention
    marketplace: Marketplace
    changelog: list[Change] = Field(min_length=1)
    tables: dict[str, Table] = Field(min_length=1)

    _p = field_validator("owner", "steward", "custodian")(classmethod(lambda cls, v: _principal(v)))

    @model_validator(mode="after")
    def _versioned(self) -> Contract:
        if max(c.version for c in self.changelog) != self.version:
            raise ValueError(f"version {self.version} has no changelog line (doctrine 4: a change is a new version)")
        return self

    def iter_columns(self):
        """Yield (fqn, table_name, column_path, Column) for every column, e.g. ('crm.customers.address.street', …)."""
        for tname, table in self.tables.items():
            for path, col in table.columns.items():
                yield f"{self.dataset}.{tname}.{path}", tname, path, col

    def table_retention_days(self, table: str) -> int:
        return self.tables[table].retention.period_days or self.retention.period_days


class Roles(Strict):
    roles: dict[str, dict]
    directory: dict[str, list[str]]

    def members(self, group: str) -> list[str]:
        return self.directory.get(group, [])


class Waiver(Strict):
    id: str
    finding: str
    target: str
    reason: str = Field(min_length=10)
    approved_by: str
    approved_on: str
    expires: str  # ISO date; required — an exception with no expiry is a policy change (doctrine 6)

    _p = field_validator("approved_by")(classmethod(lambda cls, v: _principal(v)))


def parse_contract(doc: dict) -> Contract:
    return Contract.model_validate(doc)
