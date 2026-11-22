"""Website URL discovery tool for Dify using PageSift 1.6.3 (/v2/map)."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from lib.tool_helpers import (
    build_client_from_credentials,
    collect_warnings,
    format_tool_error,
    parse_bool,
    parse_optional_int,
)


class MapSiteTool(Tool):
    """Fast site URL mapping via PageSift POST /v2/map."""

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        url = (tool_parameters.get("url") or "").strip()
        if not url:
            yield self.create_text_message("Error: 'url' parameter is required.")
            return

        search = (tool_parameters.get("search") or "").strip() or None
        limit = (
            parse_optional_int(
                tool_parameters.get("limit"), min_val=1, max_val=100_000, default=100
            )
            or 100
        )
        sitemap = (tool_parameters.get("sitemap") or "include").strip() or "include"
        include_subdomains = parse_bool(tool_parameters.get("include_subdomains"), default=True)
        ignore_query_parameters = parse_bool(
            tool_parameters.get("ignore_query_parameters"), default=True
        )

        try:
            with build_client_from_credentials(self.runtime.credentials) as client:
                res = client.map_site(
                    url=url,
                    search=search,
                    sitemap=sitemap,
                    include_subdomains=include_subdomains,
                    ignore_query_parameters=ignore_query_parameters,
                    limit=limit,
                )

            links = res.get("links") or []
            urls = [str(item["url"]) for item in links if isinstance(item, dict) and item.get("url")]
            warnings = collect_warnings(res)

            lines = [f"### Site Map for {url}: {len(urls)} URL(s) found\n"]
            for idx, item in enumerate(links[:200], 1):
                if not isinstance(item, dict):
                    continue
                u = item.get("url", "")
                title = item.get("title")
                lines.append(f"{idx}. [{title}]({u})" if title else f"{idx}. {u}")
            if len(links) > 200:
                lines.append(f"\n... and {len(links) - 200} more URLs (see JSON/variable output).")

            payload = {
                "url": url,
                "count": len(urls),
                "urls": urls,
                "links": links,
                "warnings": warnings,
            }

            yield self.create_text_message("\n".join(lines))
            yield self.create_json_message(payload)
            yield self.create_variable_message("count", len(urls))
            yield self.create_variable_message("urls", urls)
            yield self.create_variable_message("links", links)
            yield self.create_variable_message("warnings", warnings)

        except Exception as e:
            yield self.create_text_message(format_tool_error(e, "site mapping"))
