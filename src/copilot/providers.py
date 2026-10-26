"""LLM provider abstraction, deterministic MockProvider, and JSONL record-and-replay cache.

Supported providers (configured via ``COPILOT_LLM_PROVIDER``):
- ``gemini``: Google Gemini REST API (key from ``GEMINI_API_KEY``).
- ``openai_compatible``: OpenAI-compatible chat completions API (key from ``OPENAI_API_KEY``,
  base URL from ``OPENAI_BASE_URL``).
- ``ollama``: Local Ollama server (host from ``OLLAMA_HOST``).
- ``mock``: Deterministic offline provider used for unit tests, CI, and fallback evaluation.

Every real provider call can be wrapped with ``CachedProvider`` which keys by
``(provider, model, prompt_hash)`` into ``evals/cache/<provider>_<model>.jsonl``.
With ``replay_only=True``, ``CachedProvider`` serves responses strictly from disk and never
contacts a network endpoint.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
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
OLLAMA_HOST_ENV = "OLLAMA_HOST"

DEFAULT_MODELS: dict[str, str] = {
    "gemini": "gemini-3.1-flash-lite-preview",
    "openai_compatible": "gpt-4o-mini",
    "ollama": "qwen2.5-coder:7b",
    "mock": "mock-sql-v1",
}


class ProviderError(RuntimeError):
    """Raised when an LLM provider call fails, times out, or misses the offline replay cache."""


class RateLimitError(ProviderError):
    """Raised when an LLM provider returns HTTP 429 or a rate-limit status."""


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


def _call_with_backoff(
    fn: Callable[[], tuple[str, int | None, int | None, int | None]],
    *,
    max_retries: int = 3,
    base_delay_seconds: float = 1.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[str, int | None, int | None, int | None]:
    """Execute an HTTP call with exponential backoff on HTTP 429 and transient 5xx errors."""
    attempt = 0
    while True:
        try:
            return fn()
        except RateLimitError:
            if attempt >= max_retries:
                raise
            delay = base_delay_seconds * (2**attempt)
            logger.warning(
                "Rate limit hit; retrying in %.2fs (attempt %d/%d)", delay, attempt + 1, max_retries
            )
            sleep_fn(delay)
            attempt += 1
        except ProviderError as err:
            if "HTTP 5" in str(err) and attempt < max_retries:
                delay = base_delay_seconds * (2**attempt)
                logger.warning("Transient server error; retrying in %.2fs", delay)
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

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def generate(self, prompt: str, *, system_prompt: str = "") -> LLMResponse:
        prompt_hash = compute_prompt_hash(prompt, system_prompt)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent"
        )
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
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

        def _do_request() -> tuple[str, int | None, int | None, int | None]:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                err_body = err.read().decode("utf-8", errors="replace")
                if err.code == 429:
                    raise RateLimitError(
                        f"Gemini rate limit exceeded (HTTP 429): {err_body}"
                    ) from err
                raise ProviderError(f"Gemini API error (HTTP {err.code}): {err_body}") from err
            except Exception as err:
                raise ProviderError(f"Gemini request failed: {err}") from err

            candidates = data.get("candidates") or []
            if not candidates:
                raise ProviderError(f"Gemini returned no candidates: {data}")
            parts = candidates[0].get("content", {}).get("parts") or []
            text = "".join(part.get("text", "") for part in parts).strip()
            usage = data.get("usageMetadata") or {}
            return (
                text,
                usage.get("promptTokenCount"),
                usage.get("candidatesTokenCount"),
                usage.get("totalTokenCount"),
            )

        start = time.perf_counter()
        text, p_tok, c_tok, t_tok = _call_with_backoff(
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
        )


class OpenAICompatibleProvider:
    """OpenAI-compatible chat completions provider (OpenAI, Groq, Together, vLLM, etc.)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        base_delay_seconds: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        resolved_key = (
            api_key if api_key is not None else os.environ.get(OPENAI_KEY_ENV, "")
        ).strip()
        if not resolved_key:
            raise ProviderError(
                f"Missing {OPENAI_KEY_ENV} environment variable for OpenAICompatibleProvider."
            )
        self._api_key = resolved_key
        self._base_url = (
            base_url or os.environ.get(OPENAI_BASE_URL_ENV) or "https://api.openai.com/v1"
        ).rstrip("/")
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
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        def _do_request() -> tuple[str, int | None, int | None, int | None]:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                err_body = err.read().decode("utf-8", errors="replace")
                if err.code == 429:
                    raise RateLimitError(
                        f"OpenAI rate limit exceeded (HTTP 429): {err_body}"
                    ) from err
                raise ProviderError(f"OpenAI API error (HTTP {err.code}): {err_body}") from err
            except Exception as err:
                raise ProviderError(f"OpenAI request failed: {err}") from err

            choices = data.get("choices") or []
            if not choices:
                raise ProviderError(f"OpenAI returned no choices: {data}")
            text = (choices[0].get("message", {}).get("content") or "").strip()
            usage = data.get("usage") or {}
            return (
                text,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )

        start = time.perf_counter()
        text, p_tok, c_tok, t_tok = _call_with_backoff(
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
        self._model = (model or os.environ.get(MODEL_ENV) or DEFAULT_MODELS["ollama"]).strip()
        self._timeout = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    def generate(self, prompt: str, *, system_prompt: str = "") -> LLMResponse:
        prompt_hash = compute_prompt_hash(prompt, system_prompt)
        url = f"{self._host}/api/generate"
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "system": system_prompt.strip(),
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0},
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
            raise ProviderError(f"Ollama request to {self._host} failed: {err}") from err

        latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
        text = (data.get("response") or "").strip()
        p_tok = data.get("prompt_eval_count")
        c_tok = data.get("eval_count")
        t_tok = (p_tok + c_tok) if (isinstance(p_tok, int) and isinstance(c_tok, int)) else None
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
    """Deterministic offline LLM provider for unit tests, CI, and scripted evaluations.

    Can be initialized with:
    - ``responses``: an explicit sequence of raw strings or dicts returned in order on each call
      (ideal for testing multi-attempt repair flows or malformed JSON outputs).
    - ``handler``: a custom callable ``(prompt, system_prompt) -> str | dict`` for custom routing.
    - Otherwise falls back to matching the question text against built-in deterministic rules.
    """

    def __init__(
        self,
        responses: list[str | dict[str, Any]] | None = None,
        handler: Callable[[str, str], str | dict[str, Any]] | None = None,
        model: str = "mock-sql-v1",
    ) -> None:
        self._responses = list(responses) if responses is not None else None
        self._handler = handler
        self._model = model
        self.calls: list[tuple[str, str]] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model

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
        )

    @staticmethod
    def _match_default_rule(prompt: str) -> dict[str, Any]:
        # Extract the user question section if present so few-shot examples in the prompt
        # do not accidentally trigger substring matches.
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
    ``<cache_dir>/<provider>_<model>.jsonl``.
    When ``replay_only=True``, raises ``ProviderError`` on a cache miss instead of calling the
    underlying provider.
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
            return LLMResponse(
                text=str(cached_record["text"]),
                provider=str(cached_record.get("provider", self.provider_name)),
                model=str(cached_record.get("model", self.model_name)),
                prompt_hash=prompt_hash,
                latency_ms=float(cached_record.get("latency_ms", 0.0)),
                prompt_tokens=cached_record.get("prompt_tokens"),
                completion_tokens=cached_record.get("completion_tokens"),
                total_tokens=cached_record.get("total_tokens"),
                cached=True,
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

        return response


def create_provider(
    provider_name: str | None = None,
    *,
    model: str | None = None,
    use_cache: bool = False,
    replay_only: bool = False,
    cache_dir: Path | str | None = None,
) -> LLMProvider:
    """Instantiate an LLM provider from arguments or environment variables."""
    resolved = (provider_name or os.environ.get(PROVIDER_ENV) or "mock").strip().lower()
    if resolved == "mock":
        base: LLMProvider = MockProvider(model=model or DEFAULT_MODELS["mock"])
    elif resolved == "gemini":
        if replay_only and not os.environ.get(GEMINI_KEY_ENV):
            base = MockProvider(model=model or DEFAULT_MODELS["gemini"])
        else:
            base = GeminiProvider(model=model)
    elif resolved == "openai_compatible":
        if replay_only and not os.environ.get(OPENAI_KEY_ENV):
            base = MockProvider(model=model or DEFAULT_MODELS["openai_compatible"])
        else:
            base = OpenAICompatibleProvider(model=model)
    elif resolved == "ollama":
        base = OllamaProvider(model=model)
    else:
        raise ProviderError(
            f"Unsupported {PROVIDER_ENV}={resolved!r}. "
            "Expected one of: gemini, openai_compatible, ollama, mock."
        )

    if use_cache or replay_only:
        # When replay_only is used without API keys, ensure provider_name matches requested provider
        if replay_only and base.provider_name != resolved:
            base = _ReplayStubProvider(provider=resolved, model=base.model_name)
        return CachedProvider(base, cache_dir=cache_dir, replay_only=replay_only)
    return base


class _ReplayStubProvider:
    """Stub delegate used when ``replay_only=True`` and no live API key is set."""

    def __init__(self, provider: str, model: str) -> None:
        self._provider = provider
        self._model = model

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def model_name(self) -> str:
        return self._model

    def generate(self, prompt: str, *, system_prompt: str = "") -> LLMResponse:
        raise ProviderError(
            f"Cannot make live calls with _ReplayStubProvider ({self._provider}/{self._model})."
        )
