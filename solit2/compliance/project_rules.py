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


def _tested_extreme(pick: Callable[[list[float]], float]) -> Callable[[Context], float | None]:
    """`max`/`min` of the class's tested velocities, or None if none are declared
    (I3): a project rule cannot ask "how fast was it tested" of a test nobody
    described, and `max([])`/`min([])` would crash rather than say so."""
    def read(ctx: Context) -> float | None:
        values, _why = tested_velocities_ms(ctx, ctx.installation.fire.fire_class)
        return pick(values) if values else None
    return read


def _droplet_size_um(ctx: Context) -> float | None:
    fact = ctx.facts.droplet_size
    return fact.value.value_um if fact is not None else None


# name -> (fn returning the value to compare, or None if not supplied; the
# basis kind that value is; the human-readable basis text for the report).
# `fn` reads only Tier 1 results, the planned test programme, or an evidenced
# Fact -- never a laboratory measurement a project rule could invent itself.
QUANTITIES: dict[str, tuple[Callable[[Context], float | None], str, str]] = {
    "installation.peak_hrr_mw": (lambda c: c.installation_result.peaks["hrr_mw"],
                                 "predicted", "Tier 1 prediction"),
    "installation.power_kw": (lambda c: c.installation_result.hydraulics["power_kw"],
                              "predicted", "Tier 1 hydraulics (predicted)"),
    "installation.flow_lpm": (lambda c: c.installation_result.hydraulics["flow_lpm"],
                              "predicted", "Tier 1 hydraulics (predicted)"),
    "installation.density_mm_min": (lambda c: c.installation_result.hydraulics["density_mm_min"],
                                    "predicted", "Tier 1 hydraulics (predicted)"),
    "test.max_velocity_ms": (_tested_extreme(max), "planned", "planned test velocities"),
    "test.min_velocity_ms": (_tested_extreme(min), "planned", "planned test velocities"),
    "fact.droplet_size_um": (_droplet_size_um, "evidenced", "measured droplet size"),
}
# The Facts field that would settle a quantity currently reading None, so a
# "needs evidence" finding names something a spec author can actually supply.
_NEEDS_FACT = {"test.max_velocity_ms": "planned_tests", "test.min_velocity_ms": "planned_tests",
               "fact.droplet_size_um": "droplet_size"}
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


def _required_text(rule: ProjectRule) -> str:
    """A project rule combining a quantity with `requires_fact` keeps the fact
    name in `required` too, so a reader sees both conditions the clause
    actually depends on, not just the numeric half of it."""
    if rule.quantity is None:
        return rule.requires_fact
    text = f"{rule.comparator} {rule.limit:g}"
    if rule.requires_fact is not None:
        text += f", with {rule.requires_fact} declared"
    return text


def _is_empty(value: object) -> bool:
    """An empty string, False, or an empty list is "supplied but empty", never
    a pass: a fact-only project rule with such a value has not actually been
    given anything to judge. `is False` rather than `== False` so a genuine
    `0` (a legitimate numeric fact value) is not mistaken for it."""
    return value == "" or value is False or value == []


def _check(rule: ProjectRule) -> Callable[[Context], Outcome]:
    required = _required_text(rule)

    def check(ctx: Context) -> Outcome:
        evidence = ""
        if rule.requires_fact is not None:
            fact = getattr(ctx.facts, rule.requires_fact)
            if fact is None:
                return needs(rule.requires_fact, required, "evidenced")
            evidence = fact.evidence.cite()
            if rule.quantity is None:
                if _is_empty(fact.value):
                    return needs(rule.requires_fact, required, "evidenced", "supplied but empty")
                return judge(True, str(fact.value), required, "spec fact", "evidenced", evidence)
        fn, basis_kind, basis_text = QUANTITIES[rule.quantity]
        value = fn(ctx)
        if value is None:
            return needs(_NEEDS_FACT.get(rule.quantity, rule.quantity), required, basis_kind)
        found = f"{value:.4g}"
        if rule.quantity == "fact.droplet_size_um":
            fact = ctx.facts.droplet_size
            evidence = fact.evidence.cite()
            found = f"{found} µm ({fact.value.measure})"
        return judge(_COMPARE[rule.comparator](value, rule.limit), found, required, basis_text,
                     basis_kind, evidence)
    return check


def load_project_rules(path: str | Path) -> tuple[Rule, ...]:
    parsed = ProjectRuleFile.model_validate(json.loads(Path(path).read_text()))
    ids = [r.id for r in parsed.rules]
    dupes = sorted({rid for rid in ids if ids.count(rid) > 1})
    if dupes:
        raise ValueError(f"duplicate project rule id(s) in {Path(path)}: {', '.join(dupes)}; "
                         "every rule id in a project rules file must be unique")
    return tuple(Rule(f"project.{r.id}", f"Project: {parsed.source_document}", r.source,
                      r.requirement, "project", _check(r)) for r in parsed.rules)
