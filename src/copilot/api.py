from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
)

from mangum import Mangum

from src.copilot.config import (
    settings,
)

from src.copilot.schemas import (
    AskRequest,
    AskResponse,
    HealthResponse,
)

from src.copilot.service import (
    ask,
)


logging.basicConfig(
    level=settings.log_level,
    format="%(message)s",
)

logger = logging.getLogger(
    settings.service_name
)


def log_event(
    event: str,
    **kwargs,
):

    payload = {
        "event": event,
        "service": settings.service_name,
        "version": settings.service_version,
        **kwargs,
    }

    logger.info(
        json.dumps(
            payload,
            default=str,
        )
    )


app = FastAPI(
    title=(
        "Evidence-Grounded Obesity Drug "
        "Competitive Intelligence Copilot"
    ),
    version=settings.service_version,
)


@app.middleware("http")
async def request_logging(
    request: Request,
    call_next,
):

    request_id = str(
        uuid.uuid4()
    )

    started = (
        time.perf_counter()
    )

    try:

        response = await call_next(
            request
        )

    except Exception:

        latency_ms = (
            (
                time.perf_counter()
                -
                started
            )
            *
            1000
        )

        log_event(
            "request_failed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            latency_ms=round(
                latency_ms,
                2,
            ),
        )

        raise

    latency_ms = (
        (
            time.perf_counter()
            -
            started
        )
        *
        1000
    )

    response.headers[
        "X-Request-ID"
    ] = request_id

    log_event(
        "request_completed",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=(
            response.status_code
        ),
        latency_ms=round(
            latency_ms,
            2,
        ),
    )

    return response


@app.get(
    "/health",
    response_model=HealthResponse,
)
def health():

    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.service_version,
    )


@app.post(
    "/ask",
    response_model=AskResponse,
)
def ask_endpoint(
    payload: AskRequest,
):

    try:

        result = ask(
            payload.question
        )

    except Exception as exc:

        log_event(
            "copilot_failure",
            question=payload.question,
            error_type=(
                type(exc).__name__
            ),
            error=str(exc),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Copilot execution failed."
            ),
        ) from exc

    log_event(
        "copilot_answer",

        question=payload.question,

        route=result.route,

        abstained=(
            result.abstained
        ),

        citation_count=len(
            result.citations
        ),

        citation_validity=(
            result.citation_validity
        ),

        citation_coverage=(
            result.citation_coverage
        ),

        synthesis_repaired=(
            result.synthesis_repaired
        ),

        total_latency_ms=(
            result.total_latency_ms
        ),
    )

    return result


handler = Mangum(
    app,
    lifespan="off",
)
