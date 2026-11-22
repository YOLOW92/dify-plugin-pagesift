"""Read webpage to Markdown, chunks, structured extract, or DataGraph via PageSift 1.6.3."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from lib.tool_helpers import (
    build_chunking_config,
    build_client_from_credentials,
    build_graph_option,
    build_query_filter,
    collect_warnings,
    extract_document_url,
    format_markdown_with_frontmatter,
    format_tool_error,
    parse_bool,
    parse_json_object,
    parse_optional_int,
    parse_string_list,
)


class ReadUrlTool(Tool):
    """
    Sub-millisecond web extraction tool powered by PageSift 1.6.3 (/v2/scrape).
    Supports BM25 query filtering, Rust RAG chunking, zero-LLM CSS extraction with
    selector relocation, image assets, and DataGraph provenance extraction.
    """

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        url = (tool_parameters.get("url") or "").strip()
        if not url:
            yield self.create_text_message("Error: 'url' parameter is required.")
            return

        only_main_content = parse_bool(tool_parameters.get("only_main_content"), default=True)
        include_metadata = parse_bool(tool_parameters.get("include_metadata"), default=True)
        engine = (tool_parameters.get("engine") or "auto").strip() or "auto"
        formats = parse_string_list(tool_parameters.get("formats")) or ["markdown"]
        include_tags = parse_string_list(tool_parameters.get("include_tags"))
        exclude_tags = parse_string_list(tool_parameters.get("exclude_tags"))
        query_filter = build_query_filter(
            tool_parameters.get("query_filter"),
            parse_optional_int(tool_parameters.get("query_filter_max_tokens"), min_val=64),
        )
        chunking = build_chunking_config(
            tool_parameters.get("chunking_type"),
            parse_optional_int(tool_parameters.get("chunk_size"), min_val=32),
        )
        image_assets = (tool_parameters.get("image_assets") or "none").strip()
        enable_graph = parse_bool(tool_parameters.get("enable_graph"), default=False)
        max_age = parse_optional_int(tool_parameters.get("max_age"), min_val=0)

        try:
            extract_schema = parse_json_object(
                tool_parameters.get("extract_schema"), "extract_schema"
            )

            with build_client_from_credentials(self.runtime.credentials) as client:
                result = client.scrape(
                    url=url,
                    formats=formats,
                    only_main_content=only_main_content,
                    engine=engine,
                    include_tags=include_tags or None,
                    exclude_tags=exclude_tags or None,
                    max_age=max_age,
                    query_filter=query_filter,
                    chunking=chunking,
                    extract_schema=extract_schema,
                    image_assets=image_assets if image_assets != "none" else None,
                    graph=build_graph_option(enable_graph),
                )

            data = result.get("data", {})
            markdown = data.get("markdown", "")
            metadata = data.get("metadata", {}) or {}
            warnings = collect_warnings(result)
            final_url = extract_document_url(data) or url
            title = str(metadata.get("title") or "")

            final_content = format_markdown_with_frontmatter(
                markdown=markdown,
                metadata=metadata,
                include_metadata=include_metadata,
            )

            yield self.create_text_message(final_content)
            yield self.create_json_message(data)
            yield self.create_variable_message("markdown", markdown)
            yield self.create_variable_message("title", title)
            yield self.create_variable_message("url", final_url)
            yield self.create_variable_message("metadata", metadata)
            yield self.create_variable_message("warnings", warnings)
            if data.get("chunks") is not None:
                yield self.create_variable_message("chunks", data["chunks"])
            if data.get("extract") is not None:
                yield self.create_variable_message("extract", data["extract"])
            if data.get("graph") is not None:
                yield self.create_variable_message("graph", data["graph"])

        except Exception as e:
            yield self.create_text_message(format_tool_error(e, "webpage extraction"))
