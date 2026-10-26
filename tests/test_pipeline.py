"""Tests for the LLM provider abstraction, JSONL replay cache, and SQL pipeline."""

from __future__ import annotations

import pytest

from copilot.data import load_database
from copilot.pipeline import (
    ask_question,
    build_prompt,
    parse_model_decision,
)
from copilot.providers import (
    CachedProvider,
    InfrastructureError,
    MockProvider,
    ProviderError,
    RateLimitError,
    _call_with_backoff,
    create_provider,
    extract_retry_after,
    parse_duration_seconds,
    sanitize_error_text,
)


@pytest.fixture(scope="module")
def con():
    connection = load_database(harden=True)
    yield connection
    connection.close()


def test_pipeline_success_first_attempt(con):
    provider = MockProvider(
        responses=[
            {
                "answerable": True,
                "reason": "Count the rows in sim_policy_summary.",
                "sql": "SELECT COUNT(*) AS n FROM sim_policy_summary",
            }
        ]
    )
    res = ask_question("How many rows are in sim_policy_summary?", con, provider)
    assert res.status == "ok"
    assert res.answerable is True
    assert res.attempts == 1
    assert res.columns == ("n",)
    assert res.rows == ((39,),)
    assert "39" in res.answer
    assert res.sql is not None and "LIMIT 100" in res.sql.upper()
    assert res.total_tokens is not None and res.total_tokens > 0
    assert len(res.request_id) > 0


def test_pipeline_repair_then_success_on_sql_error(con):
    provider = MockProvider(
        responses=[
            {
                "answerable": True,
                "reason": "First try uses a hallucinated column name.",
                "sql": "SELECT nonexistent_column FROM sim_policy_summary",
            },
            {
                "answerable": True,
                "reason": "Fixed column name to policy.",
                "sql": "SELECT COUNT(DISTINCT policy) AS policies FROM sim_policy_summary",
            },
        ]
    )
    res = ask_question("How many distinct policies exist?", con, provider)
    assert res.status == "ok"
    assert res.attempts == 2
    assert res.rows == ((7,),)
    # Verify the second call prompt included the DuckDB Binder Error from attempt 1
    assert "nonexistent_column" in provider.calls[1][0]
    assert "ERROR ENCOUNTERED:" in provider.calls[1][0]


def test_pipeline_repair_exhausted(con):
    provider = MockProvider(
        responses=[
            {
                "answerable": True,
                "reason": "Bad column 1",
                "sql": "SELECT bad_col_1 FROM sim_policy_summary",
            },
            {
                "answerable": True,
                "reason": "Bad column 2",
                "sql": "SELECT bad_col_2 FROM sim_policy_summary",
            },
            {
                "answerable": True,
                "reason": "Bad column 3",
                "sql": "SELECT bad_col_3 FROM sim_policy_summary",
            },
        ]
    )
    res = ask_question("What is bad_col?", con, provider, max_repairs=2)
    assert res.status == "error"
    assert res.attempts == 3
    assert res.error is not None
    assert "bad_col_3" in res.error
    assert res.error_category == "hallucinated_table_or_column"


def test_pipeline_repair_off_stops_after_one_attempt(con):
    provider = MockProvider(
        responses=[
            {
                "answerable": True,
                "reason": "Bad column on attempt 1",
                "sql": "SELECT bad_col_1 FROM sim_policy_summary",
            },
            {
                "answerable": True,
                "reason": "Would succeed if repair were enabled",
                "sql": "SELECT COUNT(*) FROM sim_policy_summary",
            },
        ]
    )
    res = ask_question("Count rows", con, provider, max_repairs=0)
    assert res.status == "error"
    assert res.attempts == 1


def test_pipeline_refusal_for_unanswerable_question(con):
    provider = MockProvider(
        responses=[
            {
                "answerable": False,
                "reason": "Competitor prices are not recorded in the dataset.",
                "sql": "",
            }
        ]
    )
    res = ask_question("What were competitor prices in Quito?", con, provider)
    assert res.status == "refused"
    assert res.answerable is False
    assert res.attempts == 1
    assert res.sql is None
    assert res.rows == ()
    assert "Competitor prices" in res.answer


def test_pipeline_guard_rejection_triggers_repair_and_exhaustion(con):
    # First test guard rejection repaired on second attempt
    provider_repair = MockProvider(
        responses=[
            {
                "answerable": True,
                "reason": "Try reading secret file.",
                "sql": "SELECT * FROM read_csv('secret.csv')",
            },
            {
                "answerable": True,
                "reason": "Use allowlisted table instead.",
                "sql": "SELECT COUNT(*) AS c FROM sim_policy_summary",
            },
        ]
    )
    res_ok = ask_question("Count policy rows", con, provider_repair, max_repairs=1)
    assert res_ok.status == "ok"
    assert res_ok.attempts == 2
    assert "SecurityViolation" in provider_repair.calls[1][0]

    # Now test persistent guard rejection
    provider_fail = MockProvider(
        responses=[
            {
                "answerable": True,
                "reason": "Drop table",
                "sql": "DROP TABLE sim_policy_summary",
            }
        ]
    )
    res_blocked = ask_question("Drop table", con, provider_fail, max_repairs=0)
    assert res_blocked.status == "error"
    assert res_blocked.error_category == "guard_blocked"
    assert res_blocked.error is not None and "SecurityViolation" in res_blocked.error


def test_pipeline_malformed_model_output_repair_and_failure(con):
    recovered = (
        '```json\n{"answerable": true, "reason": "Recovered valid JSON", '
        '"sql": "SELECT COUNT(*) AS n FROM sim_policy_summary"}\n```'
    )
    provider = MockProvider(
        responses=[
            "not valid json at all {{{",
            '{"answerable": "not_a_bool"}',
            recovered,
        ]
    )
    res = ask_question("How many rows?", con, provider, max_repairs=2)
    assert res.status == "ok"
    assert res.attempts == 3
    assert res.rows == ((39,),)

    provider_bad = MockProvider(responses=["still not json"])
    res_bad = ask_question("How many rows?", con, provider_bad, max_repairs=0)
    assert res_bad.status == "error"
    assert res_bad.error_category == "malformed_output"


def test_parse_model_decision_handles_code_fences_and_surrounding_text():
    raw = 'Here is the JSON:\n```json\n{"answerable": true, "reason": "ok", "sql": "SELECT 1"}\n```'
    decision = parse_model_decision(raw)
    assert decision.answerable is True
    assert decision.sql == "SELECT 1"


def test_cached_provider_record_and_replay(tmp_path):
    inner = MockProvider(
        responses=[
            {
                "answerable": True,
                "reason": "Cached answer.",
                "sql": "SELECT 42 AS answer",
            }
        ]
    )
    cached = CachedProvider(inner, cache_dir=tmp_path, replay_only=False)
    r1 = cached.generate("What is the answer?", system_prompt="sys")
    assert r1.cached is False
    assert len(inner.calls) == 1
    assert cached.cache_path.is_file()

    # Second call with same prompt hits memory/disk cache without invoking inner provider
    r2 = cached.generate("What is the answer?", system_prompt="sys")
    assert r2.cached is True
    assert r2.text == r1.text
    assert len(inner.calls) == 1

    # Fresh instance in replay_only=True mode serves from the JSONL file on disk
    replay = CachedProvider(MockProvider(responses=[]), cache_dir=tmp_path, replay_only=True)
    r3 = replay.generate("What is the answer?", system_prompt="sys")
    assert r3.cached is True
    assert r3.text == r1.text

    # Cache miss in replay_only=True mode raises ProviderError
    with pytest.raises(ProviderError, match="Replay cache miss"):
        replay.generate("Uncached question?", system_prompt="sys")


def test_exponential_backoff_retries_on_rate_limit():
    sleeps: list[float] = []
    calls = 0

    def flaky_call():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RateLimitError("HTTP 429 rate limit")
        return ("ok", 10, 5, 15)

    text, p_tok, c_tok, t_tok = _call_with_backoff(
        flaky_call,
        max_retries=3,
        base_delay_seconds=0.5,
        sleep_fn=sleeps.append,
    )
    assert text == "ok"
    assert (p_tok, c_tok, t_tok) == (10, 5, 15)
    assert sleeps == [0.5, 1.0]


def test_build_prompt_ablation_with_and_without_descriptions(con):
    full_prompt = build_prompt("Test question", con, include_descriptions=True)
    bare_prompt = build_prompt("Test question", con, include_descriptions=False)
    assert "Monday that starts the week" in full_prompt
    assert "Monday that starts the week" not in bare_prompt
    assert "TABLE weekly_store_family_summary:" in bare_prompt
    assert "- store_nbr (TINYINT)" in bare_prompt


def test_create_provider_env_selection(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_LLM_PROVIDER", "mock")
    prov = create_provider(use_cache=True, cache_dir=tmp_path)
    assert prov.provider_name == "mock"

    with pytest.raises(ProviderError, match="Unsupported"):
        create_provider("nonexistent_provider")


def test_cached_provider_stores_metadata_fields(tmp_path):
    import json

    inner = MockProvider(
        responses=[{"answerable": True, "reason": "ok", "sql": "SELECT 1"}],
        model="mock-sql-v1",
        run_date="2026-10-26",
    )
    cached = CachedProvider(inner, cache_dir=tmp_path, replay_only=False)
    resp = cached.generate("Metadata test?", system_prompt="sys")
    assert resp.response_model == "mock-sql-v1"
    assert resp.base_url_host == "local-mock"
    assert resp.temperature == 0.0
    assert resp.run_date == "2026-10-26"

    lines = cached.cache_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["response_model"] == "mock-sql-v1"
    assert row["base_url_host"] == "local-mock"
    assert row["temperature"] == 0.0
    assert row["run_date"] == "2026-10-26"


def test_retry_after_and_secret_sanitization():
    assert parse_duration_seconds("25.5s") == 25.5
    assert parse_duration_seconds("2m30s") == 150.0
    assert parse_duration_seconds("500ms") == 0.5
    retry_sec, is_daily = extract_retry_after(
        {"Retry-After": "17"}, '{"error": {"message": "Rate limit"}}'
    )
    assert retry_sec == 17.0
    assert is_daily is False

    scrubbed = sanitize_error_text(
        "Failed with key gsk_secret12345 and Authorization: Bearer sk-abcdef123456"
    )
    assert "gsk_" not in scrubbed
    assert "sk-" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_pipeline_infrastructure_error_isolated(con):
    class FailingInfraProvider:
        provider_name = "openai_compatible"
        model_name = "test-model"

        def generate(self, prompt: str, *, system_prompt: str = ""):
            raise InfrastructureError("HTTP 503 Service Unavailable")

    res = ask_question("How many rows are in sim_policy_summary?", con, FailingInfraProvider())
    assert res.status == "infra_error"
    assert res.error_category == "infrastructure_failure"
    assert res.error is not None and "503" in res.error
