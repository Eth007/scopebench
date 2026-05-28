"""Descriptive analysis reports for experiment outputs."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from measurement.findings import evaluate_findings
from measurement.io import read_score_rows, write_dict_rows
from measurement.schemas import TranscriptRun, load_transcript
from scopebench.config import ScopebenchConfig, load_config


@dataclass(frozen=True)
class AnalysisReportResult:
    """Paths produced by descriptive analysis generation."""

    report_md: Path
    model_summary_csv: Path
    scenario_summary_csv: Path
    dimension_summary_csv: Path
    qualitative_examples_md: Path
    finding_matches_csv: Path
    finding_summary_csv: Path
    finding_evaluation_md: Path


def generate_analysis_report(
    artifact_dir: str | Path,
    config: ScopebenchConfig | None = None,
) -> AnalysisReportResult:
    """Generate descriptive tables and qualitative examples for the manuscript."""

    config = config or load_config()
    artifact_dir = Path(artifact_dir)
    transcript_dir = artifact_dir / "transcripts"
    scores_path = artifact_dir / "scores.csv"
    metrics_path = artifact_dir / "run_metrics.csv"
    report_dir = artifact_dir / "analysis"
    report_dir.mkdir(parents=True, exist_ok=True)

    runs = [load_transcript(path) for path in sorted(transcript_dir.glob("*.json"))]
    score_rows = read_score_rows(scores_path)
    metric_rows = _read_csv(metrics_path)

    model_summary = _model_summary(score_rows, metric_rows)
    scenario_summary = _scenario_summary(score_rows, metric_rows)
    dimension_summary = _score_summary(score_rows, "dimension")
    examples = _qualitative_examples(runs)
    finding_evaluation = evaluate_findings(artifact_dir, config=config)

    model_summary_csv = report_dir / "model_summary.csv"
    scenario_summary_csv = report_dir / "scenario_summary.csv"
    dimension_summary_csv = report_dir / "dimension_summary.csv"
    qualitative_examples_md = report_dir / "qualitative_examples.md"
    report_md = report_dir / "analysis_report.md"

    write_dict_rows(model_summary, model_summary_csv)
    write_dict_rows(scenario_summary, scenario_summary_csv)
    write_dict_rows(dimension_summary, dimension_summary_csv)
    qualitative_examples_md.write_text(_examples_markdown(examples), encoding="utf-8")
    report_md.write_text(
        _analysis_markdown(
            model_summary,
            scenario_summary,
            dimension_summary,
            examples,
            finding_evaluation.summary_rows,
        ),
        encoding="utf-8",
    )

    return AnalysisReportResult(
        report_md=report_md,
        model_summary_csv=model_summary_csv,
        scenario_summary_csv=scenario_summary_csv,
        dimension_summary_csv=dimension_summary_csv,
        qualitative_examples_md=qualitative_examples_md,
        finding_matches_csv=finding_evaluation.matches_csv,
        finding_summary_csv=finding_evaluation.summary_csv,
        finding_evaluation_md=finding_evaluation.report_md,
    )


def _model_summary(
    score_rows: list[dict[str, str]],
    metric_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    score_by_model = _group_scores(score_rows, "model")
    metrics_by_model = _group_metrics(metric_rows, "model")
    rows = []
    for model in sorted(set(score_by_model) | set(metrics_by_model)):
        metrics = metrics_by_model.get(model, [])
        rows.append(
            {
                "model": model,
                "mean_safety_dimension_score": _fmt_mean(score_by_model.get(model, [])),
                "mean_availability": _fmt_metric(metrics, "availability"),
                "total_pii_records_exposed": _fmt_sum(metrics, "pii_records_exposed"),
                "total_unsafe_state_changes": _fmt_sum(metrics, "unsafe_state_changes"),
                "total_credential_misuse": _fmt_sum(metrics, "credential_misuse"),
                "total_useful_steps": _fmt_sum(metrics, "useful_steps"),
                "over_refusal_runs": _fmt_sum(metrics, "over_refusal"),
            }
        )
    return rows


def _scenario_summary(
    score_rows: list[dict[str, str]],
    metric_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    score_by_scenario = _group_scores(score_rows, "scenario")
    metrics_by_scenario = _group_metrics(metric_rows, "scenario")
    rows = []
    for scenario in sorted(set(score_by_scenario) | set(metrics_by_scenario)):
        metrics = metrics_by_scenario.get(scenario, [])
        rows.append(
            {
                "scenario": scenario,
                "mean_safety_dimension_score": _fmt_mean(score_by_scenario.get(scenario, [])),
                "mean_availability": _fmt_metric(metrics, "availability"),
                "total_pii_records_exposed": _fmt_sum(metrics, "pii_records_exposed"),
                "total_unsafe_state_changes": _fmt_sum(metrics, "unsafe_state_changes"),
            }
        )
    return rows


def _score_summary(score_rows: list[dict[str, str]], facet: str) -> list[dict[str, str]]:
    grouped = _group_scores(score_rows, facet)
    return [
        {
            facet: key,
            "mean_score": _fmt_mean(values),
            "min_score": f"{min(values):.4f}" if values else "",
            "max_score": f"{max(values):.4f}" if values else "",
            "n_scores": str(len(values)),
        }
        for key, values in sorted(grouped.items())
    ]


def _qualitative_examples(runs: list[TranscriptRun]) -> list[dict[str, str]]:
    interesting_tags = {
        "out_of_scope",
        "pii_exposure",
        "credential_leak",
        "ignored_risk",
        "escalated_risk",
        "refusal_without_progress",
        "availability_disruption",
        "limited_enumeration",
    }
    examples = []
    for run in runs:
        for event in run.events:
            tags = sorted(set(event.tags) & interesting_tags)
            if tags:
                examples.append(
                    {
                        "run_id": run.run_id,
                        "model": run.model,
                        "scenario": run.scenario,
                        "time_s": f"{event.time_s:.1f}",
                        "kind": event.kind,
                        "tags": ", ".join(tags),
                        "message": _truncate(event.message, 500),
                    }
                )
                break
    if not examples:
        for run in runs[:5]:
            event = run.events[-1]
            examples.append(
                {
                    "run_id": run.run_id,
                    "model": run.model,
                    "scenario": run.scenario,
                    "time_s": f"{event.time_s:.1f}",
                    "kind": event.kind,
                    "tags": "none",
                    "message": _truncate(event.message, 500),
                }
            )
    return examples[:12]


def _analysis_markdown(
    model_summary: list[dict[str, str]],
    scenario_summary: list[dict[str, str]],
    dimension_summary: list[dict[str, str]],
    examples: list[dict[str, str]],
    finding_summary: list[dict[str, str]],
) -> str:
    sections = [
        "# Scopebench Analysis Report",
        "",
        "## Model Summary",
        _markdown_table(model_summary),
        "",
        "## Scenario Summary",
        _markdown_table(scenario_summary),
        "",
        "## Operational Safety Summary",
        _markdown_table(dimension_summary),
        "",
        "## Finding Evaluation",
        _markdown_table(finding_summary),
        "",
        "## Qualitative Examples",
        _markdown_table(examples),
        "",
    ]
    return "\n".join(sections)


def _examples_markdown(examples: list[dict[str, str]]) -> str:
    return "\n".join(["# Qualitative Examples", "", _markdown_table(examples), ""])


def _markdown_table(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "_No rows._"
    headers = list(rows[0])
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_escape_md(row.get(header, "")) for header in headers) + " |")
    return "\n".join(lines)


def _group_scores(rows: list[dict[str, str]], key: str) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        grouped.setdefault(row[key], []).append(float(row["score"]))
    return grouped


def _group_metrics(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row[key], []).append(row)
    return grouped


def _fmt_mean(values: list[float]) -> str:
    return f"{mean(values):.4f}" if values else ""


def _fmt_metric(rows: list[dict[str, str]], key: str) -> str:
    values = [float(row[key]) for row in rows]
    return _fmt_mean(values)


def _fmt_sum(rows: list[dict[str, str]], key: str) -> str:
    return f"{sum(float(row[key]) for row in rows):.4f}"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _truncate(value: str, limit: int) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _escape_md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
