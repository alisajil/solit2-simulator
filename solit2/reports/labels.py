"""Plain-English names, units and precision for the quantities a result reports.

An identifier like `max_air_temp_c` or `hrr_below_tvs_design_mw` tells a reader of
the code what a field holds; it tells a fire engineer reading a report very little,
and a raw `0.010960400510528656` tells them less than `0.011` does. Everything a
person reads — the tables on screen, the exported markdown — goes through here, so a
criterion is named and dimensioned the same way wherever it appears.

The names are the standard's own quantities, not any project's or product's wording.
"""
from __future__ import annotations

# id -> (name a fire engineer would use, unit, decimal places)
LABELS: dict[str, tuple[str, str, int]] = {
    # SOLIT2 Annex 7 section 7 acceptance criteria
    "target_ignited": ("Target ignited", "", 0),
    "hrr_below_tvs_design_mw": ("Peak heat release rate", "MW", 1),
    "max_air_temp_c": ("Peak air temperature", "°C", 1),
    "max_heat_flux_kwm2": ("Peak heat flux", "kW/m²", 2),
    "min_visibility_m": ("Minimum visibility", "m", 1),
    "max_fed": ("Peak fractional effective dose", "", 3),
    "max_co_ppm": ("Peak carbon monoxide", "ppm", 0),
    "structure_exposure_length_m": ("Structure exposed above limit", "m", 1),
    "structure_exposure_duration_s": ("Structure exposure duration", "s", 0),
    # user-declared site constraints
    "max_pump_power_kw": ("Pump power", "kW", 0),
    "max_application_density_mm_min": ("Application density", "mm/min", 2),
    "max_water_volume_m3": ("Water volume", "m³", 1),
    "max_nozzle_pressure_bar": ("Nozzle pressure", "bar", 1),
    "min_nozzle_pressure_bar": ("Nozzle pressure", "bar", 1),
    # peaks and timeseries
    "hrr_mw": ("Heat release rate", "MW", 1),
    "hrr_free_burn_mw": ("Free-burn heat release rate", "MW", 1),
    "ceiling_temp_c": ("Ceiling temperature", "°C", 1),
    "lining_temp_c": ("Lining temperature", "°C", 1),
    "pipe_surface_temp_c": ("Pipe surface temperature", "°C", 1),
    "smoke_layer_temp_d15_c": ("Smoke layer temperature at D15", "°C", 1),
    "smoke_layer_temp_d100_c": ("Smoke layer temperature at D100", "°C", 1),
    "target_peak_flux_kwm2": ("Peak flux at the target", "kW/m²", 2),
    "target_max_exposure_s": ("Target exposure above limit", "s", 0),
    "t_s": ("Test clock", "s", 0),
    "u45_temp_c": ("Temperature at U45", "°C", 1),
    "u15_temp_c": ("Temperature at U15", "°C", 1),
    "d15_temp_c": ("Temperature at D15", "°C", 1),
    "d100_temp_c": ("Temperature at D100", "°C", 1),
    "hf_u15_kwm2": ("Heat flux at U15", "kW/m²", 2),
    "hf_d15_kwm2": ("Heat flux at D15", "kW/m²", 2),
    "fed_d45": ("Fractional effective dose at D45", "", 3),
    "backlayering_m": ("Backlayering length", "m", 1),
    "velocity_ms": ("Ventilation velocity", "m/s", 2),
}

DEFAULT_DECIMALS = 2


def label(key: str) -> str:
    """The quantity's name, without its unit."""
    known = LABELS.get(key)
    return known[0] if known else key.replace("_", " ").capitalize()


def unit(key: str) -> str:
    known = LABELS.get(key)
    return known[1] if known else ""


def heading(key: str) -> str:
    """Name and unit together, for a column head or a tile label."""
    suffix = unit(key)
    return f"{label(key)} ({suffix})" if suffix else label(key)


def value(key: str, raw: object) -> str:
    """One reading, rounded to the precision the quantity is actually known to.

    A criterion nobody set reads `—`, not `0`: an absent limit is not a measurement.
    """
    if raw is None:
        return "—"
    if isinstance(raw, bool):
        return "yes" if raw else "no"
    if not isinstance(raw, (int, float)):
        return str(raw)
    known = LABELS.get(key)
    places = known[2] if known else DEFAULT_DECIMALS
    return f"{float(raw):.{places}f}"


def with_unit(key: str, raw: object) -> str:
    """A reading that has to carry its own unit, such as a metric tile."""
    text = value(key, raw)
    suffix = unit(key)
    return f"{text} {suffix}" if suffix and text != "—" else text
