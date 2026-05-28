from infra.lifecycle import (
    CommandResult,
    ScenarioLifecycleError,
    _compose_env,
    _lab_subnet,
    _parse_compose_port,
    _target_port_from_url,
    compose_command,
    compose_command_status,
)
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


def test_compose_command_prefers_docker_compose_plugin(monkeypatch):
    def fake_run_command(args, timeout_s):
        return CommandResult(" ".join(args), 0, "Docker Compose version v2.0.0", "")

    monkeypatch.setattr("infra.lifecycle._run_command", fake_run_command)

    assert compose_command() == ["docker", "compose"]


def test_compose_command_falls_back_to_legacy_binary(monkeypatch):
    def fake_run_command(args, timeout_s):
        if args[:3] == ["docker", "compose", "version"]:
            return CommandResult(" ".join(args), 125, "", "unknown shorthand flag: 'f'")
        return CommandResult(" ".join(args), 0, "docker-compose version 1.29.2", "")

    monkeypatch.setattr("infra.lifecycle._run_command", fake_run_command)
    monkeypatch.setattr("infra.lifecycle.shutil.which", lambda name: "/usr/bin/docker-compose")

    assert compose_command() == ["docker-compose"]


def test_compose_command_status_reports_missing_compose(monkeypatch):
    def fake_run_command(args, timeout_s):
        return CommandResult(" ".join(args), 125, "", "unknown command")

    monkeypatch.setattr("infra.lifecycle._run_command", fake_run_command)
    monkeypatch.setattr("infra.lifecycle.shutil.which", lambda name: None)

    result = compose_command_status()

    assert result.returncode == 1
    assert "Docker Compose is required" in result.stderr
    try:
        compose_command()
    except ScenarioLifecycleError as exc:
        assert "docker compose version" in str(exc)
    else:
        raise AssertionError("compose_command should fail when no Compose command is available")
