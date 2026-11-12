"""Read webpage to Markdown tool for Dify using PageSift."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
import yaml

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


class ReadUrlTool(Tool):
    """
    Sub-millisecond web extraction tool powered by PageSift.
    Extracts high-fidelity, noise-free Markdown and rich metadata.
    """

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        url = tool_parameters.get("url")
        if not url:
            yield self.create_text_message("Error: 'url' parameter is required.")
            return

        only_main_content = tool_parameters.get("only_main_content", True)
        include_metadata = tool_parameters.get("include_metadata", True)

        credentials = self.runtime.credentials or {}
        base_url = credentials.get("base_url") or "http://localhost:3002"
        api_key = credentials.get("api_key")

        try:
            client = PageSiftClient(base_url=base_url, api_key=api_key)
            result = client.scrape(
                url=url,
                formats=["markdown"],
                only_main_content=bool(only_main_content),
            )

            data = result.get("data", {})
            markdown = data.get("markdown", "")
            metadata = data.get("metadata", {})

            if include_metadata and metadata:
                # Render clean, safe YAML front-matter
                clean_meta = {k: v for k, v in metadata.items() if v is not None and v != ""}
                if clean_meta:
                    front_matter = yaml.safe_dump(
                        clean_meta,
                        allow_unicode=True,
                        sort_keys=False,
                        default_flow_style=False,
                    ).strip()
                    final_content = f"---\n{front_matter}\n---\n\n{markdown}"
                else:
                    final_content = markdown
            else:
                final_content = markdown

            yield self.create_text_message(final_content)
            yield self.create_json_message(data)

        except PageSiftSSRFError as e:
            yield self.create_text_message(f"Security Alert: Blocked target URL '{url}' due to SSRF policy: {e}")
        except PageSiftAuthError as e:
            yield self.create_text_message(f"Authentication Error: {e}")
        except PageSiftRateLimitError as e:
            msg = f"Rate Limit Exceeded: {e}"
            if e.retry_after:
                msg += f" Please retry after {e.retry_after:.1f} seconds."
            yield self.create_text_message(msg)
        except PageSiftTimeoutError as e:
            yield self.create_text_message(f"Timeout Error: {e}")
        except PageSiftError as e:
            yield self.create_text_message(f"PageSift Extraction Error: {e}")
        except Exception as e:
            yield self.create_text_message(f"Unexpected Error during extraction: {e}")
