"""The user's own engineering limits, evaluated apart from the criteria.

SOLIT2 Annex 7 is a standard; a feeder capacity, a tank volume and a
procurement pressure band are not. Both get judged, but a reader must be able
to tell at a glance which verdict is which, so these are evaluated here, keyed
by their own ids, and reported in the result's `constraints` block. They never
reach `score.compute`, so a breached constraint cannot fail a SOLIT2 gate.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from solit2.engines.reduced.hydraulics import HydraulicsResult
from solit2.schema.design import Constraints, Design
from solit2.schema.result import Criterion

# A constraint is never a gate. `Criterion.hard` means "failing this zeroes the
# score" everywhere else in the engine, so every constraint carries False: the
# separation is what keeps a local limit from reading as a standard's verdict.
CONSTRAINT_IS_NEVER_A_GATE = False


@dataclass(frozen=True)
class ConstraintSpec:
    """One user-declared limit: where its value is read, and how it is compared."""
    id: str
    limit: Callable[[Constraints], float | None]
    op: str
    extract: Callable[[HydraulicsResult, Design], float]


CONSTRAINT_SPECS: tuple[ConstraintSpec, ...] = (
    ConstraintSpec("max_pump_power_kw", lambda c: c.max_pump_power_kw, "<=",
                   lambda h, d: h.power_kw),
    ConstraintSpec("max_application_density_mm_min",
                   lambda c: c.max_application_density_mm_min, "<=",
                   lambda h, d: h.density_mm_min),
    ConstraintSpec("max_water_volume_m3", lambda c: c.max_water_volume_m3, "<=",
                   lambda h, d: h.tank_m3),
    ConstraintSpec("max_nozzle_pressure_bar", lambda c: c.max_nozzle_pressure_bar, "<=",
                   lambda h, d: d.nozzles.pressure_bar),
    ConstraintSpec("min_nozzle_pressure_bar", lambda c: c.min_nozzle_pressure_bar, ">=",
                   lambda h, d: d.nozzles.pressure_bar),
)


def evaluate(hyd: HydraulicsResult, design: Design) -> dict[str, Criterion]:
    """Apply every constraint; an undeclared one reports as unset."""
    return {
        spec.id: Criterion.build(
            value=spec.extract(hyd, design),
            limit=spec.limit(design.constraints),
            op=spec.op,
            hard=CONSTRAINT_IS_NEVER_A_GATE,
        )
        for spec in CONSTRAINT_SPECS
    }


def breached(constraints: dict[str, Criterion]) -> list[str]:
    """The ids whose declared limit the design exceeds. Reported, never gating."""
    return [cid for cid, c in constraints.items() if c.status == "fail"]
