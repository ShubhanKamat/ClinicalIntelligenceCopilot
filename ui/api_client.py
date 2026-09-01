from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class ApiResult:
    ok: bool
    status_code: int | None
    data: dict[str, Any] | None
    error: str | None


class CopilotApiClient:

    def __init__(
        self,
        base_url: str,
    ) -> None:

        self.base_url = (
            base_url
            .strip()
            .rstrip("/")
        )


    def health(
        self,
    ) -> ApiResult:

        try:

            response = requests.get(
                f"{self.base_url}/health",
                timeout=15,
            )

            try:
                payload = response.json()
            except Exception:
                payload = None

            if response.ok:

                return ApiResult(
                    ok=True,
                    status_code=response.status_code,
                    data=payload,
                    error=None,
                )

            return ApiResult(
                ok=False,
                status_code=response.status_code,
                data=payload,
                error=response.text,
            )

        except requests.RequestException as exc:

            return ApiResult(
                ok=False,
                status_code=None,
                data=None,
                error=str(exc),
            )


    def ask(
        self,
        question: str,
    ) -> ApiResult:

        try:

            response = requests.post(
                f"{self.base_url}/ask",
                json={
                    "question": question
                },
                timeout=(10, 300),
            )

            try:
                payload = response.json()
            except Exception:
                payload = None

            if response.ok:

                return ApiResult(
                    ok=True,
                    status_code=response.status_code,
                    data=payload,
                    error=None,
                )

            error = (
                payload.get("detail")
                if isinstance(payload, dict)
                else response.text
            )

            return ApiResult(
                ok=False,
                status_code=response.status_code,
                data=payload,
                error=error,
            )

        except requests.RequestException as exc:

            return ApiResult(
                ok=False,
                status_code=None,
                data=None,
                error=str(exc),
            )
