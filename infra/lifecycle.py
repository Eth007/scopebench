"""Docker Compose lifecycle helpers for sandboxed scenarios."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

from scopebench.config import ScopebenchConfig, load_config


class ScenarioLifecycleError(RuntimeError):
    """Raised when Docker Compose scenario management fails."""


@dataclass(frozen=True)
class CommandResult:
    """Captured command result from a scenario container."""

    command: str
    returncode: int
    stdout: str
    stderr: str


class ScenarioLifecycle:
    """Manage one scenario's Docker Compose stack."""

    def __init__(
        self,
        scenario_name: str,
        config: ScopebenchConfig | None = None,
        project_name: str | None = None,
    ) -> None:
        self.config = config or load_config()
        self.scenario = self.config.scenario(scenario_name)
        self.scenario_name = scenario_name
        self.project_name = project_name or str(
            self.scenario.get("compose_project_name", "") or ""
        )
        self.compose_path = Path(str(self.scenario["infra_compose_path"]))
        self.agent_service = str(self.config.experiment.get("agent_service", "agent"))
        self.target_service = str(self.config.experiment.get("target_service", "target"))
        self.compose_env = _compose_env(self.project_name or self.scenario_name, self.scenario)
        if not self.compose_path.exists():
            raise ScenarioLifecycleError(f"missing compose file: {self.compose_path}")

    def up(self, build: bool = True) -> None:
        """Start the scenario stack."""

        args = [*self.compose_args(), "up", "-d"]
        if build:
            args.append("--build")
        self._run(args, check=True)

    def down(self) -> None:
        """Stop and remove the scenario stack."""

        self._run([*self.compose_args(), "down", "-v"], check=True)

    def ps(self) -> CommandResult:
        """Return Docker Compose service status."""

        return self._run([*self.compose_args(), "ps"], check=False)

    def compose_args(self) -> list[str]:
        """Return the base Docker Compose command for this scenario instance."""

        args = [*compose_command(), "-f", str(self.compose_path)]
        if self.project_name:
            args.extend(["-p", self.project_name])
        return args

    def runtime_config(self) -> ScopebenchConfig:
        """Return a config copy bound to this compose project and published host port."""

        return self.config.with_scenario_overrides(
            self.scenario_name,
            {
                "compose_project_name": self.project_name,
                "host_base_url": self.host_base_url(),
            },
        )

    def host_base_url(self) -> str:
        """Return the host URL for the target service in this compose project."""

        target_port = int(
            self.scenario.get("target_port") or _target_port_from_url(self.scenario)
        )
        result = self._run(
            [*self.compose_args(), "port", self.target_service, str(target_port)],
            check=False,
            timeout_s=10,
        )
        endpoint = (result.stdout or "").strip().splitlines()
        if result.returncode != 0 or not endpoint:
            return str(self.scenario["host_base_url"]).rstrip("/")
        host, port = _parse_compose_port(endpoint[-1])
        scheme = urlsplit(str(self.scenario["host_base_url"])).scheme or "http"
        return f"{scheme}://{host}:{port}"

    def exec_agent(self, command: str, timeout_s: int | float) -> CommandResult:
        """Execute a shell command inside the scenario's agent container."""

        return self._run(self.agent_exec_args(command), check=False, timeout_s=timeout_s)

    def popen_agent(self, command: str) -> subprocess.Popen[str]:
        """Start a shell command inside the agent container and return the process."""

        return subprocess.Popen(
            self.agent_exec_args(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def agent_exec_args(self, command: str) -> list[str]:
        """Return the Docker Compose exec arguments for an agent shell command."""

        return [
            *self.compose_args(),
            "exec",
            "-T",
            self.agent_service,
            "bash",
            "-lc",
            command,
        ]

    def codex_version(self) -> CommandResult:
        """Return the Codex CLI version inside the agent container."""

        return self.exec_agent("codex --version", timeout_s=10)

    def _run(
        self,
        args: list[str],
        check: bool,
        timeout_s: int | float | None = None,
    ) -> CommandResult:
        try:
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                env=self.compose_env,
                text=True,
                timeout=timeout_s,
            )
        except FileNotFoundError as exc:
            raise ScenarioLifecycleError("Docker Compose is required for live experiments") from exc
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=" ".join(args),
                returncode=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "command timed out",
            )
        result = CommandResult(
            command=" ".join(args),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and completed.returncode != 0:
            raise ScenarioLifecycleError(
                f"command failed ({completed.returncode}): {result.command}\n{result.stderr}"
            )
        return result


def compose_command() -> list[str]:
    """Return the available Docker Compose command."""

    if _command_ok(["docker", "compose", "version"]):
        return ["docker", "compose"]
    if shutil.which("docker-compose") and _command_ok(["docker-compose", "version"]):
        return ["docker-compose"]
    raise ScenarioLifecycleError(
        "Docker Compose is required for live experiments. Install the Docker "
        "Compose plugin so `docker compose version` works, or install the "
        "legacy `docker-compose` command."
    )


def compose_command_status() -> CommandResult:
    """Return a diagnostic result for the configured Docker Compose command."""

    try:
        command = compose_command()
    except ScenarioLifecycleError as exc:
        return CommandResult(
            command="docker compose version",
            returncode=1,
            stdout="",
            stderr=str(exc),
        )
    return _run_command([*command, "version"], timeout_s=10)


def _command_ok(args: list[str]) -> bool:
    result = _run_command(args, timeout_s=10)
    return result.returncode == 0


def _run_command(args: list[str], timeout_s: int | float) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return CommandResult(
            command=" ".join(args),
            returncode=124 if isinstance(exc, subprocess.TimeoutExpired) else 127,
            stdout=getattr(exc, "stdout", "") or "",
            stderr=getattr(exc, "stderr", "") or str(exc),
        )
    return CommandResult(
        command=" ".join(args),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _target_port_from_url(scenario: dict[str, object]) -> int:
    parsed = urlsplit(str(scenario.get("agent_base_url") or scenario.get("host_base_url")))
    if parsed.port:
        return int(parsed.port)
    return 443 if parsed.scheme == "https" else 80


def _parse_compose_port(value: str) -> tuple[str, int]:
    value = value.strip()
    if value.startswith("["):
        host, _, remainder = value[1:].partition("]:")
        port = int(remainder)
    else:
        host, _, port_text = value.rpartition(":")
        port = int(port_text)
    if host in {"", "0.0.0.0", "::", "::1", "[::]"}:
        host = "127.0.0.1"
    return host, port


def _compose_env(seed: str, scenario: dict[str, object] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("SCOPEBENCH_LAB_SUBNET", _lab_subnet(seed))
    scenario = scenario or {}
    _set_scenario_env(
        env,
        "failed_login_outage_threshold",
        "SAAS_FAILED_LOGIN_OUTAGE_THRESHOLD",
        scenario,
    )
    _set_scenario_env(env, "failed_login_window_s", "SAAS_FAILED_LOGIN_WINDOW_S", scenario)
    _set_scenario_env(env, "outage_lock_ttl_s", "SAAS_OUTAGE_LOCK_TTL_S", scenario)
    return env


def _set_scenario_env(
    env: dict[str, str],
    config_key: str,
    env_key: str,
    scenario: dict[str, object],
) -> None:
    value = scenario.get(config_key)
    if value is not None:
        env.setdefault(env_key, str(value))


def _lab_subnet(seed: str) -> str:
    """Return a small deterministic subnet outside Docker's usual default pools."""

    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    value = int.from_bytes(digest[:3], "big")
    second_octet = 240 + ((value >> 12) & 0x0F)
    third_octet = (value >> 4) & 0xFF
    fourth_octet = (value & 0x0F) * 16
    return f"10.{second_octet}.{third_octet}.{fourth_octet}/28"
