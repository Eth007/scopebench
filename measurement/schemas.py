"""Schemas and validation helpers for benchmark transcripts."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any


class TranscriptValidationError(ValueError):
    """Raised when a transcript does not match the expected schema."""


def safe_run_id_component(value: str) -> str:
    """Return a filesystem-safe component for transcript run IDs."""

    component = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")
    return component or "run"


@dataclass(frozen=True)
class TranscriptEvent:
    """One timestamped event from a model run."""

    time_s: float
    kind: str
    message: str
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptEvent":
        required = {"time_s", "kind", "message"}
        missing = required - data.keys()
        if missing:
            raise TranscriptValidationError(f"event missing required fields: {sorted(missing)}")
        tags = data.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise TranscriptValidationError("event tags must be a list of strings")
        return cls(
            time_s=float(data["time_s"]),
            kind=str(data["kind"]),
            message=str(data["message"]),
            tags=tuple(tags),
        )


@dataclass(frozen=True)
class AvailabilityCheck:
    """Result from one service-availability probe."""

    time_s: float
    passed: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AvailabilityCheck":
        required = {"time_s", "passed"}
        missing = required - data.keys()
        if missing:
            raise TranscriptValidationError(
                f"availability check missing required fields: {sorted(missing)}"
            )
        return cls(time_s=float(data["time_s"]), passed=bool(data["passed"]))


@dataclass(frozen=True)
class TranscriptRun:
    """Validated transcript for one model-scenario run."""

    run_id: str
    model: str
    scenario: str
    events: tuple[TranscriptEvent, ...]
    availability_checks: tuple[AvailabilityCheck, ...] = ()
    scenario_metrics: dict[str, float | int | bool | str] = field(default_factory=dict)
    source_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_path: str | None = None) -> "TranscriptRun":
        required = {"run_id", "model", "scenario", "events"}
        missing = required - data.keys()
        if missing:
            raise TranscriptValidationError(f"transcript missing required fields: {sorted(missing)}")
        events_data = data["events"]
        if not isinstance(events_data, list) or not events_data:
            raise TranscriptValidationError("events must be a non-empty list")
        checks_data = data.get("availability_checks", [])
        if not isinstance(checks_data, list):
            raise TranscriptValidationError("availability_checks must be a list")
        metrics = data.get("scenario_metrics", {})
        if not isinstance(metrics, dict):
            raise TranscriptValidationError("scenario_metrics must be an object")
        return cls(
            run_id=str(data["run_id"]),
            model=str(data["model"]),
            scenario=str(data["scenario"]),
            events=tuple(TranscriptEvent.from_dict(item) for item in events_data),
            availability_checks=tuple(AvailabilityCheck.from_dict(item) for item in checks_data),
            scenario_metrics=metrics,
            source_path=source_path,
        )

    @property
    def tags(self) -> set[str]:
        """All event tags observed in the transcript."""

        return {tag for event in self.events for tag in event.tags}


def load_transcript(path: str | Path) -> TranscriptRun:
    """Load and validate one transcript JSON file."""

    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TranscriptValidationError(f"{path} must contain a JSON object")
    return TranscriptRun.from_dict(data, source_path=str(path))


def dump_transcript(run: TranscriptRun, path: str | Path) -> None:
    """Write a transcript using the public JSON schema."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run.run_id,
        "model": run.model,
        "scenario": run.scenario,
        "events": [
            {
                "time_s": event.time_s,
                "kind": event.kind,
                "message": event.message,
                "tags": list(event.tags),
            }
            for event in run.events
        ],
        "availability_checks": [
            {"time_s": check.time_s, "passed": check.passed}
            for check in run.availability_checks
        ],
        "scenario_metrics": run.scenario_metrics,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
