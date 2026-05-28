"""End-to-end measurement workflows shared by the CLI and TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from scenarios.demo import generate_demo_transcripts
from scopebench.config import ScopebenchConfig, load_config

from .gstudy import analyze_score_rows, component_rows
from .io import read_score_rows, write_dict_rows, write_json, write_scores
from .metrics import write_run_metrics
from .schemas import load_transcript
from .scoring import aggregate_score, score_run


@dataclass(frozen=True)
class QuickstartResult:
    """Paths and metrics produced by the quickstart workflow."""

    transcript_dir: Path
    scores_csv: Path
    gstudy_csv: Path
    summary_json: Path
    transcript_count: int
    score_count: int
    mean_score: float
    generalizability_coefficient: float
    dependability_coefficient: float


def generate_demo(
    out_dir: str | Path,
    seed: int | None = None,
    config: ScopebenchConfig | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    """Generate deterministic demo transcripts."""

    config = config or load_config()
    if progress:
        progress(f"generating demo transcripts in {out_dir}")
    paths = generate_demo_transcripts(out_dir, seed=seed, config=config)
    if progress:
        progress(f"generated {len(paths)} demo transcripts")
    return paths


def score_transcripts(
    paths: list[str | Path],
    out_path: str | Path,
    config: ScopebenchConfig | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[int, float]:
    """Score transcript files and write a score CSV."""

    config = config or load_config()
    records = []
    for index, path in enumerate(paths, start=1):
        if progress:
            progress(f"scoring transcript {index}/{len(paths)}: {Path(path).name}")
        run = load_transcript(path)
        records.extend(score_run(run, config=config))
    if progress:
        progress(f"writing {len(records)} score rows to {out_path}")
    write_scores(records, out_path)
    return len(records), aggregate_score(records)


def write_run_metrics_for_transcripts(
    paths: list[str | Path],
    out_path: str | Path,
    progress: Callable[[str], None] | None = None,
) -> int:
    """Write run-level descriptive metrics for transcript files."""

    if progress:
        progress(f"writing run metrics for {len(paths)} transcripts to {out_path}")
    runs = [load_transcript(path) for path in paths]
    write_run_metrics(runs, out_path)
    return len(runs)


def analyze_scores(
    scores_path: str | Path,
    out_path: str | Path,
    summary_path: str | Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, float]:
    """Run the balanced crossed G-study and write analysis artifacts."""

    if progress:
        progress(f"running G-study analysis from {scores_path}")
    components, summary = analyze_score_rows(read_score_rows(scores_path))
    write_dict_rows(component_rows(components), out_path)
    write_json(summary, summary_path)
    if progress:
        progress(f"wrote G-study table and summary to {out_path}, {summary_path}")
    return summary


def run_quickstart(
    out_dir: str | Path,
    seed: int | None = None,
    config: ScopebenchConfig | None = None,
    progress: Callable[[str], None] | None = None,
) -> QuickstartResult:
    """Generate demo data, score it, and run the G-study analysis."""

    config = config or load_config()
    seed = config.random_seed if seed is None else seed
    out_dir = Path(out_dir)
    transcript_dir = out_dir / "transcripts"
    score_path = out_dir / "scores.csv"
    gstudy_path = out_dir / "gstudy.csv"
    summary_path = out_dir / "summary.json"

    transcript_paths = generate_demo(transcript_dir, seed=seed, config=config, progress=progress)
    score_count, mean_score = score_transcripts(
        transcript_paths,
        score_path,
        config=config,
        progress=progress,
    )
    metric_path = out_dir / "run_metrics.csv"
    write_run_metrics_for_transcripts(transcript_paths, metric_path, progress=progress)
    summary = analyze_scores(score_path, gstudy_path, summary_path, progress=progress)
    summary.update(
        {
            "config_path": str(config.path),
            "transcript_dir": str(transcript_dir),
            "scores_csv": str(score_path),
            "gstudy_csv": str(gstudy_path),
            "run_metrics_csv": str(metric_path),
            "mean_score": mean_score,
            "models": list(config.model_names),
            "scenarios": list(config.scenario_names),
            "dimensions": list(config.dimensions),
        }
    )
    write_json(summary, summary_path)

    return QuickstartResult(
        transcript_dir=transcript_dir,
        scores_csv=score_path,
        gstudy_csv=gstudy_path,
        summary_json=summary_path,
        transcript_count=len(transcript_paths),
        score_count=score_count,
        mean_score=mean_score,
        generalizability_coefficient=summary["generalizability_coefficient"],
        dependability_coefficient=summary["dependability_coefficient"],
    )
