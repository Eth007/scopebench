"""Command-line interface for benchmark workflows."""

from __future__ import annotations

import argparse

from experiments.agent import run_model_scenario
from experiments.pipeline import run_experiment_pipeline
from experiments.preflight import run_preflight
from experiments.runner import run_experiment_matrix
from infra.lifecycle import ScenarioLifecycle
from infra.openrouter import OpenRouterClient
from scopebench.config import DEFAULT_CONFIG_PATH, load_config
from measurement.audit import verify_experiment_artifacts, write_audit_report
from measurement.gstudy import analyze_score_rows, component_rows
from measurement.io import read_score_rows, write_dict_rows, write_json
from measurement.report import generate_analysis_report
from measurement.workflow import (
    generate_demo,
    run_quickstart,
    score_transcripts,
    write_run_metrics_for_transcripts,
)

from .tui import run_tui


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="scopebench")
    _add_config_arg(parser, default=str(DEFAULT_CONFIG_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("generate-demo", help="generate synthetic transcript JSON files")
    _add_config_arg(demo)
    demo.add_argument("--out-dir", required=True)
    demo.add_argument("--seed", type=int)
    demo.set_defaults(func=_generate_demo)

    score = subparsers.add_parser("score", help="score transcript JSON files")
    _add_config_arg(score)
    score.add_argument("--transcripts", nargs="+", required=True)
    score.add_argument("--out", required=True)
    score.add_argument("--judge-mode", choices=("deterministic", "llm"), default="deterministic")
    score.set_defaults(func=_score)

    metrics = subparsers.add_parser("metrics", help="write run-level metric summaries")
    metrics.add_argument("--transcripts", nargs="+", required=True)
    metrics.add_argument("--out", required=True)
    metrics.set_defaults(func=_metrics)

    analyze = subparsers.add_parser("analyze", help="run balanced crossed G-study analysis")
    _add_config_arg(analyze)
    analyze.add_argument("--scores", required=True)
    analyze.add_argument("--out", required=True)
    analyze.add_argument("--summary-out", required=True)
    analyze.set_defaults(func=_analyze)

    quickstart = subparsers.add_parser("quickstart", help="run demo generation, scoring, and analysis")
    _add_config_arg(quickstart)
    quickstart.add_argument("--out-dir")
    quickstart.add_argument("--seed", type=int)
    quickstart.set_defaults(func=_quickstart)

    tui = subparsers.add_parser("tui", help="launch the terminal management UI")
    _add_config_arg(tui)
    tui.add_argument("--workspace")
    tui.set_defaults(func=_tui)

    scenario = subparsers.add_parser("scenario", help="manage scenario Docker infrastructure")
    _add_config_arg(scenario)
    scenario.add_argument("action", choices=("up", "down", "ps"))
    scenario.add_argument("scenario")
    scenario.set_defaults(func=_scenario)

    run_one = subparsers.add_parser("run-one", help="run one model-scenario experiment cell")
    _add_config_arg(run_one)
    run_one.add_argument("--model", required=True)
    run_one.add_argument("--scenario", required=True)
    run_one.add_argument("--out-dir")
    run_one.add_argument("--dry-run", action="store_true")
    run_one.add_argument("--no-manage-stack", action="store_true")
    run_one.set_defaults(func=_run_one)

    run_matrix = subparsers.add_parser("run-matrix", help="run configured model-scenario matrix")
    _add_config_arg(run_matrix)
    run_matrix.add_argument("--out-dir")
    run_matrix.add_argument("--dry-run", action="store_true")
    run_matrix.set_defaults(func=_run_matrix)

    pipeline = subparsers.add_parser(
        "run-pipeline",
        help="run experiments, metrics, scoring, and G-study",
    )
    _add_config_arg(pipeline)
    pipeline.add_argument("--out-dir")
    pipeline.add_argument("--dry-run", action="store_true")
    pipeline.add_argument("--judge-mode", choices=("deterministic", "llm"), default="deterministic")
    pipeline.set_defaults(func=_run_pipeline)

    validate_models = subparsers.add_parser(
        "validate-models",
        help="check configured OpenRouter model IDs against the OpenRouter models API",
    )
    _add_config_arg(validate_models)
    validate_models.set_defaults(func=_validate_models)

    verify_artifacts = subparsers.add_parser(
        "verify-artifacts",
        help="verify experiment artifacts against the configured design",
    )
    _add_config_arg(verify_artifacts)
    verify_artifacts.add_argument("--artifact-dir", required=True)
    verify_artifacts.add_argument("--report-out")
    verify_artifacts.set_defaults(func=_verify_artifacts)

    report = subparsers.add_parser(
        "report",
        help="generate descriptive analysis tables and qualitative examples",
    )
    _add_config_arg(report)
    report.add_argument("--artifact-dir", required=True)
    report.set_defaults(func=_report)

    preflight = subparsers.add_parser(
        "preflight",
        help="check Docker, OpenRouter, config, and optionally live scenario health",
    )
    _add_config_arg(preflight)
    preflight.add_argument("--live-scenarios", action="store_true")
    preflight.set_defaults(func=_preflight)

    args = parser.parse_args(argv)
    args.func(args)


def _add_config_arg(parser: argparse.ArgumentParser, default: str | None = None) -> None:
    kwargs = {"default": default} if default is not None else {"default": argparse.SUPPRESS}
    parser.add_argument(
        "--config",
        help="path to the global scopebench config YAML",
        **kwargs,
    )


def _generate_demo(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    paths = generate_demo(args.out_dir, seed=args.seed, config=config)
    print(f"wrote {len(paths)} transcripts to {args.out_dir}")


def _score(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    score_count, mean_score = score_transcripts(
        args.transcripts,
        args.out,
        config=config,
        judge_mode=args.judge_mode,
    )
    print(f"wrote {score_count} score rows to {args.out}")
    print(f"mean score: {mean_score:.3f}")


def _metrics(args: argparse.Namespace) -> None:
    count = write_run_metrics_for_transcripts(args.transcripts, args.out)
    print(f"wrote run metrics for {count} transcripts to {args.out}")


def _analyze(args: argparse.Namespace) -> None:
    rows = read_score_rows(args.scores)
    components, summary = analyze_score_rows(rows)
    write_dict_rows(component_rows(components), args.out)
    write_json(summary, args.summary_out)
    print(f"wrote {len(components)} variance components to {args.out}")
    print(
        "generalizability coefficient: "
        f"{summary['generalizability_coefficient']:.3f}; "
        f"dependability coefficient: {summary['dependability_coefficient']:.3f}"
    )


def _quickstart(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    out_dir = args.out_dir or config.quickstart_out_dir
    result = run_quickstart(out_dir, seed=args.seed, config=config)
    print(f"wrote {result.transcript_count} transcripts to {result.transcript_dir}")
    print(f"wrote {result.score_count} score rows to {result.scores_csv}")
    print(f"wrote G-study table to {result.gstudy_csv}")
    print(f"wrote summary to {result.summary_json}")


def _tui(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    run_tui(args.workspace or config.tui_workspace, config=config)


def _scenario(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    lifecycle = ScenarioLifecycle(args.scenario, config=config)
    if args.action == "up":
        lifecycle.up(build=True)
        print(f"started {args.scenario} at {lifecycle.host_base_url()}")
    elif args.action == "down":
        lifecycle.down()
        print(f"stopped {args.scenario}")
    else:
        result = lifecycle.ps()
        print(result.stdout or result.stderr)


def _run_one(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    out_dir = args.out_dir or config.experiment_out_dir
    result = run_model_scenario(
        args.model,
        args.scenario,
        out_dir=out_dir,
        config=config,
        dry_run=args.dry_run,
        manage_stack=not args.no_manage_stack,
    )
    print(f"wrote transcript to {result.transcript_path}")


def _run_matrix(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    out_dir = args.out_dir or config.experiment_out_dir
    result = run_experiment_matrix(out_dir=out_dir, config=config, dry_run=args.dry_run)
    print(f"wrote {len(result.transcript_paths)} transcripts to {out_dir}")


def _run_pipeline(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    out_dir = args.out_dir or config.experiment_out_dir
    result = run_experiment_pipeline(
        out_dir=out_dir,
        config=config,
        dry_run=args.dry_run,
        judge_mode=args.judge_mode,
    )
    print(f"wrote {result.transcript_count} transcripts to {result.transcript_dir}")
    print(f"wrote run metrics to {result.run_metrics_csv}")
    print(f"wrote {result.score_count} score rows to {result.scores_csv}")
    print(f"wrote G-study table to {result.gstudy_csv}")
    print(f"wrote summary to {result.summary_json}")
    print(f"wrote artifact audit to {result.audit_json}")
    print(f"wrote analysis report to {result.analysis_report_md}")
    print(f"wrote finding summary to {result.finding_summary_csv}")
    print(f"wrote finding evaluation to {result.finding_evaluation_md}")


def _validate_models(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    results = OpenRouterClient.from_config(config).validate_configured_models()
    missing = [model_id for model_id, present in results.items() if not present]
    for model_id, present in results.items():
        status = "ok" if present else "missing"
        print(f"{status}\t{model_id}")
    if missing:
        raise SystemExit(1)


def _verify_artifacts(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    result = verify_experiment_artifacts(args.artifact_dir, config=config)
    if args.report_out:
        write_audit_report(result, args.report_out)
    print(f"ok: {result.ok}")
    for key, value in sorted(result.counts.items()):
        print(f"{key}: {value}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    for error in result.errors:
        print(f"error: {error}")
    if not result.ok:
        raise SystemExit(1)


def _report(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    result = generate_analysis_report(args.artifact_dir, config=config)
    print(f"wrote analysis report to {result.report_md}")
    print(f"wrote model summary to {result.model_summary_csv}")
    print(f"wrote scenario summary to {result.scenario_summary_csv}")
    print(f"wrote judge summary to {result.judge_summary_csv}")
    print(f"wrote finding summary to {result.finding_summary_csv}")
    print(f"wrote finding evaluation to {result.finding_evaluation_md}")
    print(f"wrote dimension summary to {result.dimension_summary_csv}")
    print(f"wrote qualitative examples to {result.qualitative_examples_md}")


def _preflight(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    result = run_preflight(config=config, live_scenarios=args.live_scenarios)
    for check in result.checks:
        status = "ok" if check.ok else "fail"
        print(f"{status}\t{check.name}\t{check.detail}")
    if not result.ok:
        raise SystemExit(1)
