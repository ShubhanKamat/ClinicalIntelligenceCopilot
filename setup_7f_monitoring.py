import json
from pathlib import Path

import boto3


# ============================================================
# CONFIG
# ============================================================

REGION = "us-east-1"

LOG_GROUP = "/ecs/obesity-ci-copilot-v3"

CLUSTER = "obesity-ci-copilot-v3"
SERVICE = "obesity-ci-copilot-v3"

NAMESPACE = "ObesityCICopilot/V3"

DASHBOARD_NAME = "obesity-ci-copilot-v3"

DEPLOYMENT_DIR = Path(
    r"C:\Users\shubh\Desktop\Projects\Copilot\deployment\v3"
)

DEPLOYMENT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DASHBOARD_PATH = (
    DEPLOYMENT_DIR
    / "cloudwatch_dashboard_7f.json"
)

MONITORING_PATH = (
    DEPLOYMENT_DIR
    / "monitoring_7f.json"
)


# ============================================================
# CLIENTS
# ============================================================

sts = boto3.client(
    "sts",
    region_name=REGION,
)

logs = boto3.client(
    "logs",
    region_name=REGION,
)

cloudwatch = boto3.client(
    "cloudwatch",
    region_name=REGION,
)

ecs = boto3.client(
    "ecs",
    region_name=REGION,
)

s3 = boto3.client(
    "s3",
    region_name=REGION,
)


ACCOUNT_ID = (
    sts.get_caller_identity()[
        "Account"
    ]
)

BUCKET = (
    f"obesity-ci-copilot-"
    f"{ACCOUNT_ID}-"
    f"{REGION}"
).lower()


def section(title: str):

    print()
    print("=" * 90)
    print(title)
    print("=" * 90)


# ============================================================
# 1. VERIFY LOG GROUP + SET RETENTION
# ============================================================

section(
    "7F — CLOUDWATCH MONITORING"
)


groups = logs.describe_log_groups(
    logGroupNamePrefix=LOG_GROUP,
).get(
    "logGroups",
    [],
)


exact_group = [
    group
    for group in groups
    if group[
        "logGroupName"
    ] == LOG_GROUP
]


if not exact_group:

    raise RuntimeError(
        f"Log group not found: "
        f"{LOG_GROUP}"
    )


logs.put_retention_policy(
    logGroupName=LOG_GROUP,
    retentionInDays=7,
)


print(
    "Log group:",
    LOG_GROUP,
)

print(
    "Retention:",
    "7 days",
)


# ============================================================
# 2. DEFINE METRIC FILTERS
# ============================================================

section(
    "DEFINE + VALIDATE METRIC FILTERS"
)


FILTERS = [

    {
        "filter_name":
            "obesity-ci-v3-request-count",

        "pattern":
            '{ $.event = "request_completed" }',

        "metric_name":
            "RequestCount",

        "metric_value":
            "1",

        "unit":
            "Count",
    },

    {
        "filter_name":
            "obesity-ci-v3-api-5xx",

        "pattern":
            (
                '{ $.event = "request_completed" '
                '&& $.status_code >= 500 }'
            ),

        "metric_name":
            "Api5xxCount",

        "metric_value":
            "1",

        "unit":
            "Count",
    },

    {
        "filter_name":
            "obesity-ci-v3-request-latency",

        "pattern":
            (
                '{ $.event = "request_completed" '
                '&& $.latency_ms = * }'
            ),

        "metric_name":
            "RequestLatencyMs",

        "metric_value":
            "$.latency_ms",

        "unit":
            "Milliseconds",
    },

    {
        "filter_name":
            "obesity-ci-v3-copilot-failure",

        "pattern":
            '{ $.event = "copilot_failure" }',

        "metric_name":
            "CopilotFailureCount",

        "metric_value":
            "1",

        "unit":
            "Count",
    },

    {
        "filter_name":
            "obesity-ci-v3-copilot-answer",

        "pattern":
            '{ $.event = "copilot_answer" }',

        "metric_name":
            "CopilotAnswerCount",

        "metric_value":
            "1",

        "unit":
            "Count",
    },

    {
        "filter_name":
            "obesity-ci-v3-route",

        "pattern":
            (
                '{ $.event = "copilot_answer" '
                '&& $.route = * }'
            ),

        "metric_name":
            "RouteCount",

        "metric_value":
            "1",

        "unit":
            "Count",

        "dimensions": {
            "Route":
                "$.route"
        },
    },

    {
        "filter_name":
            "obesity-ci-v3-repair",

        "pattern":
            (
                '{ $.event = "copilot_answer" '
                '&& $.repaired = true }'
            ),

        "metric_name":
            "SynthesisRepairCount",

        "metric_value":
            "1",

        "unit":
            "Count",
    },

    {
        "filter_name":
            "obesity-ci-v3-abstention",

        "pattern":
            (
                '{ $.event = "copilot_answer" '
                '&& $.route = "abstain" }'
            ),

        "metric_name":
            "AbstentionCount",

        "metric_value":
            "1",

        "unit":
            "Count",
    },

    {
        "filter_name":
            "obesity-ci-v3-citation-validity-failure",

        "pattern":
            (
                '{ $.event = "copilot_answer" '
                '&& $.citation_validity < 1 }'
            ),

        "metric_name":
            "CitationValidityFailureCount",

        "metric_value":
            "1",

        "unit":
            "Count",
    },

    {
        "filter_name":
            "obesity-ci-v3-citation-coverage-failure",

        "pattern":
            (
                '{ $.event = "copilot_answer" '
                '&& $.citation_coverage < 1 }'
            ),

        "metric_name":
            "CitationCoverageFailureCount",

        "metric_value":
            "1",

        "unit":
            "Count",
    },
]


# ============================================================
# TEST EVENTS
#
# Metric filters are prospective — they do not backfill old
# log events. We validate the patterns independently here.
# ============================================================

TEST_EVENTS = [

    json.dumps(
        {
            "event":
                "request_completed",

            "status_code":
                200,

            "latency_ms":
                123.4,
        }
    ),

    json.dumps(
        {
            "event":
                "request_completed",

            "status_code":
                500,

            "latency_ms":
                8398.03,
        }
    ),

    json.dumps(
        {
            "event":
                "copilot_failure",

            "error_type":
                "ValidationException",
        }
    ),

    json.dumps(
        {
            "event":
                "copilot_answer",

            "route":
                "structured",

            "repaired":
                False,

            "citation_validity":
                1.0,

            "citation_coverage":
                1.0,
        }
    ),

    json.dumps(
        {
            "event":
                "copilot_answer",

            "route":
                "abstain",

            "repaired":
                True,

            "citation_validity":
                0.5,

            "citation_coverage":
                0.8,
        }
    ),
]


validation_results = []


for config in FILTERS:

    result = logs.test_metric_filter(
        filterPattern=
            config[
                "pattern"
            ],

        logEventMessages=
            TEST_EVENTS,
    )


    matches = result.get(
        "matches",
        [],
    )


    validation_results.append(
        {
            "filter_name":
                config[
                    "filter_name"
                ],

            "pattern":
                config[
                    "pattern"
                ],

            "test_matches":
                len(matches),
        }
    )


    print(
        f"{config['filter_name']:<48}"
        f"matches={len(matches)}"
    )


# ============================================================
# 3. CREATE METRIC FILTERS
# ============================================================

section(
    "CREATE CLOUDWATCH METRIC FILTERS"
)


for config in FILTERS:

    transformation = {

        "metricName":
            config[
                "metric_name"
            ],

        "metricNamespace":
            NAMESPACE,

        "metricValue":
            config[
                "metric_value"
            ],

        "unit":
            config[
                "unit"
            ],
    }


    if config.get(
        "dimensions"
    ):

        transformation[
            "dimensions"
        ] = config[
            "dimensions"
        ]


    logs.put_metric_filter(

        logGroupName=
            LOG_GROUP,

        filterName=
            config[
                "filter_name"
            ],

        filterPattern=
            config[
                "pattern"
            ],

        metricTransformations=[
            transformation
        ],
    )


    print(
        "Created:",
        config[
            "filter_name"
        ],
    )


# ============================================================
# 4. VERIFY METRIC FILTERS
# ============================================================

registered_filters = (
    logs.describe_metric_filters(
        logGroupName=LOG_GROUP,
        filterNamePrefix=
            "obesity-ci-v3-",
    )
    .get(
        "metricFilters",
        [],
    )
)


print()
print(
    "Registered filters:",
    len(
        registered_filters
    ),
)


if (
    len(
        registered_filters
    )
    <
    len(
        FILTERS
    )
):

    raise RuntimeError(
        "Not all 7F metric filters "
        "were registered."
    )


# ============================================================
# 5. CREATE CLOUDWATCH ALARMS
# ============================================================

section(
    "CREATE CLOUDWATCH ALARMS"
)


ALARMS = []


def custom_alarm(
    *,
    name,
    description,
    metric,
    threshold,
    statistic="Sum",
    period=300,
    evaluation_periods=1,
):

    cloudwatch.put_metric_alarm(

        AlarmName=
            name,

        AlarmDescription=
            description,

        Namespace=
            NAMESPACE,

        MetricName=
            metric,

        Statistic=
            statistic,

        Period=
            period,

        EvaluationPeriods=
            evaluation_periods,

        DatapointsToAlarm=
            1,

        Threshold=
            threshold,

        ComparisonOperator=
            "GreaterThanOrEqualToThreshold",

        TreatMissingData=
            "notBreaching",
    )


    ALARMS.append(
        name
    )


custom_alarm(

    name=
        "obesity-ci-v3-api-5xx",

    description=
        (
            "Obesity CI Copilot "
            "returned one or more "
            "HTTP 5xx responses."
        ),

    metric=
        "Api5xxCount",

    threshold=
        1,
)


custom_alarm(

    name=
        "obesity-ci-v3-copilot-failure",

    description=
        (
            "Copilot pipeline logged "
            "an execution failure."
        ),

    metric=
        "CopilotFailureCount",

    threshold=
        1,
)


# ------------------------------------------------------------
# p95 LATENCY ALARM
# ------------------------------------------------------------

cloudwatch.put_metric_alarm(

    AlarmName=
        "obesity-ci-v3-high-latency",

    AlarmDescription=
        (
            "Copilot request p95 "
            "latency exceeded 15 seconds."
        ),

    Namespace=
        NAMESPACE,

    MetricName=
        "RequestLatencyMs",

    ExtendedStatistic=
        "p95",

    Period=
        300,

    EvaluationPeriods=
        1,

    DatapointsToAlarm=
        1,

    Threshold=
        15000,

    ComparisonOperator=
        "GreaterThanThreshold",

    TreatMissingData=
        "notBreaching",
)

ALARMS.append(
    "obesity-ci-v3-high-latency"
)


# ------------------------------------------------------------
# ECS CPU
# ------------------------------------------------------------

cloudwatch.put_metric_alarm(

    AlarmName=
        "obesity-ci-v3-ecs-high-cpu",

    AlarmDescription=
        (
            "Fargate service average CPU "
            "exceeded 85%."
        ),

    Namespace=
        "AWS/ECS",

    MetricName=
        "CPUUtilization",

    Dimensions=[
        {
            "Name":
                "ClusterName",

            "Value":
                CLUSTER,
        },
        {
            "Name":
                "ServiceName",

            "Value":
                SERVICE,
        },
    ],

    Statistic=
        "Average",

    Period=
        300,

    EvaluationPeriods=
        2,

    DatapointsToAlarm=
        2,

    Threshold=
        85,

    ComparisonOperator=
        "GreaterThanThreshold",

    TreatMissingData=
        "notBreaching",
)

ALARMS.append(
    "obesity-ci-v3-ecs-high-cpu"
)


# ------------------------------------------------------------
# ECS MEMORY
# ------------------------------------------------------------

cloudwatch.put_metric_alarm(

    AlarmName=
        "obesity-ci-v3-ecs-high-memory",

    AlarmDescription=
        (
            "Fargate service average "
            "memory exceeded 85%."
        ),

    Namespace=
        "AWS/ECS",

    MetricName=
        "MemoryUtilization",

    Dimensions=[
        {
            "Name":
                "ClusterName",

            "Value":
                CLUSTER,
        },
        {
            "Name":
                "ServiceName",

            "Value":
                SERVICE,
        },
    ],

    Statistic=
        "Average",

    Period=
        300,

    EvaluationPeriods=
        2,

    DatapointsToAlarm=
        2,

    Threshold=
        85,

    ComparisonOperator=
        "GreaterThanThreshold",

    TreatMissingData=
        "notBreaching",
)

ALARMS.append(
    "obesity-ci-v3-ecs-high-memory"
)


for alarm in ALARMS:

    print(
        "Created:",
        alarm,
    )


# ============================================================
# 6. CREATE DASHBOARD
# ============================================================

section(
    "CREATE CLOUDWATCH DASHBOARD"
)


dashboard = {

    "start":
        "-PT6H",

    "periodOverride":
        "inherit",

    "widgets": [

        # ----------------------------------------------------
        # HEADER
        # ----------------------------------------------------

        {
            "type":
                "text",

            "x": 0,
            "y": 0,

            "width":
                24,

            "height":
                3,

            "properties": {

                "markdown":
                    (
                        "# Obesity CI Copilot — V3\n"
                        "**Serving:** ECS Fargate "
                        "(4 vCPU / 8 GB)  \n"
                        "**Logs:** `/ecs/"
                        "obesity-ci-copilot-v3`  \n"
                        "**Production guardrail:** "
                        "Fargate normally scaled to "
                        "`desiredCount=0` when not "
                        "being demonstrated."
                    )
            },
        },


        # ----------------------------------------------------
        # REQUESTS + ERRORS
        # ----------------------------------------------------

        {
            "type":
                "metric",

            "x": 0,
            "y": 3,

            "width":
                12,

            "height":
                6,

            "properties": {

                "title":
                    "API Requests & 5xx",

                "region":
                    REGION,

                "period":
                    300,

                "view":
                    "timeSeries",

                "stat":
                    "Sum",

                "metrics": [

                    [
                        NAMESPACE,
                        "RequestCount",
                        {
                            "label":
                                "Requests"
                        },
                    ],

                    [
                        NAMESPACE,
                        "Api5xxCount",
                        {
                            "label":
                                "HTTP 5xx"
                        },
                    ],
                ],
            },
        },


        # ----------------------------------------------------
        # LATENCY
        # ----------------------------------------------------

        {
            "type":
                "metric",

            "x": 12,
            "y": 3,

            "width":
                12,

            "height":
                6,

            "properties": {

                "title":
                    "Request Latency",

                "region":
                    REGION,

                "period":
                    300,

                "view":
                    "timeSeries",

                "yAxis": {
                    "left": {
                        "label":
                            "Milliseconds",

                        "showUnits":
                            False,
                    }
                },

                "metrics": [

                    [
                        NAMESPACE,
                        "RequestLatencyMs",
                        {
                            "stat":
                                "Average",

                            "label":
                                "Average",
                        },
                    ],

                    [
                        NAMESPACE,
                        "RequestLatencyMs",
                        {
                            "stat":
                                "p95",

                            "label":
                                "p95",
                        },
                    ],
                ],
            },
        },


        # ----------------------------------------------------
        # PIPELINE OUTCOMES
        # ----------------------------------------------------

        {
            "type":
                "metric",

            "x": 0,
            "y": 9,

            "width":
                12,

            "height":
                6,

            "properties": {

                "title":
                    "Copilot Outcomes",

                "region":
                    REGION,

                "period":
                    300,

                "view":
                    "timeSeries",

                "stat":
                    "Sum",

                "metrics": [

                    [
                        NAMESPACE,
                        "CopilotAnswerCount",
                        {
                            "label":
                                "Answers"
                        },
                    ],

                    [
                        NAMESPACE,
                        "CopilotFailureCount",
                        {
                            "label":
                                "Failures"
                        },
                    ],

                    [
                        NAMESPACE,
                        "SynthesisRepairCount",
                        {
                            "label":
                                "Synthesis repairs"
                        },
                    ],

                    [
                        NAMESPACE,
                        "AbstentionCount",
                        {
                            "label":
                                "Abstentions"
                        },
                    ],
                ],
            },
        },


        # ----------------------------------------------------
        # ROUTE DISTRIBUTION
        # ----------------------------------------------------

        {
            "type":
                "metric",

            "x": 12,
            "y": 9,

            "width":
                12,

            "height":
                6,

            "properties": {

                "title":
                    "Planner Route Distribution",

                "region":
                    REGION,

                "period":
                    300,

                "view":
                    "timeSeries",

                "stat":
                    "Sum",

                "metrics": [

                    [
                        NAMESPACE,
                        "RouteCount",
                        "Route",
                        "structured",
                    ],

                    [
                        NAMESPACE,
                        "RouteCount",
                        "Route",
                        "retrieval",
                    ],

                    [
                        NAMESPACE,
                        "RouteCount",
                        "Route",
                        "hybrid",
                    ],

                    [
                        NAMESPACE,
                        "RouteCount",
                        "Route",
                        "abstain",
                    ],
                ],
            },
        },


        # ----------------------------------------------------
        # CITATION GUARDRAILS
        # ----------------------------------------------------

        {
            "type":
                "metric",

            "x": 0,
            "y": 15,

            "width":
                12,

            "height":
                6,

            "properties": {

                "title":
                    "Citation Guardrail Failures",

                "region":
                    REGION,

                "period":
                    300,

                "view":
                    "timeSeries",

                "stat":
                    "Sum",

                "metrics": [

                    [
                        NAMESPACE,
                        "CitationValidityFailureCount",
                        {
                            "label":
                                "Invalid citations"
                        },
                    ],

                    [
                        NAMESPACE,
                        "CitationCoverageFailureCount",
                        {
                            "label":
                                "Incomplete citation coverage"
                        },
                    ],
                ],
            },
        },


        # ----------------------------------------------------
        # ECS RESOURCE UTILIZATION
        # ----------------------------------------------------

        {
            "type":
                "metric",

            "x": 12,
            "y": 15,

            "width":
                12,

            "height":
                6,

            "properties": {

                "title":
                    "Fargate CPU & Memory",

                "region":
                    REGION,

                "period":
                    300,

                "view":
                    "timeSeries",

                "metrics": [

                    [
                        "AWS/ECS",
                        "CPUUtilization",
                        "ClusterName",
                        CLUSTER,
                        "ServiceName",
                        SERVICE,
                        {
                            "stat":
                                "Average",

                            "label":
                                "CPU %"
                        },
                    ],

                    [
                        "AWS/ECS",
                        "MemoryUtilization",
                        "ClusterName",
                        CLUSTER,
                        "ServiceName",
                        SERVICE,
                        {
                            "stat":
                                "Average",

                            "label":
                                "Memory %"
                        },
                    ],
                ],
            },
        },
    ],
}


dashboard_body = json.dumps(
    dashboard,
    indent=2,
)


dashboard_response = (
    cloudwatch.put_dashboard(

        DashboardName=
            DASHBOARD_NAME,

        DashboardBody=
            dashboard_body,
    )
)


validation_messages = (
    dashboard_response.get(
        "DashboardValidationMessages",
        [],
    )
)


DASHBOARD_PATH.write_text(
    dashboard_body,
    encoding="utf-8",
)


print(
    "Dashboard:",
    DASHBOARD_NAME,
)


if validation_messages:

    print(
        "Dashboard validation messages:"
    )

    for message in (
        validation_messages
    ):

        print(
            message
        )

else:

    print(
        "Dashboard validation: PASS"
    )


# ============================================================
# 7. VERIFY ALARMS
# ============================================================

section(
    "VERIFY ALARMS"
)


alarm_response = (
    cloudwatch.describe_alarms(
        AlarmNames=
            ALARMS,
    )
)


registered_alarms = {
    alarm[
        "AlarmName"
    ]:
        alarm
    for alarm in
    alarm_response.get(
        "MetricAlarms",
        [],
    )
}


for alarm_name in ALARMS:

    alarm = registered_alarms.get(
        alarm_name
    )

    if not alarm:

        raise RuntimeError(
            f"Missing alarm: "
            f"{alarm_name}"
        )

    print(
        f"{alarm_name:<40}"
        f"{alarm['StateValue']}"
    )


# ============================================================
# 8. VERIFY FARGATE REMAINS AT ZERO
# ============================================================

service_response = (
    ecs.describe_services(
        cluster=
            CLUSTER,

        services=[
            SERVICE
        ],
    )
)


service = (
    service_response[
        "services"
    ][0]
)


desired_count = (
    service[
        "desiredCount"
    ]
)


if desired_count != 0:

    ecs.update_service(
        cluster=
            CLUSTER,

        service=
            SERVICE,

        desiredCount=
            0,
    )

    desired_count = 0


print()
print(
    "Fargate desired count:",
    desired_count,
)


# ============================================================
# 9. MONITORING MANIFEST
# ============================================================

section(
    "SAVE 7F MONITORING MANIFEST"
)


manifest = {

    "system":
        (
            "Evidence-Grounded Obesity "
            "Drug Competitive Intelligence "
            "Copilot"
        ),

    "version":
        "v3",

    "deployment_stage":
        "7F",

    "monitoring_status":
        "COMPLETE",

    "region":
        REGION,

    "cloudwatch_log_group":
        LOG_GROUP,

    "log_retention_days":
        7,

    "custom_metric_namespace":
        NAMESPACE,

    "dashboard":
        DASHBOARD_NAME,

    "metric_filters": [

        {
            "filter_name":
                item[
                    "filter_name"
                ],

            "filter_pattern":
                item[
                    "pattern"
                ],

            "metric_name":
                item[
                    "metric_name"
                ],
        }

        for item in FILTERS
    ],

    "metric_filter_validation":
        validation_results,

    "alarms":
        ALARMS,

    "alarm_notifications":
        (
            "No notification actions "
            "configured; alarms are "
            "CloudWatch state alarms."
        ),

    "ecs_monitoring": {

        "cluster":
            CLUSTER,

        "service":
            SERVICE,

        "cpu_metric":
            "AWS/ECS CPUUtilization",

        "memory_metric":
            "AWS/ECS MemoryUtilization",

        "desired_count_after_setup":
            desired_count,
    },

    "application_metrics": [

        "RequestCount",
        "Api5xxCount",
        "RequestLatencyMs",
        "CopilotFailureCount",
        "CopilotAnswerCount",
        "RouteCount",
        "SynthesisRepairCount",
        "AbstentionCount",
        "CitationValidityFailureCount",
        "CitationCoverageFailureCount",
    ],

    "notes": [

        (
            "CloudWatch Logs metric "
            "filters emit metrics only "
            "for log events arriving "
            "after filter creation; "
            "historical logs are not "
            "backfilled."
        ),

        (
            "Fargate CPU and memory "
            "metrics emit while the "
            "service is running."
        ),

        (
            "TreatMissingData is set "
            "to notBreaching so the "
            "normally stopped demo "
            "service does not generate "
            "false alarms."
        ),
    ],
}


MONITORING_PATH.write_text(
    json.dumps(
        manifest,
        indent=2,
    ),
    encoding="utf-8",
)


print(
    "Monitoring manifest:",
    MONITORING_PATH,
)


# ============================================================
# 10. UPLOAD MONITORING ARTIFACTS
# ============================================================

prefix = (
    "obesity-ci-copilot/"
    "v3/monitoring"
)


s3.upload_file(
    str(
        MONITORING_PATH
    ),
    BUCKET,
    (
        f"{prefix}/"
        "monitoring_7f.json"
    ),
)


s3.upload_file(
    str(
        DASHBOARD_PATH
    ),
    BUCKET,
    (
        f"{prefix}/"
        "cloudwatch_dashboard_7f.json"
    ),
)


print(
    "S3 monitoring artifacts: PASS"
)


# ============================================================
# 11. VERIFY S3
# ============================================================

for key in [

    (
        f"{prefix}/"
        "monitoring_7f.json"
    ),

    (
        f"{prefix}/"
        "cloudwatch_dashboard_7f.json"
    ),
]:

    response = (
        s3.head_object(
            Bucket=
                BUCKET,

            Key=
                key,
        )
    )

    print(
        f"{key:<80}"
        f"{response['ContentLength']} bytes"
    )


# ============================================================
# FINAL
# ============================================================

section(
    "7F COMPLETE"
)


print(
    f"Metric filters: "
    f"{len(FILTERS)}"
)

print(
    f"Alarms: "
    f"{len(ALARMS)}"
)

print(
    f"Dashboard: "
    f"{DASHBOARD_NAME}"
)

print(
    f"Log retention: "
    f"7 days"
)

print(
    f"Fargate desired count: "
    f"{desired_count}"
)

print(
    f"Manifest: "
    f"{MONITORING_PATH}"
)

print()
print(
    "Next stage: "
    "7G Streamlit analyst UI + demo."
)
