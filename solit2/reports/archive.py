"""Save an assessment and everything behind it, so it can be re-read later.

A report on its own ages badly. Six months on, the numbers in it cannot be
checked without the design that produced them, the engine version that ran,
and the calibration the engine was carrying at the time -- and the last of
those is a file in this repository that changes. An archive keeps all of it
together in one timestamped folder.

Nothing here interprets anything. It copies what already exists.
"""
from __future__ import annotations

import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from solit2.schema.design import Design
from solit2.schema.presets import load_calibration
from solit2.schema.result import Result

STAMP_FORMAT = "%Y%m%d-%H%M%S"


def _git_commit() -> str:
    """The commit the tool was at, or a plain statement that it is unknown."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = out.stdout.strip()
    if out.returncode != 0 or not commit:
        return "unknown"
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                           text=True, timeout=5, check=False)
    return commit + (" (working tree modified)" if dirty.stdout.strip() else "")


def validation_text() -> str:
    """`solit2 validate` as text, however it exits.

    A non-zero exit is the normal case today and is not an error to swallow:
    the point of putting it in an archive is that it records where the engine
    stood, misses included.
    """
    try:
        out = subprocess.run(["uv", "run", "solit2", "validate"], capture_output=True,
                             text=True, timeout=600, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"validation could not be run: {exc}"
    return (out.stdout or "") + (out.stderr or "")


def provenance(design: Design, result: Result) -> dict:
    """Everything needed to say what produced this, and to reproduce it."""
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "design_name": design.meta.name,
        "design_sha": result.meta.get("design_sha"),
        "engine": result.meta.get("engine"),
        "engine_version": result.meta.get("engine_version"),
        "tool_commit": _git_commit(),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
    }


def write(root: Path, design: Design, result: Result, markdown: str,
          tier2: Result | None = None, validation: str | None = None,
          deck_text: str | None = None) -> list[Path]:
    """Write the archive and return every file written, report first.

    The folder is named for the design and the instant, so repeated
    assessments accumulate rather than overwrite: an archive that replaces
    the previous one cannot show that an answer changed.
    """
    root = Path(root)
    folder = root / f"{design.meta.name}-{datetime.now(timezone.utc).strftime(STAMP_FORMAT)}"
    folder.mkdir(parents=True, exist_ok=True)

    files: list[tuple[str, str]] = [
        ("assessment.md", markdown),
        ("result.json", result.model_dump_json(indent=2)),
        # The design AS THE ENGINE SAW IT: presets merged in, defaults resolved.
        # The source file alone does not say what a preset contributed, and a
        # preset can change under it.
        ("design.resolved.json", design.model_dump_json(indent=2)),
        # The fitted constants in force at the time. These move, and a result
        # cannot be reproduced without the set that produced it.
        ("calibration.json", json.dumps(load_calibration(), indent=2)),
        ("provenance.json", json.dumps(provenance(design, result), indent=2)),
    ]
    if tier2 is not None:
        files.append(("result.tier2.json", tier2.model_dump_json(indent=2)))
    if validation:
        files.append(("validation.txt", validation))
    if deck_text:
        files.append(("deck.fds", deck_text))

    written = []
    for name, text in files:
        path = folder / name
        path.write_text(text if text.endswith("\n") else text + "\n")
        written.append(path)
    return written
