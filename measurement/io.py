"""CSV and JSON IO helpers for score and analysis artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .scoring import ScoreRecord


SCORE_FIELDS = ("run_id", "model", "scenario", "judge", "dimension", "score", "rationale")


def write_scores(records: Iterable[ScoreRecord], path: str | Path) -> None:
    """Write score records to CSV."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCORE_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "run_id": record.run_id,
                    "model": record.model,
                    "scenario": record.scenario,
                    "judge": record.judge,
                    "dimension": record.dimension,
                    "score": f"{record.score:.4f}",
                    "rationale": record.rationale,
                }
            )


def read_score_rows(path: str | Path) -> list[dict[str, str]]:
    """Read score CSV rows."""

    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_dict_rows(rows: Iterable[dict[str, Any]], path: str | Path) -> None:
    """Write arbitrary dictionaries as CSV rows."""

    rows = list(rows)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(data: dict[str, Any], path: str | Path) -> None:
    """Write an indented JSON object."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
