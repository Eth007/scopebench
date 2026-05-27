"""Curses-based terminal UI for managing scopebench workflows."""

from __future__ import annotations

import curses
import json
from pathlib import Path
import textwrap
import time
import traceback
from typing import Callable

import yaml

from experiments.agent import run_model_scenario
from experiments.pipeline import run_experiment_pipeline
from experiments.preflight import run_preflight
from infra.manager import load_scenarios, status_lines, validate_infra
from infra.openrouter import OpenRouterClient
from measurement.audit import verify_experiment_artifacts, write_audit_report
from measurement.report import generate_analysis_report
from measurement.run_summary import build_run_summary_lines
from measurement.workflow import (
    analyze_scores,
    generate_demo,
    run_quickstart,
    score_transcripts,
)
from scopebench.config import ScopebenchConfig, load_config


MAIN_MENU = (
    "Run batch",
    "View run logs",
    "Testing and utilities",
    "Inspect",
    "Quit",
)

RUN_MENU = (
    "Live preflight",
    "Choose single-run model",
    "Choose single-run scenario",
    "Run single model x scenario",
    "Choose batch models",
    "Choose batch scenarios",
    "Run selected batch",
    "Run full batch",
    "Verify full batch artifacts",
    "Generate full batch report",
    "View full batch summary",
    "Back",
)

TESTING_MENU = (
    "Run quickstart pipeline",
    "Run dry experiment pipeline",
    "Run live smoke cell",
    "Run live pipeline (deterministic judges)",
    "Generate demo transcripts",
    "Score workspace transcripts",
    "Run G-study analysis",
    "Validate OpenRouter models",
    "Verify latest test artifacts",
    "Generate latest test report",
    "Back",
)

INSPECT_MENU = (
    "View run guide",
    "View latest summary",
    "View scenario catalog",
    "View model and judge config",
    "View infrastructure status",
    "Back",
)

MENUS = {
    "main": MAIN_MENU,
    "run": RUN_MENU,
    "testing": TESTING_MENU,
    "inspect": INSPECT_MENU,
}

MENU_TITLES = {
    "main": "Main menu",
    "run": "Run batch",
    "logs": "Run logs",
    "testing": "Testing and utilities",
    "inspect": "Inspect",
    "single_model": "Choose Single-Run Model",
    "single_scenario": "Choose Single-Run Scenario",
    "matrix_models": "Choose Batch Models",
    "matrix_scenarios": "Choose Batch Scenarios",
}


class ScopebenchTUI:
    """Keyboard-driven TUI for running and observing benchmark workflows."""

    def __init__(
        self, screen: curses.window, workspace: str | Path, config: ScopebenchConfig
    ) -> None:
        self.screen = screen
        self.workspace = Path(workspace)
        self.config = config
        self.menu = "main"
        self.selected = 0
        self.single_model = config.model_names[0]
        self.single_scenario = config.scenario_names[0]
        self.matrix_models = set(config.model_names)
        self.matrix_scenarios = set(config.scenario_names)
        self.message = "Use up/down or j/k to navigate. Enter selects. b goes back. q quits."
        self.detail_follow_tail = False
        self.detail_scroll_top = 0
        self.visible_log_dirs: list[Path] = []
        self.selected_log_dir: Path | None = None
        self.latest_transcript_dir: Path | None = None
        self.latest_scores_path: Path | None = None
        self.latest_artifact_dir = self._find_latest_artifact_dir()
        self.detail_lines: list[str] = []
        self._set_detail_lines(self._workspace_lines())

    def run(self) -> None:
        curses.curs_set(0)
        self.screen.keypad(True)
        while True:
            self._draw()
            key = self.screen.getch()
            if key in (ord("q"), ord("Q")):
                return
            if self._handle_scroll_key(key):
                continue
            if key in (ord("b"), ord("B"), 27):
                self._go_back()
                continue
            menu_items = self._menu_items()
            if key in (curses.KEY_UP, ord("k"), ord("K")):
                self.selected = (self.selected - 1) % len(menu_items)
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                self.selected = (self.selected + 1) % len(menu_items)
            elif key in (10, 13, curses.KEY_ENTER):
                label = menu_items[self.selected]
                if label == "Quit":
                    return
                if label == "Back":
                    self._go_back()
                    continue
                self._run_action(label)

    def _draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        self._add(0, 0, f"scopebench > {MENU_TITLES[self.menu]}", curses.A_BOLD)
        self._add(1, 0, f"workspace: {self.workspace}")
        self._add(2, 0, self.message[: max(0, width - 1)])

        menu_width = min(42, max(24, width // 3))
        for index, label in enumerate(self._menu_items()):
            attr = curses.A_REVERSE if index == self.selected else curses.A_NORMAL
            self._add(4 + index, 0, f" {label}".ljust(menu_width - 1), attr)

        detail_x = menu_width + 2
        max_detail_width = max(10, width - detail_x - 1)
        max_detail_rows = max(0, height - 6)
        detail_view = self._wrapped_detail_lines(max_detail_width)
        detail_start = self._detail_start(max_detail_rows, len(detail_view))
        detail_end = min(len(detail_view), detail_start + max_detail_rows)
        self._add(
            4,
            detail_x,
            self._detail_title(detail_start, detail_end, max_detail_rows, len(detail_view)),
            curses.A_BOLD,
        )
        detail_lines = detail_view[detail_start:detail_end]
        for offset, line in enumerate(detail_lines):
            self._add(5 + offset, detail_x, line[:max_detail_width])
        self.screen.refresh()

    def _set_detail_lines(self, lines: list[str], follow_tail: bool = False) -> None:
        self.detail_lines = list(lines)
        self.detail_follow_tail = follow_tail
        self.detail_scroll_top = 0

    def _detail_start(self, rows: int, total: int | None = None) -> int:
        if rows <= 0:
            return 0
        total = len(self.detail_lines) if total is None else total
        max_start = max(0, total - rows)
        if self.detail_follow_tail:
            self.detail_scroll_top = max_start
        else:
            self.detail_scroll_top = max(0, min(self.detail_scroll_top, max_start))
        return self.detail_scroll_top

    def _detail_title(self, start: int, end: int, rows: int, total: int | None = None) -> str:
        total = len(self.detail_lines) if total is None else total
        if total <= rows or rows <= 0:
            return "details"
        mode = "tail" if self.detail_follow_tail else "scroll"
        return f"details ({start + 1}-{end}/{total}, {mode}; PgUp/PgDn, Home/End)"

    def _detail_page_size(self) -> int:
        height, _ = self.screen.getmaxyx()
        return max(1, height - 6)

    def _detail_view_width(self) -> int:
        _, width = self.screen.getmaxyx()
        menu_width = min(42, max(24, width // 3))
        detail_x = menu_width + 2
        return max(10, width - detail_x - 1)

    def _wrapped_detail_lines(self, width: int | None = None) -> list[str]:
        width = self._detail_view_width() if width is None else width
        wrapped: list[str] = []
        for line in self.detail_lines:
            if not line:
                wrapped.append("")
                continue
            chunks = textwrap.wrap(
                line,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
                replace_whitespace=False,
                drop_whitespace=False,
            )
            wrapped.extend(chunks or [""])
        return wrapped

    def _handle_scroll_key(self, key: int) -> bool:
        rows = self._detail_page_size()
        max_start = max(0, len(self._wrapped_detail_lines()) - rows)
        if max_start <= 0:
            return False
        if key == curses.KEY_PPAGE:
            self.detail_follow_tail = False
            self.detail_scroll_top = max(0, self.detail_scroll_top - rows)
        elif key == curses.KEY_NPAGE:
            self.detail_scroll_top = min(max_start, self.detail_scroll_top + rows)
            self.detail_follow_tail = self.detail_scroll_top >= max_start
        elif key == curses.KEY_HOME:
            self.detail_follow_tail = False
            self.detail_scroll_top = 0
        elif key == curses.KEY_END:
            self.detail_follow_tail = True
            self.detail_scroll_top = max_start
        else:
            return False
        self.message = self._scroll_message(rows)
        return True

    def _scroll_message(self, rows: int) -> str:
        total = len(self._wrapped_detail_lines())
        start = self._detail_start(rows, total)
        end = min(total, start + rows)
        return f"detail log {start + 1}-{end}/{total}; End follows new log lines"

    def _set_nodelay(self, enabled: bool) -> None:
        if hasattr(self.screen, "nodelay"):
            self.screen.nodelay(enabled)

    def _poll_scroll_keys(self) -> None:
        if not hasattr(self.screen, "getch"):
            return
        while True:
            key = self.screen.getch()
            if key == -1:
                return
            if not self._handle_scroll_key(key):
                return

    def _run_action(self, label: str) -> None:
        try:
            if self.menu in {"single_model", "single_scenario", "matrix_models", "matrix_scenarios"}:
                self._run_selection_action(label)
                return
            if self.menu == "logs":
                self._run_log_action(label)
                return
            if label == "Run batch":
                self._enter_menu("run", self._run_menu_lines())
            elif label == "View run logs":
                self._enter_menu("logs", self._log_viewer_lines())
            elif label == "Testing and utilities":
                self._enter_menu("testing", self._testing_lines())
            elif label == "Inspect":
                self._enter_menu("inspect", self._workspace_lines())
            elif label == "Live preflight":
                self._run_live_preflight()
            elif label == "Choose single-run model":
                self._enter_menu("single_model", self._single_model_lines())
            elif label == "Choose single-run scenario":
                self._enter_menu("single_scenario", self._single_scenario_lines())
            elif label == "Run single model x scenario":
                self._run_one_selected_cell()
            elif label == "Choose batch models":
                self._enter_menu("matrix_models", self._matrix_selection_lines())
            elif label == "Choose batch scenarios":
                self._enter_menu("matrix_scenarios", self._matrix_selection_lines())
            elif label == "Run selected batch":
                self._run_selected_matrix()
            elif label == "Run full batch":
                self._run_final_live_experiment()
            elif label == "Verify full batch artifacts":
                self._verify_final_experiment_artifacts()
            elif label == "Generate full batch report":
                self._generate_final_experiment_report()
            elif label == "View full batch summary":
                self._view_final_experiment_summary()
            elif label == "View run guide":
                self._set_detail_lines(self._run_menu_lines())
                self.message = "loaded run guide"
            elif label == "Run quickstart pipeline":
                self._run_quickstart()
            elif label == "Run dry experiment pipeline":
                self._run_dry_pipeline()
            elif label == "Run live smoke cell":
                self._run_live_smoke()
            elif label == "Run live pipeline (deterministic judges)":
                self._run_live_pipeline_action("deterministic")
            elif label == "Generate demo transcripts":
                self._generate_demo_transcripts()
            elif label == "Score workspace transcripts":
                self._score_workspace_transcripts()
            elif label == "Run G-study analysis":
                self._run_workspace_gstudy()
            elif label == "Validate OpenRouter models":
                self._validate_openrouter_models()
            elif label == "Verify latest test artifacts":
                self._verify_latest_artifacts()
            elif label == "Generate latest test report":
                self._generate_latest_report()
            elif label == "View scenario catalog":
                self._set_detail_lines(self._scenario_lines())
                self.message = "loaded scenario catalog"
            elif label == "View model and judge config":
                self._set_detail_lines(self._model_judge_lines())
                self.message = "loaded OpenRouter model config"
            elif label == "View infrastructure status":
                self._set_detail_lines(status_lines(self.config))
                failed = [
                    name for name, status in validate_infra(self.config).items() if status != "ok"
                ]
                self.message = "infra validation ok" if not failed else f"infra issues: {', '.join(failed)}"
            elif label == "View latest summary":
                summary_path = self._latest_summary_path()
                self._set_detail_lines(
                    self._summary_lines(summary_path) if summary_path else [
                        "summary not found; run a pipeline first"
                    ]
                )
                self.message = "loaded latest summary"
        except Exception as exc:  # pragma: no cover - keeps TUI recoverable.
            self.message = f"error: {exc}"
            self._set_detail_lines(traceback.format_exc().splitlines(), follow_tail=True)

    def _menu_items(self) -> tuple[str, ...]:
        if self.menu == "single_model":
            return (*self.config.model_names, "Back")
        if self.menu == "single_scenario":
            return (*self.config.scenario_names, "Back")
        if self.menu == "matrix_models":
            return (
                "Select all models",
                "Clear selected models",
                *(
                    f"[{'x' if name in self.matrix_models else ' '}] {name}"
                    for name in self.config.model_names
                ),
                "Back",
            )
        if self.menu == "matrix_scenarios":
            return (
                "Select all scenarios",
                "Clear selected scenarios",
                *(
                    f"[{'x' if name in self.matrix_scenarios else ' '}] {name}"
                    for name in self.config.scenario_names
                ),
                "Back",
            )
        if self.menu == "logs":
            return self._log_menu_items()
        return MENUS[self.menu]

    def _run_selection_action(self, label: str) -> None:
        if self.menu == "single_model":
            self.single_model = label
            self._go_back("run")
            self._set_detail_lines(self._run_menu_lines())
            self.message = f"single-run model selected: {label}"
            return
        if self.menu == "single_scenario":
            self.single_scenario = label
            self._go_back("run")
            self._set_detail_lines(self._run_menu_lines())
            self.message = f"single-run scenario selected: {label}"
            return
        if self.menu == "matrix_models":
            if label == "Select all models":
                self.matrix_models = set(self.config.model_names)
            elif label == "Clear selected models":
                self.matrix_models = set()
            else:
                name = label.split("] ", 1)[1]
                self._toggle(self.matrix_models, name)
            self._set_detail_lines(self._matrix_selection_lines())
            self.message = self._selection_message()
            return
        if self.menu == "matrix_scenarios":
            if label == "Select all scenarios":
                self.matrix_scenarios = set(self.config.scenario_names)
            elif label == "Clear selected scenarios":
                self.matrix_scenarios = set()
            else:
                name = label.split("] ", 1)[1]
                self._toggle(self.matrix_scenarios, name)
            self._set_detail_lines(self._matrix_selection_lines())
            self.message = self._selection_message()

    def _toggle(self, values: set[str], name: str) -> None:
        if name in values:
            values.remove(name)
        else:
            values.add(name)

    def _enter_menu(self, menu: str, detail_lines: list[str]) -> None:
        self.menu = menu
        self.selected = 0
        self._set_detail_lines(detail_lines)
        self.message = "Enter runs the highlighted step. b returns to the main menu. q quits."

    def _go_back(self, target: str | None = None) -> None:
        if self.menu == "main":
            return
        if target is None:
            target = "run" if self.menu in {
                "single_model",
                "single_scenario",
                "matrix_models",
                "matrix_scenarios",
            } else "main"
        self.menu = target
        self.selected = 0
        if target == "main":
            detail_lines = self._workspace_lines()
        elif target == "logs":
            detail_lines = self._log_viewer_lines()
        elif target == "inspect":
            detail_lines = self._workspace_lines()
        elif target == "testing":
            detail_lines = self._testing_lines()
        else:
            detail_lines = self._run_menu_lines()
        self._set_detail_lines(detail_lines)
        self.message = "Use up/down or j/k to navigate. Enter selects. b goes back. q quits."

    def _run_quickstart(self) -> None:
        out_dir = self._new_run_dir("quickstart", {"dry_run": True})

        def worker(progress: Callable[[str], None]) -> None:
            result = run_quickstart(out_dir, config=self.config, progress=progress)
            self.latest_artifact_dir = out_dir
            progress(
                f"quickstart complete: {result.score_count} scores, "
                f"G={result.generalizability_coefficient:.3f}"
            )

        if self._observe("quickstart pipeline", worker, run_dir=out_dir):
            self._set_detail_lines(self._post_run_summary(out_dir, include_llm=False))

    def _run_dry_pipeline(self) -> None:
        out_dir = self._new_run_dir("dry_pipeline", {"dry_run": True, "judge_mode": "deterministic"})

        def worker(progress: Callable[[str], None]) -> None:
            result = run_experiment_pipeline(
                out_dir,
                config=self.config,
                dry_run=True,
                judge_mode="deterministic",
                progress=progress,
            )
            self.latest_artifact_dir = out_dir
            progress(f"dry pipeline complete: {result.transcript_count} transcripts")

        if self._observe("dry experiment pipeline", worker, run_dir=out_dir):
            self._set_detail_lines(self._post_run_summary(out_dir, include_llm=False))

    def _run_live_preflight(self) -> None:
        def worker(progress: Callable[[str], None]) -> None:
            result = run_preflight(config=self.config, live_scenarios=True, progress=progress)
            for check in result.checks:
                status = "ok" if check.ok else "fail"
                progress(f"{status}: {check.name}: {check.detail}")
            if not result.ok:
                raise RuntimeError("live preflight failed")

        self._observe("live preflight", worker)

    def _run_live_smoke(self) -> None:
        if not self._confirm_live_action(
            "Run one live OpenRouter model-scenario cell? This may use API credits."
        ):
            return
        model_name = self.single_model
        scenario_name = self.single_scenario
        out_dir = self._new_run_dir(
            "live_smoke",
            {"model": model_name, "scenario": scenario_name, "judge_mode": "none"},
        )
        transcript_dir = out_dir / "transcripts"

        def worker(progress: Callable[[str], None]) -> None:
            result = run_model_scenario(
                model_name,
                scenario_name,
                out_dir=transcript_dir,
                config=self.config,
                dry_run=False,
                manage_stack=True,
                progress=progress,
            )
            self.latest_artifact_dir = out_dir
            self.latest_transcript_dir = transcript_dir
            progress(f"wrote transcript: {result.transcript_path}")

        if self._observe(f"live smoke: {model_name} / {scenario_name}", worker, run_dir=out_dir):
            self._set_detail_lines(self._log_detail_lines(out_dir, include_llm=False))

    def _run_one_selected_cell(self) -> None:
        if not self._confirm_live_action(
            f"Run {self.single_model} on {self.single_scenario} with LLM judges? This uses OpenRouter credits."
        ):
            return
        out_dir = self._new_run_dir(
            "single_cell",
            {
                "models": [self.single_model],
                "scenarios": [self.single_scenario],
                "judge_mode": "llm",
            },
        )

        def worker(progress: Callable[[str], None]) -> None:
            result = run_experiment_pipeline(
                out_dir,
                config=self.config,
                dry_run=False,
                judge_mode="llm",
                models=(self.single_model,),
                scenarios=(self.single_scenario,),
                require_full_design=False,
                progress=progress,
            )
            self.latest_artifact_dir = out_dir
            progress(
                f"selected cell complete: {result.transcript_count} transcript, "
                f"{result.score_count} LLM-judge scores"
            )

        if self._observe(f"selected cell: {self.single_model} / {self.single_scenario}", worker, run_dir=out_dir):
            self._set_detail_lines(self._post_run_summary(out_dir, include_llm=True))

    def _run_selected_matrix(self) -> None:
        models = self._selected_models()
        scenarios = self._selected_scenarios()
        if not models or not scenarios:
            self.message = "select at least one model and one scenario before running a batch"
            self._set_detail_lines(self._matrix_selection_lines())
            return
        cell_count = len(models) * len(scenarios)
        if not self._confirm_live_action(
            f"Run selected batch with {len(models)} models x {len(scenarios)} scenarios ({cell_count} cells)?"
        ):
            return
        out_dir = self._new_run_dir(
            "selected_batch",
            {"models": list(models), "scenarios": list(scenarios), "judge_mode": "llm"},
        )

        def worker(progress: Callable[[str], None]) -> None:
            result = run_experiment_pipeline(
                out_dir,
                config=self.config,
                dry_run=False,
                judge_mode="llm",
                models=models,
                scenarios=scenarios,
                require_full_design=False,
                progress=progress,
            )
            self.latest_artifact_dir = out_dir
            progress(
                f"selected batch complete: {result.transcript_count} transcripts, "
                f"{result.score_count} LLM-judge scores"
            )

        if self._observe("selected model-scenario batch", worker, run_dir=out_dir):
            self._set_detail_lines(self._post_run_summary(out_dir, include_llm=True))

    def _run_live_pipeline_action(self, judge_mode: str) -> None:
        prompt = (
            "Run the full live batch plus LLM judges? This uses the most API credits."
            if judge_mode == "llm"
            else "Run the full live model-scenario batch? This may use API credits."
        )
        if not self._confirm_live_action(prompt):
            return
        suffix = "llm" if judge_mode == "llm" else "deterministic"
        out_dir = self._new_run_dir(
            f"live_pipeline_{suffix}",
            {
                "models": list(self.config.model_names),
                "scenarios": list(self.config.scenario_names),
                "judge_mode": judge_mode,
            },
        )

        def worker(progress: Callable[[str], None]) -> None:
            result = run_experiment_pipeline(
                out_dir,
                config=self.config,
                dry_run=False,
                judge_mode=judge_mode,
                require_full_design=False,
                progress=progress,
            )
            self.latest_artifact_dir = out_dir
            progress(
                f"live pipeline complete: {result.transcript_count} transcripts, "
                f"{result.score_count} scores"
            )

        if self._observe(f"live pipeline ({judge_mode})", worker, run_dir=out_dir):
            self._set_detail_lines(self._post_run_summary(out_dir, include_llm=judge_mode == "llm"))

    def _run_final_live_experiment(self) -> None:
        if not self._confirm_live_action(
            "Run the final live experiment with LLM judges? This uses OpenRouter credits."
        ):
            return
        out_dir = self._new_run_dir(
            "full_batch",
            {
                "models": list(self.config.model_names),
                "scenarios": list(self.config.scenario_names),
                "judge_mode": "llm",
            },
        )

        def worker(progress: Callable[[str], None]) -> None:
            result = run_experiment_pipeline(
                out_dir,
                config=self.config,
                dry_run=False,
                judge_mode="llm",
                progress=progress,
            )
            self.latest_artifact_dir = out_dir
            progress(
                f"full batch complete: {result.transcript_count} transcripts, "
                f"{result.score_count} LLM-judge scores"
            )

        if self._observe("full live batch with LLM judges", worker, run_dir=out_dir):
            self._set_detail_lines(self._post_run_summary(out_dir, include_llm=True))

    def _verify_final_experiment_artifacts(self) -> None:
        artifact_dir = self._latest_full_batch_dir()
        if artifact_dir is None or not (artifact_dir / "summary.json").exists():
            self.message = "full batch artifacts not found; run full batch first"
            self._set_detail_lines([str(self._runs_root())])
            return
        self._verify_artifacts_for(artifact_dir, "verify full batch artifacts")

    def _generate_final_experiment_report(self) -> None:
        artifact_dir = self._latest_full_batch_dir()
        if artifact_dir is None or not (artifact_dir / "scores.csv").exists():
            self.message = "full batch scores not found; run full batch first"
            self._set_detail_lines([str(self._runs_root())])
            return
        self._generate_report_for(artifact_dir, "generate full batch report")

    def _view_final_experiment_summary(self) -> None:
        artifact_dir = self._latest_full_batch_dir()
        if artifact_dir is None:
            self.message = "full batch summary not found; run full batch first"
            self._set_detail_lines([str(self._runs_root())])
            return
        self._set_detail_lines(self._log_detail_lines(artifact_dir, include_llm=False))
        self.message = "loaded full batch summary"

    def _generate_demo_transcripts(self) -> None:
        run_dir = self._new_run_dir("demo_transcripts", {"dry_run": True})
        out_dir = run_dir / "transcripts"

        def worker(progress: Callable[[str], None]) -> None:
            paths = generate_demo(out_dir, config=self.config, progress=progress)
            self.latest_artifact_dir = run_dir
            self.latest_transcript_dir = out_dir
            progress(f"generated {len(paths)} transcripts")

        if self._observe("generate demo transcripts", worker, run_dir=run_dir):
            self._set_detail_lines([str(path) for path in sorted(out_dir.glob("*.json"))])

    def _score_workspace_transcripts(self) -> None:
        transcript_dir = self.latest_transcript_dir or self.workspace / "transcripts"
        transcript_paths = sorted(transcript_dir.glob("*.json"))
        if not transcript_paths:
            self.message = "no transcripts found; generate demo transcripts first"
            self._set_detail_lines([str(transcript_dir)])
            return
        run_dir = self._new_run_dir("score_transcripts", {"source_transcripts": str(transcript_dir)})
        scores_path = run_dir / "scores.csv"

        def worker(progress: Callable[[str], None]) -> None:
            count, mean_score = score_transcripts(
                transcript_paths,
                scores_path,
                config=self.config,
                progress=progress,
            )
            self.latest_artifact_dir = run_dir
            self.latest_scores_path = scores_path
            progress(f"scored {count} rows; mean={mean_score:.3f}")

        if self._observe("score workspace transcripts", worker, run_dir=run_dir):
            self._set_detail_lines([f"scores: {scores_path}"])

    def _run_workspace_gstudy(self) -> None:
        scores_path = self.latest_scores_path or self.workspace / "scores.csv"
        if not scores_path.exists():
            self.message = "no scores.csv found; score transcripts first"
            self._set_detail_lines([str(scores_path)])
            return
        run_dir = self._new_run_dir("gstudy", {"source_scores": str(scores_path)})

        def worker(progress: Callable[[str], None]) -> None:
            summary = analyze_scores(
                scores_path,
                run_dir / "gstudy.csv",
                run_dir / "summary.json",
                progress=progress,
            )
            self.latest_artifact_dir = run_dir
            progress(f"analysis complete: G={summary['generalizability_coefficient']:.3f}")

        if self._observe("G-study analysis", worker, run_dir=run_dir):
            self._set_detail_lines(self._summary_lines(run_dir / "summary.json"))

    def _validate_openrouter_models(self) -> None:
        def worker(progress: Callable[[str], None]) -> None:
            progress("querying OpenRouter model list")
            results = OpenRouterClient.from_config(self.config).validate_configured_models()
            for model_id, present in results.items():
                progress(f"{'ok' if present else 'missing'}: {model_id}")
            if not all(results.values()):
                raise RuntimeError("one or more configured OpenRouter models are missing")

        self._observe("validate OpenRouter models", worker)

    def _verify_latest_artifacts(self) -> None:
        artifact_dir = self._require_latest_artifact_dir()
        if artifact_dir is None:
            return
        self._verify_artifacts_for(artifact_dir, "verify latest artifacts")

    def _verify_artifacts_for(self, artifact_dir: Path, title: str) -> None:
        def worker(progress: Callable[[str], None]) -> None:
            progress(f"verifying {artifact_dir}")
            result = verify_experiment_artifacts(artifact_dir, config=self.config)
            audit_path = artifact_dir / "artifact_audit.json"
            write_audit_report(result, audit_path)
            for key, value in sorted(result.counts.items()):
                progress(f"{key}: {value}")
            for warning in result.warnings:
                progress(f"warning: {warning}")
            for error in result.errors:
                progress(f"error: {error}")
            progress(f"artifact audit: {audit_path}")
            if not result.ok:
                raise RuntimeError("artifact verification failed")

        self._observe(title, worker)

    def _generate_latest_report(self) -> None:
        artifact_dir = self._require_latest_artifact_dir()
        if artifact_dir is None:
            return
        self._generate_report_for(artifact_dir, "generate latest report")

    def _generate_report_for(self, artifact_dir: Path, title: str) -> None:
        def worker(progress: Callable[[str], None]) -> None:
            progress(f"generating report from {artifact_dir}")
            result = generate_analysis_report(artifact_dir, config=self.config)
            progress(f"analysis report: {result.report_md}")
            progress(f"model summary: {result.model_summary_csv}")
            progress(f"scenario summary: {result.scenario_summary_csv}")
            progress(f"judge summary: {result.judge_summary_csv}")
            progress(f"dimension summary: {result.dimension_summary_csv}")
            progress(f"finding summary: {result.finding_summary_csv}")
            progress(f"finding evaluation: {result.finding_evaluation_md}")
            progress(f"qualitative examples: {result.qualitative_examples_md}")

        self._observe(title, worker)

    def _observe(
        self,
        title: str,
        worker: Callable[[Callable[[str], None]], None],
        run_dir: Path | None = None,
    ) -> bool:
        start = time.monotonic()
        if run_dir is not None:
            self._update_run_manifest(run_dir, {"status": "running", "started_at": self._now()})
        self._set_detail_lines(
            [f"task: {title}", f"started: {time.strftime('%Y-%m-%d %H:%M:%S')}"],
            follow_tail=True,
        )
        self.message = f"running: {title}"
        self._draw()
        self._set_nodelay(True)

        def progress(message: str) -> None:
            self._poll_scroll_keys()
            elapsed = time.monotonic() - start
            self.detail_lines.append(f"{elapsed:7.1f}s  {message}")
            self.message = f"running: {title} ({elapsed:.0f}s)"
            self._draw()

        try:
            worker(progress)
        except Exception:
            self._set_nodelay(False)
            if run_dir is not None:
                self._update_run_manifest(
                    run_dir,
                    {
                        "status": "failed",
                        "finished_at": self._now(),
                        "duration_s": round(time.monotonic() - start, 3),
                    },
                )
            self.message = f"failed: {title}"
            self.detail_lines.extend(traceback.format_exc().splitlines())
            self._draw()
            return False
        self._set_nodelay(False)
        elapsed = time.monotonic() - start
        if run_dir is not None:
            self._update_run_manifest(
                run_dir,
                {
                    "status": "complete",
                    "finished_at": self._now(),
                    "duration_s": round(elapsed, 3),
                },
            )
        self.message = f"complete: {title} ({elapsed:.1f}s)"
        self.detail_lines.append(f"{elapsed:7.1f}s  complete")
        self._draw()
        return True

    def _confirm_live_action(self, prompt: str) -> bool:
        self.message = f"{prompt} Press y to continue, any other key cancels."
        self._set_detail_lines(
            [
                "Live actions can start Docker stacks and call OpenRouter models.",
                "Use live preflight first if you have not checked the environment.",
            ]
        )
        self._draw()
        key = self.screen.getch()
        if key in (ord("y"), ord("Y")):
            return True
        self.message = "cancelled live action"
        return False

    def _workspace_lines(self) -> list[str]:
        latest = self.latest_artifact_dir or "none yet"
        full_batch = self._latest_full_batch_dir()
        return [
            "Use Run batch for live experiments.",
            "Use View run logs to inspect timestamped runs, charts, and LLM analysis.",
            "Use Testing and utilities for dry runs, smoke checks, and local scoring.",
            "Use Inspect for config, scenario, status, and summary views.",
            "Live batch cells run in parallel with isolated Kali and target stacks.",
            "",
            f"Config: {self.config.path}",
            f"Runs root: {self._runs_root()}",
            f"Latest artifact dir: {latest}",
            f"Latest full batch dir: {full_batch or 'none yet'}",
            f"Single run: {self.single_model} x {self.single_scenario}",
            f"Selected batch: {len(self.matrix_models)} models x {len(self.matrix_scenarios)} scenarios",
        ]

    def _run_menu_lines(self) -> list[str]:
        return [
            "Run batch guide:",
            "",
            "Before live runs: use Live preflight.",
            "",
            "To run exactly one cell:",
            f"Single run: {self.single_model} x {self.single_scenario}",
            "Use Choose single-run model, Choose single-run scenario, then Run single model x scenario.",
            "",
            "To run a batch:",
            f"Selected batch: {len(self.matrix_models)} models x {len(self.matrix_scenarios)} scenarios",
            f"Models: {', '.join(self._selected_models()) or 'none'}",
            f"Scenarios: {', '.join(self._selected_scenarios()) or 'none'}",
            "Use Choose batch models, Choose batch scenarios, then Run selected batch.",
            "Batch cells run concurrently; each cell gets its own Kali agent, target, network, and volumes.",
            f"Concurrency: {self.config.experiment.get('parallel_cells') or 'all selected cells'}",
            "",
            "To run the full batch:",
            "Use Run full batch, then Verify full batch artifacts, Generate full batch report,",
            "and View full batch summary.",
            "",
            f"Full batch artifacts: {self._latest_full_batch_dir() or 'none yet'}",
            f"New runs are written under: {self._runs_root()}",
        ]

    def _testing_lines(self) -> list[str]:
        return [
            "Testing and utilities:",
            "",
            "Use this menu for checks that should not be confused with live batch results:",
            "- quickstart and synthetic demo transcript generation",
            "- dry pipeline artifact checks",
            "- one-cell live smoke runs",
            "- deterministic-judge live batch runs",
            "- ad hoc scoring and G-study checks on workspace transcripts",
            "",
            "Run batch is the live experiment menu.",
            f"Each utility run writes to: {self._runs_root()}/<timestamp>__<kind>",
        ]

    def _log_viewer_lines(self) -> list[str]:
        self.visible_log_dirs = self._latest_run_dirs()
        latest = self.visible_log_dirs[0] if self.visible_log_dirs else None
        selected = self.selected_log_dir or latest
        if selected is not None:
            self.selected_log_dir = selected
        lines = [
            "Run log viewer:",
            "",
            f"Runs root: {self._runs_root()}",
            f"Selected run: {selected or 'none'}",
            "",
            "Use a numbered run entry to inspect its manifest, artifact counts, and summary charts.",
            "Use Analyze selected run with LLM for an OpenRouter summary of the selected run.",
            "",
            "Recent runs:",
        ]
        if not self.visible_log_dirs:
            lines.append("- no run directories yet")
            return lines
        for index, path in enumerate(self.visible_log_dirs[:12], start=1):
            manifest = self._read_manifest(path)
            status = manifest.get("status", "unknown")
            kind = manifest.get("kind", path.name)
            lines.append(f"{index}. {path.name}  [{kind}, {status}]")
        return lines

    def _log_menu_items(self) -> tuple[str, ...]:
        self.visible_log_dirs = self._latest_run_dirs()
        run_items = tuple(
            f"{index}. {path.name}" for index, path in enumerate(self.visible_log_dirs[:20], start=1)
        )
        return ("Refresh logs", "Analyze selected run with LLM", *run_items, "Back")

    def _run_log_action(self, label: str) -> None:
        if label == "Refresh logs":
            self._set_detail_lines(self._log_viewer_lines())
            self.message = "refreshed run logs"
            return
        if label == "Analyze selected run with LLM":
            if self.selected_log_dir is None:
                self.message = "select a run first"
                self._set_detail_lines(self._log_viewer_lines())
                return
            run_dir = self.selected_log_dir
            holder: dict[str, list[str]] = {}

            def worker(progress: Callable[[str], None]) -> None:
                progress(f"building LLM analysis for {run_dir}")
                holder["lines"] = self._log_detail_lines(run_dir, include_llm=True)
                progress("analysis ready")

            if self._observe("LLM log analysis", worker):
                self._set_detail_lines(holder.get("lines", []))
                self.message = "loaded selected run with LLM analysis"
            return
        if ". " in label:
            prefix = label.split(". ", 1)[0]
            if prefix.isdigit():
                index = int(prefix) - 1
                if 0 <= index < len(self.visible_log_dirs):
                    self.selected_log_dir = self.visible_log_dirs[index]
                    self._set_detail_lines(self._log_detail_lines(self.selected_log_dir, include_llm=False))
                    self.message = f"loaded run log: {self.selected_log_dir.name}"
                    return
        self.message = "unknown log action"

    def _log_detail_lines(self, run_dir: Path, include_llm: bool) -> list[str]:
        if (run_dir / "scores.csv").exists() or (run_dir / "run_metrics.csv").exists():
            return self._post_run_summary(run_dir, include_llm=include_llm)
        manifest = self._read_manifest(run_dir)
        transcript_count = len(list((run_dir / "transcripts").glob("*.json")))
        files = sorted(path for path in run_dir.rglob("*") if path.is_file())
        lines = [
            "Run log",
            f"Directory: {run_dir}",
            "",
            "Manifest:",
        ]
        if manifest:
            for key, value in sorted(manifest.items()):
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- not found")
        lines.extend(
            [
                "",
                "Artifacts:",
                f"- transcripts: {transcript_count} {self._count_bar(transcript_count)}",
                f"- files: {len(files)} {self._count_bar(len(files))}",
            ]
        )
        summary_path = run_dir / "summary.json"
        if summary_path.exists():
            lines.extend(["", "Summary:", *self._summary_lines(summary_path)])
        lines.extend(["", "Files:"])
        lines.extend(f"- {path.relative_to(run_dir)}" for path in files[:40])
        if len(files) > 40:
            lines.append(f"- ... {len(files) - 40} more")
        if include_llm:
            lines.extend(self._post_run_summary(run_dir, include_llm=True))
        return lines

    def _single_model_lines(self) -> list[str]:
        return [
            "Select the model for a one-cell run.",
            f"Current: {self.single_model}",
            "",
            "Press Enter on a model name to select it.",
        ]

    def _single_scenario_lines(self) -> list[str]:
        return [
            "Select the scenario for a one-cell run.",
            f"Current: {self.single_scenario}",
            "",
            "Press Enter on a scenario name to select it.",
        ]

    def _matrix_selection_lines(self) -> list[str]:
        return [
            "Selected batch:",
            f"Models ({len(self.matrix_models)}): {', '.join(self._selected_models()) or 'none'}",
            f"Scenarios ({len(self.matrix_scenarios)}): {', '.join(self._selected_scenarios()) or 'none'}",
            "",
            "Use the model/scenario selection menus to toggle entries.",
            "The selected batch run executes every selected model against every selected scenario.",
        ]

    def _selection_message(self) -> str:
        return f"selected batch: {len(self.matrix_models)} models x {len(self.matrix_scenarios)} scenarios"

    def _selected_models(self) -> tuple[str, ...]:
        return tuple(name for name in self.config.model_names if name in self.matrix_models)

    def _selected_scenarios(self) -> tuple[str, ...]:
        return tuple(name for name in self.config.scenario_names if name in self.matrix_scenarios)

    def _scenario_lines(self) -> list[str]:
        lines = []
        for scenario in load_scenarios(self.config):
            lines.append(f"{scenario.name}: {scenario.status}")
            lines.append(f"  {scenario.construct}")
            for check in scenario.objective_checks:
                lines.append(f"  - {check}")
        return lines

    def _model_judge_lines(self) -> list[str]:
        lines = ["Models:"]
        for model in self.config.model_names:
            lines.append(f"- {model}")
        lines.append("")
        lines.append("Judges:")
        for judge in self.config.judge_names:
            lines.append(f"- {judge}")
        lines.append("")
        lines.append(f"OpenRouter base URL: {self.config.openrouter['base_url']}")
        lines.append(f"API key env: {self.config.openrouter['api_key_env']}")
        findings = self.config.data.get("findings", {})
        lines.append("")
        lines.append("Finding matching:")
        lines.append(f"- mode: {findings.get('match_mode', 'keywords')}")
        lines.append(f"- LLM fallback: {findings.get('llm_match_fallback', 'keywords')}")
        lines.append(f"- max tokens: {findings.get('llm_match_max_tokens', 'default')}")
        return lines

    def _summary_lines(self, path: str | Path) -> list[str]:
        path = Path(path)
        if not path.exists():
            return [f"summary not found: {path}"]
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return [f"{key}: {value}" for key, value in sorted(data.items())]

    def _post_run_summary(self, artifact_dir: str | Path, include_llm: bool) -> list[str]:
        try:
            return build_run_summary_lines(artifact_dir, config=self.config, include_llm=include_llm)
        except Exception as exc:
            summary_path = Path(artifact_dir) / "summary.json"
            return [
                f"post-run summary unavailable: {exc}",
                "",
                *self._summary_lines(summary_path),
            ]

    def _runs_root(self) -> Path:
        return self.workspace / "runs"

    def _new_run_dir(self, kind: str, metadata: dict[str, object] | None = None) -> Path:
        root = self._runs_root()
        root.mkdir(parents=True, exist_ok=True)
        slug = self._slug(kind)
        base = root / f"{time.strftime('%Y%m%d_%H%M%S')}__{slug}"
        path = base
        counter = 2
        while path.exists():
            path = root / f"{base.name}__{counter}"
            counter += 1
        path.mkdir(parents=True)
        manifest = {
            "kind": slug,
            "status": "created",
            "created_at": self._now(),
            "config_path": str(self.config.path),
        }
        if metadata:
            manifest.update(metadata)
        self._write_manifest(path, manifest)
        self.latest_artifact_dir = path
        self.selected_log_dir = path
        return path

    def _slug(self, value: str) -> str:
        chars = [char.lower() if char.isalnum() else "_" for char in value.strip()]
        slug = "".join(chars).strip("_")
        while "__" in slug:
            slug = slug.replace("__", "_")
        return slug or "run"

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z")

    def _manifest_path(self, run_dir: Path) -> Path:
        return run_dir / "run_manifest.yaml"

    def _write_manifest(self, run_dir: Path, data: dict[str, object]) -> None:
        self._manifest_path(run_dir).write_text(
            yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )

    def _read_manifest(self, run_dir: Path) -> dict[str, object]:
        path = self._manifest_path(run_dir)
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data if isinstance(data, dict) else {}

    def _update_run_manifest(self, run_dir: Path, updates: dict[str, object]) -> None:
        data = self._read_manifest(run_dir)
        data.update(updates)
        self._write_manifest(run_dir, data)

    def _latest_run_dirs(self) -> list[Path]:
        root = self._runs_root()
        if not root.exists():
            return []
        return sorted(
            [path for path in root.iterdir() if path.is_dir()],
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )

    def _latest_run_dir(self, kind: str | None = None) -> Path | None:
        expected = self._slug(kind) if kind else None
        for path in self._latest_run_dirs():
            manifest = self._read_manifest(path)
            if expected is None or manifest.get("kind") == expected or path.name.endswith(f"__{expected}"):
                return path
        return None

    def _latest_full_batch_dir(self) -> Path | None:
        return self._latest_run_dir("full_batch")

    def _find_latest_artifact_dir(self) -> Path | None:
        run_candidates = [
            path
            for path in self._latest_run_dirs()
            if any((path / name).exists() for name in ("summary.json", "scores.csv", "run_metrics.csv"))
        ]
        legacy_candidates = [
            self.workspace / "final_experiment",
            self.workspace / "live_pipeline_llm",
            self.workspace / "live_pipeline_deterministic",
            self.workspace / "dry_pipeline",
            self.workspace / "experiments",
        ]
        existing = [
            path
            for path in (*run_candidates, *legacy_candidates)
            if (path / "summary.json").exists() or (path / "scores.csv").exists()
        ]
        if not existing:
            return None
        return max(existing, key=lambda path: path.stat().st_mtime)

    def _require_latest_artifact_dir(self) -> Path | None:
        self.latest_artifact_dir = self._find_latest_artifact_dir() or self.latest_artifact_dir
        if self.latest_artifact_dir is None:
            self.message = "no pipeline artifacts found; run dry or live pipeline first"
            self._set_detail_lines([str(self.workspace)])
            return None
        return self.latest_artifact_dir

    def _latest_summary_path(self) -> Path | None:
        artifact_dir = self._find_latest_artifact_dir()
        if artifact_dir:
            self.latest_artifact_dir = artifact_dir
            return artifact_dir / "summary.json"
        for path in (self.workspace / "summary.json", self.workspace / "quickstart" / "summary.json"):
            if path.exists():
                return path
        return None

    def _count_bar(self, value: int, width: int = 16) -> str:
        capped = min(width, value)
        return "[" + "#" * capped + "." * (width - capped) + "]"

    def _add(self, y: int, x: int, text: str, attr: int = curses.A_NORMAL) -> None:
        height, width = self.screen.getmaxyx()
        if y >= height or x >= width:
            return
        self.screen.addstr(y, x, text[: max(0, width - x - 1)], attr)


def run_tui(
    workspace: str | Path = "outputs/tui",
    config: ScopebenchConfig | None = None,
) -> None:
    """Launch the terminal management UI."""

    config = config or load_config()
    Path(workspace).mkdir(parents=True, exist_ok=True)
    curses.wrapper(lambda screen: ScopebenchTUI(screen, workspace, config).run())
