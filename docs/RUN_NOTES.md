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

4. **Git Author Email Note**:
   - Commit `93c9853` (`Merge pull request #8 from lazycoder52/docs/eval-status-note`) was
     created by GitHub's server-side merge API before the local `--no-ff` merge workflow was
     adopted. All subsequent PR merges are performed with local `--no-ff` merge commits pushed
     to `origin/main` using `214386450+lazycoder52@users.noreply.github.com`, and Task 6
     performs a final `git filter-branch` check and cleanup once Tasks 1–5 are merged.
