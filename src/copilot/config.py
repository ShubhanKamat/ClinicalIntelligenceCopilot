import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_name: str = "obesity-ci-copilot"
    service_version: str = "v3"

    aws_region: str = os.getenv(
        "AWS_REGION",
        "us-east-1",
    )

    log_level: str = os.getenv(
        "LOG_LEVEL",
        "INFO",
    )


settings = Settings()
