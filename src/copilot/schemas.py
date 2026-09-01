from typing import Any, Literal

from pydantic import BaseModel, Field


Route = Literal[
    "structured",
    "retrieval",
    "hybrid",
    "abstain",
]


class AskRequest(BaseModel):
    question: str = Field(
        min_length=3,
        max_length=2000,
    )


class KeyFinding(BaseModel):
    text: str
    support_type: str
    citations: list[str] = Field(
        default_factory=list
    )


class AskResponse(BaseModel):
    question: str
    route: Route

    answer: str
    key_findings: list[KeyFinding]
    citations: list[str]
    limitations: list[str]

    abstained: bool

    citation_validity: float | None = None
    citation_coverage: float | None = None

    synthesis_repaired: bool = False

    total_latency_ms: float | None = None
    planner_latency_ms: float | None = None
    synthesis_latency_ms: float | None = None

    structured_result: (
        dict[str, Any]
        | list[Any]
        | None
    ) = None

    retrieval_strategy: (
        dict[str, Any]
        | None
    ) = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
