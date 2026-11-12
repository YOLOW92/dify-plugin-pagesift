"""Document parsing tool for Dify using PageSift & yolowpdf."""

from __future__ import annotations

from collections.abc import Generator
import os
from typing import Any
import requests

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from lib.client import PageSiftClient
from lib.errors import (
    PageSiftAuthError,
    PageSiftDocumentError,
    PageSiftError,
    PageSiftRateLimitError,
    PageSiftSSRFError,
    PageSiftTimeoutError,
)
from lib.validation import safe_download_file, validate_target_url

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB safety limit


class ParseDocumentTool(Tool):
    """
    Sub-second document extraction tool powered by PageSift, yolowpdf, and pure-Rust Office parser.
    Converts PDF, DOCX, XLSX, PPTX, EPUB, and CSV into structured LLM Markdown.
    """

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        file_obj = tool_parameters.get("file")
        file_url = tool_parameters.get("file_url")
        enable_ocr = bool(tool_parameters.get("enable_ocr", False))

        if not file_obj and not file_url:
            yield self.create_text_message("Error: A valid Dify 'file' object or 'file_url' must be provided.")
            return

        credentials = self.runtime.credentials or {}
        base_url = credentials.get("base_url") or "http://localhost:3002"
        api_key = credentials.get("api_key")

        try:
            file_bytes: bytes | None = None
            filename = "document"

            # 1. Handle Dify file object parameter (type: file)
            if file_obj:
                # Direct blob
                if hasattr(file_obj, "blob") and file_obj.blob:
                    file_bytes = file_obj.blob
                elif isinstance(file_obj, dict) and file_obj.get("blob"):
                    file_bytes = file_obj["blob"]

                # Extract filename if available
                fn = getattr(file_obj, "filename", None) or (
                    file_obj.get("filename") if isinstance(file_obj, dict) else None
                )
                if fn:
                    filename = fn

                # Download via url if blob was not supplied
                target_url = getattr(file_obj, "url", None) or (
                    file_obj.get("url") if isinstance(file_obj, dict) else None
                )
                if not file_bytes and target_url:
                    file_bytes = safe_download_file(
                        url=target_url,
                        max_size=MAX_FILE_SIZE,
                        timeout=30.0,
                        allow_private=False,
                    )

            # 2. Handle direct file_url
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
                yield self.create_text_message("Error: Unable to read file content or file is empty.")
                return

            if len(file_bytes) > MAX_FILE_SIZE:
                raise PageSiftDocumentError(
                    f"File size {len(file_bytes) / (1024*1024):.1f}MB exceeds maximum limit of {MAX_FILE_SIZE // (1024*1024)}MB."
                )

            client = PageSiftClient(base_url=base_url, api_key=api_key)
            result = client.parse_document(
                file_bytes=file_bytes,
                filename=filename,
                ocr=enable_ocr,
            )

            data = result.get("data", {})
            markdown = data.get("markdown", "")

            yield self.create_text_message(markdown)
            yield self.create_json_message(data)

        except PageSiftSSRFError as e:
            yield self.create_text_message(f"Security Alert: Blocked file download URL due to SSRF policy: {e}")
        except PageSiftAuthError as e:
            yield self.create_text_message(f"Authentication Error: {e}")
        except PageSiftDocumentError as e:
            yield self.create_text_message(f"Document Extraction Error: {e}")
        except PageSiftRateLimitError as e:
            yield self.create_text_message(f"Rate Limit Exceeded: {e}")
        except PageSiftTimeoutError as e:
            yield self.create_text_message(f"Timeout Error: {e}")
        except PageSiftError as e:
            yield self.create_text_message(f"PageSift Error: {e}")
        except Exception as e:
            yield self.create_text_message(f"Unexpected Error during document parse: {e}")
