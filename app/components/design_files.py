"""Design files on disk, shared by every screen that offers one as a starting point
(the Design view's file picker, the simulator's presets) so the same folder is
scanned and the same shapes are filtered out exactly once."""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from solit2.compliance.spec import is_design_payload


def design_files(roots: Iterable[Path]) -> list[Path]:
    """Every design file under `roots`, sorted per root, roots in the order given.

    A compliance spec or a project rules file can live in the same folder
    (`*.rules.json`, `*-spec.json`) but is not a design, and offering one here
    would build a `Design` out of the wrong JSON shape. A file that fails to
    read or parse as JSON is skipped rather than raising -- this is a picklist,
    not a validation of the folder.
    """
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            try:
                raw = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if is_design_payload(raw):
                found.append(path)
    return found
