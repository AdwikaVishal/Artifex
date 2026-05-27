"""
HttpTool – async HTTP GET/POST with timeout and retry.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class HttpTool:
    """Thin async wrapper around httpx with retry logic."""

    DEFAULT_TIMEOUT = 30.0

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        params:
          url     (str)  – required
          method  (str)  – GET | POST  (default: GET)
          headers (dict) – optional
          body    (dict) – optional JSON body for POST
          timeout (float)– optional, default 30 s
        """
        url: str = params["url"]
        method: str = params.get("method", "GET").upper()
        headers: dict = params.get("headers", {})
        body: dict | None = params.get("body")
        timeout: float = float(params.get("timeout", self.DEFAULT_TIMEOUT))

        return await self._fetch(url, method, headers, body, timeout)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def _fetch(
        self,
        url: str,
        method: str,
        headers: dict,
        body: dict | None,
        timeout: float,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                resp = await client.get(url, headers=headers)
            elif method == "POST":
                resp = await client.post(url, headers=headers, json=body)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception:  # noqa: BLE001
                data = resp.text

            return {
                "status_code": resp.status_code,
                "data": data,
                "url": str(resp.url),
            }
