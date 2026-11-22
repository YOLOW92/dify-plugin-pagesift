"""Full-format document & source-code parsing tool for Dify using PageSift 1.6.3 (/v2/parse)."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from lib.errors import PageSiftDocumentError
from lib.tool_helpers import (
    build_chunking_config,
    build_client_from_credentials,
    build_graph_option,
    build_query_filter,
    collect_warnings,
    format_tool_error,
    parse_bool,
    parse_optional_int,
)
from lib.validation import safe_download_file

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB hard cap matching PageSift MAX_PARSE_FILE_BYTES


class ParseDocumentTool(Tool):
    """
    Universal document, archive, image (OCR), and source-code parser powered by PageSift 1.6.3.
    Uses standard `parsers: [{"type": "pdf", "mode": ...}]` options on POST /v2/parse.
    """

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        file_obj = tool_parameters.get("file")
        file_url = (tool_parameters.get("file_url") or "").strip()
        enable_ocr = parse_bool(tool_parameters.get("enable_ocr"), default=False)
        raw_pdf_mode = (tool_parameters.get("pdf_mode") or "").strip().lower()
        max_pages = parse_optional_int(
            tool_parameters.get("max_pages"), min_val=1, max_val=10_000
        )
        per_page = parse_bool(tool_parameters.get("per_page"), default=False)
        source_url = (tool_parameters.get("source_url") or "").strip() or None
        query_filter = build_query_filter(tool_parameters.get("query_filter"))
        chunking = build_chunking_config(
            tool_parameters.get("chunking_type"),
            parse_optional_int(tool_parameters.get("chunk_size"), min_val=32),
        )
        image_assets = (tool_parameters.get("image_assets") or "none").strip()
        enable_graph = parse_bool(tool_parameters.get("enable_graph"), default=False)

        if not file_obj and not file_url:
            yield self.create_text_message(
                "Error: A valid Dify 'file' object or 'file_url' must be provided."
            )
            return

        # Resolve effective PDF mode: explicit enable_ocr=True overrides default 'auto' to 'ocr'
        pdf_mode: str | None = None
        if enable_ocr:
            pdf_mode = "ocr"
        elif raw_pdf_mode in ("auto", "fast", "ocr"):
            pdf_mode = raw_pdf_mode

        try:
            file_bytes: bytes | None = None
            filename = "document"
            content_type: str | None = None

            # 1. Handle Dify file object parameter (type: file)
            if file_obj:
                fn = getattr(file_obj, "filename", None) or (
                    file_obj.get("filename") if isinstance(file_obj, dict) else None
                )
                if fn:
                    filename = str(fn)

                mt = getattr(file_obj, "mime_type", None) or (
                    file_obj.get("mime_type") if isinstance(file_obj, dict) else None
                )
                if mt:
                    content_type = str(mt)

                if hasattr(file_obj, "blob") and file_obj.blob:
                    file_bytes = file_obj.blob
                elif isinstance(file_obj, dict) and file_obj.get("blob"):
                    file_bytes = file_obj["blob"]

                target_url = getattr(file_obj, "url", None) or (
                    file_obj.get("url") if isinstance(file_obj, dict) else None
                )
                if not file_bytes and target_url:
                    # Dify-managed file URLs may live on the internal Docker network in self-hosted setups;
                    # external user-supplied `file_url` always enforces strict public-only SSRF below.
                    file_bytes = safe_download_file(
                        url=str(target_url),
                        max_size=MAX_FILE_SIZE,
                        timeout=30.0,
                        allow_private=False,
                    )

            # 2. Handle direct user-supplied file_url (strict SSRF enforced)
            elif file_url:
                file_bytes = safe_download_file(
                    url=file_url,
                    max_size=MAX_FILE_SIZE,
                    timeout=30.0,
                    allow_private=False,
                )
                clean_name = file_url.split("?")[0].rstrip("/").split("/")[-1]
                if clean_name:
                    filename = clean_name

            if not file_bytes:
                yield self.create_text_message(
                    "Error: Unable to read file content or file is empty."
                )
                return

            if len(file_bytes) > MAX_FILE_SIZE:
                raise PageSiftDocumentError(
                    f"File size {len(file_bytes) / (1024 * 1024):.1f}MB exceeds maximum limit of "
                    f"{MAX_FILE_SIZE // (1024 * 1024)}MB.",
                    code="TOO_LARGE",
                    status_code=413,
                )

            # Give OCR or large document parsing generous timeout headroom
            parse_timeout = 120.0 if (pdf_mode == "ocr" or len(file_bytes) > 5 * 1024 * 1024) else 60.0

            with build_client_from_credentials(
                self.runtime.credentials, timeout_override=parse_timeout
            ) as client:
                result = client.parse_document(
                    file_bytes=file_bytes,
                    filename=filename,
                    ocr=enable_ocr,
                    timeout=parse_timeout,
                    content_type=content_type,
                    pdf_mode=pdf_mode,
                    max_pages=max_pages,
                    per_page=per_page,
                    query_filter=query_filter,
                    chunking=chunking,
                    image_assets=image_assets if image_assets != "none" else None,
                    graph=build_graph_option(enable_graph),
                    source_url=source_url,
                )

            data = result.get("data", {})
            markdown = data.get("markdown", "")
            metadata = data.get("metadata", {}) or {}
            warnings = collect_warnings(result)

            yield self.create_text_message(markdown)
            yield self.create_json_message(data)
            yield self.create_variable_message("markdown", markdown)
            yield self.create_variable_message("filename", filename)
            yield self.create_variable_message("metadata", metadata)
            yield self.create_variable_message("warnings", warnings)
            if data.get("pages") is not None:
                yield self.create_variable_message("pages", data["pages"])
            if data.get("chunks") is not None:
                yield self.create_variable_message("chunks", data["chunks"])
            if data.get("graph") is not None:
                yield self.create_variable_message("graph", data["graph"])

        except Exception as e:
            yield self.create_text_message(format_tool_error(e, "document parse"))
