"""A minimal async client for the Liftosaur REST API."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import aiohttp

from .const import API_BASE


class LiftosaurError(Exception):
    """Base error."""


class LiftosaurAuthError(LiftosaurError):
    """The API key is missing or invalid (401)."""


class LiftosaurSubscriptionError(LiftosaurError):
    """The account has no active premium subscription (403)."""


class LiftosaurDashboardError(LiftosaurError):
    """The dashboard text did not compile (422)."""

    def __init__(self, message: str, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.details = details or []


class LiftosaurApi:
    """Talk to https://www.liftosaur.com/api/v1."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        base_url: str = API_BASE,
        timeout: float = 30,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _request(self, method: str, path: str, json: Any = None) -> Any:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        try:
            async with self._session.request(
                method,
                f"{self._base}{path}",
                json=json,
                headers=headers,
                timeout=self._timeout,
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    body = None
                if resp.status == 401:
                    raise LiftosaurAuthError("Invalid Liftosaur API key")
                if resp.status == 403:
                    raise LiftosaurSubscriptionError(
                        "The Liftosaur API needs an active premium subscription"
                    )
                error = (body or {}).get("error") if isinstance(body, dict) else None
                if resp.status == 422 and error:
                    raise LiftosaurDashboardError(
                        error.get("message", "Invalid dashboard"), error.get("details")
                    )
                if resp.status >= 400:
                    message = error.get("message") if error else resp.reason
                    raise LiftosaurError(f"Liftosaur API {resp.status}: {message}")
                if not isinstance(body, dict) or "data" not in body:
                    raise LiftosaurError("Unexpected response from the Liftosaur API")
                return body["data"]
        except (TimeoutError, aiohttp.ClientError) as err:
            raise LiftosaurError(f"Cannot reach Liftosaur: {err}") from err

    async def list_dashboards(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/dashboards")
        return list(data.get("dashboards", []))

    async def get_dashboard(self, dashboard_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/dashboards/{dashboard_id}")

    async def list_history(self, start_date: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Workout records, optionally only those since `start_date` (ISO date)."""
        query = {"limit": str(limit)}
        if start_date:
            query["startDate"] = start_date
        data = await self._request("GET", f"/history?{urlencode(query)}")
        return list(data.get("records", []))

    async def preview(self, text: str) -> dict[str, Any]:
        """Evaluate Liftograph text against the user's data without saving it."""
        return await self._request("POST", "/dashboard-preview", json={"text": text})
