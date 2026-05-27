from infra.lifecycle import _parse_compose_port, _target_port_from_url
from scopebench.config import load_config


def test_compose_port_parser_normalizes_wildcard_hosts():
    assert _parse_compose_port("0.0.0.0:49153") == ("127.0.0.1", 49153)
    assert _parse_compose_port("[::]:49154") == ("127.0.0.1", 49154)
    assert _parse_compose_port("[::1]:49154") == ("127.0.0.1", 49154)
    assert _parse_compose_port("127.0.0.1:49155") == ("127.0.0.1", 49155)


def test_runtime_config_can_bind_one_scenario_instance():
    config = load_config()
    runtime = config.with_scenario_overrides(
        "saas_site",
        {
            "compose_project_name": "scopebench_test_cell",
            "host_base_url": "http://127.0.0.1:49156",
        },
    )

    assert runtime.scenario("saas_site")["compose_project_name"] == "scopebench_test_cell"
    assert runtime.scenario("saas_site")["host_base_url"] == "http://127.0.0.1:49156"
    assert "compose_project_name" not in config.scenario("saas_site")


def test_target_port_defaults_to_agent_base_url_port():
    assert _target_port_from_url({"agent_base_url": "http://target"}) == 80
    assert _target_port_from_url({"agent_base_url": "http://target:8000"}) == 8000
