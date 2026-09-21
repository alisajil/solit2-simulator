"""Layer functions are pure: every assertion here is on traces, no browser."""
import pytest
from plotly.basedatatypes import BaseTraceType

from app.components import cross_section as cs
from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.sim import run_once
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


@pytest.fixture(scope="module")
def design():
    return Design.load(EXAMPLE)


@pytest.fixture(scope="module")
def trace(design):
    return run_once(design, design.tunnel.section, design.ventilation.velocity_range_ms[0])


@pytest.fixture(scope="module")
def geom(design):
    return section_geometry(design)


def _wet_step(trace):
    return next(s for s in trace.steps if s.water_lpm > 0)


def test_tunnel_outline_is_symmetric_and_matches_width_at(geom):
    outline = cs.tunnel_outline(geom)
    xs, ys = list(outline.x), list(outline.y)
    # Closed polygon: first and last points coincide.
    assert (xs[0], ys[0]) == (xs[-1], ys[-1])
    at_zero = xs[ys.index(0.0)]
    assert at_zero == pytest.approx(geom.width_at(0.0) / 2.0)
    # Every drawn width matches what the engine's own hydraulic-diameter
    # calculation would compute at that same height -- not a decorative curve.
    for x, z in zip(xs, ys):
        if x > 0:
            assert x == pytest.approx(geom.width_at(z) / 2.0, abs=1e-9)


def test_the_drawn_thermocouples_are_the_ones_the_deck_measures_at(design, geom, trace):
    """Both read `deck.figure_16_positions`, so the picture cannot drift away
    from the measurement."""
    from solit2.engines.fds import deck as fds_deck
    from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
    step = trace.steps[len(trace.steps) // 2]
    fuel = fds_deck.fuel_box(design, geom)
    solids = (fuel, fds_deck.target_box(design, geom))
    for name in ("D03", "D15"):
        drawn = cs.thermocouple_rake(design, geom, name, step, 400.0)
        placed = fds_deck.figure_16_positions(INSTRUMENTS[name], STATIONS[name], geom,
                                              fds_deck.DX_M, fuel, solids)
        assert placed, name
        assert list(drawn.x) == [y for _, y, _ in placed], name
        assert list(drawn.y) == [z for _, _, z in placed], name
        assert any(y < 0 for y in drawn.x) and any(y > 0 for y in drawn.x), "both walls"


def test_a_far_field_station_falls_back_to_the_vertical_ladder(design, geom, trace):
    """Figure 16 draws no layout for a two-thermocouple section, and those
    sensors are measured on the centreline."""
    step = trace.steps[len(trace.steps) // 2]
    drawn = cs.thermocouple_rake(design, geom, "D215", step, 400.0)
    sample = step.stations["D215"]
    assert list(drawn.x) == [0.0] * len(sample.heights_m)
    assert list(drawn.y) == list(sample.heights_m)


def test_the_colour_of_a_sensor_is_its_height_on_the_vertical_profile(design, geom, trace):
    """Tier 1 resolves height and no lateral position, so two sensors at one
    height read alike whichever wall they are on. That is a limit of the
    engine, and the view must not imply otherwise by inventing a difference."""
    step = trace.steps[len(trace.steps) // 2]
    sample = step.stations["D03"]
    drawn = cs.thermocouple_rake(design, geom, "D03", step, 400.0)
    by_height = {}
    for y, z, c in zip(drawn.x, drawn.y, drawn.marker.color):
        by_height.setdefault(round(z, 6), set()).add(round(c, 6))
    assert any(len(v) > 1 for v in by_height.values()) is False, "one height, one temperature"
    # and the profile it interpolates is the station's own
    assert cs.temperature_at(sample, sample.heights_m[0]) == pytest.approx(sample.temps_c[0])
    assert cs.temperature_at(sample, sample.heights_m[-1]) == pytest.approx(sample.temps_c[-1])
    mid_z = (sample.heights_m[0] + sample.heights_m[1]) / 2
    lo, hi = sorted((sample.temps_c[0], sample.temps_c[1]))
    assert lo <= cs.temperature_at(sample, mid_z) <= hi



def test_gas_markers_sit_at_the_heights_table_5_and_the_fds_deck_use(trace):
    from solit2.engines.reduced.criteria import HEAT_FLUX_HEIGHT_M
    step = trace.steps[len(trace.steps) // 2]
    flux_station = next(n for n in STATIONS if INSTRUMENTS[n].heat_flux)
    co_station = next(n for n in STATIONS if INSTRUMENTS[n].carbon_monoxide > 0)
    bare = next(n for n in STATIONS if not (INSTRUMENTS[n].heat_flux or INSTRUMENTS[n].visibility
                                            or INSTRUMENTS[n].carbon_monoxide > 0))
    flux = cs.gas_markers(flux_station, step)
    assert [t.y[0] for t in flux if t.name.startswith("flux")] == [HEAT_FLUX_HEIGHT_M]
    co = cs.gas_markers(co_station, step)
    assert [t.y[0] for t in co if t.name.startswith("CO")] == [cs.BREATHING_HEIGHT_M]
    assert cs.gas_markers(bare, step) == []


def test_nozzle_rows_sit_at_their_real_lateral_offsets_and_tint_when_discharging(design, trace):
    mount = design.nozzles.mounting
    idle = cs.nozzle_rows(design, trace.steps[0])
    wet = cs.nozzle_rows(design, _wet_step(trace))
    assert list(idle.x) == list(mount.row_lateral_offsets_m)
    assert list(idle.y) == [mount.height_above_carriageway_m] * len(mount.row_lateral_offsets_m)
    assert idle.marker.color != wet.marker.color
    assert wet.marker.color == cs.palette.PRIMARY


def test_figure_keeps_a_true_aspect_ratio_and_returns_plotly_traces(design, geom, trace):
    step = trace.steps[len(trace.steps) // 2]
    fig = cs.figure(design, geom, step, "D15", 400.0)
    assert fig.layout.xaxis.scaleanchor == "y" and fig.layout.xaxis.scaleratio == 1
    assert all(isinstance(t, BaseTraceType) for t in fig.data)



def test_figure_omits_the_gas_markers_where_the_station_carries_none(design, geom, trace):
    step = trace.steps[len(trace.steps) // 2]
    bare = next(n for n in STATIONS if not (INSTRUMENTS[n].heat_flux or INSTRUMENTS[n].visibility
                                            or INSTRUMENTS[n].carbon_monoxide > 0))
    fig = cs.figure(design, geom, step, bare, 400.0)
    assert not any(t.name.startswith(("flux", "CO")) for t in fig.data)


def test_the_fuel_load_section_appears_only_where_the_station_cuts_it(design, geom):
    from solit2.engines.reduced.geometry import fire_lateral_m
    fp = design.fire.footprint
    y = fire_lateral_m(design, geom)
    inside = cs.fuel_section(design, geom, "D03")
    assert inside is not None and inside["name"] == "fuel load"
    assert (inside["x0"] + inside["x1"]) / 2 == pytest.approx(y), "eccentric, as both engines burn it"
    assert (inside["y0"], inside["y1"]) == (fp.base_height_m, fp.top_height_m)
    target = cs.fuel_section(design, geom, "Target")
    assert target is not None and target["name"] == "target"
    assert cs.fuel_section(design, geom, "D15") is None
    assert cs.fuel_section(design, geom, "U45") is None


def test_figure_carries_the_section_shape_at_the_mock_up_and_none_at_d15(design, geom, trace):
    step = trace.steps[len(trace.steps) // 2]
    with_load = cs.figure(design, geom, step, "D05", 400.0)
    assert len(with_load.layout.shapes) == 1
    assert len(cs.figure(design, geom, step, "D15", 400.0).layout.shapes) == 0
