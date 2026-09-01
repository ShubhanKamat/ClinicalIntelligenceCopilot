from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

from src.copilot.schemas import (
    AskResponse,
    KeyFinding,
)


# ============================================================
# LAZY PIPELINE LOADING
#
# Avoid importing PyTorch / SentenceTransformers / BGE during
# Lambda cold-start. The frozen V3 pipeline loads only when an
# actual /ask request arrives.
# ============================================================

@lru_cache(maxsize=1)
def _get_pipeline_runner():

    from src.copilot.pipeline import (
        run_stage5_pipeline_v2,
    )

    return run_stage5_pipeline_v2


def _collect_citations(
    answer_object: dict[str, Any],
) -> list[str]:

    citations = []

    main_answer = (
        answer_object.get("answer")
        or {}
    )

    citations.extend(
        main_answer.get(
            "citations",
            [],
        )
        or []
    )

    for finding in (
        answer_object.get(
            "key_findings",
            [],
        )
        or []
    ):

        if isinstance(
            finding,
            dict,
        ):

            citations.extend(
                finding.get(
                    "citations",
                    [],
                )
                or []
            )

    return list(
        dict.fromkeys(
            citations
        )
    )


def ask(
    question: str,
) -> AskResponse:

    wall_start = (
        time.perf_counter()
    )

    runner = (
        _get_pipeline_runner()
    )

    result = runner(
        question
    )

    if not isinstance(
        result,
        dict,
    ):

        raise TypeError(
            "Frozen pipeline returned "
            "a non-dictionary result."
        )

    plan = (
        result.get("plan")
        or {}
    )

    execution = (
        result.get("execution")
        or {}
    )

    answer_object = (
        result.get("answer")
        or {}
    )

    main_answer = (
        answer_object.get("answer")
        or {}
    )

    grounding = (
        result.get(
            "grounding_validation"
        )
        or {}
    )

    metadata = (
        result.get("metadata")
        or {}
    )

    planner_meta = (
        metadata.get("planner")
        or {}
    )

    synthesis_meta = (
        metadata.get("synthesis")
        or {}
    )

    route = plan.get(
        "route"
    )

    if route not in {
        "structured",
        "retrieval",
        "hybrid",
        "abstain",
    }:

        raise ValueError(
            f"Unexpected route: {route!r}"
        )

    findings = []

    for finding in (
        answer_object.get(
            "key_findings",
            [],
        )
        or []
    ):

        if not isinstance(
            finding,
            dict,
        ):
            continue

        findings.append(
            KeyFinding(
                text=(
                    finding.get("text")
                    or ""
                ),
                support_type=(
                    finding.get(
                        "support_type"
                    )
                    or "unknown"
                ),
                citations=(
                    finding.get(
                        "citations"
                    )
                    or []
                ),
            )
        )

    citations = (
        _collect_citations(
            answer_object
        )
    )

    total_latency_ms = (
        metadata.get(
            "total_latency_ms"
        )
    )

    if total_latency_ms is None:

        total_latency_ms = (
            (
                time.perf_counter()
                -
                wall_start
            )
            *
            1000
        )

    return AskResponse(
        question=question,
        route=route,

        answer=(
            main_answer.get("text")
            or ""
        ),

        key_findings=findings,

        citations=citations,

        limitations=(
            answer_object.get(
                "limitations"
            )
            or []
        ),

        abstained=bool(
            execution.get(
                "abstained",
                False,
            )
            or
            route == "abstain"
        ),

        citation_validity=(
            grounding.get(
                "citation_validity"
            )
        ),

        citation_coverage=(
            grounding.get(
                "citation_coverage"
            )
        ),

        synthesis_repaired=bool(
            synthesis_meta.get(
                "repaired",
                False,
            )
        ),

        total_latency_ms=float(
            total_latency_ms
        ),

        planner_latency_ms=(
            planner_meta.get(
                "latency_ms"
            )
        ),

        synthesis_latency_ms=(
            synthesis_meta.get(
                "total_synthesis_latency_ms"
            )
        ),

        structured_result=(
            execution.get(
                "structured_result"
            )
        ),

        retrieval_strategy=(
            execution.get(
                "retrieval_strategy"
            )
        ),
    )
