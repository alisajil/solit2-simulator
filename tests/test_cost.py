"""The cost index prices the tunnel the user described, not a fixed one.

Every quantity `cost_index` reports is derived from `tunnel.length_m` and
`tunnel.tubes`, so these tests assert the RELATIONSHIPS between designs rather
than frozen totals. `BASELINE_TOTAL` is the one fixed number left and it only
sets the scale of the ratio, so no design is expected to index to exactly 1.00.
"""
import json
from pathlib import Path

import pytest

from solit2.engines.reduced import cost as cost_mod
from solit2.engines.reduced.cost import cost_index
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.schema.design import Design

BASELINE = "examples/designs/road-tunnel-twin-bore.json"


def _cost(design):
    geom = section_geometry(design)
    return cost_index(design, size_system(design, geom))


def _with_tunnel(design, **updates):
    return design.model_copy(
        update={"tunnel": design.tunnel.model_copy(update=updates)})


def test_zone_and_head_counts_come_from_the_design_not_a_fixed_tunnel():
    d = Design.load(BASELINE)
    c = _cost(d)
    per_tube = round(d.tunnel.length_m / d.zones.section_length_m)
    assert c.zones == d.tunnel.tubes * per_tube
    assert c.section_valves == c.zones
    assert c.heads == c.zones * d.heads_per_zone


def test_the_index_is_the_total_over_the_normalisation_constant():
    """`BASELINE_TOTAL` is a divisor, not a quantity: it sets the scale, only."""
    c = _cost(Design.load(BASELINE))
    assert c.index == pytest.approx(c.total / cost_mod.BASELINE_TOTAL)


def test_tighter_pitch_costs_more():
    d = Design.load(BASELINE)
    tight = d.model_copy(update={"nozzles": d.nozzles.model_copy(
        update={"mounting": d.nozzles.mounting.model_copy(update={"pitch_m": 1.6})})})
    assert _cost(tight).index > _cost(d).index
    assert _cost(tight).heads > _cost(d).heads


def test_longer_zones_need_fewer_section_valves():
    d = Design.load(BASELINE)
    longer = d.model_copy(update={"zones": d.zones.model_copy(
        update={"section_length_m": 45.0})})
    assert _cost(longer).section_valves < _cost(d).section_valves


# --- the quantities are the design's own -------------------------------------

def test_quantities_scale_with_the_tunnel_length():
    """Double the bore, double the pipe: a 600 m gallery is not priced as 8.5 km."""
    # A length that divides exactly by the zone length, so the zone count can be
    # compared without `round()` deciding the answer.
    short = _with_tunnel(Design.load(BASELINE), length_m=3000.0, tubes=1)
    long = _with_tunnel(short, length_m=6000.0)

    base, doubled = _cost(short), _cost(long)
    assert doubled.zones == 2 * base.zones
    assert doubled.ring_main_m == pytest.approx(2 * base.ring_main_m)
    assert doubled.row_pipe_m == pytest.approx(2 * base.row_pipe_m)
    assert doubled.heads == 2 * base.heads


def test_tubes_multiplies_the_quantities():
    """The same tunnel at `tubes: 2` costs twice the single-bore quantities."""
    d = Design.load(BASELINE)
    single, twin = _cost(_with_tunnel(d, tubes=1)), _cost(_with_tunnel(d, tubes=2))

    assert twin.zones == 2 * single.zones
    assert twin.section_valves == 2 * single.section_valves
    assert twin.heads == 2 * single.heads
    assert twin.ring_main_m == pytest.approx(2 * single.ring_main_m)
    assert twin.row_pipe_m == pytest.approx(2 * single.row_pipe_m)


def test_a_design_that_never_mentions_tubes_is_priced_as_a_single_bore(tmp_path):
    raw = json.loads(Path(BASELINE).read_text())
    raw["tunnel"] = {"preset": "template", "section": "cut_cover"}
    assert "tubes" not in raw["tunnel"], "the point of the test is that it is absent"
    path = tmp_path / "unstated_tubes.json"
    path.write_text(json.dumps(raw))

    d = Design.load(path)
    assert d.tunnel.tubes == 1
    c = _cost(d)
    assert c.ring_main_m == pytest.approx(2.0 * d.tunnel.length_m)
    assert c.row_pipe_m == pytest.approx(d.nozzles.mounting.rows * d.tunnel.length_m)
    assert c.zones == round(d.tunnel.length_m / d.zones.section_length_m)
