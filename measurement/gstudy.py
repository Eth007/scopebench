"""Balanced crossed Generalizability Theory analysis."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
from math import prod
from statistics import mean
from typing import Iterable


FACETS = ("model", "scenario")


@dataclass(frozen=True)
class VarianceComponent:
    """ANOVA-derived variance component for one facet or interaction."""

    component: str
    df: int
    mean_square: float
    variance: float
    percent_total: float


def analyze_score_rows(rows: Iterable[dict[str, str]]) -> tuple[list[VarianceComponent], dict[str, float]]:
    """Estimate variance components from fully crossed balanced score rows.

    The expected input has one or more safety-dimension scores for every
    model-scenario cell. Multiple dimension rows are averaged within each cell.
    With no repeated observations per full cell, the highest-order interaction
    is treated as residual measurement error.
    """

    values, levels = _balanced_values(rows)
    mean_squares = _mean_squares(values, levels)
    variances = _variance_components(mean_squares, levels)
    total = sum(max(value, 0.0) for value in variances.values())

    components: list[VarianceComponent] = []
    for subset in _all_subsets_descending(reverse=False):
        name = _name(subset)
        variance = variances[subset]
        components.append(
            VarianceComponent(
                component=name,
                df=_df(subset, levels),
                mean_square=mean_squares[subset],
                variance=variance,
                percent_total=0.0 if total <= 0 else max(variance, 0.0) / total,
            )
        )

    summary = _reliability_summary(variances, levels)
    return components, summary


def component_rows(components: Iterable[VarianceComponent]) -> list[dict[str, str]]:
    """Convert variance components into stable CSV rows."""

    return [
        {
            "component": item.component,
            "df": str(item.df),
            "mean_square": f"{item.mean_square:.6f}",
            "variance": f"{item.variance:.6f}",
            "percent_total": f"{item.percent_total:.6f}",
        }
        for item in components
    ]


def _balanced_values(
    rows: Iterable[dict[str, str]],
) -> tuple[dict[tuple[str, ...], float], dict[str, tuple[str, ...]]]:
    grouped_values: dict[tuple[str, ...], list[float]] = {}
    level_sets = {facet: set() for facet in FACETS}

    for row in rows:
        key = tuple(row[facet] for facet in FACETS)
        grouped_values.setdefault(key, []).append(float(row["score"]))
        for facet, value in zip(FACETS, key):
            level_sets[facet].add(value)
    values = {key: mean(scores) for key, scores in grouped_values.items()}

    levels = {facet: tuple(sorted(level_sets[facet])) for facet in FACETS}
    expected = set(product(*(levels[facet] for facet in FACETS)))
    observed = set(values)
    missing = expected - observed
    extra = observed - expected
    if missing or extra:
        example = sorted(missing or extra)[0]
        raise ValueError(f"scores must be fully crossed and balanced; example problem cell: {example}")
    if any(len(levels[facet]) < 2 for facet in FACETS):
        raise ValueError("each facet must have at least two levels for G-study analysis")
    return values, levels


def _mean_squares(
    values: dict[tuple[str, ...], float],
    levels: dict[str, tuple[str, ...]],
) -> dict[tuple[str, ...], float]:
    grand = sum(values.values()) / len(values)
    means: dict[tuple[str, ...], dict[tuple[str, ...], float]] = {(): {(): grand}}
    for subset in _all_subsets_descending(reverse=False):
        means[subset] = {}
        for level_combo in product(*(levels[facet] for facet in subset)):
            selected = dict(zip(subset, level_combo))
            matched = [
                score
                for key, score in values.items()
                if all(key[FACETS.index(facet)] == selected[facet] for facet in subset)
            ]
            means[subset][level_combo] = sum(matched) / len(matched)

    mean_squares: dict[tuple[str, ...], float] = {}
    for subset in _all_subsets_descending(reverse=False):
        ss = 0.0
        for level_combo in product(*(levels[facet] for facet in subset)):
            effect = 0.0
            selected = dict(zip(subset, level_combo))
            for inner in _subsets_of(subset):
                inner_combo = tuple(selected[facet] for facet in inner)
                sign = (-1) ** (len(subset) - len(inner))
                effect += sign * means[inner][inner_combo]
            ss += effect**2
        ss *= prod(len(levels[facet]) for facet in FACETS if facet not in subset)
        mean_squares[subset] = ss / _df(subset, levels)
    return mean_squares


def _variance_components(
    mean_squares: dict[tuple[str, ...], float],
    levels: dict[str, tuple[str, ...]],
) -> dict[tuple[str, ...], float]:
    variances: dict[tuple[str, ...], float] = {}
    for subset in _all_subsets_descending(reverse=True):
        expected_from_higher = 0.0
        for higher, variance in variances.items():
            if set(subset).issubset(higher):
                expected_from_higher += _coefficient(higher, levels) * variance
        variances[subset] = (mean_squares[subset] - expected_from_higher) / _coefficient(
            subset, levels
        )
    return variances


def _reliability_summary(
    variances: dict[tuple[str, ...], float],
    levels: dict[str, tuple[str, ...]],
) -> dict[str, float]:
    model_var = max(0.0, variances[("model",)])
    sample_sizes = {
        "scenario": len(levels["scenario"]),
    }

    relative_error = 0.0
    absolute_error = 0.0
    for subset, variance in variances.items():
        if subset == ("model",):
            continue
        denominator = prod(sample_sizes[facet] for facet in subset if facet != "model")
        if "model" in subset:
            relative_error += max(0.0, variance) / denominator
        else:
            absolute_error += max(0.0, variance) / denominator
    absolute_error += relative_error

    return {
        "model_universe_variance": model_var,
        "relative_error_variance": relative_error,
        "absolute_error_variance": absolute_error,
        "generalizability_coefficient": _ratio(model_var, model_var + relative_error),
        "dependability_coefficient": _ratio(model_var, model_var + absolute_error),
        "n_models": float(len(levels["model"])),
        "n_scenarios": float(len(levels["scenario"])),
    }


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _coefficient(subset: tuple[str, ...], levels: dict[str, tuple[str, ...]]) -> int:
    return prod(len(levels[facet]) for facet in FACETS if facet not in subset)


def _df(subset: tuple[str, ...], levels: dict[str, tuple[str, ...]]) -> int:
    return prod(len(levels[facet]) - 1 for facet in subset)


def _all_subsets_descending(reverse: bool) -> list[tuple[str, ...]]:
    subsets = [
        subset
        for size in range(1, len(FACETS) + 1)
        for subset in combinations(FACETS, size)
    ]
    return sorted(subsets, key=len, reverse=reverse)


def _subsets_of(subset: tuple[str, ...]) -> list[tuple[str, ...]]:
    return [
        inner
        for size in range(0, len(subset) + 1)
        for inner in combinations(subset, size)
    ]


def _name(subset: tuple[str, ...]) -> str:
    return ":".join(subset)
