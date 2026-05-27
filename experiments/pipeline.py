"""End-to-end experiment pipeline."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from experiments.runner import run_experiment_matrix
from measurement.audit import verify_experiment_artifacts, write_audit_report
from measurement.report import generate_analysis_report
from measurement.workflow import analyze_scores, score_transcripts, write_run_metrics_for_transcripts
from measurement.io import write_json
from scopebench.config import ScopebenchConfig, load_config


@dataclass(frozen=True)
class ExperimentPipelineResult:
    """Paths produced by a complete experiment pipeline."""

    transcript_dir: Path
    run_metrics_csv: Path
    scores_csv: Path
    gstudy_csv: Path
    summary_json: Path
    audit_json: Path
    analysis_report_md: Path
    finding_summary_csv: Path
    finding_evaluation_md: Path
    transcript_count: int
    score_count: int


def run_experiment_pipeline(
    out_dir: str | Path,
    config: ScopebenchConfig | None = None,
    dry_run: bool = False,
    judge_mode: str = "deterministic",
    models: tuple[str, ...] | None = None,
    scenarios: tuple[str, ...] | None = None,
    require_full_design: bool = True,
    progress: Callable[[str], None] | None = None,
) -> ExperimentPipelineResult:
    """Run experiments, write metrics, score transcripts, and run G-study."""

    config = config or load_config()
    out_dir = Path(out_dir)
    model_names = models or config.model_names
    scenario_names = scenarios or config.scenario_names
    transcript_dir = out_dir / "transcripts"
    run_metrics_csv = out_dir / "run_metrics.csv"
    scores_csv = out_dir / "scores.csv"
    gstudy_csv = out_dir / "gstudy.csv"
    summary_json = out_dir / "summary.json"
    audit_json = out_dir / "artifact_audit.json"

    if progress:
        progress("running model-scenario matrix")
    matrix = run_experiment_matrix(
        transcript_dir,
        config=config,
        dry_run=dry_run,
        models=model_names,
        scenarios=scenario_names,
        progress=progress,
    )
    transcript_paths = list(matrix.transcript_paths)
    write_run_metrics_for_transcripts(transcript_paths, run_metrics_csv, progress=progress)
    if progress:
        progress(f"scoring transcripts with {judge_mode} judges")
    score_count, mean_score = score_transcripts(
        transcript_paths,
        scores_csv,
        config=config,
        judge_mode=judge_mode,
        progress=progress,
    )
    summary = _analyze_if_supported(
        scores_csv,
        gstudy_csv,
        summary_json,
        model_names,
        scenario_names,
        config.judge_names,
        config.dimensions,
        progress=progress,
    )
    if progress:
        progress("generating analysis report")
    analysis = generate_analysis_report(out_dir, config=_analysis_config(config, dry_run))
    summary.update(
        {
            "config_path": str(config.path),
            "dry_run": dry_run,
            "judge_mode": judge_mode,
            "transcript_dir": str(transcript_dir),
            "run_metrics_csv": str(run_metrics_csv),
            "scores_csv": str(scores_csv),
            "gstudy_csv": str(gstudy_csv),
            "analysis_report_md": str(analysis.report_md),
            "finding_summary_csv": str(analysis.finding_summary_csv),
            "finding_evaluation_md": str(analysis.finding_evaluation_md),
            "mean_score": mean_score,
            "models": list(model_names),
            "scenarios": list(scenario_names),
            "judges": list(config.judge_names),
            "dimensions": list(config.dimensions),
            "require_full_design": require_full_design,
        }
    )
    write_json(summary, summary_json)
    if require_full_design:
        if progress:
            progress("verifying artifact coverage")
        audit = verify_experiment_artifacts(out_dir, config=config)
        write_audit_report(audit, audit_json)
        if progress:
            progress(f"artifact audit ok={audit.ok}")
    elif progress:
        progress("skipping full-design artifact audit for selected subset run")
    return ExperimentPipelineResult(
        transcript_dir=transcript_dir,
        run_metrics_csv=run_metrics_csv,
        scores_csv=scores_csv,
        gstudy_csv=gstudy_csv,
        summary_json=summary_json,
        audit_json=audit_json,
        analysis_report_md=analysis.report_md,
        finding_summary_csv=analysis.finding_summary_csv,
        finding_evaluation_md=analysis.finding_evaluation_md,
        transcript_count=len(transcript_paths),
        score_count=score_count,
    )


def _analysis_config(config: ScopebenchConfig, dry_run: bool) -> ScopebenchConfig:
    if not dry_run:
        return config
    data = copy.deepcopy(config.data)
    data.setdefault("findings", {})["match_mode"] = "keywords"
    return ScopebenchConfig(path=config.path, data=data)


def _analyze_if_supported(
    scores_csv: Path,
    gstudy_csv: Path,
    summary_json: Path,
    model_names: tuple[str, ...],
    scenario_names: tuple[str, ...],
    judge_names: tuple[str, ...],
    dimensions: tuple[str, ...],
    progress: Callable[[str], None] | None = None,
) -> dict[str, float | int | str | None]:
    if len(model_names) >= 2 and len(scenario_names) >= 2:
        return analyze_scores(scores_csv, gstudy_csv, summary_json, progress=progress)
    if progress:
        progress("skipping G-study; selected run needs at least 2 models and 2 scenarios")
    summary: dict[str, float | int | str | None] = {
        "model_universe_variance": None,
        "relative_error_variance": None,
        "absolute_error_variance": None,
        "generalizability_coefficient": None,
        "dependability_coefficient": None,
        "n_models": len(model_names),
        "n_scenarios": len(scenario_names),
        "n_judges": len(judge_names),
        "n_dimensions": len(dimensions),
        "gstudy_status": "skipped_for_subset",
    }
    write_json(summary, summary_json)
    gstudy_csv.parent.mkdir(parents=True, exist_ok=True)
    gstudy_csv.write_text("", encoding="utf-8")
    return summary
