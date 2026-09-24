"""Command-line entry point. Stdout is result JSON; stderr is a JSON error object."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from solit2 import history as history_mod
from solit2.engines.fds import calibrate as fds_calibrate
from solit2.engines.fds import campaign as fds_campaign
from solit2.engines.fds import deck as fds_deck
from solit2.engines.fds import exec_run as fds_exec
from solit2.engines.fds import grid as fds_grid
from solit2.engines.fds import reader as fds_reader
from solit2.engines.fds import runner as fds_runner
from solit2.engines.reduced import envelope
from solit2.reports import archive as archive_mod
from solit2.reports import assessment, correlation, test_plan
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
    try:
        text = fds_deck.generate(design, dx_m=args.dx,
                                 t_end_s=(args.minutes * 60.0 if args.minutes else None),
                                 suppression=not args.free_burn)
    except ValueError as exc:
        return _fail(str(exc), "--dx",
                     "choose a cell size that tiles the window into equal "
                     "whole-cell meshes, e.g. 0.5 or 0.6", EXIT_BAD_INPUT)
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


def _cmd_fds_exec(args: argparse.Namespace) -> int:
    """Block until FDS finishes for one run directory -- what
    scripts/cfd_queue.sh and deploy/systemd/solit2-cfd.service call, one run
    directory at a time, on the dedicated CFD server; see
    docs/cloud-compute.md."""
    run_dir = Path(args.run_dir)
    try:
        returncode = fds_exec.run_foreground(run_dir, t_end_s=args.t_end)
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        return _fail(str(exc), "run_dir",
                     "fix the reported problem (missing binary, missing design.json, "
                     "a moved mesh) and run fds-exec again", EXIT_ENGINE)
    if returncode != 0:
        return _fail(f"FDS did not complete in {run_dir}; see {run_dir / fds_runner.LOG_NAME} "
                     f"and {run_dir / fds_exec.LOG_NAME}", "run_dir",
                     "inspect the FDS log for the reported error", EXIT_ENGINE)
    return EXIT_OK


def _cmd_fds_calibrate_e(args: argparse.Namespace) -> int:
    from validation import compare
    try:
        anchors = compare.load_anchors(tuple(args.anchor))
    except (FileNotFoundError, ValidationError, ValueError, KeyError) as exc:
        return _fail(str(exc), "--anchor",
                     "use anchor ids that exist under validation/anchors/", EXIT_BAD_INPUT)
    out = Path(args.out)
    e_values = tuple(args.e)
    try:
        fds_calibrate.write_decks(anchors, e_values, args.dx, out)
    except ValueError as exc:
        return _fail(str(exc), "--dx",
                     "choose a cell size that tiles the window into equal "
                     "whole-cell meshes, e.g. 0.5 or 0.6", EXIT_BAD_INPUT)
    if args.run:
        problems = fds_runner.preflight()
        if problems:
            return _fail("; ".join(problems), "--run",
                         "install FDS and mpiexec, or free disk space, before launching",
                         EXIT_ENGINE)
        fds_calibrate.launch_and_wait(anchors, e_values, args.dx, out)
    if args.report:
        points = fds_calibrate.read_points(anchors, e_values, args.dx, out)
        errors = fds_calibrate.weighted_error_by_e(anchors, points)
        fit = fds_calibrate.best_e(errors)
        markdown = fds_calibrate.render(anchors, points, errors, fit, args.dx)
        print(markdown)
        try:
            out.mkdir(parents=True, exist_ok=True)
            (out / "report.md").write_text(markdown + "\n")
            (out / "report.json").write_text(json.dumps(
                fds_calibrate.to_json(anchors, points, errors, fit, args.dx), indent=2))
        except OSError as exc:
            return _fail(str(exc), "--out", "choose a writable output directory",
                         EXIT_BAD_INPUT)
    return EXIT_OK


def _cmd_fds_grid_study(args: argparse.Namespace) -> int:
    try:
        design = Design.load(args.design)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        return _fail(str(exc), getattr(exc, "field", "design"),
                     "correct the design JSON and try again", EXIT_BAD_INPUT)
    out = Path(args.out)
    dx_values = tuple(args.dx)
    try:
        fds_grid.write_decks(design, dx_values, args.t_end, out)
    except ValueError as exc:
        return _fail(str(exc), "--dx",
                     "choose cell sizes that each tile the window into equal "
                     "whole-cell meshes, e.g. 0.5, 0.6, 0.75, 1.0 or 1.2", EXIT_BAD_INPUT)
    if args.run:
        problems = fds_runner.preflight()
        if problems:
            return _fail("; ".join(problems), "--run",
                         "install FDS and mpiexec, or free disk space, before launching",
                         EXIT_ENGINE)
        fds_grid.launch_and_wait(design, dx_values, out, t_end_s=args.t_end)
    if args.report:
        grids = fds_grid.read_grids(design, dx_values, out)
        markdown = fds_grid.render(grids, args.t_end)
        print(markdown)
        try:
            out.mkdir(parents=True, exist_ok=True)
            (out / "report.md").write_text(markdown + "\n")
            (out / "report.json").write_text(json.dumps(fds_grid.to_json(grids, args.t_end),
                                                         indent=2))
        except OSError as exc:
            return _fail(str(exc), "--out", "choose a writable output directory",
                         EXIT_BAD_INPUT)
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


def _cmd_report_assessment(args: argparse.Namespace) -> int:
    try:
        design = Design.load(args.design)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        return _fail(str(exc), getattr(exc, "field", "design"),
                     "correct the design JSON and try again", EXIT_BAD_INPUT)
    try:
        result = envelope.run(design)
    except (ValueError, KeyError) as exc:
        return _fail(str(exc), "engine",
                     "the design validated but the engine could not finish the run",
                     EXIT_ENGINE)
    tier2 = None
    if args.tier2:
        try:
            tier2 = _load_result(args.tier2)
        except (ValidationError, ValueError, OSError) as exc:
            return _fail(str(exc), "--tier2",
                         "point --tier2 at a result JSON from `solit2 run --engine fds --out`",
                         EXIT_BAD_INPUT)
    validation = archive_mod.validation_text() if args.with_validation else None
    markdown = assessment.render(design, result, tier2=tier2, validation=validation)
    if args.archive:
        try:
            written = archive_mod.write(Path(args.archive), design, result, markdown,
                                        tier2=tier2, validation=validation)
        except OSError as exc:
            return _fail(str(exc), "--archive", "choose a writable directory", EXIT_BAD_INPUT)
        print(f"archived {len(written)} files to {written[0].parent}", file=sys.stderr)
    return _emit_report(markdown, args.out)


def _cmd_fds_campaign(args: argparse.Namespace) -> int:
    try:
        design = Design.load(args.design)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        return _fail(str(exc), getattr(exc, "field", "design"),
                     "correct the design JSON and try again", EXIT_BAD_INPUT)
    problems = fds_runner.preflight()
    if problems:
        return _fail("; ".join(problems), "campaign",
                     "install FDS and mpiexec, or free disk space, before launching",
                     EXIT_ENGINE)
    try:
        fds_campaign.run_campaign(
            design, Path(args.out), e_anchor_ids=tuple(args.e_anchor),
            e_values=tuple(args.e), dx_m=args.dx, grid_dx=tuple(args.grid_dx),
            grid_t_end_s=args.grid_t_end,
            print_fn=lambda msg: print(msg, file=sys.stderr))
    except (ArithmeticError, RuntimeError, ValueError, KeyError, FileNotFoundError) as exc:
        return _fail(str(exc), "campaign", "see the message for which step failed and why",
                     EXIT_ENGINE)
    return EXIT_OK


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
    fdeck.add_argument("--dx", type=float, default=fds_deck.DX_M,
                       help="cell size for every mesh; must tile the window "
                            "into equal whole-cell meshes (0.5 or 0.6 do)")
    fdeck.add_argument("--minutes", type=float,
                       help="simulate only this many minutes instead of the "
                            "design's full discharge duration. This shortens "
                            "the RUN, not the system: zones.duration_min sizes "
                            "the water tank and the cost index, so editing it "
                            "to cut a run short would redesign the system")
    fdeck.add_argument("--free-burn", action="store_true",
                       help="the same fire in the same tunnel with no mist system: "
                            "the reference the mist run is compared against")
    fdeck.add_argument("--out")
    fdeck.set_defaults(func=_cmd_fds_deck)

    fstat = sub.add_parser("fds-status", help="progress of an FDS run directory")
    fstat.add_argument("run_dir")
    fstat.set_defaults(func=_cmd_fds_status)

    fexec = sub.add_parser(
        "fds-exec",
        help="run FDS for a run directory in the FOREGROUND, blocking until it "
             "finishes or fails -- what the CFD server's run queue calls "
             "(see scripts/cfd_queue.sh and docs/cloud-compute.md)")
    fexec.add_argument("run_dir", help="a directory already holding deck.fds "
                                       "(and design.json, if it may ever need to resume)")
    fexec.add_argument("--t-end", type=float,
                       help="simulated window in seconds, used only when resuming from "
                            "restart files to regenerate the deck; a fresh run keeps "
                            "whatever T_END is already in deck.fds")
    fexec.set_defaults(func=_cmd_fds_exec)

    fcal = sub.add_parser(
        "fds-calibrate-e",
        help="sweep FDS's E_COEFFICIENT against the published anchor fire tests")
    fcal.add_argument("--anchor", nargs="+", required=True,
                      help="anchor ids from validation/anchors/, e.g. c4 c5")
    fcal.add_argument("--e", nargs="+", type=float, required=True,
                      help="E_COEFFICIENT values to sweep, e.g. 0.1 0.2 0.4 0.8")
    fcal.add_argument("--dx", type=float, default=fds_deck.DX_M,
                      help="cell size for every sweep point; a fitted E applies at "
                           "this dx only")
    fcal.add_argument("--out", required=True,
                      help="decks are written to <out>/<anchor>/e_<E>_dx_<dx>/deck.fds")
    fcal.add_argument("--run", action="store_true",
                      help="launch every sweep point sequentially and wait for each; "
                           "without this, only the decks are written")
    fcal.add_argument("--report", action="store_true",
                      help="read whatever sweep points have finished and write "
                           "<out>/report.md and <out>/report.json")
    fcal.set_defaults(func=_cmd_fds_calibrate_e)

    fgrid = sub.add_parser(
        "fds-grid-study",
        help="a Celik et al. (2008) grid-convergence study across three cell sizes")
    fgrid.add_argument("design")
    fgrid.add_argument("--dx", nargs=3, type=float, required=True, metavar=("H1", "H2", "H3"),
                       help="three cell sizes, finest first, each valid for `deck`")
    fgrid.add_argument("--t-end", type=float, required=True,
                       help="simulated window in seconds; a grid study need not run "
                            "the full design duration")
    fgrid.add_argument("--out", required=True,
                       help="decks are written to <out>/<chid>/dx_<dx>/deck.fds")
    fgrid.add_argument("--run", action="store_true",
                       help="launch every grid sequentially and wait for each; "
                            "without this, only the decks are written")
    fgrid.add_argument("--report", action="store_true",
                       help="read whatever grids have finished and write "
                            "<out>/report.md and <out>/report.json")
    fgrid.set_defaults(func=_cmd_fds_grid_study)

    fcamp = sub.add_parser(
        "fds-campaign",
        help="chain the E sweep, the grid study and a full-duration run behind one "
             "command; battery refusal and the caffeinate wrap live in "
             "scripts/tier2_campaign.sh, the supported way to run this")
    fcamp.add_argument("design", help="the design the grid study and the full-duration "
                                      "run assess")
    fcamp.add_argument("--e-anchor", nargs="+", default=["c4", "c5"],
                       help="anchor ids for the E sweep (default: c4 c5)")
    fcamp.add_argument("--e", nargs="+", type=float, default=[0.1, 0.2, 0.4, 0.8],
                       help="E_COEFFICIENT values to sweep")
    fcamp.add_argument("--dx", type=float, default=fds_deck.DX_M,
                       help="cell size for the E sweep and the full-duration run")
    fcamp.add_argument("--grid-dx", nargs=3, type=float, required=True,
                       metavar=("H1", "H2", "H3"),
                       help="three cell sizes for the grid-convergence study")
    fcamp.add_argument("--grid-t-end", type=float, required=True,
                       help="simulated window, in seconds, for the grid study")
    fcamp.add_argument("--out", required=True)
    fcamp.set_defaults(func=_cmd_fds_campaign)

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

    ra = report_sub.add_parser(
        "assessment", help="the full assessment document for a design")
    ra.add_argument("design")
    ra.add_argument("--tier2", help="a Tier 2 result JSON to correlate against")
    ra.add_argument("--with-validation", action="store_true",
                    help="include the engine's standing against the reference fire tests")
    ra.add_argument("--archive", metavar="DIR",
                    help="also save the report and every input and output behind it into a "
                         "timestamped folder under DIR, so the assessment can be reproduced "
                         "and audited later")
    ra.add_argument("--out")
    ra.set_defaults(func=_cmd_report_assessment)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
