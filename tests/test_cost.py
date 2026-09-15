import pytest
from solit2.schema.design import Design
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.engines.reduced.cost import cost_index

BASELINE = "examples/designs/road-tunnel-twin-bore.json"


def _cost(design):
    geom = section_geometry(design)
    return cost_index(design, size_system(design, geom))


def test_zone_and_head_counts_match_the_reference_quantities():
    c = _cost(Design.load(BASELINE))
    assert c.zones == 283            # reference quantities: 141 + 142
    assert c.section_valves == 283
    assert c.heads == 7075           # reference quantities: ~7100


def test_baseline_index_is_one():
    assert _cost(Design.load(BASELINE)).index == pytest.approx(1.0, abs=1e-9)


def test_tighter_pitch_costs_more():
    d = Design.load(BASELINE)
    tight = d.model_copy(update={"nozzles": d.nozzles.model_copy(
        update={"mounting": d.nozzles.mounting.model_copy(update={"pitch_m": 1.6})})})
    assert _cost(tight).index > 1.0
    assert _cost(tight).heads > 7075


def test_longer_zones_need_fewer_section_valves():
    d = Design.load(BASELINE)
    longer = d.model_copy(update={"zones": d.zones.model_copy(update={"section_length_m": 45.0})})
    assert _cost(longer).section_valves < 283
