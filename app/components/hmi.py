"""The test-rig strip above the twin: clock, live readouts and status lamps."""
from __future__ import annotations

import streamlit as st

from app.components.twin_canvas import mmss
from solit2.engines.reduced.hydraulics import HydraulicsResult
from solit2.engines.reduced.sim import DT_S
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.schema.design import Design

LAMPS = (("Detection", "t_detect_s"), ("Activation", "t_activate_s"),
         ("Full pressure", "t_full_pressure_s"))


def water_discharged_m3(steps: tuple[StepRecord, ...], upto_t_s: float) -> float:
    """Litres per minute integrated over the engine's fixed step, in cubic metres."""
    lpm = sum(s.water_lpm for s in steps if s.t_s <= upto_t_s)
    return lpm * DT_S / 60.0 / 1000.0


def lamp_states(step: StepRecord, events: dict) -> dict[str, bool]:
    states = {label: events.get(key) is not None and step.t_s >= events[key]
              for label, key in LAMPS}
    states["Discharge"] = step.water_lpm > 0
    return states


def render(step: StepRecord, trace: RunTrace, design: Design, hyd: HydraulicsResult) -> None:
    clock, hrr, water, tank, vent = st.columns(5)
    clock.metric("Test clock", mmss(step.t_s))
    hrr.metric("HRR", f"{step.hrr_mw:.1f} MW",
               delta=f"{step.hrr_mw - step.hrr_free_mw:+.1f} MW vs free burn", delta_color="inverse")
    water.metric("Water", f"{step.water_lpm:.0f} L/min")
    used = water_discharged_m3(trace.steps, step.t_s)
    tank.metric("Tank remaining", f"{max(hyd.tank_m3 - used, 0.0):.1f} m³", delta=f"-{used:.1f} m³",
                delta_color="off")
    vent.metric("Ventilation", f"{step.u_eff_ms:.2f} m/s",
                delta=f"{step.u_eff_ms - step.u_critical_ms:+.2f} m/s vs critical")
    lamps = "".join(f'<span><span class="lamp {"on" if on else ""}"></span>{label}</span>'
                    for label, on in lamp_states(step, trace.events).items())
    st.markdown(f'<div class="lamps">{lamps}</div>', unsafe_allow_html=True)
