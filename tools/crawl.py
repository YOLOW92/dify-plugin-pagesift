from collections.abc import Generator
from typing import Any
import time
import requests
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

class CrawlTool(Tool):
    """
    Recursive website crawling tool powered by PageSift.
    """
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        url = tool_parameters.get("url")
        limit = int(tool_parameters.get("limit", 5))

        if not url:
            yield self.create_text_message("Error: 'url' parameter is required.")
            return

        base_url = (self.runtime.credentials.get("base_url") or "http://localhost:3002").rstrip("/")
        api_key = self.runtime.credentials.get("api_key")

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "url": url,
            "limit": limit,
            "scrapeOptions": {
                "formats": ["markdown"],
                "onlyMainContent": True
            }
        }

        try:
            # Start crawl job
            start_resp = requests.post(
                f"{base_url}/v1/crawl",
                json=payload,
                headers=headers,
                timeout=30,
            )
            start_resp.raise_for_status()
            job_data = start_resp.json()

            job_id = job_data.get("id") or job_data.get("jobId")
            if not job_id:
                yield self.create_text_message(f"Failed to initiate crawl: {job_data}")
                return

            # Poll status with a timeout
            max_retries = 30
            completed_data = None
            for _ in range(max_retries):
                time.sleep(1.0)
                status_resp = requests.get(
                    f"{base_url}/v1/crawl/{job_id}",
                    headers=headers,
                    timeout=15,
                )
                status_resp.raise_for_status()
                res = status_resp.json()

                status = res.get("status")
                if status == "completed":
                    completed_data = res.get("data", [])
                    break
                elif status == "failed":
                    yield self.create_text_message(f"Crawl job failed: {res.get('error')}")
                    return

            if completed_data is not None:
                summary = [f"### Crawled {len(completed_data)} page(s) successfully:\n"]
                for i, page in enumerate(completed_data, 1):
                    meta = page.get("metadata", {})
                    title = meta.get("title") or page.get("url")
                    page_url = page.get("url", "")
                    summary.append(f"{i}. [{title}]({page_url})")

                yield self.create_text_message("\n".join(summary))
                yield self.create_json_message({"pages": completed_data, "count": len(completed_data)})
            else:
                yield self.create_text_message("Crawl job timed out before completion.")

        except Exception as e:
            yield self.create_text_message(f"Crawl failed: {str(e)}")
