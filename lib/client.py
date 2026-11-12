"""Thread-safe resilient HTTP client for PageSift Server."""

from __future__ import annotations

import io
import json
import logging
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from lib.errors import (
    PageSiftAuthError,
    PageSiftDocumentError,
    PageSiftError,
    PageSiftRateLimitError,
    PageSiftServiceError,
    PageSiftTimeoutError,
)
from lib.validation import validate_target_url

logger = logging.getLogger(__name__)


class PageSiftClient:
    """High-performance resilient client for PageSift HTTP Engine."""

    def __init__(self, base_url: str = "http://localhost:3002", api_key: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or "http://localhost:3002").rstrip("/")
        # Verify base_url format (allow internal host since PageSift may be deployed in internal network)
        validate_target_url(self.base_url, allow_private=True)
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.timeout = float(timeout)

        # Setup persistent connection pool
        self._session = requests.Session()
        retries = Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=[502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(pool_connections=25, pool_maxsize=25, max_retries=retries)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def _get_headers(self, additional: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "dify-plugin-pagesift/0.1.0"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if additional:
            headers.update(additional)
        return headers

    def validate_connection(self) -> None:
        """Verify server reachability and API key validity."""
        # 1. Health check
        try:
            resp = self._session.get(f"{self.base_url}/healthz", timeout=5.0)
            if resp.status_code != 200:
                raise PageSiftServiceError(f"Health check failed with status HTTP {resp.status_code}")
        except requests.exceptions.RequestException as e:
            raise PageSiftServiceError(f"Cannot reach PageSift server at {self.base_url}: {e}")

        # 2. If API Key is configured, verify authentication against /v1/scrape or /v2/scrape
        if self.api_key:
            try:
                probe_resp = self._session.post(
                    f"{self.base_url}/v2/scrape",
                    json={"url": "http://127.0.0.1:8800/probe", "timeout": 100},
                    headers=self._get_headers({"Content-Type": "application/json"}),
                    timeout=5.0
                )
                if probe_resp.status_code == 401:
                    raise PageSiftAuthError("Authentication failed: Invalid API Key provided.")
            except requests.exceptions.RequestException as e:
                # If network fails here, it's a connectivity issue
                raise PageSiftServiceError(f"Auth verification failed: {e}")

    def scrape(
        self,
        url: str,
        formats: list[str] | None = None,
        only_main_content: bool = True,
        api_version: str = "v2",
        timeout: float | None = None
    ) -> dict[str, Any]:
        """Scrape webpage into Markdown via /v1/scrape or /v2/scrape."""
        valid_url = validate_target_url(url, allow_private=False)
        req_timeout = timeout or self.timeout

        payload = {
            "url": valid_url,
            "formats": formats or ["markdown"],
            "onlyMainContent": bool(only_main_content),
            "timeout": int(req_timeout * 1000)
        }

        endpoint = f"{self.base_url}/{api_version}/scrape"
        try:
            resp = self._session.post(
                endpoint,
                json=payload,
                headers=self._get_headers({"Content-Type": "application/json"}),
                timeout=req_timeout
            )
            return self._handle_response(resp)
        except requests.exceptions.Timeout as e:
            raise PageSiftTimeoutError(f"Scrape timed out after {req_timeout}s: {e}")
        except requests.exceptions.RequestException as e:
            raise PageSiftServiceError(f"HTTP request to PageSift failed: {e}")

    def parse_document(
        self,
        file_bytes: bytes,
        filename: str = "document",
        ocr: bool = False,
        timeout: float = 60.0
    ) -> dict[str, Any]:
        """Parse raw document bytes (PDF, Office, CSV) via /v2/parse."""
        if not file_bytes:
            raise PageSiftDocumentError("Document file content is empty.")

        endpoint = f"{self.base_url}/v2/parse"
        files = {
            "file": (filename, io.BytesIO(file_bytes), "application/octet-stream")
        }
        data_payload = {
            "options": json.dumps({"ocr": bool(ocr)})
        }

        try:
            resp = self._session.post(
                endpoint,
                files=files,
                data=data_payload,
                headers=self._get_headers(),
                timeout=timeout
            )
            return self._handle_response(resp)
        except requests.exceptions.Timeout as e:
            raise PageSiftTimeoutError(f"Document parsing timed out after {timeout}s: {e}")
        except requests.exceptions.RequestException as e:
            raise PageSiftServiceError(f"Document upload failed: {e}")

    def start_crawl(self, url: str, limit: int = 5, api_version: str = "v1") -> str:
        """Submit an asynchronous website crawl job."""
        valid_url = validate_target_url(url, allow_private=False)
        payload = {
            "url": valid_url,
            "limit": int(limit),
            "scrapeOptions": {
                "formats": ["markdown"],
                "onlyMainContent": True
            }
        }
        resp = self._session.post(
            f"{self.base_url}/{api_version}/crawl",
            json=payload,
            headers=self._get_headers({"Content-Type": "application/json"}),
            timeout=15.0
        )
        data = self._handle_response(resp)
        job_id = data.get("id") or data.get("jobId")
        if not job_id:
            raise PageSiftServiceError("Server did not return a valid crawl job ID")
        return str(job_id)

    def get_crawl_status(self, job_id: str, api_version: str = "v1") -> dict[str, Any]:
        """Check status of a submitted crawl job."""
        resp = self._session.get(
            f"{self.base_url}/{api_version}/crawl/{job_id}",
            headers=self._get_headers(),
            timeout=15.0
        )
        return self._handle_response(resp)

    def _handle_response(self, resp: requests.Response) -> dict[str, Any]:
        """Convert HTTP response into structured dict or raise mapped exception."""
        if resp.status_code == 401:
            raise PageSiftAuthError("Invalid API key or unauthorized access.")
        elif resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            ra = float(retry_after) if retry_after and retry_after.isdigit() else None
            raise PageSiftRateLimitError("Rate limit exceeded.", retry_after=ra)
        elif resp.status_code == 408:
            raise PageSiftTimeoutError("PageSift engine reported operation timeout.")

        try:
            body = resp.json()
        except Exception:
            raise PageSiftServiceError(f"Invalid JSON returned (HTTP {resp.status_code}): {resp.text[:200]}")

        if resp.status_code >= 400:
            err_msg = body.get("error") or body.get("message") or f"HTTP {resp.status_code}"
            raise PageSiftServiceError(f"PageSift error: {err_msg}", status_code=resp.status_code)

        if not body.get("success", False):
            raise PageSiftError(body.get("error", "Operation returned failure without message."))

        return body
