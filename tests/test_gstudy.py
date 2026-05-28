from itertools import product

from measurement.gstudy import analyze_score_rows


def test_gstudy_recovers_nonzero_model_component_for_balanced_scores():
    rows = []
    model_effect = {"m1": 0.1, "m2": 0.4}
    scenario_effect = {"s1": 0.0, "s2": 0.05}
    for model, scenario in product(
        ("m1", "m2"),
        ("s1", "s2"),
    ):
        score = 0.5 + model_effect[model] + scenario_effect[scenario]
        rows.append(
            {
                "model": model,
                "scenario": scenario,
                "score": str(score),
            }
        )

    components, summary = analyze_score_rows(rows)
    by_name = {component.component: component for component in components}

    assert by_name["model"].variance > by_name["scenario"].variance
    assert summary["generalizability_coefficient"] > 0.9


def test_gstudy_averages_safety_dimensions_within_model_scenario_cells():
    rows = []
    for model, scenario in product(
        ("m1", "m2"),
        ("s1", "s2"),
    ):
        rows.append({"model": model, "scenario": scenario, "dimension": "availability", "score": "1.0"})
        rows.append({"model": model, "scenario": scenario, "dimension": "risk_management", "score": "0.5"})

    components, summary = analyze_score_rows(rows)

    assert {component.component for component in components} == {"model", "scenario", "model:scenario"}
    assert summary["n_models"] == 2.0
    assert summary["n_scenarios"] == 2.0


def test_gstudy_rejects_missing_cells():
    rows = []
    for model, scenario in product(
        ("m1", "m2"),
        ("s1", "s2"),
    ):
        if (model, scenario) == ("m2", "s2"):
            continue
        rows.append(
            {
                "model": model,
                "scenario": scenario,
                "score": "0.5",
            }
        )

    try:
        analyze_score_rows(rows)
    except ValueError as exc:
        assert "fully crossed" in str(exc)
    else:
        raise AssertionError("missing balanced cell was not rejected")
