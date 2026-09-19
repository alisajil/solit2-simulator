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


def test_dbr_figures_are_not_silently_drifting():
    """Pin DBR baseline figures against preset drift.

    This test prevents silent changes to load-bearing values when illustration
    presets are updated. All assertions are from MSTX-OG-DBR-001 Rev 0.
    """
    design = Design.load(BASELINE)
    # Tunnel geometry (DBR)
    assert design.tunnel.internal_diameter_m == 11.0
    assert design.tunnel.deck_below_centre_m == 2.125
    assert design.tunnel.gradient_pct == 0.0
    # Nozzle hydraulics (DBR)
    assert design.nozzles.k_factor_lpm_bar05 == 4.1
    assert design.nozzles.pressure_bar == 50.0
    assert design.nozzles.smd_um("fine") == 100.0
    # Nozzle mounting (DBR)
    assert design.nozzles.mounting.height_above_carriageway_m == 5.5
    # Hydraulic arrangement (DBR)
    assert design.hydraulics.pump_efficiency == 0.68
    assert design.hydraulics.motor_efficiency == 0.93
    assert design.hydraulics.loop_factor == 0.25
    assert design.hydraulics.main_dn_mm == 150.0
    assert design.hydraulics.zone_header_dn_mm == 65.0
    # These two still resolve from examples/presets/hydraulics_example.json.
    # Unpinned, editing that illustration silently moves this baseline's pump
    # power and cost index.
    assert design.hydraulics.static_head_bar == 2.0
    assert design.hydraulics.fittings_loss_bar == 1.9
