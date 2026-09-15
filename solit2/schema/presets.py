"""Preset lookup and merge.

A design JSON names a preset per block and overrides individual fields; the
preset supplies everything else.
"""
from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

PRESET_DIR = Path(__file__).resolve().parent.parent / "presets"

_KIND_PREFIX = {
    "tunnel": "tunnel_",
    "nozzle": "nozzle_",
    "fire": "fire_",
    "hydraulics": "hydraulics_",
}


def load_preset(kind: str, name: str) -> dict:
    """Load `presets/<kind>_<name>.json`."""
    if kind not in _KIND_PREFIX:
        raise KeyError(f"unknown preset kind {kind!r}; expected one of {sorted(_KIND_PREFIX)}")
    path = PRESET_DIR / f"{_KIND_PREFIX[kind]}{name}.json"
    if not path.exists():
        available = sorted(p.stem for p in PRESET_DIR.glob(f"{_KIND_PREFIX[kind]}*.json"))
        raise FileNotFoundError(f"no {kind} preset {name!r}; available: {available}")
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def load_calibration() -> dict:
    """Load `presets/calibration.json`, cached.

    Called from inside per-timestep physics functions thousands of times per
    simulation run, so the file is parsed once and the parsed dict reused.
    Call `reload_calibration()` after writing a new calibration.json (e.g.
    from a fitting loop) to pick up the change.
    """
    return json.loads((PRESET_DIR / "calibration.json").read_text())


def reload_calibration() -> None:
    """Clear the `load_calibration` cache so the next call re-reads the file."""
    load_calibration.cache_clear()


def deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict: `override` wins, nested dicts merge, `None` means 'not set'."""
    out = deepcopy(base)
    for key, value in override.items():
        if value is None and key in out:
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out
