from collections.abc import Generator
from typing import Any
import json
import os
import io
import requests
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

class ParseDocumentTool(Tool):
    """
    Sub-second document extraction tool powered by PageSift, yolowpdf, and pure-Rust Office parser.
    Converts PDF, DOCX, XLSX, PPTX, EPUB, and CSV into structured LLM Markdown.
    """
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        file_url = tool_parameters.get("file_url")
        file_path = tool_parameters.get("file_path")
        enable_ocr = tool_parameters.get("enable_ocr", False)

        if not file_url and not file_path:
            yield self.create_text_message("Error: Either 'file_url' or 'file_path' must be provided.")
            return

        base_url = (self.runtime.credentials.get("base_url") or "http://localhost:3002").rstrip("/")
        api_key = self.runtime.credentials.get("api_key")

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            file_bytes = None
            filename = "document"

            if file_path:
                if not os.path.exists(file_path):
                    yield self.create_text_message(f"Error: File not found at path '{file_path}'.")
                    return
                filename = os.path.basename(file_path)
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
            elif file_url:
                resp = requests.get(file_url, timeout=30)
                resp.raise_for_status()
                file_bytes = resp.content
                filename = file_url.split("?")[0].rstrip("/").split("/")[-1] or "document"

            files = {
                "file": (filename, io.BytesIO(file_bytes), "application/octet-stream")
            }
            data_payload = {
                "options": json.dumps({"ocr": enable_ocr})
            }

            parse_resp = requests.post(
                f"{base_url}/v2/parse",
                files=files,
                data=data_payload,
                headers=headers,
                timeout=60,
            )
            parse_resp.raise_for_status()
            res_json = parse_resp.json()

            if res_json.get("success"):
                item_data = res_json.get("data", {})
                markdown = item_data.get("markdown", "")
                metadata = item_data.get("metadata", {})

                yield self.create_text_message(markdown)
                yield self.create_json_message(item_data)
            else:
                err_msg = res_json.get("error", "Unknown document parse error")
                yield self.create_text_message(f"Parse failed: {err_msg}")

        except Exception as e:
            yield self.create_text_message(f"Document parse failed: {str(e)}")
