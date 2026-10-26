"""Schema-grounded natural-language-to-SQL pipeline with bounded self-repair.

Flow:
1. Build schema-grounded prompt using ``render_catalog`` and 3 few-shot examples.
2. Call the configured ``LLMProvider`` expecting JSON
   ``{"answerable": bool, "reason": str, "sql": str}``.
3. If ``answerable`` is False, refuse cleanly with the model's reason (no SQL executed).
4. Validate and execute the candidate SQL via ``execute_guarded_sql``.
5. On a JSON parse error, ``SecurityViolation``, ``QueryTimeoutError``, or ``duckdb.Error``,
   retry up to ``max_repairs`` (default 2) times by feeding the exact error message back into a
   repair prompt.
6. Return ``PipelineResult`` with the final SQL, capped result rows, a one-sentence answer,
   telemetry (latency, attempts, tokens, request ID), and structured logging.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import duckdb

from copilot.catalog import loaded_tables, render_catalog
from copilot.guard import (
    DEFAULT_LIMIT,
    DEFAULT_TIMEOUT_SECONDS,
    ExecutionResult,
    QueryTimeoutError,
    SecurityViolation,
    execute_guarded_sql,
)
from copilot.providers import LLMProvider, ProviderError, sanitize_error_text

logger = logging.getLogger(__name__)

DEFAULT_MAX_REPAIRS = 2
MAX_DISPLAY_ROWS = 100

SYSTEM_PROMPT = (
    "You are a careful DuckDB SQL analyst for a grocery demand planning dataset. "
    "You MUST respond with a single valid JSON object matching the exact schema:\n"
    '{"answerable": boolean, "reason": string, "sql": string}\n\n'
    "Rules:\n"
    "1. Use ONLY the tables and columns listed in the database catalog.\n"
    "2. Write a single read-only DuckDB SELECT (or WITH ... SELECT) query.\n"
    "3. Respect column grain notes: for example, weekly_transactions in "
    "weekly_store_family_summary is repeated across all 33 product families per store-week, "
    "so take MAX(weekly_transactions) per (store_nbr, week_start_date) before summing.\n"
    "4. If the question asks for information not present in the catalog (such as item prices, "
    "competitor prices, physical spoilage/shrinkage, customer loyalty IDs, employee counts, "
    "or store square footage) or is too ambiguous to map to the schema, set "
    '"answerable": false, explain why in "reason", and set "sql": "".'
)

FEW_SHOT_EXAMPLES: tuple[dict[str, Any], ...] = (
    {
        "question": "Which 5 product families had the highest total unit sales across all weeks?",
        "response": {
            "answerable": True,
            "reason": (
                "Sum total_sales by family in weekly_store_family_summary and order descending."
            ),
            "sql": (
                "SELECT family, SUM(total_sales) AS total_sales "
                "FROM weekly_store_family_summary "
                "GROUP BY family "
                "ORDER BY total_sales DESC "
                "LIMIT 5"
            ),
        },
    },
    {
        "question": (
            "Among perishable product families, which store-family series has the highest "
            "coefficient of variation of demand?"
        ),
        "response": {
            "answerable": True,
            "reason": (
                "Filter perishable_volatility_summary to PERISHABLE series and order by "
                "cv_demand descending."
            ),
            "sql": (
                "SELECT store_nbr, city, family, cv_demand, mean_daily_sales "
                "FROM perishable_volatility_summary "
                "WHERE perishability_class = 'PERISHABLE' "
                "ORDER BY cv_demand DESC "
                "LIMIT 1"
            ),
        },
    },
    {
        "question": "What was the average unit retail price charged for PRODUCE in Quito stores?",
        "response": {
            "answerable": False,
            "reason": (
                "The catalog only tracks unit sales, promotions, transactions, and oil prices; "
                "unit retail prices and revenue are not recorded in any table."
            ),
            "sql": "",
        },
    },
)


@dataclass(frozen=True)
class ModelDecision:
    """Parsed JSON decision returned by the LLM."""

    answerable: bool
    reason: str
    sql: str


@dataclass(frozen=True)
class PipelineResult:
    """Structured result of running a natural-language question through the copilot pipeline."""

    request_id: str
    question: str
    status: str  # "ok" | "refused" | "error"
    answerable: bool
    answer: str
    reason: str
    sql: str | None
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    attempts: int
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    error: str | None = None
    error_category: str | None = None


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def build_prompt(
    question: str,
    con: duckdb.DuckDBPyConnection | None = None,
    *,
    include_descriptions: bool = True,
) -> str:
    """Construct the schema-grounded prompt with catalog definitions and 3 few-shot examples."""
    catalog_text = render_catalog(con, include_descriptions=include_descriptions)
    examples_lines: list[str] = []
    for idx, ex in enumerate(FEW_SHOT_EXAMPLES, start=1):
        examples_lines.append(
            f"Example {idx}:\nQuestion: {ex['question']}\nResponse: {json.dumps(ex['response'])}"
        )
    examples_block = "\n\n".join(examples_lines)
    return (
        f"DATABASE CATALOG:\n{catalog_text}\n\n"
        f"FEW-SHOT EXAMPLES:\n{examples_block}\n\n"
        f"USER QUESTION:\n{question.strip()}\n"
    )


def build_repair_prompt(
    base_prompt: str,
    previous_output: str,
    error_message: str,
    attempt_number: int,
) -> str:
    """Append the failed model output and exact error message for a self-repair attempt."""
    return (
        f"{base_prompt}\n"
        f"PREVIOUS ATTEMPT {attempt_number} OUTPUT:\n{previous_output}\n\n"
        f"ERROR ENCOUNTERED:\n{error_message}\n\n"
        "Please fix the issue and return ONLY a valid JSON object "
        '{"answerable": boolean, "reason": string, "sql": string} '
        "that satisfies all schema and guard constraints."
    )


def parse_model_decision(raw_text: str) -> ModelDecision:
    """Parse the model output into ``ModelDecision``, stripping optional markdown code fences."""
    cleaned = _CODE_FENCE_RE.sub("", (raw_text or "").strip()).strip()
    if not cleaned:
        raise ValueError("Model returned an empty response.")

    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as err:
        # Try extracting the first {...} JSON object if extra prose surrounded it
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                payload = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                raise ValueError(f"Malformed JSON output from model: {err.msg}") from err
        else:
            raise ValueError(f"Malformed JSON output from model: {err.msg}") from err

    if not isinstance(payload, dict):
        raise ValueError("Model JSON output must be an object.")
    if "answerable" not in payload or not isinstance(payload["answerable"], bool):
        raise ValueError('Model JSON must contain boolean field "answerable".')

    answerable = bool(payload["answerable"])
    reason = str(payload.get("reason") or "").strip()
    sql = str(payload.get("sql") or "").strip()

    if answerable and not sql:
        raise ValueError('Model marked question as "answerable": true but provided empty "sql".')
    if not answerable and not reason:
        reason = "The question cannot be answered from the available grocery demand tables."

    return ModelDecision(answerable=answerable, reason=reason, sql=sql)


def summarize_result(question: str, reason: str, exec_result: ExecutionResult) -> str:
    """Format a concise one-sentence natural-language summary of the query result."""
    if exec_result.row_count == 0:
        return "The query executed successfully and returned 0 matching rows."
    if exec_result.row_count == 1 and len(exec_result.columns) == 1:
        col = exec_result.columns[0]
        val = exec_result.rows[0][0]
        return f"The result for {col} is {val}."
    if exec_result.row_count == 1:
        pairs = ", ".join(
            f"{col}={val}"
            for col, val in zip(exec_result.columns, exec_result.rows[0], strict=False)
        )
        return f"Returned 1 row ({pairs})."
    first_pairs = ", ".join(
        f"{col}={val}"
        for col, val in zip(exec_result.columns[:3], exec_result.rows[0][:3], strict=False)
    )
    suffix = f" ({reason.rstrip('.')})" if reason else ""
    return f"Returned {exec_result.row_count} rows; top row has {first_pairs}{suffix}."


def _accumulate_tokens(current: int | None, addition: int | None) -> int | None:
    if addition is None:
        return current
    return (current or 0) + addition


def ask_question(
    question: str,
    con: duckdb.DuckDBPyConnection,
    provider: LLMProvider,
    *,
    max_repairs: int = DEFAULT_MAX_REPAIRS,
    include_descriptions: bool = True,
    allowlisted_tables: Sequence[str] | set[str] | None = None,
    default_limit: int = DEFAULT_LIMIT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    request_id: str | None = None,
) -> PipelineResult:
    """Run the natural-language-to-SQL pipeline with up to ``max_repairs`` self-repair attempts."""
    req_id = request_id or uuid.uuid4().hex[:12]
    start_time = time.perf_counter()

    if allowlisted_tables is None:
        allowed = {t.name for t in loaded_tables(con)}
    else:
        allowed = {t.lower() for t in allowlisted_tables}

    base_prompt = build_prompt(question, con, include_descriptions=include_descriptions)
    current_prompt = base_prompt

    max_attempts = max(1, 1 + max_repairs)
    attempts = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    llm_latency_ms: float = 0.0

    last_error: str | None = None
    last_error_category: str | None = None
    last_sql: str | None = None
    last_reason: str = ""

    for attempt_idx in range(1, max_attempts + 1):
        attempts = attempt_idx
        try:
            llm_resp = provider.generate(current_prompt, system_prompt=SYSTEM_PROMPT)
        except ProviderError as err:
            infra_msg = sanitize_error_text(str(err))
            wall_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            eff_ms = round(llm_latency_ms, 2) if llm_latency_ms > 0 else wall_ms
            _log_infrastructure_failure(req_id, provider, attempts, infra_msg)
            return PipelineResult(
                request_id=req_id,
                question=question,
                status="infra_error",
                answerable=True,
                answer=f"Infrastructure error on attempt {attempts}: {infra_msg}",
                reason=last_reason,
                sql=last_sql,
                columns=(),
                rows=(),
                row_count=0,
                attempts=attempts,
                latency_ms=eff_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                error=infra_msg,
                error_category="infrastructure_failure",
            )

        llm_latency_ms += llm_resp.latency_ms
        prompt_tokens = _accumulate_tokens(prompt_tokens, llm_resp.prompt_tokens)
        completion_tokens = _accumulate_tokens(completion_tokens, llm_resp.completion_tokens)
        total_tokens = _accumulate_tokens(total_tokens, llm_resp.total_tokens)

        try:
            decision = parse_model_decision(llm_resp.text)
        except ValueError as err:
            last_error = str(err)
            last_error_category = "malformed_output"
            if attempt_idx < max_attempts:
                current_prompt = build_repair_prompt(
                    base_prompt, llm_resp.text, last_error, attempt_idx
                )
                continue
            break

        last_reason = decision.reason
        if not decision.answerable:
            wall_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            latency_ms = round(llm_latency_ms, 2) if llm_latency_ms > 0 else wall_ms
            result = PipelineResult(
                request_id=req_id,
                question=question,
                status="refused",
                answerable=False,
                answer=f"Cannot answer from available data: {decision.reason}",
                reason=decision.reason,
                sql=None,
                columns=(),
                rows=(),
                row_count=0,
                attempts=attempts,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
            _log_call(result, provider)
            return result

        last_sql = decision.sql
        try:
            exec_res = execute_guarded_sql(
                con,
                decision.sql,
                allowlisted_tables=allowed,
                default_limit=default_limit,
                timeout_seconds=timeout_seconds,
            )
        except SecurityViolation as err:
            last_error = f"SecurityViolation: {err}"
            last_error_category = "guard_blocked"
            if attempt_idx < max_attempts:
                current_prompt = build_repair_prompt(
                    base_prompt, llm_resp.text, last_error, attempt_idx
                )
                continue
            break
        except QueryTimeoutError as err:
            last_error = f"QueryTimeoutError: {err}"
            last_error_category = "timeout"
            if attempt_idx < max_attempts:
                current_prompt = build_repair_prompt(
                    base_prompt, llm_resp.text, last_error, attempt_idx
                )
                continue
            break
        except duckdb.Error as err:
            last_error = f"DuckDBError: {err}"
            last_error_category = _classify_duckdb_error(str(err))
            if attempt_idx < max_attempts:
                current_prompt = build_repair_prompt(
                    base_prompt, llm_resp.text, last_error, attempt_idx
                )
                continue
            break

        capped_rows = exec_res.rows[:MAX_DISPLAY_ROWS]
        answer_text = summarize_result(question, decision.reason, exec_res)
        wall_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        latency_ms = round(llm_latency_ms, 2) if llm_latency_ms > 0 else wall_ms
        result = PipelineResult(
            request_id=req_id,
            question=question,
            status="ok",
            answerable=True,
            answer=answer_text,
            reason=decision.reason,
            sql=exec_res.sql,
            columns=exec_res.columns,
            rows=capped_rows,
            row_count=len(capped_rows),
            attempts=attempts,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        _log_call(result, provider)
        return result

    wall_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    latency_ms = round(llm_latency_ms, 2) if llm_latency_ms > 0 else wall_ms
    error_msg = last_error or "Unknown pipeline failure"
    result = PipelineResult(
        request_id=req_id,
        question=question,
        status="error",
        answerable=True,
        answer=f"Failed to execute a valid query after {attempts} attempt(s): {error_msg}",
        reason=last_reason,
        sql=last_sql,
        columns=(),
        rows=(),
        row_count=0,
        attempts=attempts,
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        error=error_msg,
        error_category=last_error_category,
    )
    _log_call(result, provider)
    return result


def _classify_duckdb_error(message: str) -> str:
    lowered = message.lower()
    if "binder error" in lowered or "column" in lowered or "table" in lowered:
        return "hallucinated_table_or_column"
    if "syntax error" in lowered or "parser error" in lowered:
        return "syntax_error"
    return "sql_execution_error"


def _log_infrastructure_failure(
    request_id: str,
    provider: LLMProvider,
    attempts: int,
    error_message: str,
) -> None:
    logger.warning(
        json.dumps(
            {
                "event": "copilot_infrastructure_failure",
                "request_id": request_id,
                "provider": provider.provider_name,
                "model": provider.model_name,
                "attempts": attempts,
                "error": sanitize_error_text(error_message),
            },
            sort_keys=True,
        )
    )


def _log_call(result: PipelineResult, provider: LLMProvider) -> None:
    logger.info(
        json.dumps(
            {
                "event": "copilot_pipeline_call",
                "request_id": result.request_id,
                "provider": provider.provider_name,
                "model": provider.model_name,
                "status": result.status,
                "answerable": result.answerable,
                "attempts": result.attempts,
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.total_tokens,
                "error_category": result.error_category,
            },
            sort_keys=True,
        )
    )
