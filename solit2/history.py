"""Append-only run history and the leaderboard it backs."""
from __future__ import annotations

import json
from pathlib import Path

from solit2.schema.result import Result

DEFAULT_PATH = Path("runs/history.jsonl")


def append(result: Result, path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": result.meta["timestamp"],
        "design_name": result.meta["design_name"],
        "design_sha": result.meta["design_sha"],
        "engine": result.meta["engine"],
        "score": result.score["total"],
        "gates_passed": result.score["gates_passed"],
        "gates_failed": result.score["gates_failed"],
        "flow_lpm": result.hydraulics["flow_lpm"],
        "power_kw": result.hydraulics["power_kw"],
        "cost_index": result.cost["index"],
    }
    with path.open("a") as handle:
        handle.write(json.dumps(row) + "\n")


def leaderboard(path: Path = DEFAULT_PATH, top: int = 10,
                passing_only: bool = False) -> list[dict]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if passing_only:
        rows = [r for r in rows if r["gates_passed"]]
    return sorted(rows, key=lambda r: r["score"], reverse=True)[:top]
