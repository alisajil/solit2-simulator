import pytest

from solit2.engines.reduced import envelope
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"


def test_the_orange_gate_baseline_loads():
    design = Design.load(BASELINE)
    assert design.meta.name == "og-dbr-rev0"
    assert design.tunnel.preset == "twin_bore_11m"
    assert design.tunnel.shape == "circle"
    assert design.tunnel.length_m == 4240.0


def test_the_baseline_matches_the_dbr_hydraulics_numbers():
    design = Design.load(BASELINE)
    # DBR: K 4.1, 50 bar -> 29.0 lpm per head; 25 heads per 30 m zone;
    # 3 zones simultaneous -> 2175 lpm before the 10% design margin.
    assert round(design.nozzles.flow_per_head_lpm, 1) == 29.0
    assert design.active_heads == 75
    assert design.flow_lpm == pytest.approx(2175.0, rel=0.005)


def test_the_baseline_runs_through_tier_1():
    result = envelope.run(Design.load(BASELINE))
    assert result.meta["design_name"] == "og-dbr-rev0"
    assert "target_ignited" in result.criteria
