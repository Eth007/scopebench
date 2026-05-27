"""Local scenario-infrastructure management primitives."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scopebench.config import ScopebenchConfig, load_config


@dataclass(frozen=True)
class ScenarioInfo:
    """Metadata for one scenario environment."""

    name: str
    construct: str
    objective_checks: tuple[str, ...]
    status: str


def load_scenarios(config: ScopebenchConfig | None = None) -> list[ScenarioInfo]:
    """Load scenario metadata and attach Docker infrastructure status."""

    config = config or load_config()
    results = []
    for scenario in config.data["scenarios"]:
        checks = scenario.get("objective_checks", [])
        if not isinstance(checks, list):
            raise ValueError(f"{scenario['name']} objective_checks must be a list")
        results.append(
            ScenarioInfo(
                name=scenario["name"],
                construct=str(scenario.get("construct", "")),
                objective_checks=tuple(str(check) for check in checks),
                status=_status_for(scenario),
            )
        )
    return results


def validate_infra(config: ScopebenchConfig | None = None) -> dict[str, str]:
    """Validate local scenario-management files."""

    config = config or load_config()
    checks = {
        "global_config": config.path,
        "quickstart_runner": Path("infra/run_quickstart.sh"),
    }
    return {name: "ok" if path.exists() else f"missing: {path}" for name, path in checks.items()}


def status_lines(config: ScopebenchConfig | None = None) -> list[str]:
    """Return compact human-readable infrastructure status lines."""

    config = config or load_config()
    lines = ["Scenario infrastructure status:"]
    for name, status in validate_infra(config).items():
        lines.append(f"- {name}: {status}")
    lines.append(f"- openrouter_api_key: {_openrouter_key_status(config)}")
    for scenario in load_scenarios(config):
        lines.append(f"- {scenario.name}: {scenario.status}")
    return lines


def _status_for(scenario: dict[str, object]) -> str:
    compose_path = Path(str(scenario.get("infra_compose_path", "")))
    if compose_path.exists():
        return f"configured ({compose_path})"
    return "missing Docker Compose file"


def _openrouter_key_status(config: ScopebenchConfig) -> str:
    api_key = config.openrouter.get("api_key", "")
    env_name = config.openrouter.get("api_key_env", "OPENROUTER_API_KEY")
    if api_key and api_key != "YOUR_OPENROUTER_API_KEY":
        return f"configured in {config.path}"
    return f"placeholder in config; set {env_name} for real runs"
