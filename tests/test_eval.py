"""Tests for the gold evaluation set, Wilson confidence intervals, and replay evaluation."""

from __future__ import annotations

import json

import pytest

from copilot.data import load_database
from copilot.eval import (
    DEFAULT_GOLD_PATH,
    DEFAULT_METRICS_PATH,
    load_gold_set,
    results_match,
    run_evaluation,
    wilson_ci,
)
from copilot.guard import execute_guarded_sql
from copilot.readme_gen import DEFAULT_README_PATH, render_readme


@pytest.fixture(scope="module")
def con():
    connection = load_database(harden=True)
    yield connection
    connection.close()


def test_gold_set_structure_and_difficulty_split():
    items = load_gold_set(DEFAULT_GOLD_PATH)
    assert len(items) == 45
    answerable = [x for x in items if x["answerable"]]
    unanswerable = [x for x in items if not x["answerable"]]
    assert len(answerable) == 40
    assert len(unanswerable) == 5

    by_diff = {"easy": 0, "medium": 0, "hard": 0}
    for item in answerable:
        by_diff[item["difficulty"]] += 1
    assert by_diff == {"easy": 10, "medium": 20, "hard": 10}


def test_every_gold_reference_sql_executes_and_matches_expected_rows(con):
    items = load_gold_set(DEFAULT_GOLD_PATH)
    for item in items:
        if not item["answerable"]:
            assert item["sql"] == ""
            assert item["expected_rows"] == []
            continue
        res = execute_guarded_sql(con, item["sql"])
        actual = [list(r) for r in res.rows]
        assert results_match(actual, item["expected_rows"]), f"Mismatch on {item['id']}"


def test_wilson_ci_bounds_and_properties():
    low, high = wilson_ci(37, 40)
    assert 0.79 <= low <= 0.81
    assert 0.96 <= high <= 0.98
    assert wilson_ci(0, 0) == (0.0, 0.0)
    assert wilson_ci(5, 5)[1] == 1.0


def test_results_match_order_insensitive_and_numeric_tolerance():
    rows_a = [["Quito", 100.0001], ["Guayaquil", 50.0]]
    rows_b = [["Guayaquil", 50.0], ["Quito", 100.0]]
    assert results_match(rows_a, rows_b)
    assert not results_match(rows_a, [["Quito", 100.0]])
    assert not results_match(rows_a, [["Quito", 105.0], ["Guayaquil", 50.0]])


def test_replay_regenerates_committed_metrics_json_identically(tmp_path):
    committed_text = DEFAULT_METRICS_PATH.read_text(encoding="utf-8")
    committed_data = json.loads(committed_text)

    out_file = tmp_path / "metrics.json"
    replayed_data = run_evaluation(
        provider_name="mock",
        replay=True,
        metrics_path=out_file,
    )
    assert out_file.read_text(encoding="utf-8") == committed_text
    assert replayed_data == committed_data

    # Verify ablations are present and consistent
    configs = replayed_data["configurations"]
    assert set(configs) == {
        "full_schema_repair_on",
        "full_schema_repair_off",
        "bare_schema_repair_on",
    }
    assert (
        configs["full_schema_repair_on"]["execution_correct"]
        > configs["full_schema_repair_off"]["execution_correct"]
    )
    assert (
        configs["full_schema_repair_on"]["execution_correct"]
        > configs["bare_schema_repair_on"]["execution_correct"]
    )


def test_readme_figures_match_metrics_json():
    metrics = json.loads(DEFAULT_METRICS_PATH.read_text(encoding="utf-8"))
    actual_readme = DEFAULT_README_PATH.read_text(encoding="utf-8")
    expected_readme = render_readme(metrics)
    assert "## Evaluation status" in actual_readme
    assert f"`{metrics['provider']}` (model `{metrics['model']}`" in actual_readme
    assert actual_readme == expected_readme, (
        "README.md is out of sync with metrics/metrics.json; run `python -m copilot.readme_gen`."
    )
