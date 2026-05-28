from experiments.pipeline import run_experiment_pipeline
from measurement.run_summary import build_run_summary_lines
from scopebench.config import load_config


def test_run_summary_highlights_scores_metrics_and_dimensions(tmp_path):
    config = load_config()
    run_experiment_pipeline(tmp_path, config=config, dry_run=True)

    lines = build_run_summary_lines(tmp_path, config=config, include_llm=False)
    text = "\n".join(lines)

    assert "Run summary" in lines[0]
    assert "Mean safety-dimension score:" in text
    assert "Operational metrics:" in text
    assert "Safety dimension scores:" in text
    assert "By model:" in text
    assert "By scenario:" in text
    assert "Weighted gold-finding recall:" in text
    assert "LLM summary:" not in text
    assert (tmp_path / "analysis" / "tui_summary.md").exists()
