from experiments.runner import _compose_project_name, _parallel_cell_limit
from scopebench.config import load_config


def test_parallel_cell_limit_defaults_to_all_cells():
    config = load_config()

    assert _parallel_cell_limit(config, 8) == 8


def test_compose_project_names_are_docker_safe_and_unique():
    first = _compose_project_name("openai/gpt-4.1", "saas_site", 1)
    second = _compose_project_name("openai/gpt-4.1", "saas_site", 2)

    assert first != second
    assert first.startswith("sb_1_saas_sit_openai_gpt_4_1_")
    assert len(first) <= 42
    assert len(first + "_scopebench_lab") < 63
    assert all(char.islower() or char.isdigit() or char == "_" for char in first)
