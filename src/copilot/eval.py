"""Evaluation harness for analytics-copilot (`python -m copilot.eval`).

Runs the 45-question gold set (`evals/gold.jsonl`) across pipeline configurations
(`full_schema_repair_on`, `full_schema_repair_off`, `bare_schema_repair_on`) and writes
`metrics/metrics.json`.

Metrics computed per configuration:
- Execution accuracy on answerable questions (order-insensitive result-set match with
  numeric tolerance) and by difficulty tier (easy / medium / hard), with Wilson 95% confidence
  intervals. Infrastructure failures are logged separately and excluded from accuracy
  denominators.
- Valid-SQL rate (share of evaluated answerable questions producing a syntactically and
  guard-valid SQL query that executes without error).
- Mean attempts per evaluated question.
- Refusal accuracy on unanswerable/ambiguous questions with Wilson 95% confidence interval.
- Latency p50 and p95 in milliseconds, plus token usage totals when available.
- Provider metadata (`provider`, `model`, `response_model`, `base_url_host`, `temperature=0.0`,
  `run_date`) and completed vs. unresolved counts.
- Failure taxonomy breakdown (`wrong_join_or_aggregation`, `wrong_column_semantics`,
  `hallucinated_table_or_column`, `syntax_error`, `ambiguity`, `guard_blocked`, `timeout`)
  with concrete failed question examples.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from copilot.data import load_database
from copilot.pipeline import ask_question
from copilot.providers import (
    DEFAULT_TEMPERATURE,
    PROVIDER_ENV,
    CachedProvider,
    LLMProvider,
    MockProvider,
    create_provider,
    default_cache_dir,
    load_dotenv_file,
)

DEFAULT_GOLD_PATH = Path(__file__).resolve().parents[2] / "evals" / "gold.jsonl"
DEFAULT_HELDOUT_PATH = Path(__file__).resolve().parents[2] / "evals" / "heldout.jsonl"
DEFAULT_METRICS_PATH = Path(__file__).resolve().parents[2] / "metrics" / "metrics.json"

FAILURE_CATEGORIES: tuple[str, ...] = (
    "wrong_join_or_aggregation",
    "wrong_column_semantics",
    "hallucinated_table_or_column",
    "syntax_error",
    "ambiguity",
    "guard_blocked",
    "timeout",
)


@dataclass(frozen=True)
class EvalConfig:
    """Configuration for a single evaluation run over the gold set."""

    name: str
    description: str
    max_repairs: int
    include_descriptions: bool
    include_grain_notes: bool = False
    grain_aware_prompt: bool = False
    check_grain_sanity: bool = False


BASELINE_CONFIGS: tuple[EvalConfig, ...] = (
    EvalConfig(
        name="full_schema_repair_on",
        description="Schema with table/column descriptions + bounded self-repair (up to 2 repairs)",
        max_repairs=2,
        include_descriptions=True,
    ),
    EvalConfig(
        name="full_schema_repair_off",
        description="Schema with table/column descriptions + repair loop disabled (0 repairs)",
        max_repairs=0,
        include_descriptions=True,
    ),
    EvalConfig(
        name="bare_schema_repair_on",
        description="Bare schema (table/column names and types only, no descriptions) + repair on",
        max_repairs=2,
        include_descriptions=False,
    ),
)

GRAIN_ABLATION_CONFIGS: tuple[EvalConfig, ...] = (
    EvalConfig(
        name="catalog_grain_notes_repair_on",
        description="Full schema + explicit table grain/fan-out notes in catalog.py + repair on",
        max_repairs=2,
        include_descriptions=True,
        include_grain_notes=True,
        grain_aware_prompt=False,
        check_grain_sanity=False,
    ),
    EvalConfig(
        name="grain_aware_prompt_repair_on",
        description="Full schema + catalog grain notes + grain-aware prompt checklist + repair on",
        max_repairs=2,
        include_descriptions=True,
        include_grain_notes=True,
        grain_aware_prompt=True,
        check_grain_sanity=False,
    ),
    EvalConfig(
        name="grain_sanity_check_repair_on",
        description="Full schema + SUM-over-repeated-grain AST sanity check repair trigger",
        max_repairs=2,
        include_descriptions=True,
        include_grain_notes=False,
        grain_aware_prompt=False,
        check_grain_sanity=True,
    ),
)

DEFAULT_CONFIGS: tuple[EvalConfig, ...] = BASELINE_CONFIGS + GRAIN_ABLATION_CONFIGS

_CONFIG_BY_NAME: dict[str, EvalConfig] = {c.name: c for c in DEFAULT_CONFIGS}


def wilson_ci(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Compute the 95% Wilson score confidence interval for a binomial proportion."""
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denom
    half_width = (z / denom) * math.sqrt((p * (1.0 - p) / total) + (z2 / (4.0 * total * total)))
    low = max(0.0, round(center - half_width, 4))
    high = min(1.0, round(center + half_width, 4))
    return (low, high)


def _normalize_cell(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.isoformat()[:10]
    return str(val).strip()


def _cells_match(a: Any, b: Any, rel_tol: float = 1e-3, abs_tol: float = 1e-2) -> bool:
    na = _normalize_cell(a)
    nb = _normalize_cell(b)
    if isinstance(na, float) and isinstance(nb, float):
        return math.isclose(na, nb, rel_tol=rel_tol, abs_tol=abs_tol)
    return na == nb


def _rows_match(row_a: Sequence[Any], row_b: Sequence[Any], rel_tol: float, abs_tol: float) -> bool:
    if len(row_a) != len(row_b):
        return False
    return all(
        _cells_match(x, y, rel_tol=rel_tol, abs_tol=abs_tol)
        for x, y in zip(row_a, row_b, strict=False)
    )


def results_match(
    actual_rows: Sequence[Sequence[Any]],
    expected_rows: Sequence[Sequence[Any]],
    *,
    rel_tol: float = 1e-3,
    abs_tol: float = 1e-2,
) -> bool:
    """Order-insensitive bipartite / multiset row comparison with numeric tolerance."""
    if len(actual_rows) != len(expected_rows):
        return False
    unmatched = list(expected_rows)
    for act in actual_rows:
        matched_idx: int | None = None
        for idx, exp_row in enumerate(unmatched):
            if _rows_match(act, exp_row, rel_tol=rel_tol, abs_tol=abs_tol):
                matched_idx = idx
                break
        if matched_idx is None:
            return False
        unmatched.pop(matched_idx)
    return True


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 2)
    pos = (len(sorted_vals) - 1) * q
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return round(sorted_vals[lower], 2)
    weight = pos - lower
    return round(sorted_vals[lower] * (1.0 - weight) + sorted_vals[upper] * weight, 2)


def load_gold_set(gold_path: Path | str = DEFAULT_GOLD_PATH) -> list[dict[str, Any]]:
    """Load all questions and reference outputs from `evals/gold.jsonl`."""
    path = Path(gold_path)
    items: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                items.append(json.loads(stripped))
    return items


# ---------------------------------------------------------------------------
# Realistic Baseline Handler for MockProvider (harness validation)
# ---------------------------------------------------------------------------

_REPAIRABLE_FIRST_ATTEMPT: dict[str, dict[str, Any]] = {
    "med_07": {
        "answerable": True,
        "reason": "Query zero_sales_day_proxy_summary using hallucinated column zero_sales_pct.",
        "sql": (
            "SELECT store_nbr, city, family, zero_sales_pct, mean_daily_sales "
            "FROM zero_sales_day_proxy_summary "
            "WHERE zero_sales_proxy_tier = 'HIGH_VELOCITY_ELEVATED_ZERO_SALES_DAYS_PROXY' "
            "ORDER BY zero_sales_pct DESC LIMIT 5"
        ),
    },
    "med_14": {
        "answerable": True,
        "reason": "Calculate yearly oil price using hallucinated column oil_price.",
        "sql": (
            "SELECT EXTRACT(YEAR FROM week_start_date) AS yr, ROUND(AVG(oil_price), 2) "
            "FROM weekly_store_family_summary GROUP BY yr ORDER BY yr"
        ),
    },
    "hard_03": {
        "answerable": True,
        "reason": "Join promo and volatility tables on store_id instead of store_nbr.",
        "sql": (
            "SELECT v.volatility_proxy_tier, COUNT(*), "
            "AVG(p.empirical_promo_lift_pct), AVG(v.cv_demand) "
            "FROM promo_elasticity_summary p JOIN perishable_volatility_summary v "
            "ON p.store_id = v.store_id AND p.family = v.family "
            "WHERE v.perishability_class = 'PERISHABLE' GROUP BY v.volatility_proxy_tier"
        ),
    },
    "hard_09": {
        "answerable": True,
        "reason": "Attempt to inspect table schema with pragma_table_info first.",
        "sql": "SELECT COUNT(*) FROM pragma_table_info('promo_elasticity_summary')",
    },
}

_PERSISTENT_FAILURES_FULL_SCHEMA: dict[str, tuple[str, dict[str, Any]]] = {
    "hard_01": (
        "wrong_column_semantics",
        {
            "answerable": True,
            "reason": (
                "Naively sum weekly_transactions across all rows for each store without "
                "deduplicating the 33 product families per store-week."
            ),
            "sql": (
                "SELECT store_nbr, city, SUM(weekly_transactions) AS total_transactions "
                "FROM weekly_store_family_summary "
                "GROUP BY store_nbr, city "
                "ORDER BY total_transactions DESC "
                "LIMIT 5"
            ),
        },
    ),
    "hard_06": (
        "wrong_column_semantics",
        {
            "answerable": True,
            "reason": (
                "Compare average_inventory_units without filtering out "
                "is_sensitivity_extrapolation = TRUE (which includes L=14)."
            ),
            "sql": (
                "WITH sn AS ("
                "  SELECT lead_time_days, average_inventory_units AS sn_inv "
                "  FROM sim_policy_summary "
                "  WHERE policy = 'seasonal_naive_safety_stock' AND ROUND(service_level, 2) = 0.95"
                "), lgb AS ("
                "  SELECT lead_time_days, average_inventory_units AS lgb_inv "
                "  FROM sim_policy_summary "
                "  WHERE policy = 'lightgbm_point_safety_stock' AND ROUND(service_level, 2) = 0.95"
                ") "
                "SELECT sn.lead_time_days, "
                "ROUND(sn.sn_inv - lgb.lgb_inv, 2) AS inventory_saved_units "
                "FROM sn JOIN lgb ON sn.lead_time_days = lgb.lead_time_days "
                "ORDER BY sn.lead_time_days ASC"
            ),
        },
    ),
    "hard_08": (
        "wrong_join_or_aggregation",
        {
            "answerable": True,
            "reason": (
                "Average store-family total_sales directly by oil price regime instead of "
                "first summing chain-wide weekly sales per week_start_date."
            ),
            "sql": (
                "SELECT CASE WHEN avg_oil_price < 50 THEN 'UNDER_50' "
                "ELSE 'AT_OR_ABOVE_50' END AS oil_regime, "
                "COUNT(DISTINCT week_start_date) AS n_weeks, "
                "ROUND(AVG(total_sales), 2) AS avg_weekly_sales "
                "FROM weekly_store_family_summary "
                "WHERE avg_oil_price IS NOT NULL "
                "GROUP BY oil_regime "
                "ORDER BY oil_regime ASC"
            ),
        },
    ),
}

_BARE_SCHEMA_EXTRA_FAILURES: dict[str, tuple[str, dict[str, Any]]] = {
    "easy_09": (
        "wrong_column_semantics",
        {
            "answerable": True,
            "reason": "Without column description of tier names, guess tier label HIGH_VELOCITY.",
            "sql": (
                "SELECT COUNT(*) AS high_velocity_tier_count "
                "FROM zero_sales_day_proxy_summary "
                "WHERE zero_sales_proxy_tier = 'HIGH_VELOCITY'"
            ),
        },
    ),
    "med_10": (
        "wrong_column_semantics",
        {
            "answerable": True,
            "reason": "Without description of perishability_class values, filter on 'TRUE'.",
            "sql": (
                "SELECT store_nbr, city, family, ROUND(volatility_exposure_index, 2) "
                "FROM perishable_volatility_summary "
                "WHERE perishability_class = 'TRUE' "
                "ORDER BY volatility_exposure_index DESC LIMIT 5"
            ),
        },
    ),
    "med_15": (
        "wrong_join_or_aggregation",
        {
            "answerable": True,
            "reason": "Count all store-family rows with holidays instead of distinct weeks.",
            "sql": (
                "SELECT COUNT(*) AS holiday_weeks "
                "FROM weekly_store_family_summary "
                "WHERE non_transferred_holidays > 0"
            ),
        },
    ),
    "hard_04": (
        "wrong_column_semantics",
        {
            "answerable": True,
            "reason": "Without tier description, filter volatility_proxy_tier = 'HIGH_VOLATILITY'.",
            "sql": (
                "SELECT z.store_nbr, z.city, z.family, "
                "ROUND(z.zero_sales_rate_pct, 2) AS zero_sales_rate_pct, "
                "ROUND(v.cv_demand, 4) AS cv_demand "
                "FROM zero_sales_day_proxy_summary z "
                "JOIN perishable_volatility_summary v "
                "  ON z.store_nbr = v.store_nbr AND z.family = v.family "
                "WHERE v.volatility_proxy_tier = 'HIGH_VOLATILITY' "
                "ORDER BY z.zero_sales_rate_pct DESC LIMIT 5"
            ),
        },
    ),
}


def build_gold_mock_provider(
    gold_items: Sequence[dict[str, Any]], model: str = "mock-sql-v1"
) -> MockProvider:
    """Create a deterministic `MockProvider` grounded on the gold set for offline evaluation."""
    by_question = {item["question"].strip(): item for item in gold_items}

    def _handler(prompt: str, system_prompt: str) -> dict[str, Any]:
        is_repair = "ERROR ENCOUNTERED:" in prompt
        has_descriptions = "Monday that starts the week" in prompt

        marker = "USER QUESTION:\n"
        q_text = ""
        if marker in prompt:
            after = prompt.split(marker, 1)[1]
            q_text = after.split("\n\nPREVIOUS ATTEMPT", 1)[0].strip()

        item = by_question.get(q_text)
        if item is None:
            return {
                "answerable": False,
                "reason": "Question not recognized by deterministic baseline.",
                "sql": "",
            }

        qid = item["id"]
        if not item["answerable"]:
            return {
                "answerable": False,
                "reason": item.get(
                    "refusal_reason",
                    "The requested information is not present in the available grocery tables.",
                ),
                "sql": "",
            }

        if qid in _PERSISTENT_FAILURES_FULL_SCHEMA:
            has_grain_notes = "GRAIN & FAN-OUT NOTE:" in prompt
            has_grain_rules = "GRAIN & FAN-OUT RULES:" in prompt
            if is_repair and "GrainSanityViolation" in prompt and qid == "hard_01":
                return {
                    "answerable": True,
                    "reason": f"Repaired repeated-grain SUM for {qid}.",
                    "sql": item["sql"],
                }
            if has_grain_notes and qid == "hard_01":
                return {
                    "answerable": True,
                    "reason": f"Execute deduplicated store-week query for {qid}.",
                    "sql": item["sql"],
                }
            if has_grain_rules and qid in {"hard_01", "hard_08"}:
                return {
                    "answerable": True,
                    "reason": f"Execute grain-aware query for {qid}.",
                    "sql": item["sql"],
                }
            return _PERSISTENT_FAILURES_FULL_SCHEMA[qid][1]

        if not has_descriptions and qid in _BARE_SCHEMA_EXTRA_FAILURES:
            return _BARE_SCHEMA_EXTRA_FAILURES[qid][1]

        if not is_repair and qid in _REPAIRABLE_FIRST_ATTEMPT:
            return _REPAIRABLE_FIRST_ATTEMPT[qid]

        return {
            "answerable": True,
            "reason": f"Execute reference query for {qid}.",
            "sql": item["sql"],
        }

    return MockProvider(handler=_handler, model=model)


def _classify_failure(
    item: dict[str, Any],
    status: str,
    error_category: str | None,
    has_descriptions: bool,
    generated_sql: str | None = None,
    provider_name: str = "mock",
) -> str:
    qid = item["id"]
    if status == "error":
        if error_category in FAILURE_CATEGORIES:
            return error_category
        return "syntax_error"
    if status == "refused" and item["answerable"]:
        return "ambiguity"
    if status == "ok" and not item["answerable"]:
        return "ambiguity"

    if provider_name == "mock":
        if qid in _PERSISTENT_FAILURES_FULL_SCHEMA:
            return _PERSISTENT_FAILURES_FULL_SCHEMA[qid][0]
        if not has_descriptions and qid in _BARE_SCHEMA_EXTRA_FAILURES:
            return _BARE_SCHEMA_EXTRA_FAILURES[qid][0]

    gen = (generated_sql or "").lower()
    ref = (item.get("sql") or "").lower()
    semantic_markers = (
        "weekly_transactions",
        "is_sensitivity_extrapolation",
        "zero_sales_proxy_tier",
        "volatility_proxy_tier",
        "perishability_class",
        "non_transferred_holidays",
    )
    if any(m in ref for m in semantic_markers):
        if "sum(weekly_transactions)" in gen and "max(weekly_transactions)" not in gen:
            return "wrong_column_semantics"
        for m in semantic_markers[1:]:
            if m in ref and m not in gen:
                return "wrong_column_semantics"
        if not has_descriptions:
            return "wrong_column_semantics"
    return "wrong_join_or_aggregation"


def evaluate_config(
    config: EvalConfig,
    gold_items: Sequence[dict[str, Any]],
    con: duckdb.DuckDBPyConnection,
    provider: LLMProvider,
) -> dict[str, Any]:
    """Run a single `EvalConfig` across all items in `gold_items` and compute summary metrics.

    Infrastructure failures (`res.status == "infra_error"`) are logged separately and excluded
    from accuracy denominators.
    """
    exec_correct = 0
    valid_sql_count = 0
    n_ans_eval = 0
    n_unans_eval = 0

    by_diff_total: dict[str, int] = {"easy": 0, "medium": 0, "hard": 0}
    by_diff_correct: dict[str, int] = {"easy": 0, "medium": 0, "hard": 0}

    refusal_correct = 0
    attempts_list: list[int] = []
    latencies: list[float] = []
    total_tokens_sum = 0
    has_tokens = False

    failure_counts: dict[str, int] = {cat: 0 for cat in FAILURE_CATEGORIES}
    failed_examples: list[dict[str, Any]] = []
    infrastructure_failures: list[dict[str, Any]] = []
    unresolved_questions: list[str] = []

    for item in gold_items:
        res = ask_question(
            item["question"],
            con,
            provider,
            max_repairs=config.max_repairs,
            include_descriptions=config.include_descriptions,
            include_grain_notes=config.include_grain_notes,
            grain_aware_prompt=config.grain_aware_prompt,
            check_grain_sanity=config.check_grain_sanity,
        )
        if res.status == "infra_error":
            unresolved_questions.append(item["id"])
            infrastructure_failures.append(
                {
                    "id": item["id"],
                    "difficulty": item["difficulty"],
                    "question": item["question"],
                    "attempts": res.attempts,
                    "error": res.error,
                }
            )
            continue

        attempts_list.append(res.attempts)
        latencies.append(res.latency_ms)
        if res.total_tokens is not None:
            has_tokens = True
            total_tokens_sum += res.total_tokens

        if item["answerable"]:
            n_ans_eval += 1
            diff = item["difficulty"]
            by_diff_total[diff] = by_diff_total.get(diff, 0) + 1
            if res.status == "ok":
                valid_sql_count += 1
                actual_rows = [list(r) for r in res.rows]
                if results_match(actual_rows, item["expected_rows"]):
                    exec_correct += 1
                    by_diff_correct[diff] = by_diff_correct.get(diff, 0) + 1
                else:
                    cat = _classify_failure(
                        item,
                        res.status,
                        res.error_category,
                        config.include_descriptions,
                        generated_sql=res.sql,
                        provider_name=provider.provider_name,
                    )
                    failure_counts[cat] = failure_counts.get(cat, 0) + 1
                    failed_examples.append(
                        {
                            "id": item["id"],
                            "difficulty": diff,
                            "question": item["question"],
                            "category": cat,
                            "generated_sql": res.sql,
                            "reference_sql": item["sql"],
                            "actual_row_preview": sorted(
                                ([_normalize_cell(c) for c in row] for row in actual_rows),
                                key=str,
                            )[:2],
                            "expected_row_preview": item["expected_rows"][:2],
                            "error": None,
                        }
                    )
            else:
                cat = _classify_failure(
                    item,
                    res.status,
                    res.error_category,
                    config.include_descriptions,
                    generated_sql=res.sql,
                    provider_name=provider.provider_name,
                )
                failure_counts[cat] = failure_counts.get(cat, 0) + 1
                failed_examples.append(
                    {
                        "id": item["id"],
                        "difficulty": diff,
                        "question": item["question"],
                        "category": cat,
                        "generated_sql": res.sql,
                        "reference_sql": item["sql"],
                        "actual_row_preview": [],
                        "expected_row_preview": item["expected_rows"][:2],
                        "error": res.error or res.reason,
                    }
                )
        else:
            n_unans_eval += 1
            if res.status == "refused" and not res.answerable:
                refusal_correct += 1
            else:
                cat = "ambiguity"
                failure_counts[cat] = failure_counts.get(cat, 0) + 1
                failed_examples.append(
                    {
                        "id": item["id"],
                        "difficulty": "unanswerable",
                        "question": item["question"],
                        "category": cat,
                        "generated_sql": res.sql,
                        "reference_sql": "",
                        "actual_row_preview": [
                            [_normalize_cell(c) for c in row] for row in res.rows[:2]
                        ],
                        "expected_row_preview": [],
                        "error": "Model failed to refuse unanswerable question",
                    }
                )

    exec_acc = round(exec_correct / n_ans_eval, 4) if n_ans_eval else 0.0
    exec_ci = wilson_ci(exec_correct, n_ans_eval)
    valid_rate = round(valid_sql_count / n_ans_eval, 4) if n_ans_eval else 0.0
    valid_ci = wilson_ci(valid_sql_count, n_ans_eval)
    refusal_acc = round(refusal_correct / n_unans_eval, 4) if n_unans_eval else 0.0
    refusal_ci = wilson_ci(refusal_correct, n_unans_eval)

    tier_metrics: dict[str, Any] = {}
    for tier in ("easy", "medium", "hard"):
        t_tot = by_diff_total.get(tier, 0)
        t_cor = by_diff_correct.get(tier, 0)
        tier_metrics[tier] = {
            "correct": t_cor,
            "total": t_tot,
            "accuracy": round(t_cor / t_tot, 4) if t_tot else 0.0,
            "wilson_95_ci": list(wilson_ci(t_cor, t_tot)),
        }

    sorted_lat = sorted(latencies)
    if provider.provider_name == "mock":
        det_latencies = [round(10.0 + 4.5 * a, 2) for a in attempts_list]
        sorted_lat = sorted(det_latencies)

    return {
        "config": config.name,
        "description": config.description,
        "max_repairs": config.max_repairs,
        "include_descriptions": config.include_descriptions,
        "include_grain_notes": config.include_grain_notes,
        "grain_aware_prompt": config.grain_aware_prompt,
        "check_grain_sanity": config.check_grain_sanity,
        "n_total": len(gold_items),
        "n_completed": len(gold_items) - len(unresolved_questions),
        "n_unresolved": len(unresolved_questions),
        "unresolved_questions": unresolved_questions,
        "infrastructure_failures_count": len(infrastructure_failures),
        "infrastructure_failures": infrastructure_failures,
        "n_answerable": n_ans_eval,
        "n_unanswerable": n_unans_eval,
        "execution_correct": exec_correct,
        "execution_accuracy": exec_acc,
        "execution_accuracy_wilson_95_ci": list(exec_ci),
        "valid_sql_count": valid_sql_count,
        "valid_sql_rate": valid_rate,
        "valid_sql_wilson_95_ci": list(valid_ci),
        "refusal_correct": refusal_correct,
        "refusal_accuracy": refusal_acc,
        "refusal_wilson_95_ci": list(refusal_ci),
        "mean_attempts": round(statistics.mean(attempts_list), 3) if attempts_list else 0.0,
        "latency_p50_ms": _percentile(sorted_lat, 0.50),
        "latency_p95_ms": _percentile(sorted_lat, 0.95),
        "total_tokens": total_tokens_sum if has_tokens else None,
        "by_difficulty": tier_metrics,
        "failure_counts": failure_counts,
        "failed_questions": failed_examples,
    }


def _evaluate_secondary_cached_run(
    *,
    provider_name: str,
    model_name: str,
    base_url: str,
    config_names: Sequence[str],
    gold_items: Sequence[dict[str, Any]],
    con: duckdb.DuckDBPyConnection,
    cache_dir: Path,
) -> dict[str, Any] | None:
    """Replay a secondary cached provider run offline if its cache file exists."""
    base_prov = create_provider(
        provider_name,
        model=model_name,
        base_url=base_url,
        use_cache=False,
        replay_only=True,
    )
    if base_prov.provider_name == "mock":
        base_prov = build_gold_mock_provider(gold_items, model=base_prov.model_name)
    cached_prov = CachedProvider(base_prov, cache_dir=cache_dir, replay_only=True)
    if not cached_prov.cache_path.is_file():
        return None

    configs_out: dict[str, Any] = {}
    for cname in config_names:
        cfg = _CONFIG_BY_NAME[cname]
        configs_out[cname] = evaluate_config(cfg, gold_items, con, cached_prov)

    primary_cfg = configs_out[config_names[0]]
    return {
        "provider": cached_prov.provider_name,
        "model": cached_prov.model_name,
        "response_model": cached_prov.response_model,
        "base_url_host": cached_prov.base_url_host,
        "temperature": DEFAULT_TEMPERATURE,
        "run_date": cached_prov.run_date,
        "cache_file": f"evals/cache/{cached_prov.cache_path.name}",
        "n_total": len(gold_items),
        "n_completed": primary_cfg["n_completed"],
        "n_unresolved": primary_cfg["n_unresolved"],
        "infrastructure_failures_count": primary_cfg["infrastructure_failures_count"],
        "primary_config": config_names[0],
        "headline": {
            "execution_accuracy": primary_cfg["execution_accuracy"],
            "execution_correct": primary_cfg["execution_correct"],
            "n_answerable": primary_cfg["n_answerable"],
            "execution_wilson_95_ci": primary_cfg["execution_accuracy_wilson_95_ci"],
            "valid_sql_rate": primary_cfg["valid_sql_rate"],
            "valid_sql_count": primary_cfg["valid_sql_count"],
            "valid_sql_wilson_95_ci": primary_cfg["valid_sql_wilson_95_ci"],
            "refusal_accuracy": primary_cfg["refusal_accuracy"],
            "refusal_correct": primary_cfg["refusal_correct"],
            "n_unanswerable": primary_cfg["n_unanswerable"],
            "refusal_wilson_95_ci": primary_cfg["refusal_wilson_95_ci"],
            "mean_attempts": primary_cfg["mean_attempts"],
            "latency_p50_ms": primary_cfg["latency_p50_ms"],
            "latency_p95_ms": primary_cfg["latency_p95_ms"],
            "total_tokens": primary_cfg["total_tokens"],
        },
        "configurations": configs_out,
    }


def run_evaluation(
    *,
    provider_name: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    config_names: Sequence[str] | None = None,
    replay: bool = False,
    gold_path: Path | str = DEFAULT_GOLD_PATH,
    metrics_path: Path | str = DEFAULT_METRICS_PATH,
    cache_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Run evaluation configurations, populate/replay cache, and write `metrics.json`."""
    if not replay:
        load_dotenv_file()

    gold_items = load_gold_set(gold_path)
    con = load_database(harden=True)
    resolved_cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()

    # If replay=True and no provider/model was explicitly requested, prefer the primary live
    # Groq cache if present on disk, otherwise fall back to mock.
    effective_provider = provider_name
    effective_model = model
    effective_base_url = base_url
    groq_cache = resolved_cache_dir / "openai_compatible_openai_gpt-oss-120b.jsonl"
    if (
        replay
        and effective_provider is None
        and not os.environ.get(PROVIDER_ENV)
        and groq_cache.is_file()
    ):
        effective_provider = "openai_compatible"
        effective_model = "openai/gpt-oss-120b"
        effective_base_url = "https://api.groq.com/openai/v1"

    base_provider = create_provider(
        effective_provider,
        model=effective_model,
        base_url=effective_base_url,
        use_cache=False,
        replay_only=replay,
    )
    heldout_items: list[dict[str, Any]] = []
    if Path(gold_path).resolve() == DEFAULT_GOLD_PATH.resolve() and DEFAULT_HELDOUT_PATH.is_file():
        heldout_items = load_gold_set(DEFAULT_HELDOUT_PATH)

    if base_provider.provider_name == "mock":
        base_provider = build_gold_mock_provider(
            [*gold_items, *heldout_items], model=base_provider.model_name
        )

    cached_provider = CachedProvider(
        base_provider,
        cache_dir=resolved_cache_dir,
        replay_only=replay,
    )

    selected_configs = (
        tuple(_CONFIG_BY_NAME[name] for name in config_names) if config_names else DEFAULT_CONFIGS
    )

    try:
        configs_out: dict[str, Any] = {}
        for cfg in selected_configs:
            configs_out[cfg.name] = evaluate_config(cfg, gold_items, con, cached_provider)

        heldout_out: dict[str, Any] | None = None
        if heldout_items:
            heldout_configs_out: dict[str, Any] = {}
            for cfg in selected_configs:
                heldout_configs_out[cfg.name] = evaluate_config(
                    cfg, heldout_items, con, cached_provider
                )
            hp = heldout_configs_out[selected_configs[0].name]
            heldout_out = {
                "heldout_set_path": "evals/heldout.jsonl",
                "review_status": "needs human review",
                "provider": cached_provider.provider_name,
                "model": cached_provider.model_name,
                "response_model": cached_provider.response_model,
                "base_url_host": cached_provider.base_url_host,
                "temperature": DEFAULT_TEMPERATURE,
                "run_date": cached_provider.run_date,
                "n_total": len(heldout_items),
                "n_completed": hp["n_completed"],
                "n_unresolved": hp["n_unresolved"],
                "infrastructure_failures_count": hp["infrastructure_failures_count"],
                "n_answerable": hp["n_answerable"],
                "n_unanswerable": hp["n_unanswerable"],
                "primary_config": selected_configs[0].name,
                "headline": {
                    "execution_accuracy": hp["execution_accuracy"],
                    "execution_correct": hp["execution_correct"],
                    "execution_wilson_95_ci": hp["execution_accuracy_wilson_95_ci"],
                    "valid_sql_rate": hp["valid_sql_rate"],
                    "valid_sql_count": hp["valid_sql_count"],
                    "valid_sql_wilson_95_ci": hp["valid_sql_wilson_95_ci"],
                    "mean_attempts": hp["mean_attempts"],
                    "latency_p50_ms": hp["latency_p50_ms"],
                    "latency_p95_ms": hp["latency_p95_ms"],
                    "total_tokens": hp["total_tokens"],
                },
                "configurations": heldout_configs_out,
            }

        secondary_live_runs: list[dict[str, Any]] = []
        harness_validation_run: dict[str, Any] | None = None

        if cached_provider.provider_name != "mock":
            # Attach secondary live run (Groq openai/gpt-oss-20b) if cached
            run_b_cache = resolved_cache_dir / "openai_compatible_openai_gpt-oss-20b.jsonl"
            if run_b_cache.is_file() and cached_provider.cache_path.name != run_b_cache.name:
                sec = _evaluate_secondary_cached_run(
                    provider_name="openai_compatible",
                    model_name="openai/gpt-oss-20b",
                    base_url="https://api.groq.com/openai/v1",
                    config_names=(
                        *(c.name for c in BASELINE_CONFIGS),
                        "grain_sanity_check_repair_on",
                    ),
                    gold_items=gold_items,
                    con=con,
                    cache_dir=resolved_cache_dir,
                )
                if sec is not None:
                    secondary_live_runs.append(sec)

            # Attach deterministic mock harness validation summary
            mock_cache = resolved_cache_dir / "mock_mock-sql-v1.jsonl"
            if mock_cache.is_file():
                harness_validation_run = _evaluate_secondary_cached_run(
                    provider_name="mock",
                    model_name="mock-sql-v1",
                    base_url="",
                    config_names=tuple(c.name for c in DEFAULT_CONFIGS),
                    gold_items=gold_items,
                    con=con,
                    cache_dir=resolved_cache_dir,
                )
    finally:
        con.close()

    primary_key = selected_configs[0].name
    primary = configs_out[primary_key]
    report: dict[str, Any] = {
        "schema_version": "1.1",
        "provider": cached_provider.provider_name,
        "model": cached_provider.model_name,
        "response_model": cached_provider.response_model,
        "base_url_host": cached_provider.base_url_host,
        "temperature": DEFAULT_TEMPERATURE,
        "run_date": cached_provider.run_date,
        "gold_set_path": "evals/gold.jsonl",
        "cache_file": f"evals/cache/{cached_provider.cache_path.name}",
        "n_total": len(gold_items),
        "n_completed": primary["n_completed"],
        "n_unresolved": primary["n_unresolved"],
        "infrastructure_failures_count": primary["infrastructure_failures_count"],
        "n_answerable": primary["n_answerable"],
        "n_unanswerable": primary["n_unanswerable"],
        "primary_config": primary_key,
        "headline": {
            "execution_accuracy": primary["execution_accuracy"],
            "execution_correct": primary["execution_correct"],
            "execution_wilson_95_ci": primary["execution_accuracy_wilson_95_ci"],
            "valid_sql_rate": primary["valid_sql_rate"],
            "valid_sql_count": primary["valid_sql_count"],
            "valid_sql_wilson_95_ci": primary["valid_sql_wilson_95_ci"],
            "refusal_accuracy": primary["refusal_accuracy"],
            "refusal_correct": primary["refusal_correct"],
            "refusal_wilson_95_ci": primary["refusal_wilson_95_ci"],
            "mean_attempts": primary["mean_attempts"],
            "latency_p50_ms": primary["latency_p50_ms"],
            "latency_p95_ms": primary["latency_p95_ms"],
            "total_tokens": primary["total_tokens"],
        },
        "configurations": configs_out,
    }
    if heldout_out is not None:
        report["heldout_evaluation"] = heldout_out
    if secondary_live_runs:
        report["secondary_live_runs"] = secondary_live_runs
    if harness_validation_run is not None:
        report["harness_validation_run"] = harness_validation_run

    out_file = Path(metrics_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m copilot.eval",
        description="Run the analytics-copilot gold evaluation suite and write metrics.json.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider override (gemini | openai_compatible | ollama | mock).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL override for openai_compatible provider.",
    )
    parser.add_argument(
        "--configs",
        default=None,
        help="Comma-separated list of configuration names to evaluate.",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Reproduce evaluation offline from evals/cache/*.jsonl without API calls.",
    )
    parser.add_argument(
        "--gold",
        default=str(DEFAULT_GOLD_PATH),
        help="Path to gold JSONL file (default: evals/gold.jsonl).",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_METRICS_PATH),
        help="Output path for metrics JSON (default: metrics/metrics.json).",
    )
    args = parser.parse_args(argv)

    cfg_list = (
        tuple(x.strip() for x in args.configs.split(",") if x.strip()) if args.configs else None
    )
    report = run_evaluation(
        provider_name=args.provider,
        model=args.model,
        base_url=args.base_url,
        config_names=cfg_list,
        replay=args.replay,
        gold_path=args.gold,
        metrics_path=args.out,
    )
    hl = report["headline"]
    ci = hl["execution_wilson_95_ci"]
    acc_pct = hl["execution_accuracy"] * 100
    ci_low, ci_high = ci[0] * 100, ci[1] * 100
    print(
        f"Provider: {report['provider']} (model={report['model']}, "
        f"response_model={report['response_model']}, host={report['base_url_host']}, "
        f"temp={report['temperature']}, date={report['run_date']}) | Replay: {args.replay}\n"
        f"Completed: {report['n_completed']}/{report['n_total']} "
        f"(Unresolved: {report['n_unresolved']}, "
        f"Infra Failures: {report['infrastructure_failures_count']})\n"
        f"Execution Accuracy: {hl['execution_correct']}/{report['n_answerable']} "
        f"= {acc_pct:.1f}% (95% Wilson CI: [{ci_low:.1f}%, {ci_high:.1f}%])\n"
        f"Valid SQL Rate: {hl['valid_sql_rate'] * 100:.1f}% | "
        f"Refusal Accuracy: {hl['refusal_correct']}/{report['n_unanswerable']} "
        f"({hl['refusal_accuracy'] * 100:.1f}%) | Mean Attempts: {hl['mean_attempts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
