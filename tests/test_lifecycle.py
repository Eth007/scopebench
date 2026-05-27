from infra.lifecycle import _compose_env, _lab_subnet, _parse_compose_port, _target_port_from_url
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


def test_lab_subnet_is_small_deterministic_and_project_specific():
    first = _lab_subnet("sb_1_saas_site_openai")
    second = _lab_subnet("sb_2_saas_site_openai")

    assert first.startswith("10.")
    assert first.endswith("/28")
    assert first != second
    assert _lab_subnet("sb_1_saas_site_openai") == first
    assert _compose_env("sb_1_saas_site_openai")["SCOPEBENCH_LAB_SUBNET"] == first


def test_compose_env_includes_saas_lock_controls():
    env = _compose_env(
        "sb_1_saas_site_openai",
        {
            "failed_login_outage_threshold": 4,
            "failed_login_window_s": 60,
            "outage_lock_ttl_s": 600,
        },
    )

    assert env["SAAS_FAILED_LOGIN_OUTAGE_THRESHOLD"] == "4"
    assert env["SAAS_FAILED_LOGIN_WINDOW_S"] == "60"
    assert env["SAAS_OUTAGE_LOCK_TTL_S"] == "600"
