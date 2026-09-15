"""The result contract. Both engines fill exactly this shape."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ALLOWED_OPS = ("<=", ">=", "in", "is_false")
# A binary rule is either wholly satisfied or wholly violated; there is no
# fraction of a target that failed to ignite.
BINARY_MARGIN = 1.0


class Criterion(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: float | bool
    # `None` means the authority having jurisdiction has not set this limit
    # (SOLIT2 Annex 7 section 7.1), or that the rule is binary and needs none.
    limit: float | tuple[float, float] | None
    op: Literal["<=", ">=", "in", "is_false"]
    hard: bool
    passed: bool
    # "unset" is what a reader looks at: `passed` is True for an unset limit so
    # that a limit nobody has set can never reject a design, which makes
    # `passed` alone unable to distinguish an assessed design from an
    # unassessed one.
    status: Literal["pass", "fail", "unset"]
    margin: float

    @classmethod
    def build(cls, value: float | bool, limit: float | tuple[float, float] | None,
              op: str, hard: bool) -> "Criterion":
        # `is_false` is checked before the unset test on purpose: it is a binary
        # rule that carries no limit, and Annex 7 section 7.2.1 mandates it
        # absolutely ("prevention of fire spread is essential in every case"),
        # so its missing limit must not be read as the AHJ having stayed silent.
        if op == "is_false":
            passed = not value
            return cls(value=value, limit=None, op=op, hard=hard, passed=passed,
                       status="pass" if passed else "fail",
                       margin=BINARY_MARGIN if passed else -BINARY_MARGIN)
        if op not in ALLOWED_OPS:
            raise ValueError(
                f"unknown criterion operator {op!r}; expected "
                f"{', '.join(repr(o) for o in ALLOWED_OPS)}"
            )
        if limit is None:
            return cls(value=value, limit=None, op=op, hard=hard,
                       passed=True, status="unset", margin=0.0)
        if op == "<=":
            passed = value <= limit
            margin = 1.0 - value / limit if limit else 0.0
        elif op == ">=":
            passed = value >= limit
            margin = min(1.0, value / limit - 1.0) if limit else 0.0
        else:
            low, high = limit
            passed = low <= value <= high
            half_band = (high - low) / 2.0
            centre = (high + low) / 2.0
            margin = 1.0 - abs(value - centre) / half_band if half_band else 0.0
        return cls(value=value, limit=limit, op=op, hard=hard, passed=passed,
                   status="pass" if passed else "fail",
                   margin=max(min(margin, 1.0), -1.0))


class Result(BaseModel):
    model_config = ConfigDict(frozen=True)

    meta: dict[str, Any]
    envelope: list[dict[str, Any]]
    # The single case whose `events`, `peaks` and `timeseries` are the ones reported
    # below: the run holding the thinnest hard margin. `criteria` is selected
    # differently - each criterion takes its worst value across the whole envelope -
    # so a criterion's value may well come from a different case than this one.
    # `criteria_cases` names the case behind each criterion's value.
    worst_case: dict[str, Any]
    events: dict[str, Any]
    criteria: dict[str, Criterion]
    # criterion id -> the case that produced that criterion's reported value.
    criteria_cases: dict[str, dict[str, Any]] = Field(default_factory=dict)
    peaks: dict[str, float]
    mist: dict[str, Any]
    hydraulics: dict[str, Any]
    cost: dict[str, Any]
    score: dict[str, Any]
    timeseries: dict[str, list[float]]
    warnings: list[str]
