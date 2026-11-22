"""Concurrent batch URL scraping tool for Dify using PageSift 1.6.3 (/v2/batch/scrape)."""

from __future__ import annotations

from collections.abc import Generator
import time
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from lib.errors import PageSiftError
from lib.tool_helpers import (
    build_chunking_config,
    build_client_from_credentials,
    build_graph_option,
    build_query_filter,
    extract_document_url,
    format_tool_error,
    parse_bool,
    parse_json_object,
    parse_optional_int,
    parse_string_list,
)


class BatchScrapeTool(Tool):
    """Scrape multiple URLs concurrently in one PageSift 1.6.3 batch job."""

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        urls = parse_string_list(tool_parameters.get("urls"))
        if not urls:
            yield self.create_text_message("Error: 'urls' parameter is required (at least 1 URL).")
            return
        if len(urls) > 500:
            urls = urls[:500]

        only_main_content = parse_bool(tool_parameters.get("only_main_content"), default=True)
        engine = (tool_parameters.get("engine") or "auto").strip() or "auto"
        max_concurrency = parse_optional_int(
            tool_parameters.get("max_concurrency"), min_val=1, max_val=64
        )
        query_filter = build_query_filter(tool_parameters.get("query_filter"))
        chunking = build_chunking_config(
            tool_parameters.get("chunking_type"),
            parse_optional_int(tool_parameters.get("chunk_size"), min_val=32),
        )
        enable_graph = parse_bool(tool_parameters.get("enable_graph"), default=False)
        include_markdown = parse_bool(tool_parameters.get("include_markdown"), default=True)
        max_wait_seconds = float(
            parse_optional_int(
                tool_parameters.get("timeout_seconds"), min_val=5, max_val=270, default=90
            )
            or 90
        )
        cancel_on_timeout = parse_bool(tool_parameters.get("cancel_on_timeout"), default=True)

        try:
            extract_schema = parse_json_object(
                tool_parameters.get("extract_schema"), "extract_schema"
            )

            formats: list[Any] = ["markdown"]
            if extract_schema is not None:
                formats.append({"type": "extract", "schema": extract_schema})

            scrape_options: dict[str, Any] = {
                "formats": formats,
                "onlyMainContent": only_main_content,
                "engine": engine,
            }
            if query_filter:
                scrape_options["queryFilter"] = query_filter
            if chunking:
                scrape_options["chunking"] = chunking
            graph_opt = build_graph_option(enable_graph)
            if graph_opt:
                scrape_options["graph"] = graph_opt

            with build_client_from_credentials(self.runtime.credentials) as client:
                started = client.start_batch_scrape(
                    urls=urls,
                    ignore_invalid_urls=True,
                    max_concurrency=max_concurrency,
                    scrape_options=scrape_options,
                    api_version="v2",
                )
                job_id = str(started["id"])
                invalid_urls = started.get("invalidURLs") or []

                poll_interval = 1.0
                deadline = time.monotonic() + max_wait_seconds
                final_status_res: dict[str, Any] | None = None
                last_status = "scraping"

                while time.monotonic() < deadline:
                    status_res = client.get_batch_status(job_id, api_version="v2")
                    last_status = str(status_res.get("status", "scraping"))

                    if last_status in ("completed", "cancelled"):
                        final_status_res = status_res
                        break
                    if last_status == "failed":
                        err_msg = status_res.get("error", "Unknown batch scrape error")
                        yield self.create_text_message(
                            f"Batch scrape job `{job_id}` failed: {err_msg}"
                        )
                        yield self.create_variable_message("job_id", job_id)
                        yield self.create_variable_message("status", "failed")
                        return

                    time.sleep(poll_interval)

                if final_status_res is None:
                    cancel_note = ""
                    if cancel_on_timeout:
                        try:
                            client.cancel_batch_scrape(job_id, api_version="v2")
                            cancel_note = " Remote batch job cancelled."
                        except PageSiftError:
                            cancel_note = " Failed to cancel remote batch job."
                    yield self.create_text_message(
                        f"Batch scrape job `{job_id}` timed out after {max_wait_seconds:.0f}s "
                        f"(last status: {last_status}).{cancel_note}"
                    )
                    yield self.create_variable_message("job_id", job_id)
                    yield self.create_variable_message("status", "timeout")
                    return

                pages = client.collect_all_job_pages(
                    lambda skip: client.get_batch_status(job_id, api_version="v2", skip=skip),
                    final_status_res,
                    max_pages=len(urls),
                )

                job_errors: dict[str, Any] | None = None
                try:
                    job_errors = client.get_batch_errors(job_id, api_version="v2")
                except PageSiftError:
                    job_errors = None

                lines = [
                    f"### Batch Scrape Finished ({last_status}): {len(pages)}/{len(urls)} page(s)\n"
                ]
                for i, page in enumerate(pages, 1):
                    meta = page.get("metadata") or {}
                    p_url = extract_document_url(page)
                    title = str(meta.get("title") or p_url or f"Page {i}")
                    lines.append(f"#### {i}. {title}")
                    if p_url:
                        lines.append(f"Source: {p_url}")
                    if include_markdown:
                        md = (page.get("markdown") or "").strip()
                        if md:
                            lines.append(f"\n{md}\n")

                if isinstance(job_errors, dict):
                    err_count = len(job_errors.get("errors") or [])
                    blocked_count = len(job_errors.get("robotsBlocked") or [])
                    if err_count or blocked_count:
                        lines.append(
                            f"\n**Notices:** {err_count} page error(s), {blocked_count} robots-blocked URL(s)."
                        )

                payload_out: dict[str, Any] = {
                    "job_id": job_id,
                    "status": last_status,
                    "count": len(pages),
                    "pages": pages,
                    "invalid_urls": invalid_urls,
                }
                if job_errors is not None:
                    payload_out["errors"] = job_errors

                yield self.create_text_message("\n".join(lines))
                yield self.create_json_message(payload_out)
                yield self.create_variable_message("job_id", job_id)
                yield self.create_variable_message("status", last_status)
                yield self.create_variable_message("count", len(pages))
                yield self.create_variable_message("pages", pages)
                yield self.create_variable_message("invalid_urls", invalid_urls)
                if job_errors is not None:
                    yield self.create_variable_message("errors", job_errors)

        except Exception as e:
            yield self.create_text_message(format_tool_error(e, "batch scrape"))
