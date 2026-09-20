import pytest
from streamlit.testing.v1 import AppTest

from app.components import hmi, timeline
from solit2.engines.reduced.sim import run_once
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


@pytest.fixture(scope="module")
def trace():
    d = Design.load(EXAMPLE)
    return run_once(d, d.tunnel.section, d.ventilation.velocity_range_ms[0])


def _step_at(trace, t):
    return min(trace.steps, key=lambda s: abs(s.t_s - t))


def test_lamps_light_in_sequence(trace):
    ev = trace.events
    before = hmi.lamp_states(_step_at(trace, ev["t_detect_s"] - 5), ev)
    after = hmi.lamp_states(_step_at(trace, ev["t_full_pressure_s"] + 5), ev)
    assert list(before) == ["Detection", "Activation", "Full pressure", "Discharge"]
    assert not any(before.values())
    assert after["Detection"] and after["Activation"] and after["Full pressure"] and after["Discharge"]


def test_water_discharged_is_zero_before_activation_and_grows_after(trace):
    ev = trace.events
    assert hmi.water_discharged_m3(trace.steps, ev["t_activate_s"] - 1) == 0.0
    late = hmi.water_discharged_m3(trace.steps, trace.steps[-1].t_s)
    mid = hmi.water_discharged_m3(trace.steps, ev["t_full_pressure_s"] + 60)
    assert late > mid > 0.0


def test_event_marks_are_sorted_and_skip_unset_events():
    marks = timeline.event_marks({"t_detect_s": 90.0, "t_activate_s": 150.0, "t_full_pressure_s": 180.0,
                                  "t_peak_hrr_s": 60.0, "pools_extinguished_at_s": None,
                                  "backlayering": {"occurred": True, "cleared_at_s": 400.0}})
    assert [t for t, _ in marks] == [60.0, 90.0, 150.0, 180.0, 400.0]
    assert marks[-1][1] == "Backlayer cleared"


def test_hmi_and_timeline_render_without_error():
    script = """
from app.components import hmi, timeline
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.engines.reduced.sim import run_once
from solit2.engines.reduced import envelope
from solit2.schema.design import Design
d = Design.load("examples/designs/road-tunnel-twin-bore.json")
tr = run_once(d, d.tunnel.section, d.ventilation.velocity_range_ms[0])
res = envelope.run(d)
hmi.render(tr.steps[200], tr, d, size_system(d, section_geometry(d)))
timeline.render(tr.events, res.criteria, tr.steps[-1].t_s)
"""
    at = AppTest.from_string(script, default_timeout=60)
    at.run()
    assert not at.exception
    assert [m.label for m in at.metric][:2] == ["Test clock", "HRR"]
    assert any('class="lamps"' in m.value for m in at.markdown)
