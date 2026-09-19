"""Command-line entry point. Stdout is result JSON; stderr is a JSON error object."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from solit2 import history as history_mod
from solit2.engines.fds import deck as fds_deck
from solit2.engines.fds import reader as fds_reader
from solit2.engines.fds import runner as fds_runner
from solit2.engines.reduced import envelope
from solit2.reports import correlation, test_plan
from solit2.schema.design import Design
from solit2.schema.result import Result

EXIT_OK, EXIT_VALIDATION_MISS, EXIT_BAD_INPUT, EXIT_ENGINE = 0, 1, 2, 3
FDS_POLL_S = 30.0


def _fail(message: str, field: str, fix: str, code: int) -> int:
    json.dump({"error": message, "field": field, "fix": fix}, sys.stderr)
    sys.stderr.write("\n")
    return code


def _write_out(path: Path, payload: dict) -> None:
    """Mirror the result to a file, creating its directory as the history does."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _cmd_fds_deck(args: argparse.Namespace) -> int:
    try:
        design = Design.load(args.design)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        return _fail(str(exc), getattr(exc, "field", "design"),
                     "correct the design JSON and try again", EXIT_BAD_INPUT)
    text = fds_deck.generate(design, fine_dx_m=args.dx)
    print(text)
    if args.out:
        try:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text + "\n")
        except OSError as exc:
            return _fail(str(exc), "--out", "choose a writable output path", EXIT_BAD_INPUT)
    return EXIT_OK


def _cmd_fds_status(args: argparse.Namespace) -> int:
    state = fds_runner.status(Path(args.run_dir))
    print(f"{state['state']}  {state['progress'] * 100:.0f}%  {state.get('detail', '')}".rstrip())
    return EXIT_OK


def _run_fds(design: Design, args: argparse.Namespace) -> Result:
    """Generate, launch, wait, read. Hours, not seconds -- by design."""
    problems = fds_runner.preflight()
    if problems:
        raise RuntimeError("; ".join(problems))
    from solit2.engines.reduced.envelope import _design_sha
    out_dir = Path(args.history).parent / _design_sha(design)
    out_dir.mkdir(parents=True, exist_ok=True)
    deck_path = out_dir / "deck.fds"
    deck_path.write_text(fds_deck.generate(design))
    fds_runner.run(deck_path, out_dir)
    while fds_runner.status(out_dir)["state"] == "running":
        time.sleep(FDS_POLL_S)
    if fds_runner.status(out_dir)["state"] == "failed":
        raise RuntimeError(f"the FDS run in {out_dir} failed; see {out_dir / 'run.out'}")
    return fds_reader.read(out_dir, design)


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        design = Design.load(args.design)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        return _fail(str(exc), getattr(exc, "field", "design"),
                     "correct the design JSON and run again", EXIT_BAD_INPUT)
    try:
        if args.engine == "fds":
            result = _run_fds(design, args)
        else:
            result = envelope.run(design)
    except (ArithmeticError, RuntimeError, ValueError, KeyError) as exc:
        return _fail(str(exc), "engine",
                     "the design validated but the engine could not finish the run",
                     EXIT_ENGINE)
    payload = result.model_dump(mode="json")
    if args.out:
        try:
            _write_out(Path(args.out), payload)
        except OSError as exc:
            return _fail(str(exc), "--out", "choose a writable output path",
                         EXIT_BAD_INPUT)
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    if not args.no_history:
        try:
            history_mod.append(result, Path(args.history))
        except OSError as exc:
            # The run itself succeeded and its result is already on stdout, so this
            # is a bad path, not a failed run: never exit 1 for it.
            return _fail(str(exc), "--history",
                         "the result is on stdout but was not recorded; "
                         "choose a writable history path", EXIT_BAD_INPUT)
    return EXIT_OK


def _cmd_history(args: argparse.Namespace) -> int:
    rows = history_mod.leaderboard(Path(args.history), args.top, args.passing)
    if not rows:
        print("no runs recorded yet")
        return EXIT_OK
    print(f"{'score':>6}  {'gates':>6}  {'flow lpm':>9}  {'kW':>6}  {'cost':>5}  design")
    for row in rows:
        gates = "pass" if row["gates_passed"] else "FAIL"
        print(f"{row['score']:6.2f}  {gates:>6}  {row['flow_lpm']:9.0f}  "
              f"{row['power_kw']:6.0f}  {row['cost_index']:5.2f}  {row['design_name']}")
    return EXIT_OK


def _cmd_validate(args: argparse.Namespace) -> int:
    from validation import compare

    ids = tuple(args.anchor) if args.anchor else None
    all_passed = True
    for anchor in compare.load_anchors(ids):
        report = compare.check(anchor, args.engine)
        print(f"\n{anchor.id}  ({anchor.source})")
        print(f"  {'quantity':<24} {'modelled':>12} {'measured':>12}  {'tolerance':<16} ok")
        for quantity, modelled, measured, tol, ok in report.rows:
            mark = "yes" if ok else "NO"
            print(f"  {quantity:<24} {modelled:>12.3g} {measured:>12.3g}  {tol:<16} {mark}")
            all_passed &= ok
    print("\nall anchors within tolerance" if all_passed else "\nsome anchors out of tolerance")
    return EXIT_OK if all_passed else EXIT_VALIDATION_MISS


def _load_result(path: str) -> Result:
    return Result.model_validate_json(Path(path).read_text())


def _emit_report(markdown: str, out: str | None) -> int:
    print(markdown)
    if out:
        try:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(markdown + "\n")
        except OSError as exc:
            return _fail(str(exc), "--out", "choose a writable output path",
                         EXIT_BAD_INPUT)
    return EXIT_OK


def _cmd_report_test_plan(args: argparse.Namespace) -> int:
    try:
        design = Design.load(args.design)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        return _fail(str(exc), getattr(exc, "field", "design"),
                     "correct the design JSON and try again", EXIT_BAD_INPUT)
    try:
        result = envelope.run(design)
    except (ArithmeticError, RuntimeError, ValueError, KeyError) as exc:
        return _fail(str(exc), "engine",
                     "the design validated but the engine could not finish the run",
                     EXIT_ENGINE)
    return _emit_report(test_plan.render(design, result), args.out)


def _cmd_report_correlation(args: argparse.Namespace) -> int:
    try:
        test_result = _load_result(args.test)
        site_result = _load_result(args.site)
    except (ValidationError, ValueError, OSError) as exc:
        field = "--test" if not Path(args.test).exists() else "--site"
        return _fail(str(exc), field,
                     "point --test and --site at result JSON produced by "
                     "`solit2 run --out`", EXIT_BAD_INPUT)
    return _emit_report(correlation.render(test_result, site_result), args.out)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="solit2", description="SOLIT2 tunnel water-mist simulator")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="score a design")
    run.add_argument("design")
    run.add_argument("--engine", default="reduced", choices=["reduced", "fds"],
                     help="'fds' generates a deck, runs it and parses the result; "
                          "a Tier 2 run takes hours, not seconds")
    run.add_argument("--out")
    run.add_argument("--history", default=str(history_mod.DEFAULT_PATH))
    run.add_argument("--no-history", action="store_true")
    run.set_defaults(func=_cmd_run)

    fdeck = sub.add_parser("fds-deck", help="write the FDS input deck for a design")
    fdeck.add_argument("design")
    fdeck.add_argument("--dx", type=float, default=fds_deck.FINE_DX_M,
                       help="cell size in the fine core mesh; the far meshes "
                            "scale with it")
    fdeck.add_argument("--out")
    fdeck.set_defaults(func=_cmd_fds_deck)

    fstat = sub.add_parser("fds-status", help="progress of an FDS run directory")
    fstat.add_argument("run_dir")
    fstat.set_defaults(func=_cmd_fds_status)

    hist = sub.add_parser("history", help="show the leaderboard")
    hist.add_argument("--history", default=str(history_mod.DEFAULT_PATH))
    hist.add_argument("--top", type=int, default=10)
    hist.add_argument("--passing", action="store_true")
    hist.set_defaults(func=_cmd_history)

    val = sub.add_parser("validate", help="check the engine against the anchor fire tests")
    val.add_argument("--engine", default="reduced", choices=["reduced"])
    val.add_argument("--anchor", action="append")
    val.set_defaults(func=_cmd_validate)

    report = sub.add_parser("report", help="generate a markdown report")
    report_sub = report.add_subparsers(dest="report_command", required=True)

    rtp = report_sub.add_parser("test-plan",
                                help="test inputs and predicted outcomes for a design")
    rtp.add_argument("design")
    rtp.add_argument("--out")
    rtp.set_defaults(func=_cmd_report_test_plan)

    rc = report_sub.add_parser("correlation",
                               help="one design's criteria across two runs, side by side")
    rc.add_argument("--test", required=True)
    rc.add_argument("--site", required=True)
    rc.add_argument("--out")
    rc.set_defaults(func=_cmd_report_correlation)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
