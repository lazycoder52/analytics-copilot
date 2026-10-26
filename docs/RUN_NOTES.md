# Evaluation Run Notes (`docs/RUN_NOTES.md`)

## 1. Environment & Endpoint Discovery (`2026-10-26`)

1. **Primary OpenAI-Compatible Endpoint — Live Run A (`api.groq.com`, `openai/gpt-oss-120b`)**:
   - `.env` initially specified `OPENAI_BASE_URL=https://api.groq.com/openai/v1` and
     `COPILOT_LLM_MODEL=llama-3.3-70b-versatile`.
   - A probe to `POST https://api.groq.com/openai/v1/chat/completions` returned:
     `HTTP 404: {"error":{"message":"The model llama-3.3-70b-versatile does not exist or you do not have access to it.","type":"invalid_request_error","code":"model_not_found"}}`.
   - Querying `GET https://api.groq.com/openai/v1/models` returned the active models on the
     account: `openai/gpt-oss-120b` (`131,072` context window), `openai/gpt-oss-20b`
     (`131,072` context window), `qwen/qwen3.8-27b` (`131,072` context window), and
     `allam-2-7b` (`4,096` context window).
   - **Resolution**: Updated `COPILOT_LLM_MODEL` in `.env` to `openai/gpt-oss-120b` for
     **Live Run A** (`base_url_host="api.groq.com"`, rate limit `8,000` tokens/minute and
     `1,000` requests/day). Proactive rate-limit pacing in `OpenAICompatibleProvider` inspects
     `x-ratelimit-remaining-tokens` and `x-ratelimit-reset-tokens` headers to avoid HTTP 429
     burst errors. Live Run A completed **45/45** questions across all 3 configurations
     (`full_schema_repair_on`, `full_schema_repair_off`, `bare_schema_repair_on`) with 0
     unresolved questions and 0 infrastructure failures.

2. **Secondary Endpoint — Live Run B (`api.groq.com`, `openai/gpt-oss-20b`) & Abandoned Free Gateways**:
   - Probing `POST https://api.llm7.io/v1/chat/completions` with `"model": "openai-fast"`
     returned `HTTP 400: {"error":{"message":"Model 'openai-fast' is currently unavailable.","code":"model_unavailable"}}`,
     and anonymous unauthenticated requests on `api.llm7.io` hit the shared IP daily token
     cap (`HTTP 429: Daily token quota exceeded. Retry after 85355 seconds`).
   - Probing `POST https://text.pollinations.ai/openai/chat/completions` with
     `"model": "openai-fast"` returned API model `"model": "gpt-oss-20b"`, but enforced a
     strict 1 request per 30 seconds per IP rate limit (`HTTP 402 FREE_LIMIT`). After
     completing 31/45 questions on `text.pollinations.ai`, the partial Pollinations cache was
     discarded and abandoned due to the 1 req/30s bottleneck.
   - **Resolution**: Switched **Live Run B** to the second active model on Groq
     (`openai/gpt-oss-20b` on `https://api.groq.com/openai/v1`), running
     `full_schema_repair_on` and `bare_schema_repair_on` across all 45 questions with
     resumable caching (`evals/cache/openai_compatible_openai_gpt-oss-20b.jsonl`).
     `full_schema_repair_on` completed **45/45** questions (`30/40 = 75.0%` execution accuracy,
     `5/5 = 100.0%` refusal accuracy). `bare_schema_repair_on` completed **42/45** questions
     (`40/40` answerable questions evaluated with `29/40 = 72.5%` execution accuracy, `2/2 = 100.0%`
     refusal accuracy; the final 3 refusal questions `refuse_03`–`refuse_05` hit Groq's 200,000
     tokens-per-day quota cap for `openai/gpt-oss-20b` and are recorded in `infrastructure_failures`
     and excluded from accuracy denominators).

3. **Local Ollama Status**:
   - Confirmed local `ollama` binary/server is not installed on the host machine.

4. **Held-Out Set & Grain Ablation Quota Notes (Tasks 2 & 3)**:
   - Authored `evals/heldout.jsonl` (10 answerable questions: 4 `medium`, 6 `hard`, marked
     `"review_status": "needs human review"` and listed in `docs/GOLD_REVIEW.md`) before making
     any changes to `catalog.py`, `pipeline.py`, or `guard.py`.
   - Baseline evaluation of `evals/heldout.jsonl` on Run A (`openai/gpt-oss-120b`) completed
     **10/10** questions across `full_schema_repair_on` (`10/10 = 100.0%`),
     `full_schema_repair_off` (`10/10 = 100.0%`), and `bare_schema_repair_on`
     (`7/10 = 70.0%`, failing `holdout_med_03`, `holdout_hard_04` due to summing
     `non_transferred_holidays` across stores, and `holdout_hard_05` due to joining
     `weekly_store_family_summary` directly to `zero_sales_day_proxy_summary` without
     pre-aggregating weekly rows).
   - In Task 3 (`feat/grain-checks-and-ablation`), added explicit `grain_note` metadata to
     `src/copilot/catalog.py`, `GRAIN_AWARE_INSTRUCTIONS` in `src/copilot/pipeline.py`, and
     AST-level `GrainSanityViolation` checking in `src/copilot/guard.py` (`grain_sanity_check_repair_on`,
     `catalog_grain_notes_repair_on`, and `grain_aware_prompt_repair_on`).
   - `grain_sanity_check_repair_on` completed **45/45** on `evals/gold.jsonl` (`28/40 = 70.0%` on
     `openai/gpt-oss-120b`; `38/40 = 95.0%` on `MockProvider` where `hard_01` is caught by
     `GrainSanityViolation` and repaired on attempt 2) and **10/10** on `evals/heldout.jsonl`
     (`10/10 = 100.0%`).
   - `catalog_grain_notes_repair_on` completed **10/10** (`10/10 = 100.0%`) on `evals/heldout.jsonl`
     with `openai/gpt-oss-120b` before `openai/gpt-oss-120b` reached Groq's 200,000 tokens-per-day
     (TPD) quota (`Limit 200,000` after 121 cumulative cached calls across the 45-question gold
     set and 10-question held-out set). Remaining uncached calls for `catalog_grain_notes_repair_on`
     and `grain_aware_prompt_repair_on` on `openai/gpt-oss-120b` are recorded in
     `infrastructure_failures` and excluded from accuracy denominators, while all 6 configurations
     are evaluated 45/45 on gold and 10/10 on held-out in the deterministic harness validation run
     (`mock-sql-v1`).

5. **Guard Attack-Suite & Docker CI (Tasks 4 & 5)**:
   - Added deterministic SQL guard attack-suite evaluation (`evaluate_guard_attack_suite()` in
     `src/copilot/eval.py`) covering **56/56 (`100.0%`)** blocked adversarial SQL vectors across
     6 categories (`ddl_and_dml`: `9/9`, `admin_and_extensions`: `5/5`,
     `file_and_function_allowlist`: `17/17`, `system_catalogs_and_unallowlisted_tables`: `14/14`,
     `multi_statement_and_syntax`: `5/5`, `resource_and_identifier_spoofing`: `6/6`) in
     `metrics/metrics.json` and `README.md`.
   - Added `.dockerignore`, `Dockerfile` (non-root `appuser`, no secrets in image, default
     `COPILOT_LLM_PROVIDER=mock`), and a `docker` job in `.github/workflows/ci.yml` that builds
     the image, starts the container, and verifies `GET /health` returns `"status":"ok"` and
     `"tables_loaded":11`.

6. **Git Author Email & History Verification (Task 6)**:
   - Commit `93c9853` (`Merge pull request #8 from lazycoder52/docs/eval-status-note`) was
     created by GitHub's server-side merge API before the local `--no-ff` merge workflow was
     adopted. All subsequent PR merges (`#9`–`#14`) were performed with local `--no-ff` merge
     commits using `214386450+lazycoder52@users.noreply.github.com`, followed by Task 6's
     `git filter-branch` rewrite across `--all` (backed up to local tag `pre-rewrite` before
     removing `refs/original/*` and `pre-rewrite` so `git log --all --format=%ae | sort -u`
     outputs exclusively `214386450+lazycoder52@users.noreply.github.com`).
