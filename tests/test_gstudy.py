from itertools import product

from measurement.gstudy import analyze_score_rows


def test_gstudy_recovers_nonzero_model_component_for_balanced_scores():
    rows = []
    model_effect = {"m1": 0.1, "m2": 0.4}
    scenario_effect = {"s1": 0.0, "s2": 0.05}
    for model, scenario, judge, dimension in product(
        ("m1", "m2"),
        ("s1", "s2"),
        ("j1", "j2"),
        ("d1", "d2"),
    ):
        score = 0.5 + model_effect[model] + scenario_effect[scenario]
        rows.append(
            {
                "model": model,
                "scenario": scenario,
                "judge": judge,
                "dimension": dimension,
                "score": str(score),
            }
        )

    components, summary = analyze_score_rows(rows)
    by_name = {component.component: component for component in components}

    assert by_name["model"].variance > by_name["scenario"].variance
    assert summary["generalizability_coefficient"] > 0.9


def test_gstudy_rejects_missing_cells():
    rows = []
    for model, scenario, judge, dimension in product(
        ("m1", "m2"),
        ("s1", "s2"),
        ("j1", "j2"),
        ("d1", "d2"),
    ):
        if (model, scenario, judge, dimension) == ("m2", "s2", "j2", "d2"):
            continue
        rows.append(
            {
                "model": model,
                "scenario": scenario,
                "judge": judge,
                "dimension": dimension,
                "score": "0.5",
            }
        )

    try:
        analyze_score_rows(rows)
    except ValueError as exc:
        assert "fully crossed" in str(exc)
    else:
        raise AssertionError("missing balanced cell was not rejected")
