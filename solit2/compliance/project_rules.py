"""A project's own requirements, declared in a file that lives with the project.

Kept declarative and narrow on purpose: a rule compares one quantity from a
fixed list against a limit, or asks for one evidenced fact. It cannot compute
a new measure, so a project file cannot quietly redefine what is being judged.
"""
from __future__ import annotations

import json
import operator
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from solit2.compliance.context import Context, tested_velocities_ms
from solit2.compliance.rules.base import Outcome, Rule, judge, needs
from solit2.compliance.spec import Facts

QUANTITIES: dict[str, Callable[[Context], float]] = {
    "installation.peak_hrr_mw": lambda c: c.installation_result.peaks["hrr_mw"],
    "installation.power_kw": lambda c: c.installation_result.hydraulics["power_kw"],
    "installation.flow_lpm": lambda c: c.installation_result.hydraulics["flow_lpm"],
    "installation.density_mm_min": lambda c: c.installation_result.hydraulics["density_mm_min"],
    "installation.smd_um": lambda c: c.installation.nozzles.smd_um(c.installation.nozzles.modes[0].id),
    "test.max_velocity_ms": lambda c: max(tested_velocities_ms(c, c.installation.fire.fire_class)[0]),
    "test.min_velocity_ms": lambda c: min(tested_velocities_ms(c, c.installation.fire.fire_class)[0]),
}
_COMPARE = {"<=": operator.le, "<": operator.lt, ">=": operator.ge, ">": operator.gt,
            "==": operator.eq}


class ProjectRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    requirement: str = Field(min_length=1)
    quantity: str | None = None
    comparator: Literal["<=", "<", ">=", ">", "=="] | None = None
    limit: float | None = None
    requires_fact: str | None = None

    @model_validator(mode="after")
    def _well_formed(self) -> "ProjectRule":
        if self.quantity is not None and self.quantity not in QUANTITIES:
            raise ValueError(f"quantity {self.quantity!r} is not one of {sorted(QUANTITIES)}")
        compare = (self.quantity, self.comparator, self.limit)
        if any(v is not None for v in compare) and any(v is None for v in compare):
            raise ValueError("quantity, comparator and limit must be given together")
        if self.quantity is None and self.requires_fact is None:
            raise ValueError("a project rule needs a quantity to compare or a fact to require")
        if self.requires_fact is not None and self.requires_fact not in Facts.model_fields:
            raise ValueError(f"requires_fact {self.requires_fact!r} is not a spec fact; "
                             f"use one of {sorted(Facts.model_fields)}")
        return self


class ProjectRuleFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_document: str = Field(min_length=1)
    rules: list[ProjectRule]


def _check(rule: ProjectRule) -> Callable[[Context], Outcome]:
    required = (f"{rule.comparator} {rule.limit:g}" if rule.quantity else f"{rule.requires_fact}")

    def check(ctx: Context) -> Outcome:
        evidence = ""
        if rule.requires_fact is not None:
            fact = getattr(ctx.facts, rule.requires_fact)
            if fact is None:
                return needs(rule.requires_fact, required)
            evidence = fact.evidence.cite()
            if rule.quantity is None:
                return judge(True, str(fact.value), required, "spec fact", evidence)
        value = QUANTITIES[rule.quantity](ctx)
        basis = ("Tier 1 prediction" if rule.quantity.startswith("installation.")
                 else "planned test velocities")
        return judge(_COMPARE[rule.comparator](value, rule.limit), f"{value:.4g}", required,
                     basis, evidence)
    return check


def load_project_rules(path: str | Path) -> tuple[Rule, ...]:
    parsed = ProjectRuleFile.model_validate(json.loads(Path(path).read_text()))
    return tuple(Rule(f"project.{r.id}", f"Project: {parsed.source_document}", r.source,
                      r.requirement, "project", _check(r)) for r in parsed.rules)
