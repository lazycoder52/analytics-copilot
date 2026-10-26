"""LLM provider abstraction, deterministic MockProvider, and JSONL record-and-replay cache.

Supported providers (configured via ``COPILOT_LLM_PROVIDER``):
- ``gemini``: Google Gemini REST API (key from ``GEMINI_API_KEY``).
- ``openai_compatible``: OpenAI-compatible chat completions API (key from ``OPENAI_API_KEY``,
  base URL from ``OPENAI_BASE_URL``).
- ``ollama``: Local Ollama server (host from ``OLLAMA_HOST``).
- ``mock``: Deterministic offline provider used for unit tests, CI, and fallback evaluation.

Every real provider call can be wrapped with ``CachedProvider`` which keys by
``(provider, model, prompt_hash)`` into ``evals/cache/<provider>_<model>.jsonl``.
Each cache entry records the API-returned ``response_model``, ``base_url_host``,
``temperature=0.0``, and ``run_date`` (ISO ``YYYY-MM-DD``).
With ``replay_only=True``, ``CachedProvider`` serves responses strictly from disk and never
contacts a network endpoint.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

PROVIDER_ENV = "COPILOT_LLM_PROVIDER"
MODEL_ENV = "COPILOT_LLM_MODEL"
CACHE_DIR_ENV = "COPILOT_CACHE_DIR"

GEMINI_KEY_ENV = "GEMINI_API_KEY"
OPENAI_KEY_ENV = "OPENAI_API_KEY"
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
LLM7_KEY_ENV = "LLM7_API_KEY"
OLLAMA_HOST_ENV = "OLLAMA_HOST"

DEFAULT_TEMPERATURE = 0.0

DEFAULT_MODELS: dict[str, str] = {
    "gemini": "gemini-3.1-flash-lite-preview",
    "openai_compatible": "gpt-4o-mini",
    "ollama": "qwen2.5-coder:7b",
    "mock": "mock-sql-v1",
}

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"gsk_[A-Za-z0-9_-]+"),
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"(?i)Authorization\s*:\s*[^\s,;\"']+"),
)

_RETRY_AFTER_RE = re.compile(
    r'(?:retry[_ -]?after["\s:=]+)(\d+(?:\.\d+)?)',
    re.IGNORECASE,
)
_DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")


def sanitize_error_text(text: str) -> str:
    """Scrub API keys or Authorization tokens from error strings before logging or raising."""
    cleaned = text or ""
    for pat in _SECRET_PATTERNS:
        cleaned = pat.sub("[REDACTED]", cleaned)
    return cleaned


def load_dotenv_file(dotenv_path: Path | str | None = None) -> dict[str, str]:
    """Load key-value pairs from `.env` into `os.environ` without overwriting existing vars.

    Never prints, logs, or echoes secret values.
    """
    path = (
        Path(dotenv_path)
        if dotenv_path is not None
        else Path(__file__).resolve().parents[2] / ".env"
    )
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        k = key.strip()
        v = val.strip().strip('"').strip("'")
        if k:
            loaded[k] = v
            if k not in os.environ:
                os.environ[k] = v
    return loaded


def parse_duration_seconds(raw: str | None) -> float | None:
    """Parse header durations like `'39'`, `'25.515s'`, `'2m52.8s'`, or `'240ms'` into seconds."""
    if not raw:
        return None
    s = raw.strip()
    try:
        return max(0.0, float(s))
    except ValueError:
        pass
    matches = list(_DURATION_PART_RE.finditer(s))
    if not matches:
        return None
    total = 0.0
    for m in matches:
        val = float(m.group(1))
        unit = m.group(2)
        if unit == "ms":
            total += val / 1000.0
        elif unit == "s":
            total += val
        elif unit == "m":
            total += val * 60.0
        elif unit == "h":
            total += val * 3600.0
    return total


def extract_retry_after(headers: Any, err_body: str) -> tuple[float | None, bool]:
    """Extract `(retry_after_seconds, is_daily_quota)` from HTTP headers and error payload."""
    retry_sec: float | None = None
    if headers is not None:
        header_val = headers.get("Retry-After") or headers.get("retry-after")
        retry_sec = parse_duration_seconds(header_val)
        if retry_sec is None:
            reset_tok = headers.get("x-ratelimit-reset-tokens")
            retry_sec = parse_duration_seconds(reset_tok)
    if retry_sec is None and err_body:
        match = _RETRY_AFTER_RE.search(err_body)
        if match:
            retry_sec = float(match.group(1))
    lower_body = (err_body or "").lower()
    is_daily = ("daily token quota" in lower_body or "tokens per day" in lower_body) and (
        retry_sec is not None and retry_sec > 300.0
    )
    return retry_sec, is_daily


class ProviderError(RuntimeError):
    """Raised when an LLM provider call fails, times out, or misses the offline replay cache."""


class InfrastructureError(ProviderError):
    """Raised on transient HTTP 5xx, network timeouts, rate limits, or unavailable models."""


class RateLimitError(InfrastructureError):
    """Raised when an LLM provider returns HTTP 429 or a rate-limit status."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        is_daily_quota: bool = False,
    ) -> None:
        super().__init__(sanitize_error_text(message))
        self.retry_after_seconds = retry_after_seconds
        self.is_daily_quota = is_daily_quota


@dataclass(frozen=True)
class LLMResponse:
    """Raw text and telemetry returned by a single LLM generation call."""

    text: str
    provider: str
    model: str
    prompt_hash: str
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached: bool = False
    response_model: str | None = None
    base_url_host: str | None = None
    temperature: float = DEFAULT_TEMPERATURE
    run_date: str | None = None


class LLMProvider(Protocol):
    """Protocol implemented by all LLM providers."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def generate(self, prompt: str, *, system_prompt: str = "") -> LLMResponse: ...


def compute_prompt_hash(prompt: str, system_prompt: str = "") -> str:
    """Compute a stable SHA-256 hex digest for a (system_prompt, prompt) pair."""
    payload = f"SYSTEM:\n{system_prompt.strip()}\n\nUSER:\n{prompt.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def default_cache_dir() -> Path:
    """Return the JSONL cache directory: $COPILOT_CACHE_DIR if set, else <repo>/evals/cache."""
    override = os.environ.get(CACHE_DIR_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "evals" / "cache"


def _sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "default"


def _extract_host(url: str, default: str = "unknown") -> str:
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc or default


def _call_with_backoff(
    fn: Callable[[], Any],
    *,
    max_retries: int = 3,
    base_delay_seconds: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_wait_seconds: float = 180.0,
) -> Any:
    """Execute an HTTP call with exponential backoff on HTTP 429 and transient 5xx/timeout errors.

    Honours `RateLimitError.retry_after_seconds` when provided by the upstream API.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except RateLimitError as err:
            if err.is_daily_quota or (
                err.retry_after_seconds is not None and err.retry_after_seconds > max_wait_seconds
            ):
                raise
            if attempt >= max_retries:
                raise
            if err.retry_after_seconds is not None and err.retry_after_seconds > 0:
                delay = round(err.retry_after_seconds + 1.5, 2)
            else:
                delay = base_delay_seconds * (2**attempt)
            logger.warning(
                "Rate limit hit; retrying in %.2fs (attempt %d/%d)",
                delay,
                attempt + 1,
                max_retries,
            )
            sleep_fn(delay)
            attempt += 1
        except ProviderError as err:
            msg = str(err)
            is_transient = any(
                token in msg
                for token in ("HTTP 5", "Network/timeout error", "timed out", "TimeoutError")
            )
            if is_transient and attempt < max_retries:
                delay = base_delay_seconds * (2**attempt)
                logger.warning("Transient infrastructure error; retrying in %.2fs", delay)
                sleep_fn(delay)
                attempt += 1
            else:
                raise


class GeminiProvider:
    """Google Gemini REST API provider with exponential backoff."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        base_delay_seconds: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        resolved_key = (
            api_key if api_key is not None else os.environ.get(GEMINI_KEY_ENV, "")
        ).strip()
        if not resolved_key:
            raise ProviderError(
                f"Missing {GEMINI_KEY_ENV} environment variable for GeminiProvider."
            )
        self._api_key = resolved_key
        self._model = (model or os.environ.get(MODEL_ENV) or DEFAULT_MODELS["gemini"]).strip()
        if self._model.startswith("models/"):
            self._model = self._model[len("models/") :]
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._base_delay = base_delay_seconds
        self._sleep_fn = sleep_fn
        self._base_url_host = "generativelanguage.googleapis.com"

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def base_url_host(self) -> str:
        return self._base_url_host

    def generate(self, prompt: str, *, system_prompt: str = "") -> LLMResponse:
        prompt_hash = compute_prompt_hash(prompt, system_prompt)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        )
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": DEFAULT_TEMPERATURE,
                "responseMimeType": "application/json",
            },
        }
        if system_prompt.strip():
            payload["systemInstruction"] = {"parts": [{"text": system_prompt.strip()}]}

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }

        def _do_request() -> tuple[str, int | None, int | None, int | None, str]:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                err_body = sanitize_error_text(err.read().decode("utf-8", errors="replace"))
                if err.code == 429:
                    retry_sec, is_daily = extract_retry_after(err.headers, err_body)
                    raise RateLimitError(
                        f"Gemini rate limit exceeded (HTTP 429): {err_body}",
                        retry_after_seconds=retry_sec,
                        is_daily_quota=is_daily,
                    ) from err
                if err.code >= 500:
                    raise InfrastructureError(
                        f"Gemini server error (HTTP {err.code}): {err_body}"
                    ) from err
                raise ProviderError(f"Gemini API error (HTTP {err.code}): {err_body}") from err
            except Exception as err:
                raise InfrastructureError(
                    f"Network/timeout error on Gemini request: {sanitize_error_text(str(err))}"
                ) from err

            candidates = data.get("candidates") or []
            if not candidates:
                raise ProviderError(f"Gemini returned no candidates: {data}")
            parts = candidates[0].get("content", {}).get("parts") or []
            text = "".join(part.get("text", "") for part in parts).strip()
            usage = data.get("usageMetadata") or {}
            resp_model = str(data.get("modelVersion") or self._model)
            return (
                text,
                usage.get("promptTokenCount"),
                usage.get("candidatesTokenCount"),
                usage.get("totalTokenCount"),
                resp_model,
            )

        start = time.perf_counter()
        text, p_tok, c_tok, t_tok, resp_model = _call_with_backoff(
            _do_request,
            max_retries=self._max_retries,
            base_delay_seconds=self._base_delay,
            sleep_fn=self._sleep_fn,
        )
        latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=self.model_name,
            prompt_hash=prompt_hash,
            latency_ms=latency_ms,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            total_tokens=t_tok,
            cached=False,
            response_model=resp_model,
            base_url_host=self._base_url_host,
            temperature=DEFAULT_TEMPERATURE,
            run_date=datetime.date.today().isoformat(),
        )


class OpenAICompatibleProvider:
    """OpenAI-compatible chat completions provider (Groq, OpenRouter, Pollinations, llm7, etc.)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 45.0,
        max_retries: int = 6,
        base_delay_seconds: float = 2.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = (
            base_url or os.environ.get(OPENAI_BASE_URL_ENV) or "https://api.openai.com/v1"
        ).rstrip("/")
        self._base_url_host = _extract_host(self._base_url, default="api.openai.com")

        resolved_key = (
            api_key if api_key is not None else os.environ.get(OPENAI_KEY_ENV, "")
        ).strip()
        if not resolved_key and self._base_url_host in ("text.pollinations.ai", "api.llm7.io"):
            resolved_key = os.environ.get(LLM7_KEY_ENV, "").strip() or "unused"
        if not resolved_key:
            raise ProviderError(
                f"Missing {OPENAI_KEY_ENV} environment variable for OpenAICompatibleProvider."
            )
        self._api_key = resolved_key
        self._model = (
            model or os.environ.get(MODEL_ENV) or DEFAULT_MODELS["openai_compatible"]
        ).strip()
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._base_delay = base_delay_seconds
        self._sleep_fn = sleep_fn

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def base_url_host(self) -> str:
        return self._base_url_host

    def generate(self, prompt: str, *, system_prompt: str = "") -> LLMResponse:
        prompt_hash = compute_prompt_hash(prompt, system_prompt)
        url = f"{self._base_url}/chat/completions"
        messages: list[dict[str, str]] = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": DEFAULT_TEMPERATURE,
            "response_format": {"type": "json_object"},
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "analytics-copilot/0.1.0",
            "Authorization": f"Bearer {self._api_key}",
        }

        def _do_request() -> tuple[str, int | None, int | None, int | None, str, float]:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            call_start = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    raw_bytes = resp.read()
                    call_ms = round((time.perf_counter() - call_start) * 1000.0, 2)
                    resp_headers = resp.headers
                    data = json.loads(raw_bytes.decode("utf-8"))
            except urllib.error.HTTPError as err:
                err_body = sanitize_error_text(err.read().decode("utf-8", errors="replace"))
                if err.code == 429 or (err.code == 402 and "FREE_LIMIT" in err_body):
                    retry_sec, is_daily = extract_retry_after(err.headers, err_body)
                    raise RateLimitError(
                        f"OpenAI rate limit exceeded (HTTP {err.code}): {err_body}",
                        retry_after_seconds=retry_sec,
                        is_daily_quota=is_daily,
                    ) from err
                if err.code >= 500:
                    raise InfrastructureError(
                        f"OpenAI server error (HTTP {err.code}): {err_body}"
                    ) from err
                lower_err = err_body.lower()
                if err.code in (400, 404) and any(
                    tok in lower_err
                    for tok in ("model_unavailable", "model_not_found", "decommissioned")
                ):
                    raise InfrastructureError(
                        f"Model unavailable on {self._base_url_host} (HTTP {err.code}): {err_body}"
                    ) from err
                raise ProviderError(f"OpenAI API error (HTTP {err.code}): {err_body}") from err
            except Exception as err:
                raise InfrastructureError(
                    f"Network/timeout error on {self._base_url_host}: "
                    f"{sanitize_error_text(str(err))}"
                ) from err

            choices = data.get("choices") or []
            if not choices:
                raise ProviderError(f"OpenAI returned no choices: {data}")
            msg_obj = choices[0].get("message") or {}
            text = (msg_obj.get("content") or "").strip()
            if not text:
                reasoning = (
                    msg_obj.get("reasoning") or msg_obj.get("reasoning_content") or ""
                ).strip()
                if "{" in reasoning and "}" in reasoning:
                    text = reasoning
            usage = data.get("usage") or {}
            resp_model = str(data.get("model") or self._model).strip()

            # Proactive token-bucket pacing when x-ratelimit-remaining-tokens is low
            if resp_headers is not None:
                rem_tok_str = resp_headers.get("x-ratelimit-remaining-tokens")
                if rem_tok_str is not None:
                    try:
                        rem_tok = int(rem_tok_str)
                        if rem_tok < 3400:
                            reset_sec = (
                                parse_duration_seconds(resp_headers.get("x-ratelimit-reset-tokens"))
                                or 20.0
                            )
                            pace_wait = min(max(reset_sec + 1.0, 2.0), 35.0)
                            self._sleep_fn(pace_wait)
                    except ValueError:
                        pass

            return (
                text,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
                resp_model,
                call_ms,
            )

        text, p_tok, c_tok, t_tok, resp_model, call_ms = _call_with_backoff(
            _do_request,
            max_retries=self._max_retries,
            base_delay_seconds=self._base_delay,
            sleep_fn=self._sleep_fn,
        )
        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=self.model_name,
            prompt_hash=prompt_hash,
            latency_ms=call_ms,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            total_tokens=t_tok,
            cached=False,
            response_model=resp_model,
            base_url_host=self._base_url_host,
            temperature=DEFAULT_TEMPERATURE,
            run_date=datetime.date.today().isoformat(),
        )


class OllamaProvider:
    """Local Ollama REST API provider."""

    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._host = (host or os.environ.get(OLLAMA_HOST_ENV) or "http://localhost:11434").rstrip(
            "/"
        )
        self._base_url_host = _extract_host(self._host, default="localhost:11434")
        self._model = (model or os.environ.get(MODEL_ENV) or DEFAULT_MODELS["ollama"]).strip()
        self._timeout = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def base_url_host(self) -> str:
        return self._base_url_host

    def generate(self, prompt: str, *, system_prompt: str = "") -> LLMResponse:
        prompt_hash = compute_prompt_hash(prompt, system_prompt)
        url = f"{self._host}/api/generate"
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "system": system_prompt.strip(),
            "format": "json",
            "stream": False,
            "options": {"temperature": DEFAULT_TEMPERATURE},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as err:
            raise InfrastructureError(
                f"Ollama request to {self._base_url_host} failed: {sanitize_error_text(str(err))}"
            ) from err

        latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
        text = (data.get("response") or "").strip()
        p_tok = data.get("prompt_eval_count")
        c_tok = data.get("eval_count")
        t_tok = (p_tok + c_tok) if (isinstance(p_tok, int) and isinstance(c_tok, int)) else None
        resp_model = str(data.get("model") or self._model).strip()
        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=self.model_name,
            prompt_hash=prompt_hash,
            latency_ms=latency_ms,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            total_tokens=t_tok,
            cached=False,
            response_model=resp_model,
            base_url_host=self._base_url_host,
            temperature=DEFAULT_TEMPERATURE,
            run_date=datetime.date.today().isoformat(),
        )


# Default built-in rules for MockProvider so unit/API tests work out of the box.
_DEFAULT_MOCK_RULES: list[tuple[str, dict[str, Any]]] = [
    (
        "how many rows are in sim_policy_summary",
        {
            "answerable": True,
            "reason": "Count all rows in sim_policy_summary.",
            "sql": "SELECT COUNT(*) AS row_count FROM sim_policy_summary",
        },
    ),
    (
        "top 5 product families by total sales",
        {
            "answerable": True,
            "reason": (
                "Aggregate weekly_store_family_summary by family and order by total sales "
                "descending."
            ),
            "sql": (
                "SELECT family, SUM(total_sales) AS total_sales "
                "FROM weekly_store_family_summary "
                "GROUP BY family ORDER BY total_sales DESC LIMIT 5"
            ),
        },
    ),
    (
        "highest empirical promo lift",
        {
            "answerable": True,
            "reason": "Order promo_elasticity_summary by empirical_promo_lift_pct descending.",
            "sql": (
                "SELECT store_nbr, family, empirical_promo_lift_pct "
                "FROM promo_elasticity_summary "
                "ORDER BY empirical_promo_lift_pct DESC LIMIT 5"
            ),
        },
    ),
    (
        "competitor price",
        {
            "answerable": False,
            "reason": "The dataset does not contain competitor pricing or store-level item prices.",
            "sql": "",
        },
    ),
    (
        "customer loyalty",
        {
            "answerable": False,
            "reason": (
                "Customer-level demographics and loyalty card data are not recorded in the "
                "aggregates."
            ),
            "sql": "",
        },
    ),
    (
        "spoilage or shrinkage",
        {
            "answerable": False,
            "reason": (
                "Physical spoilage and shrinkage are not recorded; perishable_volatility_summary "
                "only measures demand variability as a proxy."
            ),
            "sql": "",
        },
    ),
]


class MockProvider:
    """Deterministic offline LLM provider for unit tests, CI, and scripted evaluations."""

    def __init__(
        self,
        responses: list[str | dict[str, Any]] | None = None,
        handler: Callable[[str, str], str | dict[str, Any]] | None = None,
        model: str = "mock-sql-v1",
        run_date: str = "2026-10-26",
    ) -> None:
        self._responses = list(responses) if responses is not None else None
        self._handler = handler
        self._model = model
        self._run_date = run_date
        self.calls: list[tuple[str, str]] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def base_url_host(self) -> str:
        return "local-mock"

    def generate(self, prompt: str, *, system_prompt: str = "") -> LLMResponse:
        self.calls.append((prompt, system_prompt))
        prompt_hash = compute_prompt_hash(prompt, system_prompt)

        if self._responses is not None:
            if not self._responses:
                raise ProviderError("MockProvider exhausted its scripted responses.")
            item = self._responses.pop(0)
            text = item if isinstance(item, str) else json.dumps(item)
        elif self._handler is not None:
            out = self._handler(prompt, system_prompt)
            text = out if isinstance(out, str) else json.dumps(out)
        else:
            text = json.dumps(self._match_default_rule(prompt))

        p_tok = max(1, len(prompt + system_prompt) // 4)
        c_tok = max(1, len(text) // 4)
        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=self.model_name,
            prompt_hash=prompt_hash,
            latency_ms=0.5,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            total_tokens=p_tok + c_tok,
            cached=False,
            response_model=self._model,
            base_url_host="local-mock",
            temperature=DEFAULT_TEMPERATURE,
            run_date=self._run_date,
        )

    @staticmethod
    def _match_default_rule(prompt: str) -> dict[str, Any]:
        marker = "USER QUESTION:"
        idx = prompt.rfind(marker)
        question_part = prompt[idx + len(marker) :].lower() if idx != -1 else prompt.lower()

        for substring, payload in _DEFAULT_MOCK_RULES:
            if substring in question_part:
                return payload

        if any(
            word in question_part
            for word in ("weather", "temperature", "profit margin", "employee", "supplier")
        ):
            return {
                "answerable": False,
                "reason": (
                    "The requested attributes are not present in any loaded grocery aggregate "
                    "table."
                ),
                "sql": "",
            }

        return {
            "answerable": True,
            "reason": "Return summary count from weekly_store_family_summary.",
            "sql": "SELECT COUNT(*) AS total_rows FROM weekly_store_family_summary",
        }


class CachedProvider:
    """Record-and-replay wrapper around any ``LLMProvider``.

    Stores each call keyed by ``(provider, model, prompt_hash)`` in
    ``<cache_dir>/<provider>_<model>.jsonl``, persisting ``response_model``,
    ``base_url_host``, ``temperature``, and ``run_date`` on every row and flushing
    after every single call so live runs are resumable.
    """

    def __init__(
        self,
        delegate: LLMProvider,
        cache_dir: Path | str | None = None,
        *,
        replay_only: bool = False,
    ) -> None:
        self._delegate = delegate
        self._cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self._replay_only = replay_only
        self._entries: dict[str, dict[str, Any]] = {}
        self._load_existing()

    @property
    def provider_name(self) -> str:
        return self._delegate.provider_name

    @property
    def model_name(self) -> str:
        return self._delegate.model_name

    @property
    def base_url_host(self) -> str:
        delegate_host = getattr(self._delegate, "base_url_host", None)
        for rec in self._entries.values():
            host = rec.get("base_url_host")
            if isinstance(host, str) and host and host != "unknown":
                return host
        return str(delegate_host or "local-mock")

    @property
    def response_model(self) -> str:
        for rec in self._entries.values():
            rm = rec.get("response_model")
            if isinstance(rm, str) and rm:
                return rm
        return self.model_name

    @property
    def run_date(self) -> str:
        for rec in self._entries.values():
            rd = rec.get("run_date")
            if isinstance(rd, str) and rd:
                return rd
        return datetime.date.today().isoformat()

    @property
    def cache_path(self) -> Path:
        fname = (
            f"{_sanitize_filename(self.provider_name)}_{_sanitize_filename(self.model_name)}.jsonl"
        )
        return self._cache_dir / fname

    def _load_existing(self) -> None:
        path = self.cache_path
        if not path.is_file():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                record = json.loads(stripped)
                key = record.get("prompt_hash")
                if isinstance(key, str):
                    self._entries[key] = record

    def generate(self, prompt: str, *, system_prompt: str = "") -> LLMResponse:
        prompt_hash = compute_prompt_hash(prompt, system_prompt)
        cached_record = self._entries.get(prompt_hash)
        if cached_record is not None:
            model_str = str(cached_record.get("model", self.model_name))
            return LLMResponse(
                text=str(cached_record["text"]),
                provider=str(cached_record.get("provider", self.provider_name)),
                model=model_str,
                prompt_hash=prompt_hash,
                latency_ms=float(cached_record.get("latency_ms", 0.0)),
                prompt_tokens=cached_record.get("prompt_tokens"),
                completion_tokens=cached_record.get("completion_tokens"),
                total_tokens=cached_record.get("total_tokens"),
                cached=True,
                response_model=str(cached_record.get("response_model") or model_str),
                base_url_host=str(cached_record.get("base_url_host") or self.base_url_host),
                temperature=float(cached_record.get("temperature", DEFAULT_TEMPERATURE)),
                run_date=str(cached_record.get("run_date") or "2026-10-26"),
            )

        if self._replay_only:
            raise ProviderError(
                f"Replay cache miss for provider={self.provider_name!r}, "
                f"model={self.model_name!r}, prompt_hash={prompt_hash[:12]}... "
                f"in {self.cache_path.name}."
            )

        response = self._delegate.generate(prompt, system_prompt=system_prompt)
        record = {
            "provider": response.provider,
            "model": response.model,
            "response_model": response.response_model or response.model,
            "base_url_host": response.base_url_host or self.base_url_host,
            "temperature": float(response.temperature),
            "run_date": response.run_date or datetime.date.today().isoformat(),
            "prompt_hash": prompt_hash,
            "text": response.text,
            "latency_ms": response.latency_ms,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
        }
        self._entries[prompt_hash] = record
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()

        return response


def create_provider(
    provider_name: str | None = None,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    use_cache: bool = False,
    replay_only: bool = False,
    cache_dir: Path | str | None = None,
) -> LLMProvider:
    """Instantiate an LLM provider from arguments or environment variables."""
    resolved = (provider_name or os.environ.get(PROVIDER_ENV) or "mock").strip().lower()
    if resolved != "mock" and not replay_only:
        load_dotenv_file()

    if resolved == "mock":
        base: LLMProvider = MockProvider(model=model or DEFAULT_MODELS["mock"])
    elif resolved == "gemini":
        if replay_only and not (api_key or os.environ.get(GEMINI_KEY_ENV)):
            base = _ReplayStubProvider(
                provider="gemini",
                model=model or os.environ.get(MODEL_ENV) or DEFAULT_MODELS["gemini"],
                base_url_host="generativelanguage.googleapis.com",
            )
        else:
            base = GeminiProvider(api_key=api_key, model=model)
    elif resolved == "openai_compatible":
        resolved_model = (
            model or os.environ.get(MODEL_ENV) or DEFAULT_MODELS["openai_compatible"]
        ).strip()
        resolved_url = (
            base_url or os.environ.get(OPENAI_BASE_URL_ENV) or "https://api.openai.com/v1"
        ).rstrip("/")
        host = _extract_host(resolved_url, default="api.openai.com")
        if replay_only and not (api_key or os.environ.get(OPENAI_KEY_ENV)):
            base = _ReplayStubProvider(
                provider="openai_compatible",
                model=resolved_model,
                base_url_host=host,
            )
        else:
            base = OpenAICompatibleProvider(
                api_key=api_key,
                base_url=resolved_url,
                model=resolved_model,
            )
    elif resolved == "ollama":
        if replay_only:
            host_url = (os.environ.get(OLLAMA_HOST_ENV) or "http://localhost:11434").rstrip("/")
            base = _ReplayStubProvider(
                provider="ollama",
                model=model or os.environ.get(MODEL_ENV) or DEFAULT_MODELS["ollama"],
                base_url_host=_extract_host(host_url, default="localhost:11434"),
            )
        else:
            base = OllamaProvider(model=model)
    else:
        raise ProviderError(
            f"Unsupported {PROVIDER_ENV}={resolved!r}. "
            "Expected one of: gemini, openai_compatible, ollama, mock."
        )

    if use_cache or replay_only:
        if replay_only and base.provider_name != resolved:
            base = _ReplayStubProvider(
                provider=resolved,
                model=base.model_name,
                base_url_host=getattr(base, "base_url_host", "unknown"),
            )
        return CachedProvider(base, cache_dir=cache_dir, replay_only=replay_only)
    return base


class _ReplayStubProvider:
    """Stub delegate used when ``replay_only=True`` and no live API key is set."""

    def __init__(self, provider: str, model: str, base_url_host: str = "unknown") -> None:
        self._provider = provider
        self._model = model
        self._base_url_host = base_url_host

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def base_url_host(self) -> str:
        return self._base_url_host

    def generate(self, prompt: str, *, system_prompt: str = "") -> LLMResponse:
        raise ProviderError(
            f"Cannot make live calls with _ReplayStubProvider ({self._provider}/{self._model})."
        )
