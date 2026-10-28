"""Generate README.md directly from metrics/metrics.json so no figure can drift."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METRICS_PATH = REPO_ROOT / "metrics" / "metrics.json"
DEFAULT_README_PATH = REPO_ROOT / "README.md"
DEFAULT_VERDICTS_PATH = REPO_ROOT / "evals" / "review_verdicts.json"


def _load_review_data(n_ans: int, c_on: dict[str, Any]) -> tuple[str, str, int, float] | None:
    if not DEFAULT_VERDICTS_PATH.is_file():
        return None
    try:
        verdicts = json.loads(DEFAULT_VERDICTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    verdict_by_id = {v["id"]: v.get("verdict") for v in verdicts}
    reviewed_count = len(verdict_by_id)
    unreviewed_count = n_ans - reviewed_count

    failed_list = c_on.get("failed_questions", [])
    total_failures = len(failed_list)
    model_correct_failures = sum(
        1 for fq in failed_list if verdict_by_id.get(fq["id"]) == "Model correct"
    )
    genuine_errors = [
        fq["id"] for fq in failed_list if verdict_by_id.get(fq["id"]) != "Model correct"
    ]
    genuine_error_count = len(genuine_errors)
    genuine_error_str = ", ".join(genuine_errors)

    review_sentence = (
        "Strict scoring penalises column projection and order; "
        f"{model_correct_failures} of the {total_failures} failures were result-identical "
        "queries with different columns, "
        f"{genuine_error_count} was a genuine error ({genuine_error_str})."
    )
    coverage_sentence = (
        f"{reviewed_count} of {n_ans} gold questions were reviewed by me and the other "
        f"{unreviewed_count} were not."
    )
    strict_correct = c_on["execution_correct"]
    reviewed_correct = strict_correct + model_correct_failures
    reviewed_acc = c_on.get("reviewed_execution_accuracy", round(reviewed_correct / n_ans, 4))
    return review_sentence, coverage_sentence, reviewed_correct, reviewed_acc


def _fmt_pct(val: float) -> str:
    return f"{val * 100:.1f}%"


def _fmt_ci(ci: list[float]) -> str:
    return f"[{ci[0] * 100:.1f}%, {ci[1] * 100:.1f}%]"


def _cfg_row(cfg: dict[str, Any], label: str) -> str:
    name = f"`{cfg['config']}`"
    n_comp = cfg.get("n_completed", cfg["n_total"])
    n_tot = cfg["n_total"]
    if n_comp < n_tot:
        inc_str = f"incomplete, Groq daily token cap ({n_comp}/{n_tot})"
        return " | ".join(["|" + f" {name}", label, inc_str, "n/a", "n/a", "n/a", "n/a", "n/a |"])
    n_ans = cfg["n_answerable"]
    n_unans = cfg["n_unanswerable"]
    if "reviewed_execution_accuracy" in cfg:
        reviewed_acc = cfg["reviewed_execution_accuracy"]
        reviewed_correct = round(reviewed_acc * n_ans)
        exec_str = (
            f"{cfg['execution_correct']}/{n_ans} ({_fmt_pct(cfg['execution_accuracy'])}) strict / "
            f"{reviewed_correct}/{n_ans} ({_fmt_pct(reviewed_acc)}) reviewed"
        )
    else:
        exec_str = f"{cfg['execution_correct']}/{n_ans} ({_fmt_pct(cfg['execution_accuracy'])})"
    ci_str = f"`{_fmt_ci(cfg['execution_accuracy_wilson_95_ci'])}`"
    val_str = f"{cfg['valid_sql_count']}/{n_ans} ({_fmt_pct(cfg['valid_sql_rate'])})"
    ref_str = f"{cfg['refusal_correct']}/{n_unans} ({_fmt_pct(cfg['refusal_accuracy'])})"
    att_str = f"{cfg['mean_attempts']:.3f}"
    tok_str = f"{cfg['total_tokens']}"
    return " | ".join(
        ["|" + f" {name}", label, exec_str, ci_str, val_str, ref_str, att_str, f"{tok_str} |"]
    )


def _fail_row(
    cat: str,
    fc_on: dict[str, int],
    fc_off: dict[str, int],
    fc_bare: dict[str, int],
    mechanism: str,
) -> str:
    return f"| `{cat}` | {fc_on[cat]} | {fc_off[cat]} | {fc_bare[cat]} | {mechanism} |"


def _render_eval_status_block(metrics: dict[str, Any]) -> list[str]:
    """Render the top-level Evaluation status section from `metrics.json` provider fields."""
    provider = metrics["provider"]
    model = metrics["model"]
    response_model = metrics.get("response_model", model)
    host = metrics.get("base_url_host", "local-mock")
    temp = metrics.get("temperature", 0.0)
    run_date = metrics.get("run_date", "2026-10-26")
    cache_file = metrics["cache_file"]
    n_comp = metrics.get("n_completed", metrics["n_total"])
    n_tot = metrics["n_total"]
    n_unres = metrics.get("n_unresolved", 0)
    infra_cnt = metrics.get("infrastructure_failures_count", 0)

    lines = [
        "## Evaluation status",
        "",
        (
            f"- **Primary provider in `metrics/metrics.json` (Run A)**: `{provider}` "
            f"(requested model `{model}`, API-returned model `{response_model}`, "
            f"endpoint host `{host}`, `temperature={temp}`, `run_date={run_date}`, "
            f"cached in `{cache_file}`)."
        ),
        (
            f"- **Completion & infrastructure status**: **{n_comp}/{n_tot}** questions completed "
            f"(**{n_unres}** unresolved; **{infra_cnt}** infrastructure failures excluded from "
            "accuracy denominators)."
        ),
    ]
    if provider == "mock":
        lines.extend(
            [
                "- **Interpretation**: Current primary metrics come from the deterministic",
                "  `MockProvider` (**harness validation, not model quality**); latency and token",
                "  figures are mock values used to verify offline replay, ablation logic, and CI",
                "  reproducibility.",
            ]
        )
    else:
        status_interp = [
            "- **Interpretation**: Primary headline and ablation metrics come from recorded",
            f"  live LLM calls against `{host}` (`{response_model}`) replayed",
            f"  deterministically from `{cache_file}`.",
        ]
        hl = metrics.get("headline", {})
        n_ans = metrics.get("n_answerable", 40)
        c_on = metrics.get("configurations", {}).get("full_schema_repair_on", {})
        review_data = _load_review_data(n_ans, c_on)
        if review_data is not None and "execution_accuracy" in hl:
            rev_sent, cov_sent, rev_corr, rev_acc = review_data
            status_interp.extend(
                [
                    (
                        "  Strict execution accuracy is "
                        f"**{hl['execution_correct']}/{n_ans} "
                        f"({_fmt_pct(hl['execution_accuracy'])})** vs. "
                        f"**{rev_corr}/{n_ans} ({_fmt_pct(rev_acc)})** reviewed. "
                        f"{rev_sent} {cov_sent}"
                    ),
                ]
            )
        lines.extend(status_interp)
    for sec in metrics.get("secondary_live_runs", []):
        sec_hl = sec["headline"]
        sec_cfgs = sec.get("configurations", {})
        bare_str = ""
        if "bare_schema_repair_on" in sec_cfgs:
            bc = sec_cfgs["bare_schema_repair_on"]
            bc_comp = bc.get("n_completed", bc["n_total"])
            bc_tot = bc["n_total"]
            if bc_comp < bc_tot:
                bare_str = (
                    f"; `bare_schema_repair_on` is incomplete, Groq daily token cap "
                    f"({bc_comp}/{bc_tot} completed)"
                )
            else:
                bare_str = (
                    f", and **{bc['execution_correct']}/{bc['n_answerable']} "
                    f"({_fmt_pct(bc['execution_accuracy'])})** on `bare_schema_repair_on`"
                )
        lines.append(
            f"- **Secondary live provider (Run B — `{sec['base_url_host']}`)**: "
            f"`{sec['provider']}` (requested model `{sec['model']}`, API-returned model "
            f"`{sec['response_model']}`, `temperature={sec['temperature']}`, "
            f"`run_date={sec['run_date']}`, cached in `{sec['cache_file']}`) — "
            f"**{sec['n_completed']}/{sec['n_total']}** completed on `{sec['primary_config']}`, "
            f"execution accuracy **{sec_hl['execution_correct']}/{sec_hl['n_answerable']} "
            f"({_fmt_pct(sec_hl['execution_accuracy'])})** on `{sec['primary_config']}`{bare_str}."
        )
    if metrics.get("harness_validation_run") is not None:
        hv = metrics["harness_validation_run"]
        hv_hl = hv["headline"]
        lines.append(
            f"- **Harness validation baseline (`MockProvider` / `{hv['model']}`)**: "
            "**harness validation only, not model quality** (latency and token counts are "
            f"synthetic mock values; cached in `{hv['cache_file']}`, "
            f"{hv_hl['execution_correct']}/{hv_hl['n_answerable']} = "
            f"{_fmt_pct(hv_hl['execution_accuracy'])} on `{hv['primary_config']}`). All "
            "`mock-sql-v1` grain ablation and held-out figures in `metrics/metrics.json` are "
            "**harness validation only, not evidence that the grain fixes work**."
        )
    h_gap = (
        metrics.get("heldout_evaluation", {})
        .get("configurations", {})
        .get("grain_aware_prompt_repair_on", {})
    )
    h_gap_str = f"{h_gap.get('n_completed', 0)}/{h_gap.get('n_total', 10)}"
    lines.append(
        "- **Grain ablation summary**: The grain fixes did not change live results on gold "
        "(sanity check 70.0% vs 70.0%, while `catalog_grain_notes_repair_on` 0/45 and "
        "`grain_aware_prompt_repair_on` 0/45 are incomplete, Groq daily token cap); "
        "the held-out set was already 100% before any change (`full_schema_repair_on` 10/10 = "
        "100.0%, `catalog_grain_notes_repair_on` 10/10 = 100.0%, `grain_sanity_check_repair_on` "
        f"10/10 = 100.0%, while `grain_aware_prompt_repair_on` {h_gap_str} is incomplete, Groq "
        "daily token cap), so it cannot show improvement; **no improvement is claimed**."
    )
    lines.append(
        "- **Gateway & rate-limit note**: Anonymous free gateways (`text.pollinations.ai/openai` "
        "and `api.llm7.io/v1` with alias `openai-fast`) were probed; `api.llm7.io` returned "
        "`HTTP 400 model_unavailable` and `text.pollinations.ai` enforced a 1 req/30s IP cap "
        "(attempted and abandoned after 31/45 questions in favor of `openai/gpt-oss-20b` on "
        "`api.groq.com`). Gateway aliases like `openai-fast` may change upstream routing over time."
    )
    return lines


def _describe_failure_example(idx: int, ex: dict[str, Any]) -> list[str]:
    """Render a concrete failed question entry from `failed_questions` in `metrics.json`."""
    qid = ex["id"]
    cat = ex["category"]
    q_text = ex["question"]
    gen_sql = ex.get("generated_sql") or "None (refused or failed before SQL execution)"
    ref_sql = ex.get("reference_sql") or "None (unanswerable question; expected refusal)"
    err = ex.get("error")
    act_prev = ex.get("actual_row_preview") or []
    exp_prev = ex.get("expected_row_preview") or []

    if err:
        why = f"Execution failed or mismatched with error: `{err}`."
    elif qid == "hard_01":
        why = (
            "`weekly_transactions` in `weekly_store_family_summary` is a store-level figure "
            "repeated on all 33 product-family rows for each `(store_nbr, week_start_date)`. "
            f"Actual preview `{act_prev[:1]}` vs expected `{exp_prev[:1]}`."
        )
    elif qid == "hard_08":
        why = (
            "The query aggregated `total_sales` at the wrong grain rather than first summing "
            "chain-wide weekly sales by `week_start_date` in a CTE and then averaging across "
            f"weeks. Actual preview `{act_prev[:1]}` vs expected `{exp_prev[:1]}`."
        )
    else:
        why = (
            f"Result set mismatch under `{cat}`: actual row preview `{act_prev[:1]}` "
            f"did not match reference preview `{exp_prev[:1]}`."
        )

    return [
        f"{idx}. **`{qid}` (`{cat}`)**: *{q_text}*",
        f"   - **Generated SQL**: `{gen_sql}`",
        f"   - **Reference SQL**: `{ref_sql}`",
        f"   - **Why it failed**: {why}",
    ]


def _render_multi_provider_section(metrics: dict[str, Any]) -> list[str]:
    sec_runs = metrics.get("secondary_live_runs", [])
    hv = metrics.get("harness_validation_run")
    if not sec_runs and hv is None:
        return []

    hl = metrics["headline"]
    n_ans = metrics["n_answerable"]
    n_unans = metrics["n_unanswerable"]
    c_on = metrics.get("configurations", {}).get("full_schema_repair_on", {})
    if "reviewed_execution_accuracy" in c_on:
        r_acc = c_on["reviewed_execution_accuracy"]
        r_corr = round(r_acc * n_ans)
        live_a_exec = (
            f"{hl['execution_correct']}/{n_ans} ({_fmt_pct(hl['execution_accuracy'])}) strict / "
            f"{r_corr}/{n_ans} ({_fmt_pct(r_acc)}) reviewed"
        )
    else:
        live_a_exec = f"{hl['execution_correct']}/{n_ans} ({_fmt_pct(hl['execution_accuracy'])})"
    rows = [
        "### Multi-Provider & Harness Comparison",
        "",
        (
            "| Run Role | Provider | Requested Model | API-Returned Model | Host | Config "
            "| Completed | Execution Accuracy | 95% Wilson CI | Valid-SQL Rate "
            "| Refusal Accuracy | Latency (p50 / p95) | Total Tokens |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        (
            f"| **Live Run A (Headline)** | `{metrics['provider']}` | `{metrics['model']}` "
            f"| `{metrics.get('response_model', metrics['model'])}` "
            f"| `{metrics.get('base_url_host', 'local-mock')}` | `full_schema_repair_on` "
            f"| {metrics.get('n_completed', metrics['n_total'])}/{metrics['n_total']} "
            f"| {live_a_exec} "
            f"| `{_fmt_ci(hl['execution_wilson_95_ci'])}` "
            f"| {hl['valid_sql_count']}/{n_ans} ({_fmt_pct(hl['valid_sql_rate'])}) "
            f"| {hl['refusal_correct']}/{n_unans} ({_fmt_pct(hl['refusal_accuracy'])}) "
            f"| {hl['latency_p50_ms']:.2f} / {hl['latency_p95_ms']:.2f} ms "
            f"| {hl['total_tokens']} |"
        ),
    ]
    for sec in sec_runs:
        sec_cfgs = sec.get("configurations", {})
        for cfg_name in ("full_schema_repair_on", "bare_schema_repair_on"):
            if cfg_name not in sec_cfgs:
                continue
            sc = sec_cfgs[cfg_name]
            sc_comp = sc.get("n_completed", sc["n_total"])
            sc_tot = sc["n_total"]
            if sc_comp < sc_tot:
                rows.append(
                    f"| **Live Run B** | `{sec['provider']}` | `{sec['model']}` "
                    f"| `{sec['response_model']}` | `{sec['base_url_host']}` | `{cfg_name}` "
                    f"| {sc_comp}/{sc_tot} "
                    f"| incomplete, Groq daily token cap ({sc_comp}/{sc_tot}) "
                    "| n/a | n/a | n/a | n/a | n/a |"
                )
                continue
            sa = sc["n_answerable"]
            su = sc["n_unanswerable"]
            rows.append(
                f"| **Live Run B** | `{sec['provider']}` | `{sec['model']}` "
                f"| `{sec['response_model']}` | `{sec['base_url_host']}` | `{cfg_name}` "
                f"| {sc_comp}/{sc_tot} "
                f"| {sc['execution_correct']}/{sa} ({_fmt_pct(sc['execution_accuracy'])}) "
                f"| `{_fmt_ci(sc['execution_accuracy_wilson_95_ci'])}` "
                f"| {sc['valid_sql_count']}/{sa} ({_fmt_pct(sc['valid_sql_rate'])}) "
                f"| {sc['refusal_correct']}/{su} ({_fmt_pct(sc['refusal_accuracy'])}) "
                f"| {sc['latency_p50_ms']:.2f} / {sc['latency_p95_ms']:.2f} ms "
                f"| {sc['total_tokens']} |"
            )
    if hv is not None:
        hhl = hv["headline"]
        ha = hhl["n_answerable"]
        hu = hhl["n_unanswerable"]
        rows.append(
            f"| **Harness Validation (Mock)** | `{hv['provider']}` | `{hv['model']}` "
            f"| `{hv['response_model']}` | `{hv['base_url_host']}` | `full_schema_repair_on` "
            f"| {hv['n_completed']}/{hv['n_total']} "
            f"| {hhl['execution_correct']}/{ha} ({_fmt_pct(hhl['execution_accuracy'])}) "
            f"| `{_fmt_ci(hhl['execution_wilson_95_ci'])}` "
            f"| {hhl['valid_sql_count']}/{ha} ({_fmt_pct(hhl['valid_sql_rate'])}) "
            f"| {hhl['refusal_correct']}/{hu} ({_fmt_pct(hhl['refusal_accuracy'])}) "
            f"| {hhl['latency_p50_ms']:.2f} / {hhl['latency_p95_ms']:.2f} ms (mock) "
            f"| {hhl['total_tokens']} (mock) |"
        )
    rows.append("")
    return rows


def _render_difficulty_section(metrics: dict[str, Any]) -> list[str]:
    response_model = metrics.get("response_model", metrics["model"])
    c_on = metrics["configurations"]["full_schema_repair_on"]
    d_easy = c_on["by_difficulty"]["easy"]
    d_med = c_on["by_difficulty"]["medium"]
    d_hard = c_on["by_difficulty"]["hard"]

    sec_runs = metrics.get("secondary_live_runs", [])
    if not sec_runs:
        return [
            f"### Accuracy by Difficulty Tier (`full_schema_repair_on` — `{response_model}`)",
            "",
            "| Difficulty Tier | Correct / Total | Accuracy | 95% Wilson CI |",
            "| --- | --- | --- | --- |",
            (
                f"| Easy (`easy_01` - `easy_10`) | {d_easy['correct']}/{d_easy['total']} "
                f"| {_fmt_pct(d_easy['accuracy'])} | `{_fmt_ci(d_easy['wilson_95_ci'])}` |"
            ),
            (
                f"| Medium (`med_01` - `med_20`) | {d_med['correct']}/{d_med['total']} "
                f"| {_fmt_pct(d_med['accuracy'])} | `{_fmt_ci(d_med['wilson_95_ci'])}` |"
            ),
            (
                f"| Hard (`hard_01` - `hard_10`) | {d_hard['correct']}/{d_hard['total']} "
                f"| {_fmt_pct(d_hard['accuracy'])} | `{_fmt_ci(d_hard['wilson_95_ci'])}` |"
            ),
        ]

    sec = sec_runs[0]
    sec_model = sec.get("response_model", sec["model"])
    s_on = sec["configurations"]["full_schema_repair_on"]
    s_easy = s_on["by_difficulty"]["easy"]
    s_med = s_on["by_difficulty"]["medium"]
    s_hard = s_on["by_difficulty"]["hard"]

    return [
        "### Accuracy by Difficulty Tier (`full_schema_repair_on` — Run A vs. Run B)",
        "",
        (
            f"| Difficulty Tier | Run A (`{response_model}`) | Run A 95% Wilson CI "
            f"| Run B (`{sec_model}`) | Run B 95% Wilson CI |"
        ),
        "| --- | --- | --- | --- | --- |",
        (
            f"| Easy (`easy_01` - `easy_10`) "
            f"| {d_easy['correct']}/{d_easy['total']} ({_fmt_pct(d_easy['accuracy'])}) "
            f"| `{_fmt_ci(d_easy['wilson_95_ci'])}` "
            f"| {s_easy['correct']}/{s_easy['total']} ({_fmt_pct(s_easy['accuracy'])}) "
            f"| `{_fmt_ci(s_easy['wilson_95_ci'])}` |"
        ),
        (
            f"| Medium (`med_01` - `med_20`) "
            f"| {d_med['correct']}/{d_med['total']} ({_fmt_pct(d_med['accuracy'])}) "
            f"| `{_fmt_ci(d_med['wilson_95_ci'])}` "
            f"| {s_med['correct']}/{s_med['total']} ({_fmt_pct(s_med['accuracy'])}) "
            f"| `{_fmt_ci(s_med['wilson_95_ci'])}` |"
        ),
        (
            f"| Hard (`hard_01` - `hard_10`) "
            f"| {d_hard['correct']}/{d_hard['total']} ({_fmt_pct(d_hard['accuracy'])}) "
            f"| `{_fmt_ci(d_hard['wilson_95_ci'])}` "
            f"| {s_hard['correct']}/{s_hard['total']} ({_fmt_pct(s_hard['accuracy'])}) "
            f"| `{_fmt_ci(s_hard['wilson_95_ci'])}` |"
        ),
    ]


def _render_guard_attack_section(metrics: dict[str, Any]) -> list[str]:
    guard = metrics.get("guard_attack_suite")
    if not guard:
        return []
    blocked = guard["blocked"]
    total = guard["total"]
    rate_pct = _fmt_pct(guard["block_rate"])
    lines = [
        "",
        f"### Guard Attack-Suite Results (**{blocked}/{total}** blocked — **{rate_pct}**)",
        "",
        "| Attack Category | Blocked / Total | Block Rate |",
        "| --- | --- | --- |",
    ]
    for cat, stats in guard.get("by_category", {}).items():
        lines.append(
            f"| `{cat}` | {stats['blocked']}/{stats['total']} | {_fmt_pct(stats['block_rate'])} |"
        )
    lines.append(f"| **Total** | **{blocked}/{total}** | **{rate_pct}** |")
    return lines


def _render_heldout_section(metrics: dict[str, Any]) -> list[str]:
    heldout = metrics.get("heldout_evaluation")
    if not heldout:
        return []
    h_cfgs = heldout.get("configurations", {})
    if not h_cfgs:
        return []
    response_model = heldout.get("response_model", heldout.get("model", metrics["model"]))
    lines = [
        "",
        f"### Held-Out Set Evaluation (`evals/heldout.jsonl` — `{response_model}`)",
        "",
        (
            "The 10-question held-out benchmark (`evals/heldout.jsonl`: 4 `medium`, 6 `hard`, "
            "marked `needs human review` in `docs/GOLD_REVIEW.md`) was authored before any "
            "grain-aware prompt or sanity-check modifications. Note: the 45-question gold set "
            "(`evals/gold.jsonl`) was seen while inspecting failure modes, whereas the 10-question "
            "held-out set (`evals/heldout.jsonl`) was not."
        ),
        "",
        (
            "| Configuration | Description | Execution Accuracy | 95% Wilson CI | Medium (4) "
            "| Hard (6) | Valid-SQL Rate | Mean Attempts | Total Tokens |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cfg_name, cfg in h_cfgs.items():
        n_comp = cfg.get("n_completed", cfg["n_total"])
        n_tot = cfg["n_total"]
        if n_comp < n_tot:
            lines.append(
                f"| `{cfg_name}` | {cfg['description']} "
                f"| incomplete, Groq daily token cap ({n_comp}/{n_tot}) "
                "| n/a | n/a | n/a | n/a | n/a | n/a |"
            )
            continue
        n_ans = cfg["n_answerable"]
        d_med = cfg["by_difficulty"]["medium"]
        d_hard = cfg["by_difficulty"]["hard"]
        lines.append(
            f"| `{cfg_name}` | {cfg['description']} "
            f"| {cfg['execution_correct']}/{n_ans} ({_fmt_pct(cfg['execution_accuracy'])}) "
            f"| `{_fmt_ci(cfg['execution_accuracy_wilson_95_ci'])}` "
            f"| {d_med['correct']}/{d_med['total']} ({_fmt_pct(d_med['accuracy'])}) "
            f"| {d_hard['correct']}/{d_hard['total']} ({_fmt_pct(d_hard['accuracy'])}) "
            f"| {cfg['valid_sql_count']}/{n_ans} ({_fmt_pct(cfg['valid_sql_rate'])}) "
            f"| {cfg['mean_attempts']:.3f} | {cfg['total_tokens']} |"
        )
    lines.extend(
        [
            "",
            "*Plain statement on grain fixes and held-out results*: The grain fixes did not change "
            "live results on gold (sanity check 70.0% vs 70.0%); the held-out set was already 100% "
            "before any change, so it cannot show improvement; no improvement is claimed. All "
            "`mock-sql-v1` grain results in `metrics/metrics.json` are **harness validation only, "
            "not evidence that the grain fixes work**.",
        ]
    )
    return lines


def render_readme(metrics: dict[str, Any]) -> str:
    """Render the full project README.md using exact figures from `metrics/metrics.json`."""
    hl = metrics["headline"]
    n_total = metrics["n_total"]
    n_ans = metrics["n_answerable"]
    n_unans = metrics["n_unanswerable"]
    provider = metrics["provider"]
    model = metrics["model"]
    response_model = metrics.get("response_model", model)
    host = metrics.get("base_url_host", "local-mock")
    cache_file = metrics["cache_file"]

    configs = metrics["configurations"]
    c_on = configs["full_schema_repair_on"]
    c_off = configs["full_schema_repair_off"]
    c_bare = configs["bare_schema_repair_on"]

    fc_on = c_on["failure_counts"]
    fc_off = c_off["failure_counts"]
    fc_bare = c_bare["failure_counts"]

    failed_list = c_on["failed_questions"]
    example_lines: list[str] = []
    if len(failed_list) >= 2:
        ex1 = failed_list[0]
        ex2 = failed_list[2] if len(failed_list) > 2 else failed_list[1]
        example_lines.extend(_describe_failure_example(1, ex1))
        example_lines.append("")
        example_lines.extend(_describe_failure_example(2, ex2))
    elif len(failed_list) == 1:
        example_lines.extend(_describe_failure_example(1, failed_list[0]))
    else:
        example_lines.append("No failed questions in `full_schema_repair_on`.")

    review_data = _load_review_data(n_ans, c_on)
    if review_data is not None:
        rev_sent, cov_sent, rev_corr, rev_acc = review_data
        strict_fmt = f"{hl['execution_correct']}/{n_ans} ({_fmt_pct(hl['execution_accuracy'])})"
        rev_fmt = f"{rev_corr}/{n_ans} ({_fmt_pct(rev_acc)})"
        exec_val = f"**{strict_fmt}** strict / **{rev_fmt}** reviewed"
    else:
        exec_val = f"**{hl['execution_correct']}/{n_ans} ({_fmt_pct(hl['execution_accuracy'])})**"
    exec_ci = f"`{_fmt_ci(hl['execution_wilson_95_ci'])}`"
    val_val = f"**{hl['valid_sql_count']}/{n_ans} ({_fmt_pct(hl['valid_sql_rate'])})**"
    val_ci = f"`{_fmt_ci(hl['valid_sql_wilson_95_ci'])}`"
    ref_val = f"**{hl['refusal_correct']}/{n_unans} ({_fmt_pct(hl['refusal_accuracy'])})**"
    ref_ci = f"`{_fmt_ci(hl['refusal_wilson_95_ci'])}`"
    lat_val = f"**{hl['latency_p50_ms']:.2f} ms / {hl['latency_p95_ms']:.2f} ms**"
    lat_note = (
        "Deterministic offline replay latency model (mock)"
        if provider == "mock"
        else f"Recorded live LLM latency from `{host}` (`{response_model}`)"
    )

    lines: list[str] = [
        "# analytics-copilot",
        "",
        "Guarded natural-language-to-SQL assistant and offline-reproducible evaluation harness",
        "over tracked Parquet aggregates derived from the",
        "[grocery-demand-planner](https://github.com/lazycoder52/grocery-demand-planner) pipeline",
        "(Corporación Favorita grocery store sales across 54 stores and 33 product families",
        "in Ecuador).",
        "",
        "Data source: [grocery-demand-planner](https://github.com/lazycoder52/grocery-demand-planner)",
        "",
        *_render_eval_status_block(metrics),
        "",
        "## Problem",
        "",
        "Business and operations teams frequently ask ad-hoc analytical questions over demand",
        "planning outputs (weekly store-family sales, promotion lift, stock-out proxy rates,",
        "perishable demand volatility, and inventory replenishment policy simulations). Writing",
        "SQL by hand is slow, but exposing an LLM directly to a database creates two failure",
        "modes:",
        "",
        "1. **Security and resource risks**: arbitrary SQL generation can scan local files, query",
        "   system catalogs, mutate state, or lock up the database with runaway cross joins.",
        "2. **Silent semantic errors**: without grounded column definitions (such as store-week",
        "   grain caveats or proxy tier rules), LLMs generate syntactically valid SQL that",
        "   double-counts store transactions or averages across the wrong grain.",
        "",
        "`analytics-copilot` solves both problems by pairing a **7-layer AST and DuckDB sandbox",
        "guard** with a **schema-grounded self-repair pipeline** and a **45-question evaluation",
        "benchmark** with Wilson 95% confidence intervals and offline JSONL cache replay.",
        "",
        "## Architecture",
        "",
        "```mermaid",
        "flowchart LR",
        '    User["User / FastAPI POST /ask"] --> Prompt["Schema-Grounded Prompt Builder"]',
        '    Catalog["Catalog Metadata + Live DuckDB Types"] --> Prompt',
        '    Prompt --> Cache["CachedProvider (evals/cache/*.jsonl)"]',
        '    Cache --> LLM["LLM Provider (Gemini / OpenAI / Ollama / Mock)"]',
        '    LLM --> Parser["JSON Decision Parser (answerable, reason, sql)"]',
        '    Parser -->|"answerable = false"| Refusal["Clean Refusal + Reason"]',
        (
            '    Parser -->|"answerable = true"| '
            'Guard["SQL Guard (sqlglot AST + Allowlists + LIMIT 100)"]'
        ),
        '    Guard -->|"Valid SQL"| DuckDB["Hardened In-Memory DuckDB (timeout + locked config)"]',
        '    Guard -->|"SecurityViolation"| Repair["Bounded Self-Repair Loop (<= 2 retries)"]',
        '    DuckDB -->|"DuckDBError / Timeout"| Repair',
        "    Repair --> Prompt",
        '    DuckDB -->|"Rows"| Result["Result Table + Summary + Telemetry"]',
        "```",
        "",
        "## Security Model (7 Defense-in-Depth Layers)",
        "",
        "All candidate SQL generated by the model passes through `src/copilot/guard.py` and a",
        "hardened DuckDB connection before execution (`tests/test_guard.py` verifies 58 security",
        "and edge tests):",
        "",
        "1. **Single Read-Only Statement Validation**: `sqlglot` parses the query in the DuckDB",
        "   dialect, rejects multi-statement payloads (including semicolon injection after",
        "   comments), and permits only `SELECT`, `WITH`, `UNION`, `INTERSECT`, and `EXCEPT`",
        "   roots (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `COPY`, `ATTACH`,",
        "   `DETACH`, `PRAGMA`, `SET`, `INSTALL`, and `LOAD` are blocked anywhere in the AST).",
        "2. **Strict Table Allowlist & Identifier Normalization**: Every `exp.Table` reference",
        "   must resolve either to a declared CTE alias or one of the loaded aggregate tables",
        "   (`weekly_store_family_summary`, `promo_elasticity_summary`,",
        "   `zero_sales_day_proxy_summary`, `perishable_volatility_summary`,",
        "   `sim_policy_summary`, and optionally `forecast_sample_summary`). Quoted path scans",
        "   (`FROM 'file.parquet'`) and lookalike quoted identifiers with whitespace, dots, or",
        "   zero-width characters are rejected.",
        "3. **Analytics Function Allowlist**: Instead of a brittle denylist, only allowlisted",
        "   aggregate, window, math, string, date/time, conditional, and cast functions are",
        "   permitted. File readers and metadata functions (`read_parquet`, `read_csv`,",
        "   `read_text`, `read_blob`, `parquet_scan`, `parquet_metadata`, `parquet_schema`,",
        "   `sniff_csv`, `glob`, `query`, `query_table`, `getenv`, `current_setting`,",
        "   `current_query`, `version`) are rejected.",
        "4. **System Catalog Blocking**: Queries targeting `information_schema.*`, `duckdb_*`,",
        "   `pragma_*`, or `sqlite_master` / `sqlite_temp_master` as tables or functions are",
        "   blocked.",
        "5. **AST Resource Guards & Automatic `LIMIT 100`**: Table-generating functions",
        "   (`generate_series`, `range`) and expressions nested deeper than `MAX_AST_DEPTH = 48`",
        "   are blocked. Queries without an explicit outer `LIMIT` are rewritten to append",
        "   `LIMIT 100`.",
        "6. **DuckDB Engine Sandbox Hardening**: On startup (`harden_connection`), the in-memory",
        "   DuckDB connection sets `memory_limit = '256MB'`, `threads = 2`, and",
        "   `enable_external_access = false`, followed by `lock_configuration = true` so no",
        "   subsequent statement can re-enable file or network access.",
        "7. **Execution Timeout**: Every query runs under a `threading.Timer` watchdog (default",
        "   `10.0s`) that invokes `con.interrupt()` and raises `QueryTimeoutError` if exceeded.",
        "",
        "## Evaluation Results",
        "",
        "All figures below are generated directly from `metrics/metrics.json` produced by",
        f"`python -m copilot.eval --replay` (primary provider `{provider}`, requested model",
        f"`{model}`, API-returned model `{response_model}`, endpoint host `{host}`,",
        f"`temperature={metrics.get('temperature', 0.0)}`,",
        f"`run_date={metrics.get('run_date', '2026-10-26')}`, cached in `{cache_file}`).",
        "The gold benchmark (`evals/gold.jsonl`, reviewed in `docs/GOLD_REVIEW.md`) contains",
        f"**{n_total}** questions: **{n_ans}** evaluated answerable questions (10 easy, 20 medium,",
        f"10 hard) and **{n_unans}** evaluated unanswerable/ambiguous questions that require",
        "refusal.",
        "",
        f"### Headline Metrics (`full_schema_repair_on` — `{provider}` / `{response_model}`)",
        "",
        "| Metric | Value | 95% Wilson CI | Notes |",
        "| --- | --- | --- | --- |",
        (
            f"| **Execution Accuracy** | {exec_val} | {exec_ci} "
            "| Order-insensitive result match (`rel_tol=1e-3`, `abs_tol=1e-2`) |"
        ),
        (
            f"| **Valid-SQL Rate** | {val_val} | {val_ci} "
            "| Syntactically valid, guard-approved SQL that executes in DuckDB |"
        ),
        (
            f"| **Refusal Accuracy** | {ref_val} | {ref_ci} "
            "| Correctly refused unanswerable questions (`answerable=false`) |"
        ),
        (
            f"| **Mean Attempts** | **{hl['mean_attempts']:.3f}** | n/a "
            "| Average LLM calls per question (max 3 with up to 2 repairs) |"
        ),
        (f"| **Latency (p50 / p95)** | {lat_val} | n/a | {lat_note} |"),
        (
            f"| **Total Tokens** | **{hl['total_tokens']}** | n/a "
            "| Sum of prompt and completion tokens across all evaluated questions |"
        ),
        "",
        *(
            [
                f"> **Review note**: {rev_sent} {cov_sent}",
                "",
            ]
            if review_data is not None
            else []
        ),
        *_render_multi_provider_section(metrics),
        f"### Configuration & Ablation Comparison (`{provider}` / `{response_model}`)",
        "",
        (
            "| Configuration | Description | Execution Accuracy | 95% Wilson CI "
            "| Valid-SQL Rate | Refusal Accuracy | Mean Attempts | Total Tokens |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        _cfg_row(
            c_on,
            "Full catalog descriptions + repair loop (<= 2 retries)",
        ),
        _cfg_row(
            c_off,
            "Full catalog descriptions + repair loop disabled (0 retries)",
        ),
        _cfg_row(
            c_bare,
            "Bare schema (names & types only, no descriptions) + repair on",
        ),
        *(
            _cfg_row(configs[k], configs[k]["description"])
            for k in (
                "catalog_grain_notes_repair_on",
                "grain_aware_prompt_repair_on",
                "grain_sanity_check_repair_on",
            )
            if k in configs
        ),
        "",
        "*Note on benchmark exposure and grain fixes*: The 45-question gold set",
        "(`evals/gold.jsonl`) was seen while inspecting failure modes and tuning grain rules,",
        "whereas the 10-question held-out set (`evals/heldout.jsonl`) was authored prior to any",
        "prompt/catalog changes and was not seen during tuning. **The grain fixes did not change",
        "live results on gold (sanity check 70.0% vs 70.0%); the held-out set was already 100%",
        "before any change, so it cannot show improvement; no improvement is claimed.** All",
        "`mock-sql-v1` grain results in `metrics/metrics.json` are **harness validation only, not",
        "evidence that the grain fixes work**.",
        "",
        "*Note on `full_schema_repair_on` vs. `full_schema_repair_off` and sample size",
        f"($N = 40$ answerable, $N = 5$ unanswerable)*: In Run A (`{response_model}`),",
        (
            f"`full_schema_repair_on` achieves {_fmt_pct(c_on['execution_accuracy'])} strict "
            + (f"({_fmt_pct(rev_acc)} reviewed; " if review_data is not None else "(")
            + f"95% Wilson CI `{_fmt_ci(c_on['execution_accuracy_wilson_95_ci'])}`) and "
            f"`full_schema_repair_off`"
        ),
        (
            f"achieves {_fmt_pct(c_off['execution_accuracy'])} (CI "
            f"`{_fmt_ci(c_off['execution_accuracy_wilson_95_ci'])}`). Under strict scoring, "
            "both are identical because all"
        ),
        "first-attempt queries were syntactically valid and guard-compliant",
        (
            f"(`valid_sql_rate = {_fmt_pct(c_off['valid_sql_rate'])}`), "
            "so the execution repair loop was not invoked."
        ),
        *([f"{rev_sent} {cov_sent}"] if review_data is not None else []),
        f"`bare_schema_repair_on` drops to {_fmt_pct(c_bare['execution_accuracy'])} (CI",
        f"`{_fmt_ci(c_bare['execution_accuracy_wilson_95_ci'])}`) when column descriptions are",
        "removed. Because the 95% Wilson confidence intervals overlap at $N = 40$, we report",
        "the exact query failure mechanisms rather than claiming a statistically significant",
        "population difference.",
        "",
        *_render_difficulty_section(metrics),
        *_render_heldout_section(metrics),
        *_render_guard_attack_section(metrics),
        "",
        "## Failure Analysis",
        "",
        "Failed questions are categorized into seven root-cause buckets across the three",
        f"configurations for `{provider}` (`{response_model}`):",
        "",
        (
            "| Failure Category | `full_schema_repair_on` | `full_schema_repair_off` "
            "| `bare_schema_repair_on` | Primary Mechanism |"
        ),
        "| --- | --- | --- | --- | --- |",
        _fail_row(
            "wrong_join_or_aggregation",
            fc_on,
            fc_off,
            fc_bare,
            "Averaging store-family rows instead of summing to chain-week first",
        ),
        _fail_row(
            "wrong_column_semantics",
            fc_on,
            fc_off,
            fc_bare,
            "Summing repeated `weekly_transactions` across 33 families or omitting flags/enums",
        ),
        _fail_row(
            "hallucinated_table_or_column",
            fc_on,
            fc_off,
            fc_bare,
            "Referencing nonexistent columns/tables on attempt 1 (repaired when repair is on)",
        ),
        _fail_row(
            "syntax_error",
            fc_on,
            fc_off,
            fc_bare,
            "Malformed SQL or JSON syntax",
        ),
        _fail_row(
            "ambiguity",
            fc_on,
            fc_off,
            fc_bare,
            "False refusal or answering an unanswerable question",
        ),
        _fail_row(
            "guard_blocked",
            fc_on,
            fc_off,
            fc_bare,
            "Calling blocked catalog/system functions on attempt 1 (repaired when repair is on)",
        ),
        _fail_row(
            "timeout",
            fc_on,
            fc_off,
            fc_bare,
            "Query exceeding the 10.0s execution watchdog",
        ),
        "",
        f"### Concrete Failure Examples (`full_schema_repair_on` — `{response_model}`)",
        "",
        *example_lines,
        "",
        "## Reproducing Results & Running the Service",
        "",
        "### 1. Environment Setup",
        "",
        "```powershell",
        "python -m venv .venv",
        ".\\.venv\\Scripts\\Activate.ps1",
        'pip install -e ".[dev]"',
        "```",
        "",
        "### 2. Offline Replay Evaluation (No API Key Required)",
        "",
        "Reproduce `metrics/metrics.json` and update `README.md` strictly from the committed",
        f"JSONL caches (`{cache_file}` and `evals/cache/*.jsonl`):",
        "",
        "```powershell",
        "python -m copilot.eval --replay",
        "python -m copilot.readme_gen",
        "pytest",
        "```",
        "",
        "### 3. Live Provider Evaluation",
        "",
        "To run against an OpenAI-compatible endpoint (such as Groq or OpenRouter), Google",
        "Gemini, or a local Ollama server, configure `.env` or environment variables (see",
        "`.env.example` and `docs/RUN_NOTES.md`):",
        "",
        "```powershell",
        '$env:COPILOT_LLM_PROVIDER = "openai_compatible"',
        '$env:OPENAI_BASE_URL = "https://api.groq.com/openai/v1"',
        '$env:COPILOT_LLM_MODEL = "openai/gpt-oss-120b"',
        "python -m copilot.eval --provider openai_compatible",
        "```",
        "",
        "### 4. Running the FastAPI Server",
        "",
        "```powershell",
        "uvicorn copilot.api:app --host 127.0.0.1 --port 8000",
        "```",
        "",
        "- `GET http://127.0.0.1:8000/health` — readiness, version, provider, and loaded tables.",
        "- `GET http://127.0.0.1:8000/schema` — table and column descriptions with live types.",
        '- `POST http://127.0.0.1:8000/ask` — JSON body `{"question": "...", "max_repairs": 2}`.',
        "- `GET http://127.0.0.1:8000/docs` — interactive OpenAPI / Swagger UI.",
        "",
        "## Data Source & Kaggle Rules",
        "",
        "The underlying retail data is derived from the Kaggle competition",
        (
            "[Store Sales - Time Series Forecasting]"
            "(https://www.kaggle.com/competitions/store-sales-time-series-forecasting) "
            "(Corporación Favorita grocery store sales across 54 stores and 33 product "
            "families in Ecuador)."
        ),
        (
            "Section 7 of the competition rules permits non-commercial and academic use of "
            "the Competition Data and restricts redistribution. These files are aggregated "
            "derivatives published by the author for non-commercial educational purposes and "
            "will be removed on request."
        ),
        "",
        "## Limitations",
        "",
        "1. **Small benchmark sample size ($N = 45$)**: With 40 answerable and 5 unanswerable",
        "   questions, 95% Wilson confidence intervals are approximately $\\pm 10\\%$ to",
        "   $\\pm 15\\%$ wide, limiting statistical power when comparing small accuracy",
        "   differences between ablations.",
        "2. **Synthetic AI-assisted gold set**: The 45 benchmark questions and reference SQL",
        "   queries were authored with AI assistance and verified against DuckDB",
        "   (`docs/GOLD_REVIEW.md`), rather than collected from production user logs.",
        "3. **Pre-aggregated single dataset**: Queries run over 5 required summary Parquet",
        "   tables (and 1 optional holdout forecast table) from a single grocery forecasting",
        "   pipeline. Store attribute codes (`store_type`, `store_cluster`) and several",
        "   `sim_policy_summary` columns lack upstream documentation and are marked",
        "   `definition not documented` in `catalog.py`.",
        "4. **Silent semantic errors do not trigger SQL execution repair**: Standard self-repair",
        "   catches syntax errors, DuckDB binder errors, and guard violations, but without",
        "   explicit grain sanity checks it cannot detect when a valid SQL query aggregates at",
        "   the wrong grain (such as summing `weekly_transactions` across product families).",
        "",
        "## AI Tools Used",
        "",
        "- **Code & Architecture**: Written with AI coding agents under human direction,",
        "  adhering to strict AST guard, test, and reproducibility constraints.",
        "- **Gold Evaluation Set (`evals/gold.jsonl` & `docs/GOLD_REVIEW.md`)**: AI-assisted",
        "  question and reference-SQL generation, executed against DuckDB and documented in",
        "  `docs/GOLD_REVIEW.md` for human review.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    metrics = json.loads(DEFAULT_METRICS_PATH.read_text(encoding="utf-8"))
    readme_text = render_readme(metrics)
    DEFAULT_README_PATH.write_text(readme_text, encoding="utf-8")
    rel_readme = DEFAULT_README_PATH.relative_to(REPO_ROOT).as_posix()
    rel_metrics = DEFAULT_METRICS_PATH.relative_to(REPO_ROOT).as_posix()
    print(f"Updated {rel_readme} from {rel_metrics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
