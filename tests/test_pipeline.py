from experiments.pipeline import run_experiment_pipeline
from measurement.audit import verify_experiment_artifacts
from scopebench.config import load_config


def test_dry_experiment_pipeline_writes_complete_artifact_set(tmp_path):
    config = load_config()

    result = run_experiment_pipeline(tmp_path, config=config, dry_run=True)

    assert result.transcript_count == len(config.model_names) * len(config.scenario_names)
    assert result.score_count == (
        len(config.model_names)
        * len(config.scenario_names)
        * len(config.judge_names)
        * len(config.dimensions)
    )
    assert result.run_metrics_csv.exists()
    assert result.scores_csv.exists()
    assert result.gstudy_csv.exists()
    assert result.summary_json.exists()
    assert result.analysis_report_md.exists()
    assert result.finding_summary_csv.exists()
    assert result.finding_evaluation_md.exists()

    audit = verify_experiment_artifacts(tmp_path, config=config)
    assert audit.ok
    assert "summary.json indicates dry_run=true" in audit.warnings[0]
