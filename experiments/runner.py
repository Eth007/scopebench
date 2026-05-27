"""Experiment matrix runners."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import threading
import time
from typing import Callable

from experiments.agent import run_model_scenario
from infra.lifecycle import ScenarioLifecycle
from scopebench.config import ScopebenchConfig, load_config


@dataclass(frozen=True)
class ExperimentMatrixResult:
    """Artifacts produced by a model-by-scenario experiment matrix."""

    transcript_paths: tuple[Path, ...]


def run_experiment_matrix(
    out_dir: str | Path,
    config: ScopebenchConfig | None = None,
    dry_run: bool = False,
    models: tuple[str, ...] | None = None,
    scenarios: tuple[str, ...] | None = None,
    progress: Callable[[str], None] | None = None,
) -> ExperimentMatrixResult:
    """Run all requested model-scenario cells."""

    config = config or load_config()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_names = models or config.model_names
    scenario_names = scenarios or config.scenario_names
    paths: list[Path] = []

    if dry_run:
        for scenario_name in scenario_names:
            for model_name in model_names:
                if progress:
                    progress(f"dry cell: {model_name} / {scenario_name}")
                result = run_model_scenario(
                    model_name,
                    scenario_name,
                    out_dir=out_dir,
                    config=config,
                    dry_run=True,
                    manage_stack=False,
                    progress=progress,
                )
                paths.append(result.transcript_path)
        return ExperimentMatrixResult(transcript_paths=tuple(paths))

    cells: list[tuple[int, str, str]] = []
    for scenario_name in scenario_names:
        for model_name in model_names:
            cells.append((len(cells) + 1, model_name, scenario_name))
    parallelism = _parallel_cell_limit(config, len(cells))
    progress_lock = threading.Lock()

    def emit(message: str) -> None:
        if progress:
            with progress_lock:
                progress(message)

    if progress:
        progress(f"running {len(cells)} live cells in parallel with concurrency={parallelism}")

    indexed_paths: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        futures = {
            executor.submit(
                _run_isolated_live_cell,
                index,
                model_name,
                scenario_name,
                out_dir,
                config,
                emit,
            ): index
            for index, model_name, scenario_name in cells
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                indexed_paths[index] = future.result()
            except Exception:
                for pending in futures:
                    pending.cancel()
                raise

    return ExperimentMatrixResult(
        transcript_paths=tuple(indexed_paths[index] for index, _, _ in cells)
    )


def _run_isolated_live_cell(
    index: int,
    model_name: str,
    scenario_name: str,
    out_dir: Path,
    config: ScopebenchConfig,
    progress: Callable[[str], None],
) -> Path:
    project_name = _compose_project_name(model_name, scenario_name, index)
    lifecycle = ScenarioLifecycle(scenario_name, config=config, project_name=project_name)
    try:
        progress(
            f"cell {index}: starting isolated stack {project_name} "
            f"for {model_name} / {scenario_name}"
        )
        lifecycle.up(build=True)
        runtime_config = lifecycle.runtime_config()
        progress(
            f"cell {index}: target host URL "
            f"{runtime_config.scenario(scenario_name)['host_base_url']}"
        )
        result = run_model_scenario(
            model_name,
            scenario_name,
            out_dir=out_dir,
            config=runtime_config,
            dry_run=False,
            manage_stack=False,
            lifecycle=lifecycle,
            progress=progress,
        )
        progress(f"cell {index}: complete {model_name} / {scenario_name}")
        return result.transcript_path
    finally:
        progress(f"cell {index}: stopping isolated stack {project_name}")
        try:
            lifecycle.down()
        except Exception as exc:
            progress(f"cell {index}: stack cleanup failed for {project_name}: {exc}")


def _parallel_cell_limit(config: ScopebenchConfig, cell_count: int) -> int:
    configured = config.experiment.get("parallel_cells")
    if configured in (None, "", "all"):
        return max(1, cell_count)
    return max(1, min(cell_count, int(configured)))


def _compose_project_name(model_name: str, scenario_name: str, index: int) -> str:
    seed = f"{time.time_ns()}:{index}:{model_name}:{scenario_name}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    scenario_slug = _short_slug(scenario_name, 8)
    model_slug = _short_slug(model_name, 18)
    return f"sb_{index}_{scenario_slug}_{model_slug}_{digest}"


def _short_slug(value: str, limit: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return (slug[:limit].strip("_") or "x")
