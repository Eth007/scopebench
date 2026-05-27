from experiments.pipeline import run_experiment_pipeline
from measurement.audit import verify_experiment_artifacts
from scopebench.config import load_config


def test_artifact_audit_detects_missing_scores(tmp_path):
    config = load_config()
    run_experiment_pipeline(tmp_path, config=config, dry_run=True)
    (tmp_path / "scores.csv").unlink()

    result = verify_experiment_artifacts(tmp_path, config=config)

    assert not result.ok
    assert any("missing CSV artifact" in error for error in result.errors)
