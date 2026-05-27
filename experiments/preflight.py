"""Preflight checks for live experiment runs."""

from __future__ import annotations

from dataclasses import dataclass
import shutil
from pathlib import Path
from typing import Callable

from infra.lifecycle import ScenarioLifecycle, ScenarioLifecycleError
from infra.openrouter import OpenRouterClient, OpenRouterError
from scenarios.checks import collect_scenario_checks, probe_availability, reset_scenario_state
from scopebench.config import ScopebenchConfig, load_config


@dataclass(frozen=True)
class PreflightCheck:
    """One preflight check result."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class PreflightResult:
    """Collection of preflight checks."""

    checks: tuple[PreflightCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


def run_preflight(
    config: ScopebenchConfig | None = None,
    live_scenarios: bool = False,
    progress: Callable[[str], None] | None = None,
) -> PreflightResult:
    """Run preflight checks for configured experiments."""

    config = config or load_config()
    checks: list[PreflightCheck] = []
    if progress:
        progress("checking local executables")
    checks.append(_check_executable("docker"))
    checks.append(_check_executable("python"))
    if progress:
        progress("checking scenario compose files")
    checks.extend(_check_compose_files(config))
    checks.append(_check_openrouter_key(config))
    if progress:
        progress("validating OpenRouter model IDs")
    checks.extend(_check_openrouter_models(config))
    if live_scenarios:
        checks.extend(_check_live_scenarios(config, progress=progress))
    return PreflightResult(checks=tuple(checks))


def _check_executable(name: str) -> PreflightCheck:
    path = shutil.which(name)
    return PreflightCheck(
        name=f"executable:{name}",
        ok=path is not None,
        detail=path or "not found on PATH",
    )


def _check_compose_files(config: ScopebenchConfig) -> list[PreflightCheck]:
    checks = []
    for scenario_name in config.scenario_names:
        scenario = config.scenario(scenario_name)
        path = Path(str(scenario["infra_compose_path"]))
        checks.append(
            PreflightCheck(
                name=f"compose:{scenario_name}",
                ok=path.exists(),
                detail=str(path),
            )
        )
    return checks


def _check_openrouter_key(config: ScopebenchConfig) -> PreflightCheck:
    try:
        OpenRouterClient.from_config(config)._api_key()
    except OpenRouterError as exc:
        return PreflightCheck("openrouter_api_key", False, str(exc))
    return PreflightCheck("openrouter_api_key", True, config.openrouter["api_key_env"])


def _check_openrouter_models(config: ScopebenchConfig) -> list[PreflightCheck]:
    try:
        results = OpenRouterClient.from_config(config).validate_configured_models()
    except OpenRouterError as exc:
        return [PreflightCheck("openrouter_models", False, str(exc))]
    return [
        PreflightCheck(
            name=f"openrouter_model:{model_id}",
            ok=present,
            detail="listed" if present else "missing from OpenRouter /models",
        )
        for model_id, present in results.items()
    ]


def _check_live_scenarios(
    config: ScopebenchConfig,
    progress: Callable[[str], None] | None = None,
) -> list[PreflightCheck]:
    checks: list[PreflightCheck] = []
    expected_codex_version = str(config.experiment.get("codex_cli_version", "")).strip()
    for scenario_name in config.scenario_names:
        lifecycle = ScenarioLifecycle(scenario_name, config=config)
        try:
            if progress:
                progress(f"starting live scenario preflight: {scenario_name}")
            lifecycle.up(build=True)
            if progress:
                progress(f"checking Codex CLI in agent: {scenario_name}")
            runtime_config = lifecycle.runtime_config()
            codex_result = lifecycle.codex_version()
            codex_detail = codex_result.stdout.strip() or codex_result.stderr.strip()
            codex_ok = codex_result.returncode == 0
            if expected_codex_version:
                codex_ok = codex_ok and expected_codex_version in codex_detail
            checks.append(
                PreflightCheck(
                    name=f"agent_codex:{scenario_name}",
                    ok=codex_ok,
                    detail=codex_detail or "no codex version output",
                )
            )
            env_name = config.openrouter.get("api_key_env", "OPENROUTER_API_KEY")
            env_result = lifecycle.exec_agent(
                f'test -n "${env_name}" && echo configured || echo missing',
                timeout_s=10,
            )
            env_detail = env_result.stdout.strip() or env_result.stderr.strip()
            checks.append(
                PreflightCheck(
                    name=f"agent_openrouter_env:{scenario_name}",
                    ok=env_result.returncode == 0 and env_detail == "configured",
                    detail=f"{env_name}={env_detail}",
                )
            )
            if progress:
                progress(f"resetting and probing target: {scenario_name}")
            reset_scenario_state(scenario_name, config=runtime_config)
            availability = probe_availability(scenario_name, 0, config=runtime_config)
            scenario_checks = collect_scenario_checks(scenario_name, config=runtime_config)
            checks.append(
                PreflightCheck(
                    name=f"live_scenario:{scenario_name}",
                    ok=availability.passed,
                    detail=f"availability={availability.passed}; metrics={scenario_checks.metrics}",
                )
            )
        except (OSError, ScenarioLifecycleError, Exception) as exc:
            checks.append(PreflightCheck(f"live_scenario:{scenario_name}", False, str(exc)))
        finally:
            try:
                if progress:
                    progress(f"stopping live scenario preflight: {scenario_name}")
                lifecycle.down()
            except ScenarioLifecycleError:
                pass
    return checks
