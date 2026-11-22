"""Thread-safe resilient HTTP client for PageSift 1.6.3 Server."""

from __future__ import annotations

import io
import json
import logging
from typing import Any, Callable
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from lib.errors import (
    PageSiftAuthError,
    PageSiftDocumentError,
    PageSiftError,
    PageSiftForbiddenError,
    PageSiftInvalidRequestError,
    PageSiftNotFoundError,
    PageSiftRateLimitError,
    PageSiftServiceError,
    PageSiftSSRFError,
    PageSiftTimeoutError,
    PageSiftUnsupportedError,
)
from lib.validation import validate_target_url

logger = logging.getLogger(__name__)

PLUGIN_USER_AGENT = "dify-plugin-pagesift/0.2.0"


class PageSiftClient:
    """High-performance resilient HTTP client for PageSift 1.6.3 Engine."""

    def __init__(
        self,
        base_url: str = "http://localhost:3002",
        api_key: str | None = None,
        timeout: float = 30.0,
        session_id: str | None = None,
    ):
        self.base_url = (base_url or "http://localhost:3002").rstrip("/")
        # Allow private network addresses ONLY for the admin-configured PageSift server URL
        validate_target_url(self.base_url, allow_private=True)
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.session_id = session_id.strip() if session_id and session_id.strip() else None
        self.timeout = max(1.0, min(float(timeout), 300.0))

        self._session = requests.Session()
        retries = Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=[502, 503, 504],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(pool_connections=25, pool_maxsize=25, max_retries=retries)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def close(self) -> None:
        """Close underlying HTTP connection pool."""
        self._session.close()

    def __enter__(self) -> PageSiftClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _get_headers(self, additional: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": PLUGIN_USER_AGENT,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.session_id:
            headers["X-Session-Id"] = self.session_id
        if additional:
            headers.update(additional)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        timeout: float | None = None,
        require_success: bool = True,
    ) -> dict[str, Any]:
        req_timeout = timeout if timeout is not None else self.timeout
        url = f"{self.base_url}{path}"
        extra_headers = {"Content-Type": "application/json"} if json_body is not None else None
        try:
            resp = self._session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                files=files,
                data=data,
                headers=self._get_headers(extra_headers),
                timeout=req_timeout,
            )
            return self._handle_response(resp, require_success=require_success)
        except requests.exceptions.Timeout as e:
            raise PageSiftTimeoutError(f"Request to {path} timed out after {req_timeout:.1f}s: {e}") from e
        except requests.exceptions.RequestException as e:
            raise PageSiftServiceError(f"HTTP request to PageSift ({path}) failed: {e}") from e

    # ------------------------------------------------------------------
    # Health & Authentication
    # ------------------------------------------------------------------

    def validate_connection(self) -> None:
        """
        Verify PageSift reachability and authentication without consuming RPM or page quotas.

        1. GET /healthz checks server liveness.
        2. GET /v2/crawl/active passes through the auth middleware (verifying both missing-key
           and invalid-key rejection) without incrementing requests_per_minute or pages_per_day.
        """
        try:
            resp = self._session.get(f"{self.base_url}/healthz", timeout=5.0)
            if resp.status_code != 200:
                raise PageSiftServiceError(
                    f"Health check failed with status HTTP {resp.status_code}",
                    status_code=resp.status_code,
                )
        except requests.exceptions.RequestException as e:
            raise PageSiftServiceError(
                f"Cannot reach PageSift server at {self.base_url}: {e}"
            ) from e

        try:
            probe_resp = self._session.get(
                f"{self.base_url}/v2/crawl/active",
                headers=self._get_headers(),
                timeout=5.0,
            )
            if probe_resp.status_code == 401:
                if self.api_key:
                    raise PageSiftAuthError("Authentication failed: Invalid API Key provided.")
                raise PageSiftAuthError(
                    "Authentication required: PageSift server requires an API Key."
                )
            if probe_resp.status_code >= 400:
                self._handle_response(probe_resp)
        except PageSiftError:
            raise
        except requests.exceptions.RequestException as e:
            raise PageSiftServiceError(f"Auth verification failed: {e}") from e

    # ------------------------------------------------------------------
    # Scrape (/v2/scrape)
    # ------------------------------------------------------------------

    def scrape(
        self,
        url: str,
        formats: list[str | dict[str, Any]] | None = None,
        only_main_content: bool = True,
        api_version: str = "v2",
        timeout: float | None = None,
        *,
        engine: str | None = None,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        max_age: int | None = None,
        query_filter: str | dict[str, Any] | None = None,
        chunking: dict[str, Any] | None = None,
        extract_schema: dict[str, Any] | None = None,
        parsers: list[str | dict[str, Any]] | None = None,
        image_assets: str | None = None,
        export_images: bool = False,
        graph: bool | dict[str, Any] | None = None,
        wait_for: int | None = None,
        mobile: bool = False,
        ignore_robots_txt: bool = False,
        explain: bool = False,
    ) -> dict[str, Any]:
        """Scrape a webpage into Markdown, structured extract, chunks, or DataGraph."""
        valid_url = validate_target_url(url, allow_private=False)
        req_timeout = timeout or self.timeout

        fmt_list: list[str | dict[str, Any]] = list(formats) if formats else ["markdown"]
        if extract_schema is not None:
            fmt_list.append({"type": "extract", "schema": extract_schema})

        payload: dict[str, Any] = {
            "url": valid_url,
            "formats": fmt_list,
            "onlyMainContent": bool(only_main_content),
            "timeout": max(1000, min(int(req_timeout * 1000), 300_000)),
        }
        if engine and engine != "auto":
            payload["engine"] = engine
        elif engine == "auto":
            payload["engine"] = "auto"
        if include_tags:
            payload["includeTags"] = include_tags
        if exclude_tags:
            payload["excludeTags"] = exclude_tags
        if max_age is not None:
            payload["maxAge"] = int(max_age)
        if query_filter:
            payload["queryFilter"] = query_filter
        if chunking:
            payload["chunking"] = chunking
        if parsers is not None:
            payload["parsers"] = parsers
        if image_assets and image_assets != "none":
            payload["imageAssets"] = image_assets
        if export_images:
            payload["exportImages"] = True
        if graph:
            payload["graph"] = graph
        if wait_for and wait_for > 0:
            payload["waitFor"] = int(wait_for)
        if mobile:
            payload["mobile"] = True
        if ignore_robots_txt:
            payload["ignoreRobotsTxt"] = True
        if explain:
            payload["explain"] = True

        # Give HTTP client slight headroom beyond server-side scrape timeout
        http_timeout = req_timeout + 10.0
        return self._request(
            "POST",
            f"/{api_version}/scrape",
            json_body=payload,
            timeout=http_timeout,
        )

    # ------------------------------------------------------------------
    # Document Parse (/v2/parse)
    # ------------------------------------------------------------------

    def parse_document(
        self,
        file_bytes: bytes,
        filename: str = "document",
        ocr: bool = False,
        timeout: float = 60.0,
        *,
        content_type: str | None = None,
        pdf_mode: str | None = None,
        max_pages: int | None = None,
        per_page: bool = False,
        only_main_content: bool = True,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        query_filter: str | dict[str, Any] | None = None,
        chunking: dict[str, Any] | None = None,
        image_assets: str | None = None,
        graph: bool | dict[str, Any] | None = None,
        source_url: str | None = None,
    ) -> dict[str, Any]:
        """Parse uploaded document/code/archive/image bytes via POST /v2/parse."""
        if not file_bytes:
            raise PageSiftDocumentError("Document file content is empty.")

        effective_pdf_mode = pdf_mode
        if not effective_pdf_mode and ocr:
            effective_pdf_mode = "ocr"

        options: dict[str, Any] = {
            "formats": ["markdown"],
            "onlyMainContent": bool(only_main_content),
            "timeout": max(1000, min(int(timeout * 1000), 300_000)),
        }

        if effective_pdf_mode or max_pages is not None or per_page:
            pdf_cfg: dict[str, Any] = {"type": "pdf"}
            if effective_pdf_mode:
                pdf_cfg["mode"] = effective_pdf_mode
            if max_pages is not None:
                pdf_cfg["maxPages"] = int(max_pages)
            if per_page:
                pdf_cfg["pages"] = True
            # Keep "image" enabled alongside pdf config so standalone image uploads still work
            options["parsers"] = [pdf_cfg, "image"]

        if include_tags:
            options["includeTags"] = include_tags
        if exclude_tags:
            options["excludeTags"] = exclude_tags
        if query_filter:
            options["queryFilter"] = query_filter
        if chunking:
            options["chunking"] = chunking
        if image_assets and image_assets != "none":
            options["imageAssets"] = image_assets
        if graph:
            options["graph"] = graph

        mime = (content_type or "application/octet-stream").strip() or "application/octet-stream"
        files = {
            "file": (filename or "document", io.BytesIO(file_bytes), mime),
        }
        data_payload: dict[str, str] = {
            "options": json.dumps(options, ensure_ascii=False),
        }
        if source_url and source_url.strip():
            # /v2/parse never fetches `url`; it only resolves relative links in uploaded HTML
            validated_source_url = validate_target_url(source_url.strip(), allow_private=True)
            data_payload["url"] = validated_source_url

        http_timeout = timeout + 15.0
        try:
            resp = self._session.post(
                f"{self.base_url}/v2/parse",
                files=files,
                data=data_payload,
                headers=self._get_headers(),
                timeout=http_timeout,
            )
            return self._handle_response(resp)
        except requests.exceptions.Timeout as e:
            raise PageSiftTimeoutError(f"Document parsing timed out after {timeout:.1f}s: {e}") from e
        except requests.exceptions.RequestException as e:
            raise PageSiftServiceError(f"Document upload failed: {e}") from e

    # ------------------------------------------------------------------
    # Site Mapping (/v2/map)
    # ------------------------------------------------------------------

    def map_site(
        self,
        url: str,
        *,
        search: str | None = None,
        sitemap: str = "include",
        include_subdomains: bool = True,
        ignore_query_parameters: bool = True,
        limit: int = 5000,
        ignore_robots_txt: bool = False,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Discover URLs on a website via POST /v2/map."""
        valid_url = validate_target_url(url, allow_private=False)
        req_timeout = timeout or self.timeout
        payload: dict[str, Any] = {
            "url": valid_url,
            "sitemap": sitemap or "include",
            "includeSubdomains": bool(include_subdomains),
            "ignoreQueryParameters": bool(ignore_query_parameters),
            "limit": int(limit),
            "timeout": max(1000, min(int(req_timeout * 1000), 300_000)),
        }
        if search and search.strip():
            payload["search"] = search.strip()
        if ignore_robots_txt:
            payload["ignoreRobotsTxt"] = True
        return self._request("POST", "/v2/map", json_body=payload, timeout=req_timeout + 10.0)

    # ------------------------------------------------------------------
    # Crawl (/v2/crawl*)
    # ------------------------------------------------------------------

    def start_crawl(
        self,
        url: str,
        limit: int = 5,
        api_version: str = "v2",
        *,
        query: str | None = None,
        adaptive: bool | dict[str, Any] | None = None,
        attachments: bool = False,
        attachment_limit: int | None = None,
        max_discovery_depth: int | None = None,
        scope: str | None = None,
        include_paths: list[str] | None = None,
        exclude_paths: list[str] | None = None,
        allow_subdomains: bool | None = None,
        allow_external_links: bool = False,
        crawl_entire_domain: bool = False,
        sitemap: str | None = None,
        ignore_query_parameters: bool = False,
        ignore_robots_txt: bool = False,
        graph: bool | dict[str, Any] | None = None,
        scrape_options: dict[str, Any] | None = None,
    ) -> str:
        """Submit an asynchronous website crawl job."""
        valid_url = validate_target_url(url, allow_private=False)
        payload: dict[str, Any] = {
            "url": valid_url,
            "limit": int(limit),
            "scrapeOptions": scrape_options
            or {
                "formats": ["markdown"],
                "onlyMainContent": True,
            },
        }
        if query and query.strip():
            payload["query"] = query.strip()
        if adaptive is not None and adaptive is not False:
            payload["adaptive"] = adaptive
        if attachments:
            payload["attachments"] = True
        if attachment_limit is not None:
            payload["attachmentLimit"] = int(attachment_limit)
        if max_discovery_depth is not None:
            payload["maxDiscoveryDepth"] = int(max_discovery_depth)
        if scope:
            payload["scope"] = scope
        if include_paths:
            payload["includePaths"] = include_paths
        if exclude_paths:
            payload["excludePaths"] = exclude_paths
        if allow_subdomains is not None:
            payload["allowSubdomains"] = bool(allow_subdomains)
        if allow_external_links:
            payload["allowExternalLinks"] = True
        if crawl_entire_domain:
            payload["crawlEntireDomain"] = True
        if sitemap:
            payload["sitemap"] = sitemap
        if ignore_query_parameters:
            payload["ignoreQueryParameters"] = True
        if ignore_robots_txt:
            payload["ignoreRobotsTxt"] = True
        if graph:
            payload["graph"] = graph

        data = self._request("POST", f"/{api_version}/crawl", json_body=payload, timeout=20.0)
        job_id = data.get("id") or data.get("jobId")
        if not job_id:
            raise PageSiftServiceError("Server did not return a valid crawl job ID")
        return str(job_id)

    def get_crawl_status(
        self,
        job_id: str,
        api_version: str = "v2",
        *,
        skip: int = 0,
    ) -> dict[str, Any]:
        """Check status and retrieve a page of results for a crawl job."""
        params = {"skip": int(skip)} if skip > 0 else None
        return self._request(
            "GET",
            f"/{api_version}/crawl/{quote(job_id, safe='')}",
            params=params,
            timeout=15.0,
        )

    def cancel_crawl(self, job_id: str, api_version: str = "v2") -> dict[str, Any]:
        """Cancel a running crawl job via DELETE /{api_version}/crawl/{id}."""
        return self._request(
            "DELETE",
            f"/{api_version}/crawl/{quote(job_id, safe='')}",
            timeout=15.0,
        )

    def get_crawl_errors(self, job_id: str, api_version: str = "v2") -> dict[str, Any]:
        """Retrieve per-page errors and robots-blocked URLs for a crawl job."""
        return self._request(
            "GET",
            f"/{api_version}/crawl/{quote(job_id, safe='')}/errors",
            timeout=15.0,
            require_success=False,
        )

    # ------------------------------------------------------------------
    # Batch Scrape (/v2/batch/scrape*)
    # ------------------------------------------------------------------

    def start_batch_scrape(
        self,
        urls: list[str],
        *,
        ignore_invalid_urls: bool = True,
        max_concurrency: int | None = None,
        scrape_options: dict[str, Any] | None = None,
        api_version: str = "v2",
    ) -> dict[str, Any]:
        """Submit an asynchronous batch scrape job."""
        validated_urls: list[str] = []
        for raw_url in urls:
            validated_urls.append(validate_target_url(raw_url, allow_private=False))

        payload: dict[str, Any] = {
            "urls": validated_urls,
            "ignoreInvalidUrls": bool(ignore_invalid_urls),
        }
        if max_concurrency is not None:
            payload["maxConcurrency"] = int(max_concurrency)
        if scrape_options:
            payload.update(scrape_options)

        data = self._request(
            "POST",
            f"/{api_version}/batch/scrape",
            json_body=payload,
            timeout=20.0,
        )
        if not data.get("id"):
            raise PageSiftServiceError("Server did not return a valid batch scrape job ID")
        return data

    def get_batch_status(
        self,
        job_id: str,
        api_version: str = "v2",
        *,
        skip: int = 0,
    ) -> dict[str, Any]:
        """Check status and retrieve a page of results for a batch scrape job."""
        params = {"skip": int(skip)} if skip > 0 else None
        return self._request(
            "GET",
            f"/{api_version}/batch/scrape/{quote(job_id, safe='')}",
            params=params,
            timeout=15.0,
        )

    def cancel_batch_scrape(self, job_id: str, api_version: str = "v2") -> dict[str, Any]:
        """Cancel a running batch scrape job via DELETE /{api_version}/batch/scrape/{id}."""
        return self._request(
            "DELETE",
            f"/{api_version}/batch/scrape/{quote(job_id, safe='')}",
            timeout=15.0,
        )

    def get_batch_errors(self, job_id: str, api_version: str = "v2") -> dict[str, Any]:
        """Retrieve per-page errors and robots-blocked URLs for a batch scrape job."""
        return self._request(
            "GET",
            f"/{api_version}/batch/scrape/{quote(job_id, safe='')}/errors",
            timeout=15.0,
            require_success=False,
        )

    def collect_all_job_pages(
        self,
        fetch_page: Callable[[int], dict[str, Any]],
        first_status: dict[str, Any],
        max_pages: int = 500,
    ) -> list[dict[str, Any]]:
        """Collect paginated job results following `next` / `skip` offsets safely."""
        pages = list(first_status.get("data") or [])
        next_link = first_status.get("next")
        guard = 0
        while next_link and len(pages) < max_pages and guard < 100:
            guard += 1
            prev_len = len(pages)
            page_res = fetch_page(prev_len)
            batch = page_res.get("data") or []
            if not batch:
                break
            pages.extend(batch)
            next_link = page_res.get("next")
            if len(pages) == prev_len:
                break
        return pages[:max_pages]

    # ------------------------------------------------------------------
    # DataGraph (/v2/crawl/{id}/graph, /v2/graph/*)
    # ------------------------------------------------------------------

    def get_crawl_graph(self, job_id: str) -> dict[str, Any]:
        """Retrieve job-level DataGraph summary via GET /v2/crawl/{id}/graph."""
        return self._request("GET", f"/v2/crawl/{quote(job_id, safe='')}/graph", timeout=20.0)

    def get_graph_history(
        self,
        url: str,
        *,
        as_of: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Query version lineage and diff edges via GET /v2/graph/history."""
        params: dict[str, Any] = {"url": url.strip()}
        if as_of and as_of.strip():
            params["asOf"] = as_of.strip()
        if limit is not None:
            params["limit"] = int(limit)
        return self._request("GET", "/v2/graph/history", params=params, timeout=20.0)

    def get_graph_conflicts(
        self,
        *,
        subject: str | None = None,
        as_of: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """Query cross-source conflicts via GET /v2/graph/conflicts."""
        params: dict[str, Any] = {}
        if subject and subject.strip():
            params["subject"] = subject.strip()
        if as_of and as_of.strip():
            params["asOf"] = as_of.strip()
        if limit is not None:
            params["limit"] = int(limit)
        if offset is not None:
            params["offset"] = int(offset)
        return self._request("GET", "/v2/graph/conflicts", params=params, timeout=20.0)

    def get_graph_claims(
        self,
        *,
        url: str | None = None,
        subject: str | None = None,
        as_of: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """Query tracked claim lifecycles via GET /v2/graph/claims."""
        params: dict[str, Any] = {}
        if url and url.strip():
            params["url"] = url.strip()
        if subject and subject.strip():
            params["subject"] = subject.strip()
        if as_of and as_of.strip():
            params["asOf"] = as_of.strip()
        if limit is not None:
            params["limit"] = int(limit)
        if offset is not None:
            params["offset"] = int(offset)
        return self._request("GET", "/v2/graph/claims", params=params, timeout=20.0)

    # ------------------------------------------------------------------
    # Loop Data Sources (/v2/sources*)
    # ------------------------------------------------------------------

    def create_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Register or upsert a persistent Loop data source via POST /v2/sources."""
        seeds = payload.get("seeds") or []
        validated_seeds = [validate_target_url(s, allow_private=False) for s in seeds]
        body = dict(payload)
        body["seeds"] = validated_seeds
        return self._request("POST", "/v2/sources", json_body=body, timeout=20.0)

    def list_sources(self) -> dict[str, Any]:
        """List registered Loop data sources via GET /v2/sources."""
        return self._request("GET", "/v2/sources", timeout=20.0)

    def get_source(self, source_id: str) -> dict[str, Any]:
        """Fetch a Loop data source specification via GET /v2/sources/{id}."""
        return self._request("GET", f"/v2/sources/{quote(source_id, safe='')}", timeout=20.0)

    def delete_source(self, source_id: str) -> dict[str, Any]:
        """Delete a Loop data source via DELETE /v2/sources/{id}."""
        return self._request("DELETE", f"/v2/sources/{quote(source_id, safe='')}", timeout=20.0)

    def trigger_sync(
        self,
        source_id: str,
        *,
        force_all: bool = False,
        max_requests: int | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Trigger one adaptive incremental sync tick via POST /v2/sources/{id}/sync."""
        body: dict[str, Any] = {}
        if force_all:
            body["forceAll"] = True
        if max_requests is not None:
            body["maxRequests"] = int(max_requests)
        return self._request(
            "POST",
            f"/v2/sources/{quote(source_id, safe='')}/sync",
            json_body=body,
            timeout=timeout or max(self.timeout, 120.0),
        )

    def get_source_state(
        self,
        source_id: str,
        *,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """Inspect Loop source inventory, active/unverified claims, and fact clusters."""
        params: dict[str, Any] = {}
        if as_of and as_of.strip():
            params["asOf"] = as_of.strip()
        return self._request(
            "GET",
            f"/v2/sources/{quote(source_id, safe='')}/state",
            params=params,
            timeout=20.0,
        )

    def list_source_deltas(
        self,
        source_id: str,
        *,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """List recent SyncDeltas via GET /v2/sources/{id}/deltas."""
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = int(limit)
        return self._request(
            "GET",
            f"/v2/sources/{quote(source_id, safe='')}/deltas",
            params=params,
            timeout=20.0,
        )

    def get_source_delta(self, source_id: str, tick_id: str) -> dict[str, Any]:
        """Get one specific SyncDelta via GET /v2/sources/{id}/deltas/{tick_id}."""
        return self._request(
            "GET",
            f"/v2/sources/{quote(source_id, safe='')}/deltas/{quote(tick_id, safe='')}",
            timeout=20.0,
        )

    # ------------------------------------------------------------------
    # Context Infrastructure (/v2/context/*)
    # ------------------------------------------------------------------

    def context_ingest(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        """Ingest documents into Context KnowledgeUnits via POST /v2/context/ingest."""
        clean = {k: v for k, v in payload.items() if k not in ("action", "op")}
        return self._request(
            "POST",
            "/v2/context/ingest",
            json_body=clean,
            timeout=timeout or max(self.timeout, 60.0),
        )

    def context_sync(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        """Reconcile a Loop source into Context via POST /v2/context/sync."""
        clean = {k: v for k, v in payload.items() if k not in ("action", "op")}
        return self._request(
            "POST",
            "/v2/context/sync",
            json_body=clean,
            timeout=timeout or max(self.timeout, 60.0),
        )

    def context_search(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        """Run multi-strategy temporal/conflict Context search via POST /v2/context/search."""
        clean = {k: v for k, v in payload.items() if k not in ("action", "op")}
        return self._request(
            "POST",
            "/v2/context/search",
            json_body=clean,
            timeout=timeout or self.timeout,
        )

    def context_pack(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        """Compile a token-budgeted ContextPack via POST /v2/context/pack."""
        clean = {k: v for k, v in payload.items() if k not in ("action", "op")}
        return self._request(
            "POST",
            "/v2/context/pack",
            json_body=clean,
            timeout=timeout or self.timeout,
        )

    def context_action(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        """Run a goal-oriented Context Action (context/research/verify/watch/changes)."""
        clean = {k: v for k, v in payload.items() if k != "op"}
        # Validate candidate URLs against SSRF when network acquisition may occur
        for url_field in ("candidateUrls", "urls"):
            if url_field in clean and isinstance(clean[url_field], list):
                clean[url_field] = [
                    validate_target_url(u, allow_private=False) for u in clean[url_field]
                ]
        return self._request(
            "POST",
            "/v2/context/action",
            json_body=clean,
            timeout=timeout or max(self.timeout, 120.0),
        )

    def context_units(self, payload: dict[str, Any]) -> dict[str, Any]:
        """List or inspect persisted KnowledgeUnits via POST /v2/context/units."""
        clean = {k: v for k, v in payload.items() if k not in ("action", "op")}
        return self._request("POST", "/v2/context/units", json_body=clean, timeout=20.0)

    def context_deltas_poll(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Poll unacknowledged ContextDeltas via POST /v2/context/deltas/poll."""
        clean = {k: v for k, v in payload.items() if k not in ("action", "op")}
        return self._request("POST", "/v2/context/deltas/poll", json_body=clean, timeout=20.0)

    def context_deltas_ack(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Acknowledge an external consumer checkpoint via POST /v2/context/deltas/ack."""
        clean = {k: v for k, v in payload.items() if k not in ("action", "op")}
        return self._request("POST", "/v2/context/deltas/ack", json_body=clean, timeout=20.0)

    def context_learn_status(self) -> dict[str, Any]:
        """Read online calibration and drift-guard status via GET /v2/context/learn (read-only)."""
        return self._request("GET", "/v2/context/learn", timeout=15.0)

    def context_learn_update(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Update online calibration settings or record feedback via POST /v2/context/learn."""
        clean = {k: v for k, v in payload.items() if k not in ("action", "op")}
        return self._request("POST", "/v2/context/learn", json_body=clean, timeout=15.0)

    # ------------------------------------------------------------------
    # Attachments (/v2/attachments/{id})
    # ------------------------------------------------------------------

    def download_attachment(self, attachment_id: str, timeout: float = 30.0) -> tuple[bytes, str]:
        """Download a tenant-scoped attachment binary via GET /v2/attachments/{id}."""
        url = f"{self.base_url}/v2/attachments/{quote(attachment_id, safe='')}"
        try:
            resp = self._session.get(url, headers=self._get_headers(), timeout=timeout)
            if resp.status_code >= 400:
                self._handle_response(resp)
            content_type = resp.headers.get("Content-Type", "application/octet-stream")
            return resp.content, content_type
        except PageSiftError:
            raise
        except requests.exceptions.Timeout as e:
            raise PageSiftTimeoutError(f"Attachment download timed out: {e}") from e
        except requests.exceptions.RequestException as e:
            raise PageSiftServiceError(f"Attachment download failed: {e}") from e

    # ------------------------------------------------------------------
    # Response & Error Mapping (PageSift 1.6.3 ErrorCode Alignment)
    # ------------------------------------------------------------------

    def _parse_retry_after(self, resp: requests.Response) -> float | None:
        raw = resp.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return float(raw.strip())
        except ValueError:
            return None

    def _handle_response(
        self,
        resp: requests.Response,
        *,
        require_success: bool = True,
    ) -> dict[str, Any]:
        """Convert HTTP response into structured dict or raise mapped PageSiftError."""
        body: dict[str, Any] | None = None
        try:
            parsed = resp.json()
            if isinstance(parsed, dict):
                body = parsed
        except Exception:
            body = None

        err_code = str(body.get("code", "")).strip() if body else ""
        err_msg = (
            (body.get("error") or body.get("message"))
            if body
            else None
        )
        details = body.get("details") if body else None
        status = resp.status_code

        if status == 401 or err_code == "UNAUTHORIZED":
            raise PageSiftAuthError(
                err_msg or "Invalid API key or unauthorized access.",
                code=err_code or "UNAUTHORIZED",
                details=details,
            )

        if status == 429 or err_code in (
            "RATE_LIMITED",
            "RATE_LIMIT_EXCEEDED",
            "CONCURRENCY_LIMIT_EXCEEDED",
            "QUOTA_EXCEEDED",
        ):
            raise PageSiftRateLimitError(
                err_msg or "Rate limit or quota exceeded.",
                retry_after=self._parse_retry_after(resp),
                code=err_code or "RATE_LIMITED",
                details=details,
            )

        if status == 408 or err_code == "TIMEOUT":
            raise PageSiftTimeoutError(
                err_msg or "PageSift engine reported operation timeout.",
                details=details,
            )

        if status == 403 or err_code in ("ROBOTS_DISALLOWED", "ACCESS_BARRIER", "FORBIDDEN"):
            raise PageSiftForbiddenError(
                err_msg or f"Access denied (HTTP {status}).",
                code=err_code or "FORBIDDEN",
                status_code=status,
                details=details,
            )

        if err_code == "SSRF_BLOCKED":
            raise PageSiftSSRFError(
                err_msg or "Target URL blocked by PageSift SSRF policy.",
                status_code=status,
                details=details,
            )

        if err_code == "UNSUPPORTED_OPTION":
            raise PageSiftUnsupportedError(
                err_msg or "Requested option or format is not supported by this PageSift server.",
                details=details,
            )

        if status == 413 or err_code == "TOO_LARGE":
            raise PageSiftDocumentError(
                err_msg or "Payload or document exceeds PageSift size limit.",
                code=err_code or "TOO_LARGE",
                status_code=413,
                details=details,
            )

        if status in (404, 410) or err_code in ("NOT_FOUND", "SESSION_GONE"):
            raise PageSiftNotFoundError(
                err_msg or f"Resource not found (HTTP {status}).",
                code=err_code or ("SESSION_GONE" if status == 410 else "NOT_FOUND"),
                status_code=status,
                details=details,
            )

        if status in (400, 422) or err_code in ("INVALID_REQUEST", "ASSERTION_FAILED"):
            raise PageSiftInvalidRequestError(
                err_msg or f"Invalid request (HTTP {status}).",
                code=err_code or "INVALID_REQUEST",
                status_code=status,
                details=details,
            )

        if body is None:
            raise PageSiftServiceError(
                f"Invalid JSON returned (HTTP {status}): {resp.text[:200]}",
                status_code=status,
            )

        if status >= 400:
            raise PageSiftServiceError(
                f"PageSift error: {err_msg or f'HTTP {status}'}",
                status_code=status,
                code=err_code or "SERVICE_ERROR",
                details=details,
            )

        if require_success and not body.get("success", False):
            raise PageSiftError(
                err_msg or "Operation returned failure without message.",
                code=err_code or "PAGESIFT_ERROR",
                status_code=status,
                details=details,
            )

        return body
