from collections.abc import Generator
from typing import Any
import requests
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

class ReadUrlTool(Tool):
    """
    Sub-millisecond web extraction tool powered by PageSift and yolowhtml.
    Extracts high-fidelity, noise-free Markdown and rich metadata.
    """
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        url = tool_parameters.get("url")
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
            "formats": ["markdown"],
            "onlyMainContent": tool_parameters.get("only_main_content", True),
        }

        try:
            resp = requests.post(
                f"{base_url}/v1/scrape",
                json=payload,
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("success"):
                item_data = data.get("data", {})
                markdown = item_data.get("markdown", "")
                metadata = item_data.get("metadata", {})

                if tool_parameters.get("include_metadata", True) and metadata:
                    meta_header = ["---"]
                    for k, v in metadata.items():
                        if v is not None and v != "":
                            meta_header.append(f"{k}: {v}")
                    meta_header.append("---\n")
                    final_markdown = "\n".join(meta_header) + "\n" + markdown
                else:
                    final_markdown = markdown

                yield self.create_text_message(final_markdown)
                yield self.create_json_message(item_data)
            else:
                error_msg = data.get("error", "Unknown extraction error")
                yield self.create_text_message(f"Extraction failed: {error_msg}")
        except Exception as e:
            yield self.create_text_message(f"PageSift request failed: {str(e)}")
