"""Preset lookup and merge.

A design JSON names a preset per block and overrides individual fields; the
preset supplies everything else.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

PRESET_DIR = Path(__file__).resolve().parent.parent / "presets"
# Illustrations live outside the package: they are examples of how a design is
# put together, never defaults, and the tool must run without them.
EXAMPLE_PRESET_DIR = PRESET_DIR.parent.parent / "examples" / "presets"
# Shipped presets win a name collision, so an example can never shadow the
# standard's own test tunnel or fire loads.
SEARCH_PATH = (PRESET_DIR, EXAMPLE_PRESET_DIR)

_KIND_PREFIX = {
    "tunnel": "tunnel_",
    "nozzle": "nozzle_",
    "fire": "fire_",
    "hydraulics": "hydraulics_",
}


def _available(prefix: str) -> list[str]:
    """Every preset name of one kind, from both locations, de-duplicated."""
    seen: dict[str, None] = {}
    for directory in SEARCH_PATH:
        for path in sorted(directory.glob(f"{prefix}*.json")):
            seen.setdefault(path.stem[len(prefix):], None)
    return sorted(seen)


def load_preset(kind: str, name: str) -> dict:
    """Load `<kind>_<name>.json` from the shipped presets, then the examples."""
    if kind not in _KIND_PREFIX:
        raise KeyError(f"unknown preset kind {kind!r}; expected one of {sorted(_KIND_PREFIX)}")
    prefix = _KIND_PREFIX[kind]
    for directory in SEARCH_PATH:
        path = directory / f"{prefix}{name}.json"
        if path.exists():
            return json.loads(path.read_text())
    raise FileNotFoundError(f"no {kind} preset {name!r}; available: {_available(prefix)}")


@lru_cache(maxsize=1)
def load_calibration() -> dict:
    """Load `presets/calibration.json`, cached.

    Called from inside per-timestep physics functions thousands of times per
    simulation run, so the file is parsed once and the parsed dict reused.
    Call `reload_calibration()` after writing a new calibration.json (e.g.
    from a fitting loop) to pick up the change.
    """
    return json.loads((PRESET_DIR / "calibration.json").read_text())


# Every module that caches something computed FROM calibration -- even only
# indirectly, through a function it calls that reads a constant this module
# never sees -- registers its cache's `.clear` here at import time. This is the
# one chokepoint every calibration write goes through (`apply_vector`, and
# nowhere else): hand-threading each individual constant into `reload_calibration`
# is fragile, because the next person who reads a calibration value from inside
# a cached function will reintroduce the same staleness unless they remember
# that exact discipline. Registering unconditionally means no constant can opt
# out of invalidation by omission.
_CACHE_INVALIDATION_HOOKS: list[Callable[[], None]] = []


def register_cache_invalidation_hook(hook: Callable[[], None]) -> None:
    """Run `hook()` on every future `reload_calibration()`, starting now."""
    _CACHE_INVALIDATION_HOOKS.append(hook)


def reload_calibration() -> None:
    """Clear the `load_calibration` cache, and every registered dependent cache."""
    load_calibration.cache_clear()
    for hook in _CACHE_INVALIDATION_HOOKS:
        hook()


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
