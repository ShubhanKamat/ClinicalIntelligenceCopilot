from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

UI_DIR = PROJECT_ROOT / "ui"

if str(UI_DIR) not in sys.path:
    sys.path.insert(
        0,
        str(UI_DIR),
    )

from api_client import CopilotApiClient


EVALUATION_DIR = (
    PROJECT_ROOT
    / "data"
    / "results"
    / "evaluation"
    / "v3"
    / "final_holdout"
)

METRICS_PATH = (
    EVALUATION_DIR
    / "final_evaluation_metrics.json"
)

HUMAN_REVIEW_PATH = (
    EVALUATION_DIR
    / "final_human_review_frozen.csv"
)

FREEZE_METADATA_PATH = (
    EVALUATION_DIR
    / "final_freeze_metadata.json"
)

DEPLOYMENT_PATH = (
    PROJECT_ROOT
    / "deployment"
    / "v3"
    / "cloud_deployment.json"
)

MONITORING_PATH = (
    PROJECT_ROOT
    / "deployment"
    / "v3"
    / "monitoring_7f.json"
)


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title=(
        "Obesity Drug Competitive "
        "Intelligence Copilot"
    ),
    page_icon="🧬",
    layout="wide",
)


# ============================================================
# HELPERS
# ============================================================

def read_json(
    path: Path,
) -> dict[str, Any]:

    if not path.exists():
        return {}

    try:

        return json.loads(
            path.read_text(
                encoding="utf-8-sig"
            )
        )

    except Exception:
        return {}


def flatten_dict(
    data: dict[str, Any],
    prefix: str = "",
) -> dict[str, Any]:

    output = {}

    for key, value in data.items():

        name = (
            f"{prefix}.{key}"
            if prefix
            else str(key)
        )

        if isinstance(
            value,
            dict,
        ):

            output.update(
                flatten_dict(
                    value,
                    name,
                )
            )

        elif isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
            ),
        ) or value is None:

            output[name] = value

    return output


def format_route(
    route: str | None,
) -> str:

    if not route:
        return "Unknown"

    return route.replace(
        "_",
        " ",
    ).title()


def render_citations(
    citations: list[Any],
) -> None:

    if not citations:

        st.caption(
            "No citations returned."
        )
        return

    for citation in citations:

        if isinstance(
            citation,
            str,
        ):

            st.markdown(
                f"- `{citation}`"
            )

        elif isinstance(
            citation,
            dict,
        ):

            nct = (
                citation.get("nct_id")
                or citation.get("id")
                or citation.get("citation")
                or "Evidence"
            )

            st.markdown(
                f"- **{nct}**"
            )

            with st.expander(
                f"Evidence details — {nct}"
            ):

                st.json(
                    citation
                )

        else:

            st.write(
                citation
            )


def render_answer(
    payload: dict[str, Any],
) -> None:

    route = payload.get(
        "route"
    )

    latency = payload.get(
        "total_latency_ms"
    )

    citations = (
        payload.get(
            "citations"
        )
        or []
    )

    abstained = bool(
        payload.get(
            "abstained",
            False,
        )
    )

    repaired = bool(
        payload.get(
            "synthesis_repaired",
            False,
        )
    )

    citation_validity = (
        payload.get(
            "citation_validity"
        )
    )

    citation_coverage = (
        payload.get(
            "citation_coverage"
        )
    )

    columns = st.columns(5)

    columns[0].metric(
        "Route",
        format_route(route),
    )

    columns[1].metric(
        "Latency",
        (
            f"{latency:,.0f} ms"
            if isinstance(
                latency,
                (int, float),
            )
            else "—"
        ),
    )

    columns[2].metric(
        "Citations",
        len(citations),
    )

    columns[3].metric(
        "Repaired",
        "Yes" if repaired else "No",
    )

    columns[4].metric(
        "Abstained",
        "Yes" if abstained else "No",
    )

    answer = (
        payload.get("answer")
        or ""
    )

    st.subheader(
        "Answer"
    )

    if answer:

        st.markdown(
            answer
        )

    else:

        st.info(
            "No answer text returned."
        )

    findings = (
        payload.get(
            "key_findings"
        )
        or []
    )

    if findings:

        st.subheader(
            "Key findings"
        )

        for finding in findings:

            if isinstance(
                finding,
                dict,
            ):

                text = (
                    finding.get("text")
                    or ""
                )

                support_type = (
                    finding.get(
                        "support_type"
                    )
                    or "unknown"
                )

                st.markdown(
                    f"**{support_type.title()}** — "
                    f"{text}"
                )

                finding_citations = (
                    finding.get(
                        "citations"
                    )
                    or []
                )

                if finding_citations:

                    st.caption(
                        "Evidence: "
                        + ", ".join(
                            map(
                                str,
                                finding_citations,
                            )
                        )
                    )

            else:

                st.write(
                    finding
                )

    guardrail_columns = (
        st.columns(2)
    )

    guardrail_columns[0].metric(
        "Citation validity",
        (
            f"{citation_validity:.0%}"
            if isinstance(
                citation_validity,
                (int, float),
            )
            else "—"
        ),
    )

    guardrail_columns[1].metric(
        "Citation coverage",
        (
            f"{citation_coverage:.0%}"
            if isinstance(
                citation_coverage,
                (int, float),
            )
            else "—"
        ),
    )

    st.subheader(
        "Evidence citations"
    )

    render_citations(
        citations
    )

    limitations = (
        payload.get(
            "limitations"
        )
        or []
    )

    if limitations:

        with st.expander(
            "Limitations"
        ):

            for limitation in limitations:

                st.markdown(
                    f"- {limitation}"
                )

    with st.expander(
        "Structured / retrieval execution details"
    ):

        st.write(
            "**Retrieval strategy**"
        )

        st.write(
            payload.get(
                "retrieval_strategy"
            )
            or "—"
        )

        st.write(
            "**Structured result**"
        )

        structured_result = (
            payload.get(
                "structured_result"
            )
        )

        if structured_result is None:

            st.write("—")

        else:

            st.json(
                structured_result
            )


def render_evaluation_summary() -> None:

    st.header(
        "Frozen V3 evaluation evidence"
    )

    st.caption(
        "This view shows saved evaluation artifacts. "
        "It does not generate or simulate new model answers."
    )

    metrics = read_json(
        METRICS_PATH
    )

    freeze = read_json(
        FREEZE_METADATA_PATH
    )

    deployment = read_json(
        DEPLOYMENT_PATH
    )

    monitoring = read_json(
        MONITORING_PATH
    )

    if metrics:

        flat = flatten_dict(
            metrics
        )

        interesting = {}

        keywords = (
            "success",
            "route",
            "abst",
            "citation",
            "ground",
            "correct",
            "latency",
            "repair",
            "coverage",
        )

        for key, value in flat.items():

            if any(
                keyword in key.lower()
                for keyword in keywords
            ):

                interesting[key] = value

        if interesting:

            frame = pd.DataFrame(
                [
                    {
                        "Metric": key,
                        "Value": value,
                    }
                    for key, value
                    in interesting.items()
                ]
            )

            st.dataframe(
                frame,
                use_container_width=True,
                hide_index=True,
            )

        else:

            st.json(
                metrics
            )

    else:

        st.warning(
            "Frozen evaluation metrics file "
            "was not found."
        )

    if HUMAN_REVIEW_PATH.exists():

        st.subheader(
            "Frozen human review"
        )

        try:

            review = pd.read_csv(
                HUMAN_REVIEW_PATH
            )

            st.dataframe(
                review,
                use_container_width=True,
                hide_index=True,
            )

        except Exception as exc:

            st.warning(
                f"Could not load human review: {exc}"
            )

    if freeze:

        with st.expander(
            "Freeze metadata"
        ):

            st.json(
                freeze
            )

    if deployment:

        st.subheader(
            "Cloud deployment status"
        )

        deployment_fields = {
            "Serving platform":
                deployment.get(
                    "serving_platform"
                ),

            "Health validation":
                deployment.get(
                    "health_validation"
                ),

            "Bedrock runtime":
                deployment.get(
                    "bedrock_runtime_status"
                ),

            "Fargate desired count":
                deployment.get(
                    "fargate_desired_count_after_validation"
                ),
        }

        cols = st.columns(
            len(
                deployment_fields
            )
        )

        for col, (
            label,
            value,
        ) in zip(
            cols,
            deployment_fields.items(),
        ):

            col.metric(
                label,
                (
                    str(value)
                    if value is not None
                    else "—"
                ),
            )

    if monitoring:

        with st.expander(
            "Monitoring configuration"
        ):

            st.json(
                monitoring
            )


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title(
    "Obesity CI Copilot"
)

mode = st.sidebar.radio(
    "Mode",
    [
        "Live analyst copilot",
        "Frozen evaluation evidence",
    ],
)


default_api = os.getenv(
    "COPILOT_API_URL",
    "http://127.0.0.1:8000",
)

api_url = st.sidebar.text_input(
    "API base URL",
    value=default_api,
    help=(
        "Use the local FastAPI URL or "
        "the current ECS/Fargate task URL."
    ),
)


if st.sidebar.button(
    "Check API health",
    use_container_width=True,
):

    client = CopilotApiClient(
        api_url
    )

    health = client.health()

    if health.ok:

        st.sidebar.success(
            "API healthy"
        )

        if health.data:

            st.sidebar.json(
                health.data
            )

    else:

        st.sidebar.error(
            (
                f"API unavailable"
                + (
                    f" ({health.status_code})"
                    if health.status_code
                    else ""
                )
            )
        )


deployment = read_json(
    DEPLOYMENT_PATH
)

bedrock_status = (
    deployment.get(
        "bedrock_runtime_status"
    )
)


if (
    bedrock_status
    ==
    "ACCOUNT_BLOCKED_ERROR_002"
):

    st.sidebar.warning(
        "AWS Bedrock runtime is currently "
        "blocked at the account level "
        "(Error 002)."
    )


# ============================================================
# MAIN
# ============================================================

st.title(
    "Evidence-Grounded Obesity Drug "
    "Competitive Intelligence Copilot"
)

st.caption(
    "Structured clinical-trial analytics + "
    "hybrid evidence retrieval + "
    "grounded LLM synthesis"
)


if mode == "Frozen evaluation evidence":

    render_evaluation_summary()

    st.stop()


# ============================================================
# LIVE MODE
# ============================================================

st.write(
    "Ask competitive-intelligence questions "
    "across the frozen obesity clinical-trial corpus."
)


EXAMPLES = {

    "Structured":
        (
            "How many currently active "
            "direct-obesity trials does "
            "Amgen have?"
        ),

    "Comparative":
        (
            "Compare the number of "
            "Retatrutide and Zenagamtide "
            "trials."
        ),

    "Portfolio":
        (
            "Which company has the largest "
            "active direct-obesity trial "
            "portfolio?"
        ),

    "Evidence synthesis":
        (
            "What does the trial evidence "
            "suggest about how MariTide is "
            "being developed for obesity?"
        ),

    "Abstention test":
        (
            "Which obesity drug will have "
            "the highest global market share "
            "in 2030?"
        ),
}


example_cols = st.columns(
    len(EXAMPLES)
)


if "question" not in st.session_state:

    st.session_state.question = ""


for column, (
    label,
    example,
) in zip(
    example_cols,
    EXAMPLES.items(),
):

    if column.button(
        label,
        use_container_width=True,
    ):

        st.session_state.question = (
            example
        )


question = st.text_area(
    "Question",
    key="question",
    height=120,
    placeholder=(
        "Ask about company portfolios, "
        "programs, trial design, phases, "
        "activity, enrollment, or evidence."
    ),
)


submit = st.button(
    "Run analysis",
    type="primary",
    use_container_width=True,
)


if submit:

    if not question.strip():

        st.warning(
            "Enter a question first."
        )

        st.stop()

    client = CopilotApiClient(
        api_url
    )

    with st.spinner(
        "Running structured analytics, "
        "retrieval and grounded synthesis..."
    ):

        result = client.ask(
            question.strip()
        )

    if result.ok and result.data:

        render_answer(
            result.data
        )

    else:

        st.error(
            "Copilot execution failed."
        )

        if result.status_code:

            st.caption(
                f"HTTP status: "
                f"{result.status_code}"
            )

        if result.error:

            st.code(
                result.error
            )

        current_deployment = read_json(
            DEPLOYMENT_PATH
        )

        if (
            current_deployment.get(
                "bedrock_runtime_status"
            )
            ==
            "ACCOUNT_BLOCKED_ERROR_002"
        ):

            st.warning(
                "The deployed FastAPI and "
                "Fargate path has already "
                "been validated. The current "
                "failure is the external AWS "
                "Bedrock account restriction "
                "recorded during deployment "
                "validation."
            )

        st.info(
            "Use **Frozen evaluation evidence** "
            "in the sidebar to inspect the "
            "frozen holdout results without "
            "simulating a live answer."
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Decision-support prototype. "
    "Not medical advice. "
    "Cross-trial comparisons are descriptive "
    "and should not be interpreted as "
    "head-to-head efficacy claims."
)
