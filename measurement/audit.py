"""Artifact verification for completed experiment runs."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from itertools import combinations
from pathlib import Path
from typing import Any

from measurement.metrics import RUN_METRIC_FIELDS
from measurement.schemas import TranscriptRun, load_transcript
from scopebench.config import ScopebenchConfig, load_config


REQUIRED_SCENARIO_METRICS = {
    "saas_site": (
        "failed_login_attempts",
        "pii_records_exposed",
        "unsafe_state_changes",
        "credential_misuse",
    ),
    "water_ics": (
        "unsafe_state_changes",
        "plant_within_safe_bounds",
        "read_count",
    ),
}


@dataclass(frozen=True)
class ArtifactAuditResult:
    """Result from verifying experiment artifacts."""

    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        """Serialize audit result for JSON output."""

        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "counts": self.counts,
        }


def verify_experiment_artifacts(
    artifact_dir: str | Path,
    config: ScopebenchConfig | None = None,
) -> ArtifactAuditResult:
    """Verify final experiment artifacts against the configured design."""

    config = config or load_config()
    artifact_dir = Path(artifact_dir)
    transcript_dir = artifact_dir / "transcripts"
    scores_path = artifact_dir / "scores.csv"
    metrics_path = artifact_dir / "run_metrics.csv"
    gstudy_path = artifact_dir / "gstudy.csv"
    summary_path = artifact_dir / "summary.json"
    analysis_dir = artifact_dir / "analysis"

    errors: list[str] = []
    warnings: list[str] = []
    counts: dict[str, int] = {}

    runs = _load_transcripts(transcript_dir, errors)
    counts["transcripts"] = len(runs)
    _verify_transcript_matrix(runs, config, errors)
    _verify_transcript_contents(runs, config, errors, warnings)

    metric_rows = _read_csv(metrics_path, errors)
    counts["run_metric_rows"] = len(metric_rows)
    _verify_run_metrics(metric_rows, config, errors)

    score_rows = _read_csv(scores_path, errors)
    counts["score_rows"] = len(score_rows)
    _verify_scores(score_rows, config, errors)

    gstudy_rows = _read_csv(gstudy_path, errors)
    counts["gstudy_rows"] = len(gstudy_rows)
    _verify_gstudy(gstudy_rows, config, errors)

    summary = _read_json(summary_path, errors)
    _verify_summary(summary, config, errors, warnings)
    _verify_analysis_outputs(analysis_dir, errors)

    return ArtifactAuditResult(
        ok=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        counts=counts,
    )


def write_audit_report(result: ArtifactAuditResult, path: str | Path) -> None:
    """Write an artifact audit report as JSON."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(result.to_dict(), handle, indent=2, sort_keys=True)
        handle.write("\n")


def _load_transcripts(transcript_dir: Path, errors: list[str]) -> list[TranscriptRun]:
    if not transcript_dir.exists():
        errors.append(f"missing transcript directory: {transcript_dir}")
        return []
    runs: list[TranscriptRun] = []
    for path in sorted(transcript_dir.glob("*.json")):
        try:
            runs.append(load_transcript(path))
        except Exception as exc:
            errors.append(f"invalid transcript {path}: {exc}")
    return runs


def _verify_transcript_matrix(
    runs: list[TranscriptRun],
    config: ScopebenchConfig,
    errors: list[str],
) -> None:
    expected = {(model, scenario) for model in config.model_names for scenario in config.scenario_names}
    observed: dict[tuple[str, str], list[str]] = {}
    for run in runs:
        observed.setdefault((run.model, run.scenario), []).append(run.run_id)
    missing = expected - set(observed)
    extra = set(observed) - expected
    duplicates = {key: ids for key, ids in observed.items() if len(ids) > 1}
    if missing:
        errors.append(f"missing transcript cells: {sorted(missing)}")
    if extra:
        errors.append(f"unexpected transcript cells: {sorted(extra)}")
    if duplicates:
        errors.append(f"duplicate transcript cells: {duplicates}")


def _verify_transcript_contents(
    runs: list[TranscriptRun],
    config: ScopebenchConfig,
    errors: list[str],
    warnings: list[str],
) -> None:
    required_event_kinds = {"message", "model_message", "observation"}
    for run in runs:
        kinds = {event.kind for event in run.events}
        missing_kinds = required_event_kinds - kinds
        if missing_kinds:
            errors.append(f"{run.run_id} missing event kinds: {sorted(missing_kinds)}")
        if not run.availability_checks:
            errors.append(f"{run.run_id} has no availability checks")
        if not any("rules_of_engagement" in event.tags for event in run.events):
            errors.append(f"{run.run_id} does not log rules of engagement")
        for metric in REQUIRED_SCENARIO_METRICS.get(run.scenario, ()):
            if metric not in run.scenario_metrics:
                errors.append(f"{run.run_id} missing scenario metric: {metric}")
        if "command" not in kinds:
            warnings.append(f"{run.run_id} has no command event; this may indicate refusal")
        if run.scenario not in config.scenario_names:
            errors.append(f"{run.run_id} has unknown scenario: {run.scenario}")
        if run.model not in config.model_names:
            errors.append(f"{run.run_id} has unknown model: {run.model}")


def _verify_run_metrics(
    rows: list[dict[str, str]],
    config: ScopebenchConfig,
    errors: list[str],
) -> None:
    expected_count = len(config.model_names) * len(config.scenario_names)
    if len(rows) != expected_count:
        errors.append(f"run_metrics.csv has {len(rows)} rows; expected {expected_count}")
    required = set(RUN_METRIC_FIELDS)
    for index, row in enumerate(rows, start=1):
        missing = required - set(row)
        if missing:
            errors.append(f"run_metrics.csv row {index} missing fields: {sorted(missing)}")
        for key in ("availability", "pii_records_exposed", "unsafe_state_changes", "useful_steps"):
            _require_numeric(row, key, f"run_metrics.csv row {index}", errors)


def _verify_scores(
    rows: list[dict[str, str]],
    config: ScopebenchConfig,
    errors: list[str],
) -> None:
    expected = {
        (model, scenario, judge, dimension)
        for model in config.model_names
        for scenario in config.scenario_names
        for judge in config.judge_names
        for dimension in config.dimensions
    }
    observed: dict[tuple[str, str, str, str], int] = {}
    score_min = float(config.data["rubric"].get("score_min", 0.0))
    score_max = float(config.data["rubric"].get("score_max", 1.0))
    for index, row in enumerate(rows, start=1):
        key = tuple(row.get(field, "") for field in ("model", "scenario", "judge", "dimension"))
        observed[key] = observed.get(key, 0) + 1
        try:
            score = float(row["score"])
        except (KeyError, ValueError):
            errors.append(f"scores.csv row {index} has invalid score")
            continue
        if score < score_min or score > score_max:
            errors.append(f"scores.csv row {index} score out of range: {score}")
        if not row.get("rationale"):
            errors.append(f"scores.csv row {index} missing rationale")
    missing = expected - set(observed)
    extra = set(observed) - expected
    duplicates = {key: count for key, count in observed.items() if count > 1}
    if missing:
        errors.append(f"missing score cells: {sorted(missing)[:10]} ({len(missing)} total)")
    if extra:
        errors.append(f"unexpected score cells: {sorted(extra)[:10]} ({len(extra)} total)")
    if duplicates:
        errors.append(f"duplicate score cells: {duplicates}")


def _verify_gstudy(
    rows: list[dict[str, str]],
    config: ScopebenchConfig,
    errors: list[str],
) -> None:
    facets = ("model", "scenario", "judge", "dimension")
    expected_components = {
        ":".join(subset)
        for size in range(1, len(facets) + 1)
        for subset in combinations(facets, size)
    }
    observed_components = {row.get("component", "") for row in rows}
    missing = expected_components - observed_components
    if missing:
        errors.append(f"gstudy.csv missing components: {sorted(missing)}")
    for index, row in enumerate(rows, start=1):
        for key in ("df", "mean_square", "variance", "percent_total"):
            _require_numeric(row, key, f"gstudy.csv row {index}", errors)
    if len(rows) != len(expected_components):
        errors.append(f"gstudy.csv has {len(rows)} rows; expected {len(expected_components)}")


def _verify_summary(
    summary: dict[str, Any],
    config: ScopebenchConfig,
    errors: list[str],
    warnings: list[str],
) -> None:
    required = {
        "generalizability_coefficient",
        "dependability_coefficient",
        "n_models",
        "n_scenarios",
        "n_judges",
        "n_dimensions",
        "models",
        "scenarios",
        "judges",
        "dimensions",
    }
    missing = required - set(summary)
    if missing:
        errors.append(f"summary.json missing keys: {sorted(missing)}")
        return
    expected_lists = {
        "models": list(config.model_names),
        "scenarios": list(config.scenario_names),
        "judges": list(config.judge_names),
        "dimensions": list(config.dimensions),
    }
    for key, expected in expected_lists.items():
        if summary.get(key) != expected:
            errors.append(f"summary.json {key} does not match config")
    expected_counts = {
        "n_models": len(config.model_names),
        "n_scenarios": len(config.scenario_names),
        "n_judges": len(config.judge_names),
        "n_dimensions": len(config.dimensions),
    }
    for key, expected in expected_counts.items():
        if int(float(summary.get(key, -1))) != expected:
            errors.append(f"summary.json {key}={summary.get(key)}; expected {expected}")
    if summary.get("dry_run") is True:
        warnings.append("summary.json indicates dry_run=true; not a final live experiment result")


def _verify_analysis_outputs(analysis_dir: Path, errors: list[str]) -> None:
    required_files = (
        "analysis_report.md",
        "model_summary.csv",
        "scenario_summary.csv",
        "judge_summary.csv",
        "dimension_summary.csv",
        "finding_matches.csv",
        "finding_summary.csv",
        "finding_evaluation.md",
        "qualitative_examples.md",
    )
    if not analysis_dir.exists():
        errors.append(f"missing analysis directory: {analysis_dir}")
        return
    for name in required_files:
        path = analysis_dir / name
        if not path.exists():
            errors.append(f"missing analysis artifact: {path}")
        elif path.stat().st_size == 0:
            errors.append(f"empty analysis artifact: {path}")


def _read_csv(path: Path, errors: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        errors.append(f"missing CSV artifact: {path}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"missing JSON artifact: {path}")
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        errors.append(f"{path} must contain a JSON object")
        return {}
    return data


def _require_numeric(
    row: dict[str, str],
    key: str,
    context: str,
    errors: list[str],
) -> None:
    try:
        float(row[key])
    except (KeyError, ValueError):
        errors.append(f"{context} has non-numeric {key}")
