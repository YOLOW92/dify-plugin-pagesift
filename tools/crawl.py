"""Focused, adaptive recursive website crawling tool for Dify using PageSift 1.6.3 (/v2/crawl)."""

from __future__ import annotations

from collections.abc import Generator
import time
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from lib.errors import PageSiftError
from lib.tool_helpers import (
    build_client_from_credentials,
    build_graph_option,
    extract_document_url,
    format_tool_error,
    parse_bool,
    parse_optional_int,
    parse_string_list,
)


class CrawlTool(Tool):
    """
    Recursive website crawling tool powered by PageSift 1.6.3 (/v2/crawl).
    Supports focused query crawling, adaptive stopping, linked attachments,
    automatic pagination, cancellation on timeout, and site-wide DataGraph summary.
    """

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        url = (tool_parameters.get("url") or "").strip()
        if not url:
            yield self.create_text_message("Error: 'url' parameter is required.")
            return

        limit = parse_optional_int(tool_parameters.get("limit"), min_val=1, max_val=500, default=5) or 5
        query = (tool_parameters.get("query") or "").strip() or None
        adaptive = parse_bool(tool_parameters.get("adaptive"), default=False)
        attachments = parse_bool(tool_parameters.get("attachments"), default=False)
        max_depth = parse_optional_int(
            tool_parameters.get("max_discovery_depth"), min_val=0, max_val=100
        )
        scope = (tool_parameters.get("scope") or "auto").strip() or "auto"
        include_paths = parse_string_list(tool_parameters.get("include_paths"))
        exclude_paths = parse_string_list(tool_parameters.get("exclude_paths"))
        raw_subdomains = tool_parameters.get("allow_subdomains")
        allow_subdomains = (
            parse_bool(raw_subdomains) if raw_subdomains not in (None, "") else None
        )
        engine = (tool_parameters.get("engine") or "auto").strip() or "auto"
        enable_graph = parse_bool(tool_parameters.get("enable_graph"), default=False)
        include_markdown = parse_bool(tool_parameters.get("include_markdown"), default=False)
        max_wait_seconds = float(
            parse_optional_int(
                tool_parameters.get("timeout_seconds"), min_val=5, max_val=270, default=90
            )
            or 90
        )
        cancel_on_timeout = parse_bool(tool_parameters.get("cancel_on_timeout"), default=True)

        scrape_options: dict[str, Any] = {
            "formats": ["markdown"],
            "onlyMainContent": True,
        }
        if engine:
            scrape_options["engine"] = engine

        try:
            with build_client_from_credentials(self.runtime.credentials) as client:
                job_id = client.start_crawl(
                    url=url,
                    limit=limit,
                    api_version="v2",
                    query=query,
                    adaptive=True if (adaptive and query) else None,
                    attachments=attachments if query else False,
                    max_discovery_depth=max_depth,
                    scope=scope,
                    include_paths=include_paths or None,
                    exclude_paths=exclude_paths or None,
                    allow_subdomains=allow_subdomains,
                    graph=build_graph_option(enable_graph),
                    scrape_options=scrape_options,
                )

                yield self.create_text_message(
                    f"Initiated crawl job `{job_id}` for {url} (limit: {limit}"
                    + (f", query: `{query}`" if query else "")
                    + "). Waiting for completion..."
                )

                poll_interval = 1.0
                deadline = time.monotonic() + max_wait_seconds
                final_status_res: dict[str, Any] | None = None
                last_status = "scraping"

                while time.monotonic() < deadline:
                    status_res = client.get_crawl_status(job_id, api_version="v2")
                    last_status = str(status_res.get("status", "scraping"))

                    if last_status in ("completed", "cancelled"):
                        final_status_res = status_res
                        break
                    if last_status == "failed":
                        err_msg = status_res.get("error", "Unknown crawler error")
                        yield self.create_text_message(
                            f"Crawl job `{job_id}` failed: {err_msg}"
                        )
                        yield self.create_variable_message("job_id", job_id)
                        yield self.create_variable_message("status", "failed")
                        return

                    time.sleep(poll_interval)

                if final_status_res is None:
                    cancel_note = ""
                    if cancel_on_timeout:
                        try:
                            client.cancel_crawl(job_id, api_version="v2")
                            cancel_note = " Remote job cancelled."
                        except PageSiftError:
                            cancel_note = " Failed to cancel remote job."
                    yield self.create_text_message(
                        f"Crawl job `{job_id}` timed out after {max_wait_seconds:.0f}s "
                        f"(last status: {last_status}).{cancel_note}"
                    )
                    yield self.create_variable_message("job_id", job_id)
                    yield self.create_variable_message("status", "timeout")
                    return

                # Collect paginated results across `next` / `?skip=` links
                pages = client.collect_all_job_pages(
                    lambda skip: client.get_crawl_status(job_id, api_version="v2", skip=skip),
                    final_status_res,
                    max_pages=limit,
                )
                crawl_summary = final_status_res.get("pagesift")

                # Fetch optional per-page errors summary (best-effort)
                job_errors: dict[str, Any] | None = None
                try:
                    job_errors = client.get_crawl_errors(job_id, api_version="v2")
                except PageSiftError:
                    job_errors = None

                # Fetch site-wide DataGraph summary when requested
                graph_summary: dict[str, Any] | None = None
                if enable_graph:
                    try:
                        graph_summary = client.get_crawl_graph(job_id)
                    except PageSiftError:
                        graph_summary = None

                pages_count = len(pages)
                summary_lines = [
                    f"### Crawl Finished ({last_status}): {pages_count} page(s) retrieved\n"
                ]
                if isinstance(crawl_summary, dict):
                    stop_reason = crawl_summary.get("stopReason")
                    coverage = crawl_summary.get("coverage")
                    meta_line = f"- **Stop Reason:** `{stop_reason}`"
                    if coverage is not None:
                        meta_line += f" | **Coverage:** {coverage:.1%}"
                    summary_lines.append(meta_line + "\n")

                for i, page in enumerate(pages, 1):
                    meta = page.get("metadata") or {}
                    p_url = extract_document_url(page)
                    title = str(meta.get("title") or p_url or f"Page {i}")
                    summary_lines.append(f"{i}. [{title}]({p_url})" if p_url else f"{i}. {title}")
                    if include_markdown:
                        md = (page.get("markdown") or "").strip()
                        if md:
                            summary_lines.append(f"\n{md}\n")

                if isinstance(graph_summary, dict):
                    stats = graph_summary.get("stats") or {}
                    summary_lines.append(
                        f"\n**DataGraph:** {stats.get('nodes', 0)} nodes, "
                        f"{stats.get('citations', 0)} citations, "
                        f"{stats.get('factClusters', 0)} fact clusters, "
                        f"{stats.get('conflicts', 0)} conflicts."
                    )

                if isinstance(job_errors, dict):
                    err_count = len(job_errors.get("errors") or [])
                    blocked_count = len(job_errors.get("robotsBlocked") or [])
                    if err_count or blocked_count:
                        summary_lines.append(
                            f"\n**Notices:** {err_count} page error(s), {blocked_count} robots-blocked URL(s)."
                        )

                payload_out: dict[str, Any] = {
                    "job_id": job_id,
                    "status": last_status,
                    "count": pages_count,
                    "pages": pages,
                }
                if crawl_summary is not None:
                    payload_out["crawl_summary"] = crawl_summary
                if graph_summary is not None:
                    payload_out["graph"] = graph_summary
                if job_errors is not None:
                    payload_out["errors"] = job_errors

                yield self.create_text_message("\n".join(summary_lines))
                yield self.create_json_message(payload_out)
                yield self.create_variable_message("job_id", job_id)
                yield self.create_variable_message("status", last_status)
                yield self.create_variable_message("count", pages_count)
                yield self.create_variable_message("pages", pages)
                if crawl_summary is not None:
                    yield self.create_variable_message("crawl_summary", crawl_summary)
                if graph_summary is not None:
                    yield self.create_variable_message("graph", graph_summary)
                if job_errors is not None:
                    yield self.create_variable_message("errors", job_errors)

        except Exception as e:
            yield self.create_text_message(format_tool_error(e, "crawl"))
