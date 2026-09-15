"""The result contract. Both engines fill exactly this shape."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Criterion(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: float
    limit: float | tuple[float, float]
    op: Literal["<=", ">=", "in"]
    hard: bool
    passed: bool
    margin: float

    @classmethod
    def build(cls, value: float, limit: float | tuple[float, float],
              op: str, hard: bool) -> "Criterion":
        if op == "<=":
            passed = value <= limit
            margin = 1.0 - value / limit if limit else 0.0
        elif op == ">=":
            passed = value >= limit
            margin = min(1.0, value / limit - 1.0) if limit else 0.0
        elif op == "in":
            low, high = limit
            passed = low <= value <= high
            half_band = (high - low) / 2.0
            centre = (high + low) / 2.0
            margin = 1.0 - abs(value - centre) / half_band if half_band else 0.0
        else:
            raise ValueError(f"unknown criterion operator {op!r}; expected '<=', '>=' or 'in'")
        return cls(value=value, limit=limit, op=op, hard=hard,
                   passed=passed, margin=max(min(margin, 1.0), -1.0))


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
