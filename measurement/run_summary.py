"""Compact run summaries for TUI and quick inspection."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import mean
from typing import Any

from infra.openrouter import OpenRouterClient, OpenRouterError
from measurement.io import read_score_rows
from measurement.schemas import load_transcript
from scopebench.config import ScopebenchConfig, load_config


def build_run_summary_lines(
    artifact_dir: str | Path,
    config: ScopebenchConfig | None = None,
    include_llm: bool = False,
) -> list[str]:
    """Build a compact, human-readable run summary for the TUI."""

    config = config or load_config()
    artifact_dir = Path(artifact_dir)
    scores = _read_scores(artifact_dir / "scores.csv")
    metrics = _read_csv(artifact_dir / "run_metrics.csv")
    finding_summary = _read_csv(artifact_dir / "analysis" / "finding_summary.csv")
    summary = _read_json(artifact_dir / "summary.json")
    transcripts = _load_transcripts(artifact_dir / "transcripts")

    lines = [
        "Run summary",
        f"Artifacts: {artifact_dir}",
        f"Models: {', '.join(_summary_list(summary, 'models')) or _unique(metrics, 'model')}",
        f"Scenarios: {', '.join(_summary_list(summary, 'scenarios')) or _unique(metrics, 'scenario')}",
        f"Judge mode: {summary.get('judge_mode', 'unknown')}",
        "",
    ]
    lines.extend(_score_lines(scores))
    lines.extend(_metric_lines(metrics))
    lines.extend(_dimension_lines(scores))
    lines.extend(_model_lines(scores, metrics))
    lines.extend(_scenario_lines(scores, metrics))
    lines.extend(_finding_evaluation_lines(finding_summary))
    lines.extend(_finding_lines(transcripts, metrics))

    if include_llm and _llm_summary_enabled(config):
        lines.extend(_llm_summary_lines(artifact_dir, config, scores, metrics, summary, transcripts))

    _write_summary_artifact(artifact_dir, lines)
    return lines


def _score_lines(rows: list[dict[str, str]]) -> list[str]:
    scores = [_float(row.get("score")) for row in rows]
    scores = [score for score in scores if score is not None]
    if not scores:
        return ["Scores: not available", ""]
    avg = mean(scores)
    return [
        f"Mean safety score: {avg:.3f} {_bar(avg)}",
        f"Score rows: {len(rows)}",
        "",
    ]


def _metric_lines(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return ["Run metrics: not available", ""]
    availability = _mean_metric(rows, "availability")
    pii = _sum_metric(rows, "pii_records_exposed")
    unsafe = _sum_metric(rows, "unsafe_state_changes")
    creds = _sum_metric(rows, "credential_misuse")
    useful = _sum_metric(rows, "useful_steps")
    over_refusal = _sum_metric(rows, "over_refusal")
    unsafe_progress = _sum_metric(rows, "unsafe_progress")
    return [
        "Operational metrics:",
        f"- Availability: {availability:.3f} {_bar(availability)}",
        f"- PII records exposed: {_fmt_number(pii)}",
        f"- Unsafe state changes: {_fmt_number(unsafe)}",
        f"- Credential misuse events: {_fmt_number(creds)}",
        f"- Useful steps: {_fmt_number(useful)}",
        f"- Over-refusal runs: {_fmt_number(over_refusal)}",
        f"- Unsafe-progress runs: {_fmt_number(unsafe_progress)}",
        "",
    ]


def _dimension_lines(rows: list[dict[str, str]]) -> list[str]:
    grouped = _group_scores(rows, "dimension")
    if not grouped:
        return []
    lines = ["Safety dimensions:"]
    for dimension, values in sorted(grouped.items(), key=lambda item: mean(item[1])):
        avg = mean(values)
        lines.append(f"- {dimension}: {avg:.3f} {_bar(avg)}")
    lines.append("")
    return lines


def _model_lines(scores: list[dict[str, str]], metrics: list[dict[str, str]]) -> list[str]:
    grouped = _group_scores(scores, "model")
    if not grouped:
        return []
    availability_by_model = _group_metric(metrics, "model", "availability")
    lines = ["By model:"]
    for model, values in sorted(grouped.items(), key=lambda item: mean(item[1]), reverse=True):
        availability = _fmt_optional_mean(availability_by_model.get(model, []))
        lines.append(f"- {model}: score={mean(values):.3f}, availability={availability}")
    lines.append("")
    return lines


def _scenario_lines(scores: list[dict[str, str]], metrics: list[dict[str, str]]) -> list[str]:
    grouped = _group_scores(scores, "scenario")
    if not grouped:
        return []
    availability_by_scenario = _group_metric(metrics, "scenario", "availability")
    lines = ["By scenario:"]
    for scenario, values in sorted(grouped.items(), key=lambda item: mean(item[1]), reverse=True):
        availability = _fmt_optional_mean(availability_by_scenario.get(scenario, []))
        lines.append(f"- {scenario}: score={mean(values):.3f}, availability={availability}")
    lines.append("")
    return lines


def _finding_lines(transcripts: list[Any], metrics: list[dict[str, str]]) -> list[str]:
    interesting = (
        "out_of_scope",
        "pii_exposure",
        "credential_leak",
        "unsafe_progress",
        "ignored_risk",
        "availability_disruption",
        "escalated_risk",
    )
    counts = {tag: 0 for tag in interesting}
    for run in transcripts:
        for tag in run.tags:
            if tag in counts:
                counts[tag] += 1
    lines = ["Notable tags:"]
    for tag, count in counts.items():
        if count:
            lines.append(f"- {tag}: {count}")
    if len(lines) == 1:
        lines.append("- none observed")
    if metrics:
        lines.append(f"- completed runs: {len(metrics)}")
    lines.append("")
    return lines


def _finding_evaluation_lines(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return []
    recall_values = [_float(row.get("finding_recall")) for row in rows]
    precision_values = [_float(row.get("finding_precision_proxy")) for row in rows]
    recall_values = [value for value in recall_values if value is not None]
    precision_values = [value for value in precision_values if value is not None]
    matched = sum(int(float(row.get("matched_findings", "0") or 0)) for row in rows)
    missed = sum(int(float(row.get("missed_findings", "0") or 0)) for row in rows)
    lines = ["Finding evaluation:"]
    if recall_values:
        recall = mean(recall_values)
        lines.append(f"- Mean gold-finding recall: {recall:.3f} {_bar(recall)}")
    if precision_values:
        precision = mean(precision_values)
        lines.append(f"- Mean reported-finding precision proxy: {precision:.3f} {_bar(precision)}")
    lines.append(f"- Matched gold findings: {matched}")
    lines.append(f"- Missed gold findings: {missed}")
    lines.append("")
    return lines


def _llm_summary_lines(
    artifact_dir: Path,
    config: ScopebenchConfig,
    scores: list[dict[str, str]],
    metrics: list[dict[str, str]],
    summary: dict[str, Any],
    transcripts: list[Any],
) -> list[str]:
    try:
        model_id = _llm_summary_model(config)
        payload = {
            "artifact_dir": str(artifact_dir),
            "judge_mode": summary.get("judge_mode"),
            "models": summary.get("models"),
            "scenarios": summary.get("scenarios"),
            "mean_score": _safe_mean([_float(row.get("score")) for row in scores]),
            "dimension_means": {
                key: round(mean(values), 4) for key, values in _group_scores(scores, "dimension").items()
            },
            "run_metrics": metrics,
            "notable_tags": sorted({tag for run in transcripts for tag in run.tags}),
        }
        response = OpenRouterClient.from_config(config).chat_completion(
            model_id=model_id,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize a sandboxed cyber-safety benchmark run for a researcher. "
                        "Be concise, concrete, and focus on safety, usefulness, and what to inspect next."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, indent=2, sort_keys=True),
                },
            ],
            temperature=0.0,
            max_tokens=int(config.data.get("run_summary", {}).get("llm_max_tokens", 350)),
        )
        text = _message_content(response).strip()
    except (OpenRouterError, OSError, ValueError, KeyError) as exc:
        text = f"LLM summary unavailable: {exc}"
    lines = ["LLM summary:"]
    lines.extend(f"- {line}" if index == 0 else f"  {line}" for index, line in enumerate(text.splitlines()))
    lines.append("")
    return lines


def _llm_summary_enabled(config: ScopebenchConfig) -> bool:
    return bool(config.data.get("run_summary", {}).get("llm_enabled", False))


def _llm_summary_model(config: ScopebenchConfig) -> str:
    configured = config.data.get("run_summary", {}).get("llm_model_id")
    if configured:
        return str(configured)
    return config.judge_names[0]


def _message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if not choices:
        return json.dumps(response, sort_keys=True)
    return str(choices[0].get("message", {}).get("content", ""))


def _write_summary_artifact(artifact_dir: Path, lines: list[str]) -> None:
    path = artifact_dir / "analysis" / "tui_summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_scores(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return read_score_rows(path)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _load_transcripts(path: Path) -> list[Any]:
    if not path.exists():
        return []
    runs = []
    for transcript_path in sorted(path.glob("*.json")):
        try:
            runs.append(load_transcript(transcript_path))
        except Exception:
            continue
    return runs


def _group_scores(rows: list[dict[str, str]], key: str) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        score = _float(row.get("score"))
        if score is not None and row.get(key):
            grouped.setdefault(row[key], []).append(score)
    return grouped


def _group_metric(rows: list[dict[str, str]], group_key: str, metric_key: str) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        value = _float(row.get(metric_key))
        if value is not None and row.get(group_key):
            grouped.setdefault(row[group_key], []).append(value)
    return grouped


def _mean_metric(rows: list[dict[str, str]], key: str) -> float:
    values = [_float(row.get(key)) for row in rows]
    return _safe_mean(values)


def _sum_metric(rows: list[dict[str, str]], key: str) -> float:
    return sum(value for value in (_float(row.get(key)) for row in rows) if value is not None)


def _safe_mean(values: list[float | None]) -> float:
    clean = [value for value in values if value is not None]
    return mean(clean) if clean else 0.0


def _float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _bar(value: float, width: int = 16) -> str:
    value = max(0.0, min(1.0, value))
    filled = round(value * width)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def _fmt_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}"


def _fmt_optional_mean(values: list[float]) -> str:
    return f"{mean(values):.3f}" if values else "n/a"


def _summary_list(summary: dict[str, Any], key: str) -> list[str]:
    value = summary.get(key, [])
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _unique(rows: list[dict[str, str]], key: str) -> str:
    values = sorted({row[key] for row in rows if row.get(key)})
    return ", ".join(values)
