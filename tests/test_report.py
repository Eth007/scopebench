from experiments.pipeline import run_experiment_pipeline
from scopebench.config import load_config


def test_analysis_report_contains_plan_required_sections(tmp_path):
    config = load_config()
    result = run_experiment_pipeline(tmp_path, config=config, dry_run=True)
    text = result.analysis_report_md.read_text(encoding="utf-8")

    assert "Model Summary" in text
    assert "Scenario Summary" in text
    assert "Judge Summary" in text
    assert "Safety Dimension Summary" in text
    assert "Finding Evaluation" in text
    assert "Qualitative Examples" in text
    assert (tmp_path / "analysis" / "model_summary.csv").exists()
    assert (tmp_path / "analysis" / "scenario_summary.csv").exists()
    assert result.finding_summary_csv.exists()
    assert result.finding_evaluation_md.exists()
