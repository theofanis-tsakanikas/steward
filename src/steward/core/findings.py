"""Findings: the one shape every gate reports in."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Which findings a waiver may suppress is decided in one place: core/validate.py WAIVABLE (an
# allowlist). Everything else — every finding about personal data above all (doctrine 7) — is not.


@dataclass(frozen=True)
class Finding:
    code: str
    gate: str
    target: str
    message: str
    severity: str = "error"  # error | warn | info
    waived_by: str | None = None
    evidence: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def blocking(self) -> bool:
        return self.severity == "error" and self.waived_by is None

    def line(self) -> str:
        w = f" [waived by {self.waived_by}]" if self.waived_by else ""
        return f"{self.severity.upper():5} {self.code} {self.target} — {self.message}{w}"

    def to_dict(self) -> dict:
        return asdict(self)


def report(gate: str, findings: list[Finding]) -> tuple[int, list[str]]:
    """Return (exit code, lines). Exit 1 iff any blocking finding."""
    lines = [f.line() for f in sorted(findings, key=lambda f: (f.severity != "error", f.code, f.target))]
    blocking = [f for f in findings if f.blocking]
    if blocking:
        lines.append(f"FAIL {gate}: {len(blocking)} blocking finding(s)")
        return 1, lines
    lines.append(f"ok {gate}: 0 blocking ({len(findings)} reported)")
    return 0, lines
