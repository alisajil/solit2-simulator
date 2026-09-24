"""The planned test, as the laboratory and the authority evidence it.

Every fact is a fixed, typed field: a free dictionary would let a misspelt
fact leave its clause silently unjudged. Every fact carries its evidence, and
a fact without evidence is not a fact.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from solit2.schema.design import Design

T = TypeVar("T")


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Evidence(_Strict):
    document: str = Field(min_length=1)
    locator: str = Field(min_length=1)

    def cite(self) -> str:
        return f"{self.document}, {self.locator}"


class Fact(_Strict, Generic[T]):
    value: T
    evidence: Evidence


class PlannedTest(_Strict):
    fire_class: Literal["A", "B"]
    covered: bool
    velocity_ms: float = Field(gt=0)


class Facts(_Strict):
    pallet_dims_mm: Fact[tuple[float, float, float]] | None = None
    pallet_mass_kg: Fact[tuple[float, float]] | None = None  # lightest, heaviest weighed
    pallet_moisture_pct: Fact[float] | None = None            # highest measured
    frame_coverage_pct: Fact[float] | None = None
    tarpaulin_fitted: Fact[bool] | None = None
    ignition_pans: Fact[int] | None = None
    ignition_pan_mm: Fact[tuple[float, float, float]] | None = None
    ignition_petrol_l: Fact[float] | None = None              # per pan
    class_b_free_burn_min: Fact[float] | None = None
    class_b_ignition_s: Fact[float] | None = None
    class_b_trigger_s: Fact[float] | None = None
    velocity_measured_at_m: Fact[dict[str, float]] | None = None  # by fire class
    flow_deviation_pct: Fact[float] | None = None
    last_nozzle_pressure_measured: Fact[bool] | None = None
    instruments_compliant: Fact[list[str]] | None = None      # INSTRUMENT_SPEC names
    table5_layout: Fact[bool] | None = None
    sampling_interval_s: Fact[float] | None = None
    measurement_schedule: Fact[list[str]] | None = None       # MAIN_MEASUREMENT_SCHEDULE names
    hrr_method: Fact[str] | None = None
    hrr_delay_s: Fact[float] | None = None
    calibration_fires_mw: Fact[list[float]] | None = None
    planned_tests: Fact[list[PlannedTest]] | None = None
    test_series: Fact[int] | None = None
    droplet_distribution_report: Fact[str] | None = None
    spray_deviation_tested_ms: Fact[list[float]] | None = None
    authority_limits: Fact[str] | None = None
    activation_option: Fact[Literal["A", "B"]] | None = None
    tested_pressure_bar: Fact[tuple[float, float]] | None = None  # lowest, highest tested
    droplet_size_measure: Fact[str] | None = None
    correlation_cfd_report: Fact[str] | None = None


class Deviation(_Strict):
    accepted_by: str = Field(min_length=1)
    document: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    def cite(self) -> str:
        return f"accepted by {self.accepted_by} ({self.document}, {self.locator}): {self.reason}"


class ComplianceSpec(_Strict):
    spec_version: Literal[1]
    name: str = Field(min_length=1)
    test_designs: dict[Literal["A", "B"], str]
    installation_design: str
    project_rules: str | None = None
    facts: Facts = Field(default_factory=Facts)
    deviations: dict[str, Deviation] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _class_a_required(self) -> "ComplianceSpec":
        if "A" not in self.test_designs:
            raise ValueError("test_designs must include the Class A test design: Annex 7 "
                             "Table 4's required tests 1 and 2 are Class A")
        return self


@dataclass(frozen=True)
class LoadedSpec:
    path: Path
    spec: ComplianceSpec
    tests: dict[str, Design]
    installation: Design
    project_rules_path: Path | None


def _resolve(base: Path, relative: str, field: str) -> Path:
    path = (base / relative).resolve()
    if not path.exists():
        raise FileNotFoundError(f"{field}: {relative} does not exist (resolved to {path}); "
                                "paths in a spec are relative to the spec file")
    return path


def load_spec(path: str | Path) -> LoadedSpec:
    spec_path = Path(path).resolve()
    spec = ComplianceSpec.model_validate(json.loads(spec_path.read_text()))
    base = spec_path.parent
    installation = Design.load(_resolve(base, spec.installation_design, "installation_design"))
    tests = {cls: Design.load(_resolve(base, rel, f"test_designs.{cls}"))
             for cls, rel in spec.test_designs.items()}
    rules = (_resolve(base, spec.project_rules, "project_rules")
             if spec.project_rules else None)
    return LoadedSpec(spec_path, spec, tests, installation, rules)
