"""Tests for the gold evaluation set, Wilson confidence intervals, and replay evaluation."""

from __future__ import annotations

import json

import pytest

from copilot.data import load_database
from copilot.eval import (
    DEFAULT_CONFIGS,
    DEFAULT_GOLD_PATH,
    DEFAULT_HELDOUT_PATH,
    DEFAULT_METRICS_PATH,
    evaluate_config,
    load_gold_set,
    results_match,
    run_evaluation,
    wilson_ci,
)
from copilot.guard import GrainSanityViolation, execute_guarded_sql, validate_and_rewrite_sql
from copilot.providers import InfrastructureError
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


def test_heldout_set_structure_and_reference_sql_executes(con):
    items = load_gold_set(DEFAULT_HELDOUT_PATH)
    assert len(items) == 10
    by_diff = {"medium": 0, "hard": 0}
    review_doc = (DEFAULT_GOLD_PATH.parents[1] / "docs" / "GOLD_REVIEW.md").read_text(
        encoding="utf-8"
    )
    for item in items:
        assert item["answerable"] is True
        assert item["review_status"] == "needs human review"
        by_diff[item["difficulty"]] += 1
        assert item["id"] in review_doc
        res = execute_guarded_sql(con, item["sql"])
        actual = [list(r) for r in res.rows]
        assert results_match(actual, item["expected_rows"]), f"Mismatch on {item['id']}"
    assert by_diff == {"medium": 4, "hard": 6}


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
        replay=True,
        metrics_path=out_file,
    )
    assert out_file.read_text(encoding="utf-8") == committed_text
    assert replayed_data == committed_data
    assert "response_model" in replayed_data
    assert "base_url_host" in replayed_data
    assert replayed_data["temperature"] == 0.0
    assert "run_date" in replayed_data

    # Verify ablations are present and consistent
    configs = replayed_data["configurations"]
    expected_cfg_names = {
        "full_schema_repair_on",
        "full_schema_repair_off",
        "bare_schema_repair_on",
        "catalog_grain_notes_repair_on",
        "grain_aware_prompt_repair_on",
        "grain_sanity_check_repair_on",
    }
    assert set(configs) == expected_cfg_names
    assert set(replayed_data["heldout_evaluation"]["configurations"]) == expected_cfg_names
    guard = replayed_data["guard_attack_suite"]
    assert guard["total"] >= 50
    assert guard["blocked"] == guard["total"]
    assert guard["block_rate"] == 1.0


def test_grain_sanity_check_blocks_sum_over_repeated_grain_and_allows_deduplicated_cte():
    with pytest.raises(GrainSanityViolation, match="weekly_transactions"):
        validate_and_rewrite_sql(
            "SELECT store_nbr, SUM(weekly_transactions) "
            "FROM weekly_store_family_summary GROUP BY store_nbr",
            check_grain_sanity=True,
        )

    with pytest.raises(GrainSanityViolation, match="non_transferred_holidays"):
        validate_and_rewrite_sql(
            "SELECT SUM(non_transferred_holidays) FROM weekly_store_family_summary",
            check_grain_sanity=True,
        )

    with pytest.raises(GrainSanityViolation, match="store_nbr"):
        validate_and_rewrite_sql(
            "WITH wk AS (SELECT store_nbr, week_start_date, MAX(non_transferred_holidays) AS h "
            "FROM weekly_store_family_summary GROUP BY store_nbr, week_start_date) "
            "SELECT SUM(h) FROM wk",
            check_grain_sanity=True,
        )

    # Deduplicated CTE should pass
    valid = validate_and_rewrite_sql(
        "WITH store_weeks AS ("
        "SELECT store_nbr, week_start_date, MAX(weekly_transactions) AS wk_tx "
        "FROM weekly_store_family_summary GROUP BY store_nbr, week_start_date"
        ") SELECT store_nbr, SUM(wk_tx) AS total_tx FROM store_weeks GROUP BY store_nbr",
        check_grain_sanity=True,
    )
    assert "SUM(wk_tx)" in valid


def test_infrastructure_failures_excluded_from_accuracy_denominator(con):
    items = load_gold_set(DEFAULT_GOLD_PATH)[:3]

    class PartialInfraProvider:
        provider_name = "openai_compatible"
        model_name = "test-model"

        def __init__(self):
            self.n = 0

        def generate(self, prompt: str, *, system_prompt: str = ""):
            self.n += 1
            if self.n == 1:
                raise InfrastructureError("HTTP 429 rate limit")
            from copilot.providers import LLMResponse

            return LLMResponse(
                text='{"answerable": true, "reason": "ok", "sql": '
                + json.dumps(items[self.n - 1]["sql"])
                + "}",
                provider="openai_compatible",
                model="test-model",
                prompt_hash="h",
                latency_ms=10.0,
            )

    res = evaluate_config(DEFAULT_CONFIGS[0], items, con, PartialInfraProvider())
    assert res["n_total"] == 3
    assert res["n_completed"] == 2
    assert res["n_unresolved"] == 1
    assert res["infrastructure_failures_count"] == 1
    assert res["n_answerable"] == 2
    assert res["execution_correct"] == 2
    assert res["execution_accuracy"] == 1.0


def test_readme_figures_match_metrics_json():
    metrics = json.loads(DEFAULT_METRICS_PATH.read_text(encoding="utf-8"))
    actual_readme = DEFAULT_README_PATH.read_text(encoding="utf-8")
    expected_readme = render_readme(metrics)
    assert "## Evaluation status" in actual_readme
    assert f"`{metrics['provider']}` (requested model `{metrics['model']}`" in actual_readme
    assert actual_readme == expected_readme, (
        "README.md is out of sync with metrics/metrics.json; run `python -m copilot.readme_gen`."
    )
