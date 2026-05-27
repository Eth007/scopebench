from experiments.preflight import run_preflight
from scopebench.config import load_config


def test_preflight_static_checks_report_required_surfaces():
    config = load_config()

    result = run_preflight(config=config, live_scenarios=False)
    names = {check.name for check in result.checks}

    assert "executable:docker" in names
    assert "openrouter_api_key" in names
    assert "compose:saas_site" in names
    assert "compose:water_ics" in names
