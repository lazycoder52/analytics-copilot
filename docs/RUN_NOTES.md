# Evaluation Run Notes (`docs/RUN_NOTES.md`)

## 1. Environment & Endpoint Discovery (`2026-10-26`)

1. **Primary OpenAI-Compatible Endpoint (`api.groq.com`)**:
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
     burst errors.

2. **Secondary Free Gateway Endpoint (`text.pollinations.ai` vs `api.llm7.io`)**:
   - No `LLM7_API_KEY` was configured in `.env`.
   - Probing `POST https://api.llm7.io/v1/chat/completions` with `"model": "openai-fast"`
     returned `HTTP 400: {"error":{"message":"Model 'openai-fast' is currently unavailable.","code":"model_unavailable"}}`,
     and anonymous unauthenticated requests on `api.llm7.io` hit the shared IP daily token
     cap (`HTTP 429: Daily token quota exceeded. Retry after 85355 seconds`).
   - Probing `POST https://text.pollinations.ai/openai/chat/completions` with
     `"model": "openai-fast"` succeeded (`HTTP 200`) and returned API model
     `"model": "gpt-oss-20b"` with a rate limit of 1 request per 30 seconds per IP
     (`HTTP 402 FREE_LIMIT` with explicit `Retry after Ns` in the JSON body).
   - **Resolution**: **Live Run B** runs against `https://text.pollinations.ai/openai` with
     requested model alias `openai-fast` (API-returned `response_model="gpt-oss-20b"`,
     `base_url_host="text.pollinations.ai"`) on `full_schema_repair_on`.

3. **Local Ollama Status**:
   - Confirmed local `ollama` binary/server is not installed on the host machine.

4. **Git Author Email Note**:
   - Commit `93c9853` (`Merge pull request #8 from lazycoder52/docs/eval-status-note`) was
     created by GitHub's server-side merge API before the no-history-rewrite rule took effect.
     All subsequent PR merges are performed with local `--no-ff` merge commits pushed to
     `origin/main` so that every new commit and merge commit uses
     `214386450+lazycoder52@users.noreply.github.com` without rewriting history or
     force-pushing.
