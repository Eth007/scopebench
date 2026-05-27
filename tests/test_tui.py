import curses

import yaml

from scopebench.config import load_config
from scopebench.tui import ScopebenchTUI


class FakeScreen:
    def keypad(self, value: bool) -> None:
        pass

    def getmaxyx(self) -> tuple[int, int]:
        return (50, 180)

    def erase(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    def addstr(self, *args: object) -> None:
        pass

    def getch(self) -> int:
        return ord("n")


class ScrollScreen(FakeScreen):
    def getmaxyx(self) -> tuple[int, int]:
        return (12, 120)


def test_tui_tracks_single_cell_and_batch_selections(tmp_path):
    config = load_config()
    tui = ScopebenchTUI(FakeScreen(), tmp_path, config)

    tui._run_action("Run batch")
    tui._run_action("Choose single-run model")
    tui._run_action(config.model_names[1])
    tui._run_action("Choose single-run scenario")
    tui._run_action(config.scenario_names[1])

    assert tui.single_model == config.model_names[1]
    assert tui.single_scenario == config.scenario_names[1]

    tui._run_action("Choose batch models")
    tui._run_action("Clear selected models")
    tui._run_action(f"[ ] {config.model_names[0]}")

    assert tui._selected_models() == (config.model_names[0],)
    assert tui._selected_scenarios() == config.scenario_names


def test_tui_detail_pane_scrolls_logs(tmp_path):
    config = load_config()
    tui = ScopebenchTUI(ScrollScreen(), tmp_path, config)
    tui._set_detail_lines([f"line {index}" for index in range(20)], follow_tail=True)

    tui._draw()
    assert tui.detail_scroll_top == 14

    assert tui._handle_scroll_key(curses.KEY_PPAGE)
    assert tui.detail_follow_tail is False
    assert tui.detail_scroll_top == 8

    assert tui._handle_scroll_key(curses.KEY_HOME)
    assert tui.detail_scroll_top == 0

    assert tui._handle_scroll_key(curses.KEY_END)
    assert tui.detail_follow_tail is True
    assert tui.detail_scroll_top == 14


def test_tui_wraps_long_detail_lines(tmp_path):
    config = load_config()
    tui = ScopebenchTUI(ScrollScreen(), tmp_path, config)
    tui._set_detail_lines(["x" * 160])

    wrapped = tui._wrapped_detail_lines(width=40)

    assert len(wrapped) == 4
    assert all(len(line) <= 40 for line in wrapped)


def test_tui_creates_timestamped_run_dirs_with_manifest(tmp_path):
    config = load_config()
    tui = ScopebenchTUI(FakeScreen(), tmp_path, config)

    run_dir = tui._new_run_dir("dry pipeline", {"dry_run": True})

    assert run_dir.parent == tmp_path / "runs"
    assert run_dir.name.endswith("__dry_pipeline")
    assert tui.latest_artifact_dir == run_dir
    assert tui.selected_log_dir == run_dir

    manifest = yaml.safe_load((run_dir / "run_manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["kind"] == "dry_pipeline"
    assert manifest["status"] == "created"
    assert manifest["dry_run"] is True


def test_tui_log_viewer_lists_and_loads_runs(tmp_path):
    config = load_config()
    tui = ScopebenchTUI(FakeScreen(), tmp_path, config)
    first = tui._new_run_dir("quickstart", {"dry_run": True})
    second = tui._new_run_dir("full_batch", {"judge_mode": "llm"})

    tui._run_action("View run logs")

    assert tui.menu == "logs"
    menu_items = tui._menu_items()
    assert "Refresh logs" in menu_items
    assert any(first.name in item for item in menu_items)
    assert any(second.name in item for item in menu_items)

    run_item = next(item for item in menu_items if second.name in item)
    tui._run_action(run_item)

    assert tui.selected_log_dir == second
    assert any("Manifest:" in line for line in tui.detail_lines)
