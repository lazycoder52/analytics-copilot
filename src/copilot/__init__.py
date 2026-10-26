"""analytics-copilot: natural-language-to-SQL assistant over grocery demand aggregates."""

__version__ = "0.1.0"

from copilot.guard import (
    DEFAULT_LIMIT,
    DEFAULT_MEMORY_LIMIT,
    DEFAULT_THREADS,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_AST_DEPTH,
    ExecutionResult,
    QueryTimeoutError,
    SecurityViolation,
    execute_guarded_sql,
    harden_connection,
    validate_and_rewrite_sql,
)
from copilot.pipeline import (
    DEFAULT_MAX_REPAIRS,
    ModelDecision,
    PipelineResult,
    ask_question,
    build_prompt,
)
from copilot.providers import (
    CachedProvider,
    GeminiProvider,
    LLMProvider,
    LLMResponse,
    MockProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderError,
    RateLimitError,
    create_provider,
)

__all__ = [
    "CachedProvider",
    "DEFAULT_LIMIT",
    "DEFAULT_MAX_REPAIRS",
    "DEFAULT_MEMORY_LIMIT",
    "DEFAULT_THREADS",
    "DEFAULT_TIMEOUT_SECONDS",
    "ExecutionResult",
    "GeminiProvider",
    "LLMProvider",
    "LLMResponse",
    "MAX_AST_DEPTH",
    "MockProvider",
    "ModelDecision",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "PipelineResult",
    "ProviderError",
    "QueryTimeoutError",
    "RateLimitError",
    "SecurityViolation",
    "ask_question",
    "build_prompt",
    "create_provider",
    "execute_guarded_sql",
    "harden_connection",
    "validate_and_rewrite_sql",
]
