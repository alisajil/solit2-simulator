# SOLIT² Compliance Checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A clause-by-clause SOLIT² compliance checker for a planned full-scale fire test and the installation it qualifies, surfaced as a wizard step and a markdown report.

**Architecture:** A registry of small frozen `Rule`s (SOLIT² only, numbers from `solit2/reports/guidance.py`) evaluated against a `Context` built from a strict evidence-backed spec file, one Tier 1 run per design, and an optional declarative project rule file. Findings carry one of five verdicts; the headline reaches 100 % only with zero Fails and zero Needs evidence.

**Tech Stack:** Python 3.12, pydantic v2, pytest, Streamlit (AppTest), `uv`.

**Spec:** `docs/superpowers/specs/2026-09-24-solit2-compliance-checker-design.md`

## Global Constraints

- No new dependencies. Run everything with `uv run`.
- INDEPENDENCE rules 1 and 2: no project or vendor names anywhere under `solit2/`, `app/` or `examples/` (`tests/test_independence.py` enforces it). Project files go in `designs/` only.
- Never write an acceptance limit or a laboratory fact that nobody supplied. Missing input is `Needs evidence`, never `Complies`.
- Every SOLIT² number comes from `solit2/reports/guidance.py`; rules never repeat a literal the module already holds.
- A rule's `requirement` is a plain-language statement of the clause with its reference. **Ruling (deviation from the spec's "quoted"):** verbatim quotation is used only where `guidance.py` already quotes the source, because quoting from memory would fabricate text; the report labels requirements as "requirement (paraphrased)".
- Frozen dataclasses / frozen pydantic models; explanatory comments on constants; `ValueError` messages that say how to fix the input.
- Commit messages: conventional (`feat(compliance): ...`), **no Co-Authored-By trailer** (the user disabled attribution).
- Full suite must stay green: `uv run pytest -q`.

## File structure

| File | Responsibility |
|---|---|
| `solit2/compliance/__init__.py` | package marker |
| `solit2/compliance/verdict.py` | `Verdict`, `Finding`, `Headline`, `headline()` |
| `solit2/compliance/spec.py` | `Evidence`, `Fact`, `PlannedTest`, `Facts`, `Deviation`, `ComplianceSpec`, `LoadedSpec`, `load_spec()` |
| `solit2/compliance/context.py` | `Context` and the quantities rules share (`hrr_at_mw`, `time_to_full_operation_s`, `standoff_m`, `target_ignited`, `tested_velocities_ms`) |
| `solit2/compliance/rules/base.py` | `Outcome`, `Rule`, `judge`, `needs`, `evaluate` |
| `solit2/compliance/rules/test_rules.py` | design-derived SOLIT² rules on the test designs |
| `solit2/compliance/rules/lab_rules.py` | evidence-gated SOLIT² rules |
| `solit2/compliance/rules/transfer_rules.py` | installation-against-test rules |
| `solit2/compliance/rules/__init__.py` | `REGISTRY` |
| `solit2/compliance/project_rules.py` | `QUANTITIES`, `ProjectRule`, `load_project_rules()` |
| `solit2/compliance/check.py` | `ComplianceReport`, `run()` |
| `solit2/reports/compliance.py` | `render()`, `lab_checklist()` |
| `solit2/cli.py` | `report compliance` subcommand |
| `app/views/compliance.py` | the Compliance wizard step |
| `app/components/stepper.py`, `app/state.py`, `app/streamlit_app.py` | six steps |
| `examples/compliance/` | neutral example spec (+ its designs are the existing examples) |
| `designs/og-*.json` | the project spec, test designs and tender rule file |
| `tests/test_compliance_*.py`, `tests/fixtures/compliance/` | tests |

---

### Task 1: Verdicts, findings and the headline

**Files:**
- Create: `solit2/compliance/__init__.py`, `solit2/compliance/verdict.py`
- Test: `tests/test_compliance_verdict.py`

**Interfaces:**
- Produces: `Verdict` (str enum: `COMPLIES`, `FAILS`, `DEVIATION_ACCEPTED`, `NEEDS_EVIDENCE`, `NOT_APPLICABLE`); `Finding` (frozen dataclass: `rule_id, group, clause, requirement, kind, verdict, found, required, basis, evidence="", fact="", deviation=""`); `Headline` (frozen: `applicable, complying, by_deviation, fails, needs_evidence`, properties `full: bool`, `text: str`); `headline(findings: Iterable[Finding]) -> Headline`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compliance_verdict.py
from solit2.compliance.verdict import Finding, Verdict, headline


def _f(verdict: Verdict, rule_id: str = "r") -> Finding:
    return Finding(rule_id=rule_id, group="g", clause="§1", requirement="req", kind="design",
                   verdict=verdict, found="x", required="y", basis="b")


def test_not_applicable_is_excluded_from_the_count():
    h = headline([_f(Verdict.COMPLIES), _f(Verdict.NOT_APPLICABLE)])
    assert (h.applicable, h.complying) == (1, 1)
    assert h.full and h.text == "1 of 1 applicable clauses comply — 100 %"


def test_needs_evidence_never_rounds_up_to_full():
    h = headline([_f(Verdict.COMPLIES), _f(Verdict.NEEDS_EVIDENCE)])
    assert not h.full
    assert h.text == "1 of 2 applicable clauses comply"


def test_a_fail_blocks_full_and_an_accepted_deviation_counts_but_is_named():
    h = headline([_f(Verdict.COMPLIES), _f(Verdict.DEVIATION_ACCEPTED), _f(Verdict.FAILS)])
    assert (h.complying, h.by_deviation, h.fails) == (2, 1, 1)
    assert not h.full
    assert h.text == "2 of 3 applicable clauses comply (1 by accepted deviation)"


def test_nothing_applicable_is_not_full():
    assert not headline([_f(Verdict.NOT_APPLICABLE)]).full
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_compliance_verdict.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.compliance'`

- [ ] **Step 3: Implement**

```python
# solit2/compliance/__init__.py
"""SOLIT2 compliance checking for a planned full-scale fire test."""
```

```python
# solit2/compliance/verdict.py
"""What the compliance checker concludes about one clause, and about all of them.

Five verdicts, because "not met" and "not known" are different findings and a
checker that merged them could report a test as compliant nobody had evidenced.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    COMPLIES = "complies"
    FAILS = "fails"
    # Not met, but an authority's acceptance is on record -- only for clauses
    # SOLIT2 lets the authority accept (see Rule.waivable).
    DEVIATION_ACCEPTED = "deviation_accepted"
    # The fact that decides the clause has not been supplied. Never a pass.
    NEEDS_EVIDENCE = "needs_evidence"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Finding:
    rule_id: str
    group: str
    clause: str
    requirement: str
    kind: str
    verdict: Verdict
    found: str
    required: str
    basis: str
    evidence: str = ""
    # For a Needs-evidence finding: the spec fact that would decide it.
    fact: str = ""
    # For an accepted deviation: who accepted it, where, and why.
    deviation: str = ""


@dataclass(frozen=True)
class Headline:
    applicable: int
    complying: int
    by_deviation: int
    fails: int
    needs_evidence: int

    @property
    def full(self) -> bool:
        """100 % only with nothing failing and nothing unevidenced."""
        return self.applicable > 0 and self.fails == 0 and self.needs_evidence == 0

    @property
    def text(self) -> str:
        out = f"{self.complying} of {self.applicable} applicable clauses comply"
        if self.by_deviation:
            out += f" ({self.by_deviation} by accepted deviation)"
        if self.full:
            out += " — 100 %"
        return out


def headline(findings: Iterable[Finding]) -> Headline:
    verdicts = [f.verdict for f in findings]
    by_deviation = verdicts.count(Verdict.DEVIATION_ACCEPTED)
    return Headline(
        applicable=sum(v is not Verdict.NOT_APPLICABLE for v in verdicts),
        complying=verdicts.count(Verdict.COMPLIES) + by_deviation,
        by_deviation=by_deviation,
        fails=verdicts.count(Verdict.FAILS),
        needs_evidence=verdicts.count(Verdict.NEEDS_EVIDENCE),
    )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_compliance_verdict.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add solit2/compliance/__init__.py solit2/compliance/verdict.py tests/test_compliance_verdict.py
git commit -m "feat(compliance): verdicts, findings and a headline that never rounds up"
```

---

### Task 2: The evidence-backed spec file

**Files:**
- Create: `solit2/compliance/spec.py`
- Create: `tests/fixtures/compliance/minimal.spec.json`
- Test: `tests/test_compliance_spec.py`

**Interfaces:**
- Consumes: `solit2.schema.design.Design` (`Design.load(path)`).
- Produces: `Evidence(document, locator)` with `.cite() -> str`; `Fact[T](value, evidence)`; `PlannedTest(fire_class, covered, velocity_ms)`; `Facts` (fields below, all optional); `Deviation(accepted_by, document, locator, reason)` with `.cite() -> str`; `ComplianceSpec(spec_version, name, test_designs, installation_design, project_rules, facts, deviations)`; `LoadedSpec(path, spec, tests: dict[str, Design], installation: Design, project_rules_path: Path | None)`; `load_spec(path: str | Path) -> LoadedSpec`.

- [ ] **Step 1: Write the fixture and the failing test**

```json
// tests/fixtures/compliance/minimal.spec.json  (write WITHOUT this comment line)
{
  "spec_version": 1,
  "name": "fixture",
  "test_designs": {"A": "../../../examples/designs/solit2-test-protocol.json"},
  "installation_design": "../../../examples/designs/road-tunnel-twin-bore.json",
  "facts": {
    "pallet_moisture_pct": {"value": 14.0,
                            "evidence": {"document": "fixture certificate", "locator": "p. 1"}}
  }
}
```

```python
# tests/test_compliance_spec.py
import json

import pytest
from pydantic import ValidationError

from solit2.compliance.spec import ComplianceSpec, load_spec

FIXTURE = "tests/fixtures/compliance/minimal.spec.json"


def test_the_spec_loads_its_designs_relative_to_itself():
    loaded = load_spec(FIXTURE)
    assert set(loaded.tests) == {"A"}
    assert loaded.tests["A"].fire.fire_class == "A"
    assert loaded.installation.tunnel.section == "bored"
    assert loaded.spec.facts.pallet_moisture_pct.value == 14.0
    assert loaded.spec.facts.pallet_moisture_pct.evidence.cite() == "fixture certificate, p. 1"
    assert loaded.project_rules_path is None


def _raw() -> dict:
    return json.loads(open(FIXTURE).read())


def test_a_misspelt_fact_is_refused_not_ignored():
    raw = _raw()
    raw["facts"]["pallet_moisture"] = raw["facts"].pop("pallet_moisture_pct")
    with pytest.raises(ValidationError, match="pallet_moisture"):
        ComplianceSpec.model_validate(raw)


def test_a_fact_without_evidence_is_refused():
    raw = _raw()
    raw["facts"]["pallet_moisture_pct"] = {"value": 14.0}
    with pytest.raises(ValidationError, match="evidence"):
        ComplianceSpec.model_validate(raw)


def test_a_class_a_test_design_is_required():
    raw = _raw()
    raw["test_designs"] = {"B": raw["test_designs"]["A"]}
    with pytest.raises(ValidationError, match="Class A"):
        ComplianceSpec.model_validate(raw)


def test_a_missing_design_file_names_the_field(tmp_path):
    raw = _raw()
    raw["installation_design"] = "nowhere.json"
    path = tmp_path / "s.spec.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(FileNotFoundError, match="installation_design"):
        load_spec(path)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_compliance_spec.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.compliance.spec'`

- [ ] **Step 3: Implement**

```python
# solit2/compliance/spec.py
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
    tests = {cls: Design.load(_resolve(base, rel, f"test_designs.{cls}"))
             for cls, rel in spec.test_designs.items()}
    installation = Design.load(_resolve(base, spec.installation_design, "installation_design"))
    rules = (_resolve(base, spec.project_rules, "project_rules")
             if spec.project_rules else None)
    return LoadedSpec(spec_path, spec, tests, installation, rules)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_compliance_spec.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add solit2/compliance/spec.py tests/fixtures/compliance/minimal.spec.json tests/test_compliance_spec.py
git commit -m "feat(compliance): a strict spec file where every fact carries its evidence"
```

---

### Task 3: Context, the rule base, and the design rules on the test

**Files:**
- Create: `solit2/compliance/context.py`, `solit2/compliance/rules/__init__.py`, `solit2/compliance/rules/base.py`, `solit2/compliance/rules/test_rules.py`
- Test: `tests/test_compliance_test_rules.py`

**Interfaces:**
- Consumes: `Facts` (Task 2), `Verdict`, `Finding` (Task 1), `solit2.schema.result.Result`, `solit2.engines.reduced.geometry.section_geometry`, `solit2.engines.reduced.criteria.FLAME_CONTACT_FLUX_KWM2`, `IGNITION_EXPOSURE_S`, `solit2.reports.guidance`.
- Produces:
  - `Context(tests, test_results, installation, installation_result, facts, protocol_text)` (frozen); `hrr_at_mw(result, t_s) -> float`; `time_to_full_operation_s(result) -> float`; `standoff_m(design) -> float`; `target_ignited(result) -> bool`; `tested_velocities_ms(ctx, fire_class) -> tuple[list[float], str]` (values, basis).
  - `Outcome(verdict, found, required, basis, evidence="", fact="")`; `Rule(id, group, clause, requirement, kind, check, waivable=False, constants=())`; `judge(ok, found, required, basis, evidence="") -> Outcome`; `needs(fact, required, why="not supplied") -> Outcome`; `not_applicable(why) -> Outcome`; `evaluate(rule, ctx, deviations) -> Finding`.
  - `test_rules.RULES: tuple[Rule, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compliance_test_rules.py
from dataclasses import replace

import pytest

from solit2.compliance.context import Context
from solit2.compliance.rules.base import evaluate
from solit2.compliance.rules.test_rules import RULES
from solit2.compliance.spec import Deviation, Facts
from solit2.compliance.verdict import Verdict
from solit2.engines.reduced import envelope
from solit2.schema.design import Design

A = "examples/designs/solit2-test-protocol.json"
B = "examples/designs/solit2-test-protocol-class-b.json"
INSTALL = "examples/designs/road-tunnel-twin-bore.json"
BY_ID = {r.id: r for r in RULES}


@pytest.fixture(scope="module")
def ctx() -> Context:
    tests = {"A": Design.load(A), "B": Design.load(B)}
    inst = Design.load(INSTALL)
    return Context(tests=tests, test_results={k: envelope.run(d) for k, d in tests.items()},
                   installation=inst, installation_result=envelope.run(inst),
                   facts=Facts(), protocol_text={})


def _with_tunnel(ctx: Context, **tunnel) -> Context:
    a = ctx.tests["A"]
    moved = a.model_copy(update={"tunnel": a.tunnel.model_copy(update=tunnel)})
    return replace(ctx, tests={**ctx.tests, "A": moved})


def _verdict(rule_id: str, ctx: Context, deviations=None) -> Verdict:
    return evaluate(BY_ID[rule_id], ctx, deviations or {}).verdict


def test_rule_ids_are_unique_and_every_rule_cites_a_clause():
    assert len(BY_ID) == len(RULES)
    assert all(r.clause.startswith(("Annex 7", "Main", "Annex 3")) for r in RULES)


def test_the_test_tunnel_area_boundary_is_the_annex_7_figure(ctx):
    assert _verdict("annex7.3_6.free_area", _with_tunnel(ctx, area_m2=40.0)) is Verdict.COMPLIES
    assert _verdict("annex7.3_6.free_area", _with_tunnel(ctx, area_m2=39.9)) is Verdict.FAILS


def test_the_stricter_main_document_height_governs(ctx):
    at_4_8 = _with_tunnel(ctx, height_m=4.8)
    assert _verdict("annex7.3_6.height", at_4_8) is Verdict.COMPLIES
    assert _verdict("main.3_6_2.height", at_4_8) is Verdict.FAILS


def test_an_accepted_deviation_applies_only_where_solit2_allows_it(ctx):
    small = _with_tunnel(ctx, area_m2=39.0)
    dev = {"annex7.3_6.free_area": Deviation(accepted_by="authority", document="letter",
                                             locator="§1", reason="reason")}
    finding = evaluate(BY_ID["annex7.3_6.free_area"], small, dev)
    assert finding.verdict is Verdict.DEVIATION_ACCEPTED
    assert "accepted by authority" in finding.deviation
    assert not BY_ID["main.3_6_2.height"].waivable


def test_class_b_rules_need_evidence_when_no_class_b_design_is_given(ctx):
    only_a = replace(ctx, tests={"A": ctx.tests["A"]},
                     test_results={"A": ctx.test_results["A"]})
    assert _verdict("annex7.5_3_1.hrr", only_a) is Verdict.NEEDS_EVIDENCE
    assert _verdict("annex7.5_3_1.hrr", ctx) is Verdict.COMPLIES


def test_the_example_class_a_mock_up_meets_its_geometry_clauses(ctx):
    for rule_id in ("annex7.5_2_1.potential", "annex7.5_2_2.pallets", "annex7.5_2_2.energy",
                    "annex7.5_2_2.height", "annex7.5_2_2.fuel_height", "annex7.5_2_2.width",
                    "annex7.5_2_2.length", "annex7.5_2_3.wall_clearance", "annex7.5_2_6.target",
                    "annex7.5_4.covered", "annex7.5_2_8.area"):
        assert _verdict(rule_id, ctx) is Verdict.COMPLIES, rule_id


def test_discharge_shorter_than_thirty_minutes_after_activation_fails(ctx):
    a = ctx.tests["A"]
    short = a.model_copy(update={"zones": a.zones.model_copy(update={"duration_min": 20.0})})
    shorter = replace(ctx, tests={**ctx.tests, "A": short},
                      test_results={**ctx.test_results, "A": envelope.run(short)})
    assert _verdict("annex7.5_2_8.discharge", shorter) is Verdict.FAILS
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_compliance_test_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.compliance.context'`

- [ ] **Step 3: Implement the context**

```python
# solit2/compliance/context.py
"""Everything a rule may read, and the few quantities several rules share."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from solit2.compliance.spec import Facts
from solit2.engines.reduced.criteria import FLAME_CONTACT_FLUX_KWM2, IGNITION_EXPOSURE_S
from solit2.schema.design import Design
from solit2.schema.result import Result


@dataclass(frozen=True)
class Context:
    tests: Mapping[str, Design]            # by fire class, "A" always present
    test_results: Mapping[str, Result]
    installation: Design
    installation_result: Result
    facts: Facts
    protocol_text: Mapping[str, str]       # the rendered Annex 7 §8.2 protocol, by class


def hrr_at_mw(result: Result, t_s: float) -> float:
    """HRR at `t_s`, linearly interpolated on the result's sampled series."""
    ts, hrr = result.timeseries["t_s"], result.timeseries["hrr_mw"]
    if t_s <= ts[0]:
        return hrr[0]
    for (t0, h0), (t1, h1) in zip(zip(ts, hrr), zip(ts[1:], hrr[1:])):
        if t0 <= t_s <= t1:
            return h0 + (h1 - h0) * (t_s - t0) / (t1 - t0)
    return hrr[-1]


def time_to_full_operation_s(result: Result) -> float:
    """Detection to full pressure: Annex 3 §3.3's 'time to full operation'."""
    return result.events["t_full_pressure_s"] - result.events["t_detect_s"]


def standoff_m(design: Design) -> float:
    """Nozzle to top of the fire load, the distance main document §3.6.2 bounds."""
    return design.nozzles.mounting.height_above_carriageway_m - design.fire.footprint.top_height_m


def target_ignited(result: Result) -> bool:
    peaks = result.peaks
    return bool(peaks["target_peak_flux_kwm2"] >= FLAME_CONTACT_FLUX_KWM2
                or peaks["target_max_exposure_s"] >= IGNITION_EXPOSURE_S)


def tested_velocities_ms(ctx: Context, fire_class: str) -> tuple[list[float], str]:
    """The velocities the test programme runs this class at, and where that came from."""
    planned = ctx.facts.planned_tests
    if planned is not None:
        values = [t.velocity_ms for t in planned.value if t.fire_class == fire_class]
        if values:
            return values, f"planned tests ({planned.evidence.cite()})"
    design = ctx.tests.get(fire_class)
    if design is None:
        return [], "no test design of this class"
    return list(design.ventilation.velocity_range_ms), "the test design's velocity range"
```

- [ ] **Step 4: Implement the rule base**

```python
# solit2/compliance/rules/base.py
"""A rule is one clause: where it comes from, what it asks, and how to judge it."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from solit2.compliance.context import Context
from solit2.compliance.spec import Deviation
from solit2.compliance.verdict import Finding, Verdict


@dataclass(frozen=True)
class Outcome:
    verdict: Verdict
    found: str
    required: str
    basis: str
    evidence: str = ""
    fact: str = ""


@dataclass(frozen=True)
class Rule:
    id: str
    group: str
    clause: str
    requirement: str
    kind: Literal["design", "lab", "transfer", "project"]
    check: Callable[[Context], Outcome]
    # SOLIT2 lets the authority accept a shortfall on this clause (Annex 7 §3.6
    # does for the test tunnel; the main document states no such allowance).
    waivable: bool = False
    # Names of the guidance.py constants this rule reads, so a test can prove
    # every requirement in guidance.py is checked by something.
    constants: tuple[str, ...] = ()


def judge(ok: bool, found: str, required: str, basis: str, evidence: str = "") -> Outcome:
    return Outcome(Verdict.COMPLIES if ok else Verdict.FAILS, found, required, basis, evidence)


def needs(fact: str, required: str, why: str = "not supplied") -> Outcome:
    return Outcome(Verdict.NEEDS_EVIDENCE, why, required, "spec fact", fact=fact)


def not_applicable(why: str) -> Outcome:
    return Outcome(Verdict.NOT_APPLICABLE, why, "—", "—")


def evaluate(rule: Rule, ctx: Context, deviations: Mapping[str, Deviation]) -> Finding:
    try:
        out = rule.check(ctx)
    except Exception as exc:  # a crashing rule must stop the check, never pass quietly
        raise RuntimeError(f"rule {rule.id} ({rule.clause}) could not be evaluated: {exc}") from exc
    verdict, note = out.verdict, ""
    dev = deviations.get(rule.id)
    if dev is not None and verdict is Verdict.FAILS:
        verdict, note = Verdict.DEVIATION_ACCEPTED, dev.cite()
    return Finding(rule_id=rule.id, group=rule.group, clause=rule.clause,
                   requirement=rule.requirement, kind=rule.kind, verdict=verdict,
                   found=out.found, required=out.required, basis=out.basis,
                   evidence=out.evidence, fact=out.fact, deviation=note)
```

- [ ] **Step 5: Implement the design rules on the test**

```python
# solit2/compliance/rules/test_rules.py
"""SOLIT2 clauses judged from the test designs and their Tier 1 runs."""
from __future__ import annotations

from collections.abc import Callable

from solit2.compliance.context import Context, target_ignited
from solit2.compliance.rules.base import Outcome, Rule, judge, needs
from solit2.engines.reduced.geometry import section_geometry
from solit2.reports import guidance as g
from solit2.reports.guidance import CONTENT_MARKERS
from solit2.schema.design import Design

TUNNEL = "Test tunnel"
CLASS_A = "Class A fire load"
CLASS_B = "Class B fire load"
ACTIVATION = "Activation"
SYSTEM = "System"
PROTOCOL = "Protocol"
ACCEPTANCE = "Acceptance"


def _every_test(value: Callable[[Design], float], ok: Callable[[float], bool],
                required: str, basis: str) -> Callable[[Context], Outcome]:
    """Judge one quantity on every test design; all must pass."""
    def check(ctx: Context) -> Outcome:
        values = {cls: value(d) for cls, d in sorted(ctx.tests.items())}
        found = "; ".join(f"{cls}: {v:g}" for cls, v in values.items())
        return judge(all(ok(v) for v in values.values()), found, required, basis)
    return check


def _on_class(fire_class: str, value: Callable[[Design], float], ok: Callable[[float], bool],
              required: str, basis: str) -> Callable[[Context], Outcome]:
    """Judge one quantity on the test design of one fire class."""
    def check(ctx: Context) -> Outcome:
        design = ctx.tests.get(fire_class)
        if design is None:
            return needs(f"test_designs.{fire_class}", required,
                         f"no Class {fire_class} test design in the spec")
        return judge(ok(value(design)), f"{value(design):g}", required, basis)
    return check


def _area(d: Design) -> float:
    return section_geometry(d).free_area_m2


def _height(d: Design) -> float:
    return section_geometry(d).crown_height_m


def _width(d: Design) -> float:
    return section_geometry(d).road_width_m


def _energy_gj(d: Design) -> float:
    return (d.fire.pallets or 0) * d.fire.energy_mj_per_pallet / 1000.0


def _wall_clearance(d: Design) -> float:
    return d.fire.lane_centre_offset_from_wall_m - d.fire.footprint.width_m / 2.0


def _pool_area(d: Design) -> float:
    pools = d.fire.pools
    return pools.length_m * pools.width_m if pools else 0.0


def _activation(event: str) -> Callable[[Context], Outcome]:
    """Annex 7 §5.2.8 option A timing, judged on every test's Tier 1 timetable."""
    def check(ctx: Context) -> Outcome:
        rows = []
        ok = True
        for cls, res in sorted(ctx.test_results.items()):
            t_act, t_det = res.events["t_activate_s"], res.events["t_detect_s"]
            if event == "after_ignition":
                ok &= t_act >= g.ACTIVATION_MIN_AFTER_IGNITION_S
                rows.append(f"{cls}: {t_act:.0f} s after ignition")
            elif event == "after_detection":
                ok &= t_act > t_det
                rows.append(f"{cls}: detection {t_det:.0f} s, activation {t_act:.0f} s")
            else:  # discharge
                design = ctx.tests[cls]
                discharge_min = (design.zones.duration_min * 60.0 - t_act) / 60.0
                ok &= discharge_min >= g.MIN_DISCHARGE_MIN
                rows.append(f"{cls}: {discharge_min:.1f} min after activation")
        required = {"after_ignition": f">= {g.ACTIVATION_MIN_AFTER_IGNITION_S:g} s after ignition",
                    "after_detection": "after detection",
                    "discharge": f">= {g.MIN_DISCHARGE_MIN:g} min after activation"}[event]
        return judge(ok, "; ".join(rows), required, "Tier 1 activation timetable")
    return check


def _pressure_spread(ctx: Context) -> Outcome:
    rows, ok = [], True
    for cls, res in sorted(ctx.test_results.items()):
        spread = 100.0 * res.hydraulics["zone_loss_bar"] / ctx.tests[cls].nozzles.pressure_bar
        ok &= spread <= g.NOZZLE_SPREAD_MAX_PCT
        rows.append(f"{cls}: {spread:.1f} %")
    return judge(ok, "; ".join(rows), f"<= {g.NOZZLE_SPREAD_MAX_PCT:g} % first to last nozzle",
                 "Tier 1 hydraulics: zone pipe loss against the design pressure")


def _protocol(ctx: Context) -> Outcome:
    missing = sorted({key for text in ctx.protocol_text.values()
                      for key, marker in CONTENT_MARKERS.items() if marker not in text})
    return judge(not missing and bool(ctx.protocol_text),
                 "all present" if not missing else "missing: " + ", ".join(missing),
                 f"all {len(g.PROTOCOL_CONTENTS)} Annex 7 §8.2 contents",
                 "the generated fire test protocol")


def _target(ctx: Context) -> Outcome:
    ignited = {cls: target_ignited(res) for cls, res in sorted(ctx.test_results.items())}
    found = "; ".join(f"{cls}: {'ignited' if v else 'not ignited'}" for cls, v in ignited.items())
    return judge(not any(ignited.values()), found, "target not ignited",
                 "Tier 1 prediction (replaced by the measurement after the test)")


RULES: tuple[Rule, ...] = (
    # --- Test tunnel: Annex 7 §3.6 and main document §3.6.2, both bind (STRICTER_OF).
    Rule("annex7.3_6.free_area", TUNNEL, "Annex 7 §3.6",
         "Test tunnel free cross-section of at least the Annex 7 minimum.", "design",
         _every_test(_area, lambda v: v >= g.MIN_TEST_TUNNEL["free area (m2)"],
                     f">= {g.MIN_TEST_TUNNEL['free area (m2)']:g} m²", "test design geometry"),
         waivable=True, constants=("MIN_TEST_TUNNEL",)),
    Rule("annex7.3_6.height", TUNNEL, "Annex 7 §3.6",
         "Test tunnel height of at least the Annex 7 minimum.", "design",
         _every_test(_height, lambda v: v >= g.MIN_TEST_TUNNEL["height (m)"],
                     f">= {g.MIN_TEST_TUNNEL['height (m)']:g} m", "test design geometry"),
         waivable=True, constants=("MIN_TEST_TUNNEL",)),
    Rule("annex7.3_6.length", TUNNEL, "Annex 7 §3.6",
         "Test tunnel length of at least the Annex 7 minimum.", "design",
         _every_test(lambda d: d.tunnel.length_m, lambda v: v >= g.MIN_TEST_TUNNEL["length (m)"],
                     f">= {g.MIN_TEST_TUNNEL['length (m)']:g} m", "test design tunnel"),
         waivable=True, constants=("MIN_TEST_TUNNEL",)),
    Rule("main.3_6_2.height", TUNNEL, "Main document §3.6.2",
         "Test tunnel height of at least the main document's minimum, which is the stricter.",
         "design",
         _every_test(_height, lambda v: v >= g.MAIN_MIN_TEST_TUNNEL["height (m)"],
                     f">= {g.MAIN_MIN_TEST_TUNNEL['height (m)']:g} m", "test design geometry"),
         constants=("MAIN_MIN_TEST_TUNNEL", "STRICTER_OF")),
    Rule("main.3_6_2.width", TUNNEL, "Main document §3.6.2",
         "Test tunnel width of at least the main document's minimum.", "design",
         _every_test(_width, lambda v: v >= g.MAIN_MIN_TEST_TUNNEL["width (m)"],
                     f">= {g.MAIN_MIN_TEST_TUNNEL['width (m)']:g} m", "test design geometry"),
         constants=("MAIN_MIN_TEST_TUNNEL",)),
    Rule("main.3_6_2.length", TUNNEL, "Main document §3.6.2",
         "Test tunnel length of at least the main document's minimum.", "design",
         _every_test(lambda d: d.tunnel.length_m,
                     lambda v: v >= g.MAIN_MIN_TEST_TUNNEL["length (m)"],
                     f">= {g.MAIN_MIN_TEST_TUNNEL['length (m)']:g} m", "test design tunnel"),
         constants=("MAIN_MIN_TEST_TUNNEL", "STRICTER_OF")),
    # --- Class A fire load, Annex 7 §5.2.
    Rule("annex7.5_2_1.potential", CLASS_A, "Annex 7 §5.2.1",
         "Class A design fire of at least the minimum unsuppressed potential.", "design",
         _on_class("A", lambda d: d.fire.design_hrr_mw,
                   lambda v: v >= g.CLASS_A_MIN_UNSUPPRESSED_MW,
                   f">= {g.CLASS_A_MIN_UNSUPPRESSED_MW:g} MW", "test design fire"),
         constants=("CLASS_A_MIN_UNSUPPRESSED_MW",)),
    Rule("annex7.5_2_2.pallets", CLASS_A, "Annex 7 §5.2.2",
         "At least the minimum number of pallets in the mock-up.", "design",
         _on_class("A", lambda d: float(d.fire.pallets or 0),
                   lambda v: v >= g.CLASS_A_MIN_PALLETS,
                   f">= {g.CLASS_A_MIN_PALLETS}", "test design fire"),
         constants=("CLASS_A_MIN_PALLETS",)),
    Rule("annex7.5_2_2.energy", CLASS_A, "Annex 7 §5.2.2",
         "Mock-up fuel energy within the stated range.", "design",
         _on_class("A", _energy_gj,
                   lambda v: g.CLASS_A_ENERGY_GJ[0] <= v <= g.CLASS_A_ENERGY_GJ[1],
                   f"{g.CLASS_A_ENERGY_GJ[0]:g}–{g.CLASS_A_ENERGY_GJ[1]:g} GJ",
                   "pallets × energy per pallet"),
         constants=("CLASS_A_ENERGY_GJ",)),
    Rule("annex7.5_2_2.height", CLASS_A, "Annex 7 §5.2.2", "Mock-up height of at least the minimum.",
         "design",
         _on_class("A", lambda d: d.fire.footprint.top_height_m,
                   lambda v: v >= g.MOCKUP_MIN_M["height"],
                   f">= {g.MOCKUP_MIN_M['height']:g} m", "test design footprint"),
         constants=("MOCKUP_MIN_M",)),
    Rule("annex7.5_2_2.fuel_height", CLASS_A, "Annex 7 §5.2.2",
         "Fuel part of the mock-up of at least the minimum height.", "design",
         _on_class("A", lambda d: d.fire.footprint.top_height_m - d.fire.footprint.base_height_m,
                   lambda v: v >= g.MOCKUP_MIN_M["fuel height"],
                   f">= {g.MOCKUP_MIN_M['fuel height']:g} m", "test design footprint"),
         constants=("MOCKUP_MIN_M",)),
    Rule("annex7.5_2_2.width", CLASS_A, "Annex 7 §5.2.2", "Mock-up width of at least the minimum.",
         "design",
         _on_class("A", lambda d: d.fire.footprint.width_m,
                   lambda v: v >= g.MOCKUP_MIN_M["width"],
                   f">= {g.MOCKUP_MIN_M['width']:g} m", "test design footprint"),
         constants=("MOCKUP_MIN_M",)),
    Rule("annex7.5_2_2.length", CLASS_A, "Annex 7 §5.2.2", "Mock-up length of at least the minimum.",
         "design",
         _on_class("A", lambda d: d.fire.footprint.length_m,
                   lambda v: v >= g.MOCKUP_MIN_M["length"],
                   f">= {g.MOCKUP_MIN_M['length']:g} m", "test design footprint"),
         constants=("MOCKUP_MIN_M",)),
    Rule("annex7.5_2_3.wall_clearance", CLASS_A, "Annex 7 §5.2.3",
         "Mock-up placed eccentrically, no further than the maximum from the side wall.", "design",
         _on_class("A", _wall_clearance, lambda v: 0.0 <= v <= g.MAX_WALL_CLEARANCE_M,
                   f"0–{g.MAX_WALL_CLEARANCE_M:g} m", "lane offset minus half the mock-up width"),
         constants=("MAX_WALL_CLEARANCE_M",)),
    Rule("annex7.5_2_6.target", CLASS_A, "Annex 7 §5.2.6",
         "Fire target the stated distance downstream of the mock-up.", "design",
         _on_class("A", lambda d: d.fire.target_distance_m,
                   lambda v: abs(v - g.TARGET_STANDOFF_M) < 1e-9,
                   f"{g.TARGET_STANDOFF_M:g} m", "test design fire"),
         constants=("TARGET_STANDOFF_M",)),
    Rule("annex7.5_4.covered", CLASS_A, "Annex 7 §5.4 Table 4",
         "The required Class A tests use the tarpaulin-covered mock-up.", "design",
         _on_class("A", lambda d: float(d.fire.covered), lambda v: v == 1.0,
                   "covered (1)", "test design fire"),
         constants=("MINIMUM_TESTS",)),
    # --- Class B fire load, Annex 7 §5.3.
    Rule("annex7.5_3_1.hrr", CLASS_B, "Annex 7 §5.3.1", "Class B pool fire of at least the minimum.",
         "design",
         _on_class("B", lambda d: d.fire.design_hrr_mw, lambda v: v >= g.CLASS_B_MIN_MW,
                   f">= {g.CLASS_B_MIN_MW:g} MW", "test design fire"),
         constants=("CLASS_B_MIN_MW",)),
    Rule("annex7.5_3_2.width", CLASS_B, "Annex 7 §5.3.2", "Pool mock-up of at least the minimum width.",
         "design",
         _on_class("B", lambda d: d.fire.footprint.width_m,
                   lambda v: v >= g.CLASS_B_POOL_MIN_M["width"],
                   f">= {g.CLASS_B_POOL_MIN_M['width']:g} m", "test design footprint"),
         constants=("CLASS_B_POOL_MIN_M",)),
    Rule("annex7.5_3_2.length", CLASS_B, "Annex 7 §5.3.2",
         "Pool mock-up of at least the minimum length.", "design",
         _on_class("B", lambda d: d.fire.footprint.length_m,
                   lambda v: v >= g.CLASS_B_POOL_MIN_M["length"],
                   f">= {g.CLASS_B_POOL_MIN_M['length']:g} m", "test design footprint"),
         constants=("CLASS_B_POOL_MIN_M",)),
    Rule("annex7.5_3_2.height", CLASS_B, "Annex 7 §5.3.2",
         "Pool no higher than the maximum above the road.", "design",
         _on_class("B", lambda d: d.fire.footprint.top_height_m,
                   lambda v: v <= g.CLASS_B_POOL_MIN_M["height above road"],
                   f"<= {g.CLASS_B_POOL_MIN_M['height above road']:g} m", "test design footprint"),
         constants=("CLASS_B_POOL_MIN_M",)),
    Rule("annex7.5_3_2.pool_area", CLASS_B, "Annex 7 §5.3.2",
         "Each pool at least the minimum area.", "design",
         _on_class("B", _pool_area, lambda v: v >= g.CLASS_B_SINGLE_POOL_MIN_M2,
                   f">= {g.CLASS_B_SINGLE_POOL_MIN_M2:g} m²", "test design pools"),
         constants=("CLASS_B_SINGLE_POOL_MIN_M2",)),
    # --- Activation, Annex 7 §5.2.8 option A.
    Rule("annex7.5_2_8.after_ignition", ACTIVATION, "Annex 7 §5.2.8",
         "Option A: the system is activated no earlier than the minimum after ignition.",
         "design", _activation("after_ignition"), constants=("ACTIVATION_MIN_AFTER_IGNITION_S",)),
    Rule("annex7.5_2_8.after_detection", ACTIVATION, "Annex 7 §5.2.8",
         "Activation is delayed relative to detection.", "design", _activation("after_detection")),
    Rule("annex7.5_2_8.discharge", ACTIVATION, "Annex 7 §5.2.8",
         "The system discharges for at least the minimum after activation.", "design",
         _activation("discharge"), constants=("MIN_DISCHARGE_MIN",)),
    Rule("annex7.5_2_8.area", ACTIVATION, "Annex 7 §5.2.8",
         "The activated length is at least the stated multiple of the mock-up length.", "design",
         _every_test(lambda d: d.active_length_m / d.fire.footprint.length_m,
                     lambda v: v >= g.ACTIVATION_AREA_MIN_MULTIPLE,
                     f">= {g.ACTIVATION_AREA_MIN_MULTIPLE:g} × mock-up length",
                     "active length over mock-up length"),
         constants=("ACTIVATION_AREA_MIN_MULTIPLE",)),
    # --- System, protocol and acceptance.
    Rule("annex7.4.pressure_spread", SYSTEM, "Annex 7 §4",
         "Pressure difference from the first to the last nozzle within the maximum.", "design",
         _pressure_spread, constants=("NOZZLE_SPREAD_MAX_PCT",)),
    Rule("annex7.8_2.contents", PROTOCOL, "Annex 7 §8.2",
         "The fire test protocol covers every minimum content.", "design", _protocol,
         constants=("PROTOCOL_CONTENTS", "CONTENT_MARKERS")),
    Rule("annex7.7_2_1.target", ACCEPTANCE, "Annex 7 §7.2.1",
         "The fire does not spread to the target.", "design", _target),
)
```

```python
# solit2/compliance/rules/__init__.py
"""Every SOLIT2 rule the checker runs, in report order."""
from solit2.compliance.rules.test_rules import RULES as _TEST

REGISTRY = _TEST
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_compliance_test_rules.py -q`
Expected: PASS (7 tests). If `annex7.5_2_8.discharge` on the example unexpectedly fails in the fixture, do not change the rule: check `duration_min` in `examples/designs/solit2-test-protocol.json` (35 min; activation well under 5 min, so 30+ min remain).

- [ ] **Step 7: Commit**

```bash
git add solit2/compliance/context.py solit2/compliance/rules tests/test_compliance_test_rules.py
git commit -m "feat(compliance): the SOLIT2 design clauses judged on the test designs"
```

---

### Task 4: Evidence-gated laboratory rules

**Files:**
- Create: `solit2/compliance/rules/lab_rules.py`
- Modify: `solit2/compliance/rules/__init__.py`
- Test: `tests/test_compliance_lab_rules.py`

**Interfaces:**
- Consumes: `Context`, `Rule`, `judge`, `needs`, `Outcome` (Task 3); `Facts`, `Fact`, `Evidence`, `PlannedTest` (Task 2).
- Produces: `lab_rules.RULES: tuple[Rule, ...]`; `REGISTRY = test RULES + lab RULES`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compliance_lab_rules.py
from dataclasses import replace

import pytest

from solit2.compliance.context import Context
from solit2.compliance.rules.base import evaluate
from solit2.compliance.rules.lab_rules import RULES
from solit2.compliance.spec import Evidence, Fact, Facts, PlannedTest
from solit2.compliance.verdict import Verdict
from solit2.engines.reduced import envelope
from solit2.reports import guidance as g
from solit2.schema.design import Design

EV = Evidence(document="lab report", locator="§2")
BY_ID = {r.id: r for r in RULES}


@pytest.fixture(scope="module")
def ctx() -> Context:
    a = Design.load("examples/designs/solit2-test-protocol.json")
    res = envelope.run(a)
    return Context(tests={"A": a}, test_results={"A": res}, installation=a,
                   installation_result=res, facts=Facts(), protocol_text={})


def _facts(ctx: Context, **facts) -> Context:
    return replace(ctx, facts=Facts(**{k: Fact(value=v, evidence=EV) for k, v in facts.items()}))


def _v(rule_id: str, ctx: Context) -> Verdict:
    return evaluate(BY_ID[rule_id], ctx, {}).verdict


def test_a_lab_clause_with_no_fact_needs_evidence_and_names_the_fact(ctx):
    finding = evaluate(BY_ID["annex7.5_2_4.moisture"], ctx, {})
    assert finding.verdict is Verdict.NEEDS_EVIDENCE
    assert finding.fact == "pallet_moisture_pct"


def test_moisture_boundary(ctx):
    assert _v("annex7.5_2_4.moisture", _facts(ctx, pallet_moisture_pct=18.0)) is Verdict.COMPLIES
    assert _v("annex7.5_2_4.moisture", _facts(ctx, pallet_moisture_pct=18.1)) is Verdict.FAILS


def test_a_complying_fact_carries_its_evidence(ctx):
    finding = evaluate(BY_ID["annex7.5_2_4.moisture"], _facts(ctx, pallet_moisture_pct=14.0), {})
    assert finding.evidence == "lab report, §2"


def test_one_rule_per_instrument_type_and_per_schedule_item():
    assert sum(r.constants == ("INSTRUMENT_SPEC",) for r in RULES) == len(g.INSTRUMENT_SPEC)
    assert (sum(r.constants == ("MAIN_MEASUREMENT_SCHEDULE",) for r in RULES)
            == len(g.MAIN_MEASUREMENT_SCHEDULE))


def test_the_four_required_table_4_tests_must_each_be_planned(ctx):
    planned = [PlannedTest(fire_class="A", covered=True, velocity_ms=1.5),
               PlannedTest(fire_class="A", covered=True, velocity_ms=3.0),
               PlannedTest(fire_class="B", covered=False, velocity_ms=1.5)]
    with_three = _facts(ctx, planned_tests=planned)
    assert _v("annex7.5_4.test_1", with_three) is Verdict.COMPLIES
    assert _v("annex7.5_4.test_4", with_three) is Verdict.FAILS


def test_activation_option_b_cannot_be_judged(ctx):
    assert _v("annex7.5_2_8.option", _facts(ctx, activation_option="A")) is Verdict.COMPLIES
    assert _v("annex7.5_2_8.option", _facts(ctx, activation_option="B")) is Verdict.NEEDS_EVIDENCE


def test_spray_deviation_must_cover_every_listed_velocity(ctx):
    assert _v("main.3_6_2.spray_deviation",
              _facts(ctx, spray_deviation_tested_ms=[1.0, 3.0])) is Verdict.FAILS
    assert _v("main.3_6_2.spray_deviation",
              _facts(ctx, spray_deviation_tested_ms=[1.0, 3.0, 5.0])) is Verdict.COMPLIES
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_compliance_lab_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.compliance.rules.lab_rules'`

- [ ] **Step 3: Implement**

```python
# solit2/compliance/rules/lab_rules.py
"""SOLIT2 clauses only the laboratory can evidence.

Every rule here reads one `Facts` field. No fact, no verdict beyond Needs
evidence: the checker never assumes a laboratory did what the standard asks.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from solit2.compliance.context import Context
from solit2.compliance.rules.base import Outcome, Rule, judge, needs
from solit2.reports import guidance as g

CLASS_A = "Class A fire load"
CLASS_B = "Class B fire load"
VENTILATION = "Ventilation"
ACTIVATION = "Activation"
SYSTEM = "System"
INSTRUMENTS = "Instruments"
PROGRAMME = "Test programme"
NOZZLE = "Nozzle"
ACCEPTANCE = "Acceptance"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _fact(name: str, ok: Callable[[Any], bool], required: str,
          show: Callable[[Any], str] = str) -> Callable[[Context], Outcome]:
    def check(ctx: Context) -> Outcome:
        fact = getattr(ctx.facts, name)
        if fact is None:
            return needs(name, required)
        return judge(ok(fact.value), show(fact.value), required, "spec fact",
                     fact.evidence.cite())
    return check


def _contains(name: str, item: str, required: str) -> Callable[[Context], Outcome]:
    return _fact(name, lambda values: item in values, required, lambda v: ", ".join(map(str, v)))


def _option(ctx: Context) -> Outcome:
    fact = ctx.facts.activation_option
    required = "option A, whose timing Annex 7 states"
    if fact is None:
        return needs("activation_option", required)
    if fact.value == "B":
        return needs("activation_option", required,
                     "option B declared; Annex 7 leaves its content blank, so it cannot be judged")
    return judge(True, "option A", required, "spec fact", fact.evidence.cite())


def _required_test(row: tuple[str, ...]) -> Callable[[Context], Outcome]:
    fire_class = "A" if row[1].startswith("Class A") else "B"
    covered = "with tarpaulin" in row[2]
    velocity = float(row[3].split()[0])
    required = f"{row[1]}, {row[2]}, {row[3]}"

    def check(ctx: Context) -> Outcome:
        fact = ctx.facts.planned_tests
        if fact is None:
            return needs("planned_tests", required)
        found = any(t.fire_class == fire_class and t.velocity_ms == velocity
                    and (fire_class == "B" or t.covered == covered) for t in fact.value)
        return judge(found, "planned" if found else "not in the planned tests", required,
                     "spec fact", fact.evidence.cite())
    return check


def _authority_limits(ctx: Context) -> Outcome:
    required = "every Annex 7 §7 limit set by a cited authority"
    fact = ctx.facts.authority_limits
    if fact is None:
        return needs("authority_limits", required)
    unset = [k for k, v in ctx.installation.ahj.model_dump().items()
             if k not in ("note", "structure_temp_threshold_c") and v is None]
    if unset:
        return needs("authority_limits", required, "limits still unset: " + ", ".join(unset))
    return judge(True, "all set", required, "installation design ahj block", fact.evidence.cite())


def _velocity_station(ctx: Context) -> Outcome:
    required = "; ".join(f"{k}: U{v:g}" for k, v in sorted(g.VELOCITY_STATION_M.items()))
    fact = ctx.facts.velocity_measured_at_m
    if fact is None:
        return needs("velocity_measured_at_m", required)
    ok = all(fact.value.get(cls) == g.VELOCITY_STATION_M[cls] for cls in ctx.tests)
    return judge(ok, "; ".join(f"{k}: U{v:g}" for k, v in sorted(fact.value.items())),
                 required, "spec fact", fact.evidence.cite())


def _lab(rule_id: str, group: str, clause: str, requirement: str,
         check: Callable[[Context], Outcome], *constants: str) -> Rule:
    return Rule(rule_id, group, clause, requirement, "lab", check, constants=constants)


_INSTRUMENT_RULES = tuple(
    _lab(f"annex7.{clause.lstrip('§').replace('.', '_')}.{_slug(name)}", INSTRUMENTS,
         f"Annex 7 {clause}",
         f"{name} measured with the stated range ({rng}) and accuracy ({acc}).",
         _contains("instruments_compliant", name, f"{name}: {rng}, {acc}"), "INSTRUMENT_SPEC")
    for name, _code, _kind, rng, acc, clause in g.INSTRUMENT_SPEC
)

_SCHEDULE_RULES = tuple(
    _lab(f"main.3_6_2.schedule.{_slug(item)}", INSTRUMENTS, "Main document §3.6.2",
         f"Measurement schedule: {item} — {where}.",
         _contains("measurement_schedule", item, where), "MAIN_MEASUREMENT_SCHEDULE")
    for item, where in g.MAIN_MEASUREMENT_SCHEDULE
)

_PROGRAMME_RULES = tuple(
    _lab(f"annex7.5_4.test_{row[0]}", PROGRAMME, "Annex 7 §5.4 Table 4",
         f"Required test {row[0]} is in the programme.", _required_test(row),
         "MINIMUM_TESTS", "TEST_VELOCITIES_MS")
    for row in g.MINIMUM_TESTS if row[4] == "required"
)

RULES: tuple[Rule, ...] = (
    _lab("annex7.5_2_4.pallet_size", CLASS_A, "Annex 7 §5.2.4", "Pallets of the stated size.",
         _fact("pallet_dims_mm", lambda v: tuple(v) == tuple(map(float, g.PALLET_MM)),
               "×".join(map(str, g.PALLET_MM)) + " mm"), "PALLET_MM"),
    _lab("annex7.5_2_4.pallet_mass", CLASS_A, "Annex 7 §5.2.4", "Pallet mass within the stated range.",
         _fact("pallet_mass_kg",
               lambda v: g.PALLET_MASS_KG[0] <= v[0] and v[1] <= g.PALLET_MASS_KG[1],
               f"{g.PALLET_MASS_KG[0]:g}–{g.PALLET_MASS_KG[1]:g} kg"), "PALLET_MASS_KG"),
    _lab("annex7.5_2_4.moisture", CLASS_A, "Annex 7 §5.2.4", "Pallet moisture within the maximum.",
         _fact("pallet_moisture_pct", lambda v: v <= g.MAX_PALLET_MOISTURE_PCT,
               f"<= {g.MAX_PALLET_MOISTURE_PCT:g} %"), "MAX_PALLET_MOISTURE_PCT"),
    _lab("annex7.5_2_2.frames", CLASS_A, "Annex 7 §5.2.2",
         "Steel frames cover no more than the maximum of the fuel faces.",
         _fact("frame_coverage_pct", lambda v: v <= g.FRAME_COVERAGE_MAX_PCT,
               f"<= {g.FRAME_COVERAGE_MAX_PCT:g} %"), "FRAME_COVERAGE_MAX_PCT"),
    _lab("annex7.5_2_2.tarpaulin", CLASS_A, "Annex 7 §5.2.2", "The tarpaulin cover is fitted.",
         _fact("tarpaulin_fitted", lambda v: v is True, "fitted")),
    _lab("annex7.5_2_5.pans", CLASS_A, "Annex 7 §5.2.5", "At least the stated number of ignition pans.",
         _fact("ignition_pans", lambda v: v >= g.IGNITION_PANS, f">= {g.IGNITION_PANS}"),
         "IGNITION_PANS"),
    _lab("annex7.5_2_5.pan_size", CLASS_A, "Annex 7 §5.2.5", "Ignition pans of the stated size.",
         _fact("ignition_pan_mm", lambda v: tuple(v) == tuple(map(float, g.IGNITION_PAN_MM)),
               "×".join(map(str, g.IGNITION_PAN_MM)) + " mm"), "IGNITION_PAN_MM"),
    _lab("annex7.5_2_5.petrol", CLASS_A, "Annex 7 §5.2.5", "The stated volume of petrol in each pan.",
         _fact("ignition_petrol_l", lambda v: v == g.IGNITION_PETROL_L,
               f"{g.IGNITION_PETROL_L:g} L per pan"), "IGNITION_PETROL_L"),
    _lab("annex7.5_3_4.free_burn", CLASS_B, "Annex 7 §5.3.4",
         "Enough fuel to burn unsuppressed for at least the minimum.",
         _fact("class_b_free_burn_min", lambda v: v >= g.CLASS_B_MIN_BURN_MIN,
               f">= {g.CLASS_B_MIN_BURN_MIN:g} min"), "CLASS_B_MIN_BURN_MIN"),
    _lab("annex7.5_3_5.ignition", CLASS_B, "Annex 7 §5.3.5", "All pools ignited within the maximum.",
         _fact("class_b_ignition_s", lambda v: v <= g.CLASS_B_IGNITION_WITHIN_S,
               f"<= {g.CLASS_B_IGNITION_WITHIN_S:g} s"), "CLASS_B_IGNITION_WITHIN_S"),
    _lab("annex7.5_3_7.trigger", CLASS_B, "Annex 7 §5.3.7", "The system triggered within the maximum.",
         _fact("class_b_trigger_s", lambda v: v <= g.CLASS_B_TRIGGER_WITHIN_S,
               f"<= {g.CLASS_B_TRIGGER_WITHIN_S:g} s"), "CLASS_B_TRIGGER_WITHIN_S"),
    _lab("annex7.5_2_7.velocity_station", VENTILATION, "Annex 7 §5.2.7, §5.3.6",
         "Ventilation velocity measured at the stated upstream station.", _velocity_station,
         "VELOCITY_STATION_M"),
    _lab("annex7.5_2_8.option", ACTIVATION, "Annex 7 §5.2.8",
         "The activation option used is declared.", _option),
    _lab("annex7.6_4_7.flow", SYSTEM, "Annex 7 §6.4.7", "Measured flow within the tolerance.",
         _fact("flow_deviation_pct", lambda v: abs(v) <= g.FLOW_TOLERANCE_PCT,
               f"± {g.FLOW_TOLERANCE_PCT:g} %"), "FLOW_TOLERANCE_PCT"),
    _lab("annex7.6_4_6.last_nozzle", SYSTEM, "Annex 7 §6.4.6",
         "Pressure measured at the hydraulically last nozzle.",
         _fact("last_nozzle_pressure_measured", lambda v: v is True, "measured")),
    *_INSTRUMENT_RULES,
    _lab("annex7.table5.layout", INSTRUMENTS, "Annex 7 §6.3 Table 5",
         "Instruments at every Table 5 station.",
         _fact("table5_layout", lambda v: v is True, "every Table 5 station instrumented")),
    _lab("main.3_6_2.sampling", INSTRUMENTS, "Main document §3.6.2",
         "Data measured and collated at least as often as stated.",
         _fact("sampling_interval_s", lambda v: v <= g.MAIN_MAX_SAMPLE_INTERVAL_S,
               f"<= {g.MAIN_MAX_SAMPLE_INTERVAL_S:g} s"), "MAIN_MAX_SAMPLE_INTERVAL_S"),
    *_SCHEDULE_RULES,
    _lab("annex7.6_5.hrr_method", INSTRUMENTS, "Annex 7 §6.5",
         "Heat release rate by oxygen consumption.",
         _fact("hrr_method", lambda v: v.strip().lower() == "oxygen consumption",
               "oxygen consumption")),
    _lab("annex7.6_5.hrr_delay", INSTRUMENTS, "Annex 7 §6.5",
         "Heat release rate measurement delay within the maximum.",
         _fact("hrr_delay_s", lambda v: v <= g.HRR_MAX_DELAY_S, f"<= {g.HRR_MAX_DELAY_S:g} s"),
         "HRR_MAX_DELAY_S"),
    _lab("annex7.6_2.calibration", INSTRUMENTS, "Annex 7 §6.2",
         "Calibration fires of each stated size.",
         _fact("calibration_fires_mw", lambda v: all(mw in v for mw in g.CALIBRATION_POOL_MW),
               " and ".join(f"{mw:g} MW" for mw in g.CALIBRATION_POOL_MW),
               lambda v: ", ".join(f"{mw:g} MW" for mw in v)), "CALIBRATION_POOL_MW"),
    *_PROGRAMME_RULES,
    _lab("main.3_6_2.series", PROGRAMME, "Main document §3.6.2",
         "At least the stated number of test series.",
         _fact("test_series", lambda v: v >= g.MAIN_MIN_TEST_SERIES,
               f">= {g.MAIN_MIN_TEST_SERIES}"), "MAIN_MIN_TEST_SERIES"),
    _lab("main.3_6_2.droplet_distribution", NOZZLE, "Main document §3.6.2",
         "The exact nozzle is tested, with its droplet distribution documented.",
         _fact("droplet_distribution_report", lambda v: bool(v.strip()), "a measured report")),
    _lab("main.3_6_2.spray_deviation", NOZZLE, "Main document §3.6.2",
         "The spray's deviation in the airflow defined at least at the stated velocities.",
         _fact("spray_deviation_tested_ms",
               lambda v: all(ms in v for ms in g.MAIN_SPRAY_DEVIATION_MS),
               ", ".join(f"{ms:g}" for ms in g.MAIN_SPRAY_DEVIATION_MS) + " m/s",
               lambda v: ", ".join(f"{ms:g}" for ms in v) + " m/s"), "MAIN_SPRAY_DEVIATION_MS"),
    _lab("annex7.7_1.authority_limits", ACCEPTANCE, "Annex 7 §7.1",
         "Every acceptance limit other than the target is set by the authority.",
         _authority_limits),
)
```

Modify `solit2/compliance/rules/__init__.py` to:

```python
"""Every SOLIT2 rule the checker runs, in report order."""
from solit2.compliance.rules.lab_rules import RULES as _LAB
from solit2.compliance.rules.test_rules import RULES as _TEST

REGISTRY = _TEST + _LAB
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_compliance_lab_rules.py tests/test_compliance_test_rules.py -q`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add solit2/compliance/rules tests/test_compliance_lab_rules.py
git commit -m "feat(compliance): laboratory clauses that only evidence can close"
```

---

### Task 5: Transfer rules — the installation against the test

**Files:**
- Create: `solit2/compliance/rules/transfer_rules.py`
- Modify: `solit2/compliance/rules/__init__.py`
- Test: `tests/test_compliance_transfer_rules.py`

**Interfaces:**
- Consumes: `Context`, `hrr_at_mw`, `time_to_full_operation_s`, `standoff_m`, `tested_velocities_ms` (Task 3); `Rule`, `judge`, `needs`.
- Produces: `transfer_rules.RULES`; `REGISTRY = test + lab + transfer`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compliance_transfer_rules.py
from dataclasses import replace

import pytest

from solit2.compliance.context import Context
from solit2.compliance.rules.base import evaluate
from solit2.compliance.rules.transfer_rules import RULES
from solit2.compliance.spec import Facts
from solit2.compliance.verdict import Verdict
from solit2.engines.reduced import envelope
from solit2.schema.design import Design

BY_ID = {r.id: r for r in RULES}


def _ctx(test: Design, installation: Design) -> Context:
    return Context(tests={"A": test}, test_results={"A": envelope.run(test)},
                   installation=installation, installation_result=envelope.run(installation),
                   facts=Facts(), protocol_text={})


@pytest.fixture(scope="module")
def same() -> Context:
    a = Design.load("examples/designs/solit2-test-protocol.json")
    return _ctx(a, a)


def _v(rule_id: str, ctx: Context) -> Verdict:
    return evaluate(BY_ID[rule_id], ctx, {}).verdict


def test_an_installation_identical_to_its_test_transfers(same):
    for rule_id in BY_ID:
        assert _v(rule_id, same) is Verdict.COMPLIES, rule_id


def test_a_faster_installation_velocity_than_tested_fails(same):
    inst = same.installation
    fast = inst.model_copy(update={"ventilation": inst.ventilation.model_copy(
        update={"velocity_range_ms": (3.88, 5.08)})})
    ctx = replace(same, installation=fast, installation_result=envelope.run(fast))
    assert _v("annex3.3_3.ventilation", ctx) is Verdict.FAILS
    assert _v("annex7.3_4.no_extrapolation", ctx) is Verdict.FAILS


def test_standoff_may_exceed_the_tested_one_by_twenty_percent_and_no_more(same):
    inst = same.installation
    top = inst.fire.footprint.top_height_m
    tested = inst.nozzles.mounting.height_above_carriageway_m - top

    def at(standoff: float) -> Context:
        mount = inst.nozzles.mounting.model_copy(update={"height_above_carriageway_m": top + standoff})
        moved = inst.model_copy(update={"nozzles": inst.nozzles.model_copy(update={"mounting": mount})})
        return replace(same, installation=moved)

    assert _v("main.3_6_2.standoff", at(tested * 1.2)) is Verdict.COMPLIES
    assert _v("main.3_6_2.standoff", at(tested * 1.21)) is Verdict.FAILS
    assert _v("main.3_6_2.standoff", at(tested * 0.9)) is Verdict.FAILS


def test_no_test_of_the_installations_fire_class_needs_evidence():
    b = Design.load("examples/designs/solit2-test-protocol-class-b.json")
    a = Design.load("examples/designs/solit2-test-protocol.json")
    ctx = Context(tests={"B": b}, test_results={"B": envelope.run(b)}, installation=a,
                  installation_result=envelope.run(a), facts=Facts(), protocol_text={})
    assert _v("annex3.3_3.k_factor", ctx) is Verdict.NEEDS_EVIDENCE
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_compliance_transfer_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.compliance.rules.transfer_rules'`

- [ ] **Step 3: Implement**

```python
# solit2/compliance/rules/transfer_rules.py
"""Does the test's result transfer to the installation?

Annex 7 §3.3 lets a result transfer only while the protected tunnel sits inside
the tested parameters, Annex 3 §3.3 lists the parameters, and §3.4 does not let
CFD stand in for a test outside them. A single tested value is a range of one:
the installation must equal it. The main document relaxes one parameter, the
nozzle-to-load distance, to at most 20 % more than tested.
"""
from __future__ import annotations

from collections.abc import Callable

from solit2.compliance.context import (Context, hrr_at_mw, standoff_m,
                                       time_to_full_operation_s, tested_velocities_ms)
from solit2.compliance.rules.base import Outcome, Rule, judge, needs
from solit2.reports import guidance as g
from solit2.schema.design import Design

GROUP = "Transfer to the installation"
REL_TOL = 1e-9


def _pair(ctx: Context) -> tuple[Design, str] | None:
    cls = ctx.installation.fire.fire_class
    return (ctx.tests[cls], cls) if cls in ctx.tests else None


def _transfer(body: Callable[[Context, Design, str], Outcome], required: str) -> Callable[[Context], Outcome]:
    def check(ctx: Context) -> Outcome:
        pair = _pair(ctx)
        if pair is None:
            cls = ctx.installation.fire.fire_class
            return needs(f"test_designs.{cls}", required,
                         f"no Class {cls} test design to transfer from")
        return body(ctx, *pair)
    return check


def _equal(a: float, b: float) -> bool:
    return abs(a - b) <= REL_TOL * max(abs(a), abs(b), 1.0)


def _response(ctx: Context, test: Design, cls: str) -> Outcome:
    inst_s = time_to_full_operation_s(ctx.installation_result)
    test_s = time_to_full_operation_s(ctx.test_results[cls])
    return judge(inst_s <= test_s, f"installation {inst_s:.0f} s", f"<= tested {test_s:.0f} s",
                 "Tier 1 detection-to-full-pressure, both designs (predicted)")


def _k_factor(ctx: Context, test: Design, cls: str) -> Outcome:
    i, t = ctx.installation.nozzles, test.nozzles
    ok = i.preset == t.preset and _equal(i.k_factor_lpm_bar05, t.k_factor_lpm_bar05)
    return judge(ok, f"{i.preset}, K {i.k_factor_lpm_bar05:g}", f"{t.preset}, K {t.k_factor_lpm_bar05:g}",
                 "nozzle blocks of both designs")


def _pressure(ctx: Context, test: Design, cls: str) -> Outcome:
    fact = ctx.facts.tested_pressure_bar
    lo, hi = fact.value if fact else (test.nozzles.pressure_bar, test.nozzles.pressure_bar)
    p = ctx.installation.nozzles.pressure_bar
    basis = f"tested range ({fact.evidence.cite()})" if fact else "the test design's single pressure"
    return judge(lo - REL_TOL <= p <= hi + REL_TOL, f"{p:g} bar", f"{lo:g}–{hi:g} bar", basis)


def _positions(ctx: Context, test: Design, cls: str) -> Outcome:
    i, t = ctx.installation.nozzles.mounting, test.nozzles.mounting
    ok = (i.rows == t.rows and i.tilt_deg == t.tilt_deg
          and all(_equal(a, b) for a, b in zip(i.row_lateral_offsets_m, t.row_lateral_offsets_m)))
    return judge(ok, f"{i.rows} rows at {list(i.row_lateral_offsets_m)}, tilt {i.tilt_deg:g}°",
                 f"{t.rows} rows at {list(t.row_lateral_offsets_m)}, tilt {t.tilt_deg:g}°",
                 "mounting blocks of both designs")


def _spacing(ctx: Context, test: Design, cls: str) -> Outcome:
    i, t = ctx.installation.nozzles.mounting.pitch_m, test.nozzles.mounting.pitch_m
    return judge(_equal(i, t), f"{i:g} m", f"{t:g} m", "mounting pitch of both designs")


def _standoff(ctx: Context, test: Design, cls: str) -> Outcome:
    inst, tested = standoff_m(ctx.installation), standoff_m(test)
    most = tested * (1.0 + g.MAIN_MAX_STANDOFF_EXCESS_PCT / 100.0)
    ok = tested - REL_TOL <= inst <= most + REL_TOL
    return judge(ok, f"{inst:.2f} m", f"{tested:.2f}–{most:.2f} m",
                 "nozzle height minus fire-load top, both designs")


def _ventilation(ctx: Context, test: Design, cls: str) -> Outcome:
    tested, basis = tested_velocities_ms(ctx, cls)
    lo, hi = ctx.installation.ventilation.velocity_range_ms
    ok = bool(tested) and min(tested) <= lo and hi <= max(tested)
    return judge(ok, f"{lo:g}–{hi:g} m/s",
                 f"inside {min(tested):g}–{max(tested):g} m/s" if tested else "a tested velocity",
                 basis)


def _fire_at_activation(ctx: Context, test: Design, cls: str) -> Outcome:
    inst_r, test_r = ctx.installation_result, ctx.test_results[cls]
    inst_mw = hrr_at_mw(inst_r, inst_r.events["t_activate_s"])
    test_mw = hrr_at_mw(test_r, test_r.events["t_activate_s"])
    return judge(inst_mw <= test_mw + REL_TOL, f"{inst_mw:.1f} MW", f"<= tested {test_mw:.1f} MW",
                 "Tier 1 HRR at activation, both designs (predicted)")


def _zones(field: str) -> Callable[[Context, Design, str], Outcome]:
    def body(ctx: Context, test: Design, cls: str) -> Outcome:
        i, t = getattr(ctx.installation.zones, field), getattr(test.zones, field)
        return judge(_equal(float(i), float(t)), f"{i:g}", f"{t:g}", f"zones.{field}, both designs")
    return body


def _no_extrapolation(ctx: Context, test: Design, cls: str) -> Outcome:
    outside = [name for name, body in (("ventilation", _ventilation), ("pressure", _pressure),
                                       ("standoff", _standoff))
               if body(ctx, test, cls).verdict.value != "complies"]
    return judge(not outside, "outside the tested envelope: " + ", ".join(outside) if outside
                 else "inside the tested envelope", "no parameter outside the tested envelope",
                 "the ventilation, pressure and standoff transfer checks")


def _t(rule_id: str, clause: str, requirement: str,
       body: Callable[[Context, Design, str], Outcome], required: str, *constants: str) -> Rule:
    return Rule(rule_id, GROUP, clause, requirement, "transfer", _transfer(body, required),
                constants=constants)


RULES: tuple[Rule, ...] = (
    _t("annex7.3_2.response", "Annex 7 §3.2, Annex 3 §3.3",
       "The installation detects and reaches full operation at least as fast as the test.",
       _response, "no slower than tested", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.k_factor", "Annex 3 §3.3", "Same nozzle type and K-factor as tested.",
       _k_factor, "the tested nozzle", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.pressure", "Annex 3 §3.3", "Working pressure inside the tested range.",
       _pressure, "inside the tested range", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.positions", "Annex 3 §3.3", "Nozzle positions as tested.",
       _positions, "the tested positions", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.spacing", "Annex 3 §3.3", "Nozzle spacing as tested.",
       _spacing, "the tested spacing", "TEST_DERIVED_PARAMETERS"),
    _t("main.3_6_2.standoff", "Main document §3.6.2, Annex 3 §3.3",
       "Nozzle-to-load distance no less than tested and at most the stated excess over it.",
       _standoff, "tested to tested + 20 %", "MAIN_MAX_STANDOFF_EXCESS_PCT",
       "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.ventilation", "Annex 3 §3.3, Annex 7 §3.3",
       "Installation ventilation inside the tested velocities.", _ventilation,
       "inside the tested velocities", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.fire_at_activation", "Annex 3 §3.3",
       "Fire at activation no larger than tested.", _fire_at_activation,
       "no larger than tested", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.section_length", "Annex 3 §3.3", "Section length as tested.",
       _zones("section_length_m"), "the tested section length", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.sections_simultaneous", "Annex 3 §3.3",
       "Number of sections activated together as tested.",
       _zones("sections_simultaneous"), "the tested number", "TEST_DERIVED_PARAMETERS"),
    _t("annex7.3_4.no_extrapolation", "Annex 7 §3.4",
       "No parameter outside the tested envelope, which CFD may not supply.",
       _no_extrapolation, "inside the tested envelope", "TEST_DERIVED_PARAMETERS"),
)
```

Modify `solit2/compliance/rules/__init__.py` to:

```python
"""Every SOLIT2 rule the checker runs, in report order."""
from solit2.compliance.rules.lab_rules import RULES as _LAB
from solit2.compliance.rules.test_rules import RULES as _TEST
from solit2.compliance.rules.transfer_rules import RULES as _TRANSFER

REGISTRY = _TEST + _LAB + _TRANSFER
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_compliance_transfer_rules.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add solit2/compliance/rules tests/test_compliance_transfer_rules.py
git commit -m "feat(compliance): transfer clauses judging the installation against its test"
```

---

### Task 6: Project rules, the checker, and registry completeness

**Files:**
- Create: `solit2/compliance/project_rules.py`, `solit2/compliance/check.py`
- Create: `tests/fixtures/compliance/project.rules.json`
- Test: `tests/test_compliance_check.py`

**Interfaces:**
- Consumes: everything above; `solit2.engines.reduced.envelope.run(design) -> Result`; `solit2.reports.test_plan.render(design, result) -> str`; `solit2.schema.presets.PRESET_DIR`.
- Produces: `QUANTITIES: dict[str, Callable[[Context], float]]`; `ProjectRule`; `load_project_rules(path) -> tuple[Rule, ...]`; `ComplianceReport(spec_name, spec_path, findings, headline, provenance)` with property `blockers`; `run(spec_path) -> ComplianceReport`.

- [ ] **Step 1: Write the fixture and the failing test**

```json
// tests/fixtures/compliance/project.rules.json  (write WITHOUT this comment line)
{
  "source_document": "fixture project specification",
  "rules": [
    {"id": "hrr", "source": "fixture §1", "requirement": "Reduced HRR at most 50 MW.",
     "quantity": "installation.peak_hrr_mw", "comparator": "<=", "limit": 50.0},
    {"id": "report", "source": "fixture §2", "requirement": "A correlation CFD report supplied.",
     "requires_fact": "correlation_cfd_report"}
  ]
}
```

```python
# tests/test_compliance_check.py
import json
import re
from pathlib import Path

import pytest

from solit2.compliance import check
from solit2.compliance.project_rules import ProjectRule, load_project_rules
from solit2.compliance.rules import REGISTRY
from solit2.compliance.verdict import Verdict
from solit2.reports import guidance

SPEC = "tests/fixtures/compliance/minimal.spec.json"
# guidance.py constants that are not requirements a test can meet, and why.
NOT_REQUIREMENTS = {
    "MAIN_TYPICAL_LONGITUDINAL_MS": "the main document says 'normally used', not required",
    "RISK_ANALYSIS_EXAMPLE": "a worked example on a model tunnel, not a limit",
    "RISK_RANKING_NOISE_PCT": "the example's own reading of its result",
}


def test_every_guidance_requirement_is_read_by_some_rule():
    constants = {n for n in dir(guidance) if re.fullmatch(r"[A-Z][A-Z0-9_]+", n)}
    used = {c for rule in REGISTRY for c in rule.constants}
    assert constants - used - set(NOT_REQUIREMENTS) == set()
    assert used <= constants


def test_rule_ids_are_unique_across_the_registry():
    ids = [r.id for r in REGISTRY]
    assert len(ids) == len(set(ids))


def test_the_checker_runs_every_rule_once():
    report = check.run(SPEC)
    assert len(report.findings) == len(REGISTRY)
    assert report.provenance["design_sha.A"]
    assert report.provenance["calibration"]
    assert all(f.verdict in (Verdict.FAILS, Verdict.NEEDS_EVIDENCE) for f in report.blockers)
    assert not report.headline.full


def test_project_rules_load_and_gate_on_their_fact():
    rules = load_project_rules("tests/fixtures/compliance/project.rules.json")
    assert [r.id for r in rules] == ["project.hrr", "project.report"]
    assert all(r.kind == "project" for r in rules)


def test_a_project_rule_naming_an_unknown_quantity_is_refused():
    with pytest.raises(ValueError, match="quantity"):
        ProjectRule.model_validate({"id": "x", "source": "s", "requirement": "r",
                                    "quantity": "installation.made_up", "comparator": "<=",
                                    "limit": 1.0})


def test_a_deviation_on_a_clause_solit2_does_not_let_the_authority_waive_is_refused(tmp_path):
    raw = json.loads(open(SPEC).read())
    # Absolute paths: a spec's relative paths resolve against the spec file's folder.
    raw["test_designs"] = {"A": str(Path("examples/designs/solit2-test-protocol.json").resolve())}
    raw["installation_design"] = str(Path("examples/designs/road-tunnel-twin-bore.json").resolve())
    raw["deviations"] = {"main.3_6_2.height": {"accepted_by": "a", "document": "d",
                                               "locator": "l", "reason": "r"}}
    path = tmp_path / "s.spec.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="not waivable"):
        check.run(path)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_compliance_check.py -q`
Expected: FAIL — `ImportError` on `solit2.compliance.check`

- [ ] **Step 3: Implement the project rules**

```python
# solit2/compliance/project_rules.py
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
            raise ValueError(f"requires_fact {self.requires_fact!r} is not a spec fact")
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
```

- [ ] **Step 4: Implement the checker**

```python
# solit2/compliance/check.py
"""Run every clause against a spec and say how far from compliant the test is."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from solit2.compliance.context import Context
from solit2.compliance.project_rules import load_project_rules
from solit2.compliance.rules import REGISTRY
from solit2.compliance.rules.base import Rule, evaluate
from solit2.compliance.spec import load_spec
from solit2.compliance.verdict import Finding, Headline, Verdict, headline
from solit2.engines.reduced import envelope
from solit2.reports import test_plan
from solit2.schema.presets import PRESET_DIR

CALIBRATION_HASH_CHARS = 12


@dataclass(frozen=True)
class ComplianceReport:
    spec_name: str
    spec_path: Path
    findings: tuple[Finding, ...]
    headline: Headline
    provenance: dict[str, str]

    @property
    def blockers(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings
                     if f.verdict in (Verdict.FAILS, Verdict.NEEDS_EVIDENCE))


def _check_deviations(rules: tuple[Rule, ...], deviation_ids) -> None:
    by_id = {r.id: r for r in rules}
    for rule_id in deviation_ids:
        if rule_id not in by_id:
            raise ValueError(f"deviation names unknown rule {rule_id!r}")
        if not by_id[rule_id].waivable:
            raise ValueError(f"deviation on {rule_id!r} ({by_id[rule_id].clause}) is refused: "
                             "that clause is not waivable -- SOLIT2 gives the authority no "
                             "allowance to accept a shortfall on it")


def run(spec_path: str | Path) -> ComplianceReport:
    loaded = load_spec(spec_path)
    rules = REGISTRY + (load_project_rules(loaded.project_rules_path)
                        if loaded.project_rules_path else ())
    _check_deviations(rules, loaded.spec.deviations)
    results = {cls: envelope.run(d) for cls, d in loaded.tests.items()}
    installation_result = envelope.run(loaded.installation)
    ctx = Context(tests=loaded.tests, test_results=results, installation=loaded.installation,
                  installation_result=installation_result, facts=loaded.spec.facts,
                  protocol_text={cls: test_plan.render(d, results[cls])
                                 for cls, d in loaded.tests.items()})
    findings = tuple(evaluate(r, ctx, loaded.spec.deviations) for r in rules)
    calibration = (PRESET_DIR / "calibration.json").read_bytes()
    provenance = {f"design_sha.{cls}": res.meta["design_sha"] for cls, res in results.items()}
    provenance["design_sha.installation"] = installation_result.meta["design_sha"]
    provenance["calibration"] = hashlib.sha256(calibration).hexdigest()[:CALIBRATION_HASH_CHARS]
    return ComplianceReport(loaded.spec.name, loaded.path, findings, headline(findings), provenance)
```

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run pytest tests/test_compliance_check.py -q`
Expected: PASS (6 tests). If `test_every_guidance_requirement_is_read_by_some_rule` fails, the message names the unread constant: add it to the `constants` of the rule that reads it, or — only if `guidance.py` itself says it is not a requirement — to `NOT_REQUIREMENTS` with that reason.

- [ ] **Step 6: Commit**

```bash
git add solit2/compliance/project_rules.py solit2/compliance/check.py tests/fixtures/compliance/project.rules.json tests/test_compliance_check.py
git commit -m "feat(compliance): run every clause against a spec, with project rules and provenance"
```

---

### Task 7: The markdown report and `solit2 report compliance`

**Files:**
- Create: `solit2/reports/compliance.py`
- Modify: `solit2/cli.py` (handler next to `_cmd_report_test_plan`, parser next to `rtp`)
- Test: `tests/test_compliance_report.py`

**Interfaces:**
- Consumes: `ComplianceReport` (Task 6).
- Produces: `render(report) -> str`; `lab_checklist(report) -> str`; CLI `solit2 report compliance SPEC [--out PATH]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_compliance_report.py
import subprocess

from solit2.compliance import check
from solit2.reports import compliance

SPEC = "tests/fixtures/compliance/minimal.spec.json"


def test_the_report_leads_with_the_headline_and_lists_every_blocker():
    report = check.run(SPEC)
    text = compliance.render(report)
    assert text.startswith(f"# SOLIT² compliance — {report.spec_name}")
    assert report.headline.text in text
    for f in report.blockers:
        assert f.rule_id in text
    assert "requirement (paraphrased)" in text
    assert report.provenance["calibration"] in text


def test_the_lab_checklist_names_each_missing_fact_once():
    report = check.run(SPEC)
    checklist = compliance.lab_checklist(report)
    facts = {f.fact for f in report.blockers if f.fact}
    for fact in facts:
        assert checklist.count(f"`{fact}`") >= 1
    assert "pallet_moisture_pct" not in checklist  # supplied in the fixture


def test_the_cli_writes_the_report(tmp_path):
    out = tmp_path / "c.md"
    done = subprocess.run(["uv", "run", "solit2", "report", "compliance", SPEC, "--out", str(out)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert out.read_text().startswith("# SOLIT² compliance")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_compliance_report.py -q`
Expected: FAIL — `ImportError: cannot import name 'compliance'`

- [ ] **Step 3: Implement the report**

```python
# solit2/reports/compliance.py
"""The compliance matrix as a document for the main contractor and the authority."""
from __future__ import annotations

from itertools import groupby

from solit2.compliance.check import ComplianceReport
from solit2.compliance.verdict import Finding, Verdict

MARK = {Verdict.COMPLIES: "✅ complies", Verdict.FAILS: "❌ fails",
        Verdict.DEVIATION_ACCEPTED: "🟦 deviation accepted",
        Verdict.NEEDS_EVIDENCE: "🟧 needs evidence", Verdict.NOT_APPLICABLE: "— n/a"}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _row(f: Finding) -> str:
    note = f.deviation or f.evidence
    return (f"| {f.rule_id} | {_cell(f.clause)} | {_cell(f.requirement)} | {_cell(f.found)} | "
            f"{_cell(f.required)} | {MARK[f.verdict]} | {_cell(f.basis)} | {_cell(note)} |")


HEADER = ("| rule | clause | requirement (paraphrased) | found | required | verdict | basis | "
          "evidence / deviation |\n|---|---|---|---|---|---|---|---|")


def render(report: ComplianceReport) -> str:
    h = report.headline
    lines = [f"# SOLIT² compliance — {report.spec_name}", "",
             f"**{h.text}.** Fails: {h.fails}. Needs evidence: {h.needs_evidence}.", "",
             "Needs evidence is never counted as compliant. Values marked *predicted* are "
             "Tier 1 predictions until the test measures them.", "",
             "Provenance: " + ", ".join(f"{k} `{v}`" for k, v in sorted(report.provenance.items())),
             "", "## Blockers", ""]
    lines += ([HEADER] + [_row(f) for f in report.blockers]) if report.blockers else ["None."]
    lines += ["", "## Clause matrix"]
    for group, items in groupby(report.findings, key=lambda f: f.group):
        lines += ["", f"### {group}", "", HEADER] + [_row(f) for f in items]
    lines += ["", "## What the laboratory and the authority must supply", "", lab_checklist(report)]
    return "\n".join(lines) + "\n"


def lab_checklist(report: ComplianceReport) -> str:
    wanted: dict[str, list[str]] = {}
    for f in report.findings:
        if f.verdict is Verdict.NEEDS_EVIDENCE and f.fact:
            wanted.setdefault(f.fact, []).append(f"{f.clause} ({f.rule_id})")
    if not wanted:
        return "Nothing outstanding."
    return "\n".join(f"- [ ] `{fact}` — for {', '.join(clauses)}"
                     for fact, clauses in sorted(wanted.items()))
```

- [ ] **Step 4: Wire the CLI**

In `solit2/cli.py`, add after `_cmd_report_test_plan`:

```python
def _cmd_report_compliance(args: argparse.Namespace) -> int:
    from solit2.compliance import check as compliance_check
    from solit2.reports import compliance as compliance_report
    try:
        report = compliance_check.run(args.spec)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        return _fail(str(exc), "spec", "correct the compliance spec and try again",
                     EXIT_BAD_INPUT)
    return _emit_report(compliance_report.render(report), args.out)
```

and after the `rtp` parser block:

```python
    rcomp = report_sub.add_parser("compliance",
                                  help="clause-by-clause SOLIT2 compliance of a planned test")
    rcomp.add_argument("spec")
    rcomp.add_argument("--out")
    rcomp.set_defaults(func=_cmd_report_compliance)
```

- [ ] **Step 5: Run it to verify it passes**

Run: `uv run pytest tests/test_compliance_report.py -q`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add solit2/reports/compliance.py solit2/cli.py tests/test_compliance_report.py
git commit -m "feat(reports): the SOLIT2 compliance matrix and the lab checklist"
```

---

### Task 8: The Compliance wizard step

**Files:**
- Create: `app/views/compliance.py`
- Modify: `app/components/stepper.py:13`, `app/state.py:21`, `app/streamlit_app.py:8,14-15`, `tests/test_app_stepper.py:38,43-44`
- Test: `tests/test_app_compliance_step.py`

**Interfaces:**
- Consumes: `check.run`, `compliance.render`, `compliance.lab_checklist`, `Verdict`.
- Produces: `app.views.compliance.render()`; `find_specs(root: Path) -> list[Path]`; steps become Design, Result, Fire test, CFD verify, Compliance, Reports (`STEP_MAX = 6`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_compliance_step.py
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.views import compliance

APP = "app/streamlit_app.py"
FIXTURE_DIR = Path("tests/fixtures/compliance")


def test_spec_files_are_found_by_their_version_field():
    assert FIXTURE_DIR / "minimal.spec.json" in compliance.find_specs(FIXTURE_DIR)
    assert FIXTURE_DIR / "project.rules.json" not in compliance.find_specs(FIXTURE_DIR)


def test_the_step_shows_the_headline_and_the_blockers(monkeypatch):
    monkeypatch.setattr(compliance, "SPEC_ROOTS", (FIXTURE_DIR,))
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["step"] = 5
    at.session_state["design"] = object()  # the gate only checks that a design exists
    at.run()
    text = " ".join(m.value for m in at.markdown)
    assert "applicable clauses comply" in text
    assert any("Blockers" in s.value for s in at.subheader)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_app_compliance_step.py -q`
Expected: FAIL — `ImportError: cannot import name 'compliance' from 'app.views'`

- [ ] **Step 3: Implement the view**

```python
# app/views/compliance.py
"""Step 5: is the planned fire test SOLIT2-compliant, clause by clause."""
from __future__ import annotations

import json
from itertools import groupby
from pathlib import Path

import streamlit as st

from solit2.compliance import check
from solit2.compliance.verdict import Verdict
from solit2.reports import compliance as report_md

SPEC_ROOTS: tuple[Path, ...] = (Path("designs"), Path("examples/compliance"))
ICON = {Verdict.COMPLIES: "✅", Verdict.FAILS: "❌", Verdict.DEVIATION_ACCEPTED: "🟦",
        Verdict.NEEDS_EVIDENCE: "🟧", Verdict.NOT_APPLICABLE: "—"}


def find_specs(root: Path) -> list[Path]:
    """Compliance specs are the JSON files that declare a `spec_version`."""
    found = []
    for path in sorted(root.glob("*.json")):
        try:
            if "spec_version" in json.loads(path.read_text()):
                found.append(path)
        except (OSError, json.JSONDecodeError):
            continue
    return found


@st.cache_data(show_spinner="Checking every clause…")
def _run(path: str, mtime: float) -> check.ComplianceReport:
    return check.run(path)


def render() -> None:
    st.header("Compliance")
    st.caption("Every SOLIT² clause the planned test and its installation must meet. "
               "Needs evidence is never counted as compliant.")
    specs = [p for root in SPEC_ROOTS if root.exists() for p in find_specs(root)]
    if not specs:
        st.info("No compliance spec found. Add a *.json file with `spec_version` to designs/.")
        return
    choice = st.selectbox("Compliance spec", specs, format_func=str, key="compliance_spec")
    try:
        report = _run(str(choice), choice.stat().st_mtime)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        st.error(f"This spec cannot be checked: {exc}")
        return
    h = report.headline
    st.markdown(f"### {h.text}")
    cols = st.columns(4)
    cols[0].metric("Complies", h.complying)
    cols[1].metric("Fails", h.fails)
    cols[2].metric("Needs evidence", h.needs_evidence)
    cols[3].metric("By accepted deviation", h.by_deviation)
    st.subheader("Blockers")
    if report.blockers:
        st.dataframe([{"": ICON[f.verdict], "rule": f.rule_id, "clause": f.clause,
                       "found": f.found, "required": f.required, "basis": f.basis}
                      for f in report.blockers], width="stretch", hide_index=True)
    else:
        st.markdown("None — every applicable clause complies.")
    st.download_button("Download what the lab must supply", report_md.lab_checklist(report),
                       file_name="compliance-checklist.md", key="compliance_checklist")
    st.download_button("Download the full report", report_md.render(report),
                       file_name="compliance.md", key="compliance_report")
    st.subheader("Clause matrix")
    for group, items in groupby(report.findings, key=lambda f: f.group):
        with st.expander(group):
            for f in items:
                st.markdown(f"{ICON[f.verdict]} **{f.rule_id}** — {f.clause}: {f.requirement}  \n"
                            f"found {f.found}; required {f.required}; basis {f.basis}"
                            + (f"; evidence {f.evidence}" if f.evidence else "")
                            + (f"; {f.deviation}" if f.deviation else ""))
```

- [ ] **Step 4: Make the wizard six steps**

`app/components/stepper.py` line 13:
```python
STEPS = ("Design", "Result", "Fire test", "CFD verify", "Compliance", "Reports")
```
`app/state.py` line 21:
```python
STEP_MIN, STEP_MAX = 1, 6
```
`app/streamlit_app.py`:
```python
from app.views import cfd, compliance, design, fire_test, reports, result
...
VIEWS = {1: design.render, 2: result.render, 3: fire_test.render,
         4: cfd.render, 5: compliance.render, 6: reports.render}
```
`tests/test_app_stepper.py` lines 38 and 43-44: the last step is now 6:
```python
    assert all(not at.button(key=f"step_{i}").disabled for i in range(1, 7))
    ...
    at.button(key="step_6").click().run()
    assert at.session_state["step"] == 6
```

- [ ] **Step 5: Run the app tests**

Run: `uv run pytest tests/test_app_compliance_step.py tests/test_app_stepper.py tests/test_app_wizard.py -q`
Expected: PASS. If the gate in `app/streamlit_app.py` rejects `object()` as a design, set `at.session_state` with a real design instead: `Design.load("examples/designs/solit2-test-protocol.json")` stored under the key `app/state.py` uses for the design (read `state.get_design`).

- [ ] **Step 6: Commit**

```bash
git add app/views/compliance.py app/components/stepper.py app/state.py app/streamlit_app.py tests/test_app_stepper.py tests/test_app_compliance_step.py
git commit -m "feat(app): a Compliance step between CFD verify and Reports"
```

---

### Task 9: The example spec and the project spec

**Files:**
- Create: `examples/compliance/solit2-example.spec.json`
- Create: `designs/og-test-design-a.json`, `designs/og-test-design-b.json`, `designs/og-tender-r2.rules.json`, `designs/og-test-spec.json`
- Test: `tests/test_compliance_end_to_end.py`

**Interfaces:**
- Consumes: `check.run` (Task 6).
- Produces: shipped example and project inputs.

- [ ] **Step 1: Write the example spec** (neutral; independence scan applies)

```json
{
  "spec_version": 1,
  "name": "SOLIT2 example test programme",
  "test_designs": {"A": "../designs/solit2-test-protocol.json",
                   "B": "../designs/solit2-test-protocol-class-b.json"},
  "installation_design": "../designs/road-tunnel-twin-bore.json",
  "facts": {
    "hrr_method": {"value": "oxygen consumption",
                   "evidence": {"document": "EXAMPLE ONLY - not a real laboratory document",
                                "locator": "illustrates how a fact is evidenced"}}
  }
}
```

- [ ] **Step 2: Write the project test designs** — `designs/og-test-design-a.json` is the installation `designs/og-ds01-rev00-cd-meas.json` moved into the SOLIT² test tunnel. Build it by script so every block the test must share with the installation is copied, not retyped:

```bash
uv run python - <<'EOF'
import json
from pathlib import Path
inst = json.loads(Path("designs/og-ds01-rev00-cd-meas.json").read_text())
def test_design(fire: dict, name: str, note: str) -> dict:
    d = json.loads(json.dumps(inst))
    d["meta"] = {"name": name, "notes": note}
    d["tunnel"] = {"preset": "solit2_test", "section": "test", "ambient_temp_c": 20.0}
    d["fire"] = fire
    # 0.2 m below the 5.2 m crown of the SOLIT2 test tunnel preset.
    d["nozzles"]["mounting"]["height_above_carriageway_m"] = 5.0
    d["zones"]["duration_min"] = 45.0
    d["ventilation"] = {"mode": "longitudinal", "velocity_range_ms": [1.5, 3.0]}
    return d
note = ("The DS-01 REV00 installation moved into the SOLIT2 test tunnel preset for the fire "
        "test. Nozzle, zones, detection and hydraulics are copied from "
        "og-ds01-rev00-cd-meas.json; only the tunnel, fire, mounting height (5.0 m under the "
        "5.2 m crown), discharge duration and SOLIT2's 1.5-3.0 m/s test velocities differ. The "
        "booked laboratory's real tunnel replaces the preset when the laboratory supplies it.")
Path("designs/og-test-design-a.json").write_text(json.dumps(test_design(
    {"preset": "hgv_150mw", "covered": True}, "og-test-design-a", note), indent=2) + "\n")
Path("designs/og-test-design-b.json").write_text(json.dumps(test_design(
    {"preset": "pool_60mw"}, "og-test-design-b", note), indent=2) + "\n")
EOF
```

- [ ] **Step 3: Write the tender rule file** `designs/og-tender-r2.rules.json`:

```json
{
  "source_document": "HPWM-TECHNICAL SPEC_R2",
  "rules": [
    {"id": "r2.6.reduced_hrr", "source": "§6",
     "requirement": "The 150 MW design fire is reduced to 50 MW or less.",
     "quantity": "installation.peak_hrr_mw", "comparator": "<=", "limit": 50.0},
    {"id": "r2.5a.pump_power", "source": "§5a",
     "requirement": "Pumping power, booster pumps included, at most 650 kW.",
     "quantity": "installation.power_kw", "comparator": "<=", "limit": 650.0},
    {"id": "r2.5d.droplet", "source": "§5d",
     "requirement": "Droplet size below 100 microns, with the measure declared.",
     "quantity": "installation.smd_um", "comparator": "<", "limit": 100.0,
     "requires_fact": "droplet_size_measure"},
    {"id": "r2.8.test_velocity_high", "source": "§8",
     "requirement": "Tested up to the tunnel's 5.08 m/s.",
     "quantity": "test.max_velocity_ms", "comparator": ">=", "limit": 5.08},
    {"id": "r2.8.test_velocity_low", "source": "§8",
     "requirement": "Tested down to the tunnel's 3.88 m/s.",
     "quantity": "test.min_velocity_ms", "comparator": "<=", "limit": 3.88},
    {"id": "r2.9.correlation_cfd", "source": "§9",
     "requirement": "A CFD analysis correlating the tested tunnel with this one.",
     "requires_fact": "correlation_cfd_report"}
  ]
}
```

- [ ] **Step 4: Write the project spec** `designs/og-test-spec.json` — no facts: nobody has supplied any yet, and none may be assumed.

```json
{
  "spec_version": 1,
  "name": "Orange Gate full-scale fire test (DS-01 REV00)",
  "test_designs": {"A": "og-test-design-a.json", "B": "og-test-design-b.json"},
  "installation_design": "og-ds01-rev00-cd-meas.json",
  "project_rules": "og-tender-r2.rules.json",
  "facts": {},
  "deviations": {}
}
```

- [ ] **Step 5: Write the end-to-end test**

```python
# tests/test_compliance_end_to_end.py
from solit2.compliance import check
from solit2.compliance.verdict import Verdict


def _by_id(report):
    return {f.rule_id: f for f in report.findings}


def test_the_example_spec_checks_cleanly_and_is_not_full():
    report = check.run("examples/compliance/solit2-example.spec.json")
    assert report.headline.applicable > 50
    assert not report.headline.full
    assert _by_id(report)["annex7.6_5.hrr_method"].verdict is Verdict.COMPLIES


def test_the_project_spec_shows_the_findings_the_audit_predicted():
    found = _by_id(check.run("designs/og-test-spec.json"))
    # The SOLIT2 test tunnel preset is 39.0 m2 against Annex 7's 40 m2.
    assert found["annex7.3_6.free_area"].verdict is Verdict.FAILS
    # A 1.5-3.0 m/s test cannot qualify a 3.88-5.08 m/s tunnel.
    assert found["annex3.3_3.ventilation"].verdict is Verdict.FAILS
    assert found["project.r2.8.test_velocity_high"].verdict is Verdict.FAILS
    # 1.5 m installed standoff against 1.0 m in a 5.2 m test tunnel.
    assert found["main.3_6_2.standoff"].verdict is Verdict.FAILS
    # Nothing has been evidenced, so no laboratory clause may pass.
    assert all(f.verdict is Verdict.NEEDS_EVIDENCE for f in found.values() if f.kind == "lab")
```

- [ ] **Step 6: Run the tests, then the whole suite**

Run: `uv run pytest tests/test_compliance_end_to_end.py -q && uv run pytest -q`
Expected: PASS. If a predicted project finding does not hold, do not edit the assertion to match: print that finding's `found`/`required`/`basis` and report it — the audit's prediction, not the checker, may be wrong, and that is a finding for the user.

- [ ] **Step 7: Commit**

```bash
git add examples/compliance designs/og-test-design-a.json designs/og-test-design-b.json designs/og-tender-r2.rules.json designs/og-test-spec.json tests/test_compliance_end_to_end.py
git commit -m "feat(compliance): the example spec, and the Orange Gate test spec with the tender's rules"
```
