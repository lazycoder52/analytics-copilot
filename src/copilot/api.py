"""FastAPI service exposing the guarded natural-language-to-SQL pipeline.

Endpoints:
- ``POST /ask``: Run a natural-language question through the schema-grounded LLM pipeline,
  guarded DuckDB execution, and bounded self-repair loop.
- ``GET /health``: Return service status, loaded table count, and configured LLM provider.
- ``GET /schema``: Return catalog metadata (table descriptions, column names, live DuckDB types,
  and column descriptions) for all loaded tables.

Includes:
- Pydantic request/response and uniform error models.
- Request ID propagation (``X-Request-ID``) and structured JSON request logging.
- In-memory sliding-window rate limiting per client IP.
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from copilot import __version__
from copilot.catalog import column_types, loaded_tables
from copilot.data import load_database
from copilot.pipeline import DEFAULT_MAX_REPAIRS, ask_question
from copilot.providers import LLMProvider, ProviderError, create_provider

logger = logging.getLogger(__name__)

DEFAULT_RATE_LIMIT_MAX_REQUESTS = 30
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60.0


class AskRequest(BaseModel):
    """Request body for ``POST /ask``."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Natural-language analytical question over the grocery demand tables.",
        examples=["Which 5 product families had the highest total unit sales across all weeks?"],
    )
    max_repairs: int = Field(
        default=DEFAULT_MAX_REPAIRS,
        ge=0,
        le=3,
        description="Maximum self-repair attempts on SQL or guard errors.",
    )


class AskResponse(BaseModel):
    """Response body for ``POST /ask``."""

    request_id: str
    question: str
    status: str = Field(description="Pipeline outcome: ok | refused | error")
    answerable: bool
    answer: str
    reason: str
    sql: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    attempts: int = 1
    latency_ms: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    """Response body for ``GET /health``."""

    status: str
    version: str
    provider: str
    model: str
    tables_loaded: int


class ColumnSchemaItem(BaseModel):
    """Metadata for a single column in ``GET /schema``."""

    name: str
    type: str
    description: str


class TableSchemaItem(BaseModel):
    """Metadata for a single table in ``GET /schema``."""

    name: str
    description: str
    optional: bool
    columns: list[ColumnSchemaItem]


class SchemaResponse(BaseModel):
    """Response body for ``GET /schema``."""

    tables: list[TableSchemaItem]


class ErrorDetail(BaseModel):
    """Uniform error envelope returned on 4xx/5xx responses."""

    request_id: str
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Top-level uniform error response."""

    error: ErrorDetail


class RateLimitExceededError(Exception):
    """Raised when a client exceeds the sliding-window rate limit."""

    def __init__(self, request_id: str) -> None:
        super().__init__("Rate limit exceeded. Please retry later.")
        self.request_id = request_id


class SlidingWindowRateLimiter:
    """Simple in-memory per-client sliding-window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        if self.max_requests <= 0:
            return False
        ts = now if now is not None else time.monotonic()
        cutoff = ts - self.window_seconds
        dq = self._buckets.setdefault(key, deque())
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= self.max_requests:
            return False
        dq.append(ts)
        return True


def _serialize_cell(val: Any) -> Any:
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.isoformat()[:10]
    return val


async def verify_request_and_rate_limit(request: Request, response: Response) -> str:
    """Assign `X-Request-ID`, enforce the sliding-window rate limit, and log the request."""
    req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request.state.request_id = req_id
    response.headers["X-Request-ID"] = req_id

    client_host = request.client.host if request.client else "local"
    if not request.app.state.rate_limiter.allow(client_host):
        logger.warning(
            json.dumps(
                {
                    "event": "http_rate_limited",
                    "request_id": req_id,
                    "method": request.method,
                    "path": request.url.path,
                    "client": client_host,
                },
                sort_keys=True,
            )
        )
        raise RateLimitExceededError(req_id)

    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": req_id,
                "method": request.method,
                "path": request.url.path,
            },
            sort_keys=True,
        )
    )
    return req_id


def create_app(
    *,
    con: duckdb.DuckDBPyConnection | None = None,
    provider: LLMProvider | None = None,
    data_dir: Path | str | None = None,
    rate_limit_max_requests: int = DEFAULT_RATE_LIMIT_MAX_REQUESTS,
    rate_limit_window_seconds: float = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    owns_connection = con is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if getattr(app.state, "con", None) is None:
            app.state.con = load_database(data_dir=data_dir, harden=True)
        if getattr(app.state, "provider", None) is None:
            app.state.provider = create_provider()
        if getattr(app.state, "db_lock", None) is None:
            app.state.db_lock = threading.Lock()
        try:
            yield
        finally:
            if owns_connection and getattr(app.state, "con", None) is not None:
                app.state.con.close()
                app.state.con = None

    app = FastAPI(
        title="analytics-copilot",
        description=(
            "Guarded natural-language-to-SQL assistant over grocery demand planner "
            "Parquet aggregates."
        ),
        version=__version__,
        lifespan=lifespan,
        dependencies=[Depends(verify_request_and_rate_limit)],
    )
    app.state.con = con
    app.state.provider = provider
    app.state.db_lock = threading.Lock()
    app.state.rate_limiter = SlidingWindowRateLimiter(
        max_requests=rate_limit_max_requests,
        window_seconds=rate_limit_window_seconds,
    )

    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_exception_handler(
        request: Request, exc: RateLimitExceededError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"X-Request-ID": exc.request_id},
            content={
                "error": {
                    "request_id": exc.request_id,
                    "code": "rate_limit_exceeded",
                    "message": str(exc),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        req_id = getattr(
            request.state,
            "request_id",
            request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12],
        )
        return JSONResponse(
            status_code=422,
            headers={"X-Request-ID": req_id},
            content={
                "error": {
                    "request_id": req_id,
                    "code": "validation_error",
                    "message": str(exc.errors()[0].get("msg", "Invalid request payload"))
                    if exc.errors()
                    else "Invalid request payload",
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        req_id = getattr(
            request.state,
            "request_id",
            request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12],
        )
        return JSONResponse(
            status_code=exc.status_code,
            headers={"X-Request-ID": req_id},
            content={
                "error": {
                    "request_id": req_id,
                    "code": f"http_{exc.status_code}",
                    "message": str(exc.detail),
                }
            },
        )

    @app.exception_handler(ProviderError)
    async def provider_exception_handler(request: Request, exc: ProviderError) -> JSONResponse:
        req_id = getattr(
            request.state,
            "request_id",
            request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12],
        )
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            headers={"X-Request-ID": req_id},
            content={
                "error": {
                    "request_id": req_id,
                    "code": "provider_error",
                    "message": str(exc),
                }
            },
        )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def get_health(request: Request) -> HealthResponse:
        db_con: duckdb.DuckDBPyConnection = request.app.state.con
        llm_prov: LLMProvider = request.app.state.provider
        with request.app.state.db_lock:
            tables = loaded_tables(db_con)
        return HealthResponse(
            status="ok",
            version=__version__,
            provider=llm_prov.provider_name,
            model=llm_prov.model_name,
            tables_loaded=len(tables),
        )

    @app.get("/schema", response_model=SchemaResponse, tags=["schema"])
    async def get_schema(request: Request) -> SchemaResponse:
        db_con: duckdb.DuckDBPyConnection = request.app.state.con
        with request.app.state.db_lock:
            tables = loaded_tables(db_con)
            out_tables: list[TableSchemaItem] = []
            for t in tables:
                live_types = column_types(db_con, t.name)
                cols = [
                    ColumnSchemaItem(
                        name=c.name,
                        type=live_types.get(c.name, "UNKNOWN"),
                        description=c.description,
                    )
                    for c in t.columns
                ]
                out_tables.append(
                    TableSchemaItem(
                        name=t.name,
                        description=t.description,
                        optional=t.optional,
                        columns=cols,
                    )
                )
        return SchemaResponse(tables=out_tables)

    @app.post(
        "/ask",
        response_model=AskResponse,
        responses={
            422: {"model": ErrorResponse},
            429: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
        },
        tags=["copilot"],
    )
    async def post_ask(payload: AskRequest, request: Request) -> AskResponse:
        req_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        db_con: duckdb.DuckDBPyConnection = request.app.state.con
        llm_prov: LLMProvider = request.app.state.provider

        with request.app.state.db_lock:
            result = ask_question(
                payload.question,
                db_con,
                llm_prov,
                max_repairs=payload.max_repairs,
                request_id=req_id,
            )

        if result.status == "infra_error":
            raise ProviderError(result.error or "Upstream LLM provider error")

        serialized_rows = [[_serialize_cell(c) for c in row] for row in result.rows]
        return AskResponse(
            request_id=result.request_id,
            question=result.question,
            status=result.status,
            answerable=result.answerable,
            answer=result.answer,
            reason=result.reason,
            sql=result.sql,
            columns=list(result.columns),
            rows=serialized_rows,
            row_count=result.row_count,
            attempts=result.attempts,
            latency_ms=result.latency_ms,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            error=result.error,
        )

    return app


app = create_app()
