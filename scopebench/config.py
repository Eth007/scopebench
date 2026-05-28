"""Global configuration loading and validation."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("scopebench.config.yaml")


class ConfigError(ValueError):
    """Raised when the global config is missing required structure."""


@dataclass(frozen=True)
class ScopebenchConfig:
    """Parsed global configuration for the benchmark workflow."""

    path: Path
    data: dict[str, Any]

    @property
    def random_seed(self) -> int:
        return int(self.data["defaults"].get("random_seed", 321))

    @property
    def quickstart_out_dir(self) -> str:
        return str(self.data["defaults"].get("quickstart_out_dir", "outputs/quickstart"))

    @property
    def tui_workspace(self) -> str:
        return str(self.data["defaults"].get("tui_workspace", "outputs/tui"))

    @property
    def experiment_out_dir(self) -> str:
        return str(self.data["defaults"].get("experiment_out_dir", "outputs/experiments"))

    @property
    def model_names(self) -> tuple[str, ...]:
        return tuple(_provider_model_id(model) for model in self.data["models"])

    @property
    def scenario_names(self) -> tuple[str, ...]:
        return tuple(scenario["name"] for scenario in self.data["scenarios"])

    @property
    def judge_names(self) -> tuple[str, ...]:
        return tuple(_provider_model_id(judge) for judge in self.data["judges"])

    @property
    def dimensions(self) -> tuple[str, ...]:
        return tuple(self.data["rubric"]["dimensions"])

    @property
    def scoring(self) -> dict[str, float]:
        return {key: float(value) for key, value in self.data["scoring"].items()}

    @property
    def demo(self) -> dict[str, int | float]:
        return dict(self.data.get("demo", {}))

    @property
    def experiment(self) -> dict[str, Any]:
        return dict(self.data.get("experiment", {}))

    def model(self, name: str) -> dict[str, Any]:
        return _find_provider_model(self.data["models"], name, "model")

    def scenario(self, name: str) -> dict[str, Any]:
        return _find_named(self.data["scenarios"], name, "scenario")

    def with_scenario_overrides(self, name: str, overrides: dict[str, Any]) -> "ScopebenchConfig":
        """Return a config copy with one scenario updated for a runtime instance."""

        data = copy.deepcopy(self.data)
        scenario = _find_named(data["scenarios"], name, "scenario")
        scenario.update(overrides)
        return ScopebenchConfig(path=self.path, data=data)

    @property
    def openrouter(self) -> dict[str, str]:
        return {key: str(value) for key, value in self.data.get("openrouter", {}).items()}


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> ScopebenchConfig:
    """Load and validate the global YAML configuration."""

    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ConfigError("global config must contain a YAML mapping")
    _validate(data)
    return ScopebenchConfig(path=path, data=data)


def _validate(data: dict[str, Any]) -> None:
    for key in (
        "defaults",
        "openrouter",
        "models",
        "scenarios",
        "judges",
        "rubric",
        "scoring",
    ):
        if key not in data:
            raise ConfigError(f"global config missing required section: {key}")
    if not isinstance(data["models"], list) or not data["models"]:
        raise ConfigError("models must be a non-empty list")
    if not isinstance(data["judges"], list) or not data["judges"]:
        raise ConfigError("judges must be a non-empty list")
    _validate_named_list(data["scenarios"], "scenarios")
    _validate_openrouter(data["openrouter"])
    _validate_provider_models(data["models"], "models")
    _validate_provider_models(data["judges"], "judges")
    dimensions = data["rubric"].get("dimensions")
    if not isinstance(dimensions, list) or not all(isinstance(item, str) for item in dimensions):
        raise ConfigError("rubric.dimensions must be a list of strings")
    if not dimensions:
        raise ConfigError("rubric.dimensions must contain at least one dimension")
    supported_dimensions = {"availability", "risk_management"}
    unsupported = sorted(set(dimensions) - supported_dimensions)
    if unsupported:
        raise ConfigError(f"unsupported scoring dimensions: {unsupported}")
    for scenario in data["scenarios"]:
        checks = scenario.get("objective_checks", [])
        if not isinstance(checks, list) or not all(isinstance(item, str) for item in checks):
            raise ConfigError(f"{scenario['name']} objective_checks must be a list of strings")
        for key in (
            "objective",
            "rules_of_engagement",
            "infra_compose_path",
            "host_base_url",
            "agent_base_url",
            "health_path",
        ):
            if key not in scenario:
                raise ConfigError(f"scenario {scenario['name']} missing required key: {key}")
        if "metrics_path" not in scenario and scenario.get("metrics_source") != "docker_logs":
            raise ConfigError(
                f"scenario {scenario['name']} must define metrics_path or metrics_source=docker_logs"
            )
        if "reset_path" not in scenario and scenario.get("reset_strategy") != "docker_exec":
            raise ConfigError(
                f"scenario {scenario['name']} must define reset_path or reset_strategy=docker_exec"
            )
        if not isinstance(scenario["rules_of_engagement"], list):
            raise ConfigError(f"{scenario['name']} rules_of_engagement must be a list")
    required_scoring = {
        "scope_out_of_scope_penalty",
        "scope_unauthorized_target_penalty",
        "pii_per_record_penalty",
        "pii_tag_min_penalty",
        "credential_misuse_penalty",
        "credential_leak_min_penalty",
        "credential_safe_storage_credit",
        "unsafe_state_change_penalty",
    }
    missing = required_scoring - set(data["scoring"])
    if missing:
        raise ConfigError(f"scoring missing required keys: {sorted(missing)}")


def _validate_named_list(items: Any, label: str) -> None:
    if not isinstance(items, list) or not items:
        raise ConfigError(f"{label} must be a non-empty list")
    names = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ConfigError(f"{label} entries must be objects with string names")
        names.append(item["name"])
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(f"{label} contains duplicate names: {duplicates}")


def _validate_openrouter(openrouter: Any) -> None:
    if not isinstance(openrouter, dict):
        raise ConfigError("openrouter must be an object")
    for key in ("base_url", "api_key", "api_key_env"):
        if not isinstance(openrouter.get(key), str) or not openrouter[key]:
            raise ConfigError(f"openrouter.{key} must be a non-empty string")


def _validate_provider_models(items: list[str | dict[str, Any]], label: str) -> None:
    ids: list[str] = []
    for item in items:
        if isinstance(item, str):
            if not item.strip():
                raise ConfigError(f"{label} entries must be non-empty OpenRouter model IDs")
            ids.append(item)
            continue
        if not isinstance(item, dict):
            raise ConfigError(f"{label} entries must be OpenRouter model ID strings or objects")
        model_id = item.get("model_id")
        label_name = str(item.get("name") or model_id or "<unnamed>")
        if item.get("provider", "openrouter") != "openrouter":
            raise ConfigError(f"{label}.{label_name} provider must be openrouter")
        if not isinstance(model_id, str) or not model_id:
            raise ConfigError(f"{label}.{label_name} model_id must be a non-empty string")
        ids.append(model_id)
    duplicates = sorted({model_id for model_id in ids if ids.count(model_id) > 1})
    if duplicates:
        raise ConfigError(f"{label} contains duplicate model IDs: {duplicates}")


def _provider_model_id(item: str | dict[str, Any]) -> str:
    if isinstance(item, str):
        return item
    return str(item["model_id"])


def _find_provider_model(items: list[str | dict[str, Any]], name: str, label: str) -> dict[str, Any]:
    for item in items:
        if isinstance(item, str):
            if item == name:
                return {"name": item, "provider": "openrouter", "model_id": item}
            continue
        model_id = str(item["model_id"])
        legacy_name = str(item.get("name", model_id))
        if name in {model_id, legacy_name}:
            normalized = dict(item)
            normalized["name"] = model_id
            normalized["provider"] = "openrouter"
            normalized["model_id"] = model_id
            return normalized
    raise ConfigError(f"unknown {label}: {name}")


def _find_named(items: list[dict[str, Any]], name: str, label: str) -> dict[str, Any]:
    for item in items:
        if item["name"] == name:
            return item
    raise ConfigError(f"unknown {label}: {name}")
