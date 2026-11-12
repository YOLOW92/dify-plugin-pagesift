"""Recursive website crawling tool for Dify using PageSift."""

from __future__ import annotations

from collections.abc import Generator
import time
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from lib.client import PageSiftClient
from lib.errors import (
    PageSiftAuthError,
    PageSiftError,
    PageSiftRateLimitError,
    PageSiftSSRFError,
    PageSiftTimeoutError,
)


class CrawlTool(Tool):
    """
    Recursive website crawling tool powered by PageSift.
    Cuts crawl time with zero-overhead async dispatch.
    """

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        url = tool_parameters.get("url")
        if not url:
            yield self.create_text_message("Error: 'url' parameter is required.")
            return

        try:
            limit = int(tool_parameters.get("limit", 5))
            if limit < 1:
                limit = 1
            elif limit > 100:
                limit = 100
        except (ValueError, TypeError):
            limit = 5

        credentials = self.runtime.credentials or {}
        base_url = credentials.get("base_url") or "http://localhost:3002"
        api_key = credentials.get("api_key")

        try:
            client = PageSiftClient(base_url=base_url, api_key=api_key)
            job_id = client.start_crawl(url=url, limit=limit)

            yield self.create_text_message(f"Initiated crawl job `{job_id}` for {url} (limit: {limit}). Waiting for completion...")

            # Monotonic deadline polling
            poll_interval = 1.0
            max_wait_seconds = 60.0
            deadline = time.monotonic() + max_wait_seconds

            completed_data = None
            last_status = "submitted"

            while time.monotonic() < deadline:
                status_res = client.get_crawl_status(job_id)
                last_status = status_res.get("status", "running")

                if last_status == "completed":
                    completed_data = status_res.get("data", [])
                    break
                elif last_status == "failed":
                    err_msg = status_res.get("error", "Unknown crawler error")
                    yield self.create_text_message(f"Crawl job `{job_id}` failed: {err_msg}")
                    return

                time.sleep(poll_interval)

            if completed_data is not None:
                pages_count = len(completed_data)
                summary_lines = [f"### Crawl Finished: {pages_count} page(s) retrieved\n"]
                for i, page in enumerate(completed_data, 1):
                    meta = page.get("metadata", {})
                    title = meta.get("title") or page.get("url")
                    p_url = page.get("url", "")
                    summary_lines.append(f"{i}. [{title}]({p_url})")

                yield self.create_text_message("\n".join(summary_lines))
                yield self.create_json_message({
                    "job_id": job_id,
                    "status": "completed",
                    "count": pages_count,
                    "pages": completed_data,
                })
            else:
                yield self.create_text_message(
                    f"Crawl job `{job_id}` timed out after {max_wait_seconds:.0f}s (last status: {last_status})."
                )

        except PageSiftSSRFError as e:
            yield self.create_text_message(f"Security Alert: Blocked crawl root URL '{url}' due to SSRF policy: {e}")
        except PageSiftAuthError as e:
            yield self.create_text_message(f"Authentication Error: {e}")
        except PageSiftRateLimitError as e:
            yield self.create_text_message(f"Rate Limit Exceeded: {e}")
        except PageSiftTimeoutError as e:
            yield self.create_text_message(f"Timeout Error: {e}")
        except PageSiftError as e:
            yield self.create_text_message(f"PageSift Crawl Error: {e}")
        except Exception as e:
            yield self.create_text_message(f"Unexpected Error during crawl: {e}")
