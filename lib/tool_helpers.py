"""Shared parameter parsing, formatting, and error-handling helpers for PageSift Dify tools."""

from __future__ import annotations

import json
from typing import Any
import yaml

from lib.client import PageSiftClient
from lib.errors import (
    PageSiftAuthError,
    PageSiftDocumentError,
    PageSiftError,
    PageSiftForbiddenError,
    PageSiftInvalidRequestError,
    PageSiftNotFoundError,
    PageSiftRateLimitError,
    PageSiftServiceError,
    PageSiftSSRFError,
    PageSiftTimeoutError,
    PageSiftUnsupportedError,
)


def build_client_from_credentials(
    credentials: dict[str, Any] | None,
    timeout_override: float | None = None,
) -> PageSiftClient:
    """Create a configured PageSiftClient from Dify provider credentials."""
    creds = credentials or {}
    base_url = creds.get("base_url") or "http://localhost:3002"
    api_key = creds.get("api_key")
    session_id = creds.get("session_id")

    timeout = 30.0
    raw_default = creds.get("default_timeout")
    if raw_default not in (None, ""):
        try:
            timeout = float(raw_default)
        except (TypeError, ValueError):
            timeout = 30.0

    if timeout_override is not None:
        timeout = float(timeout_override)

    return PageSiftClient(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        session_id=session_id,
    )


def parse_bool(value: Any, default: bool = False) -> bool:
    """Parse boolean parameter defensively from Python bool or string."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off"):
        return False
    return default


def parse_optional_int(
    value: Any,
    *,
    min_val: int | None = None,
    max_val: int | None = None,
    default: int | None = None,
) -> int | None:
    """Parse optional integer with optional clamping."""
    if value is None or value == "":
        return default
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default
    if min_val is not None and parsed < min_val:
        parsed = min_val
    if max_val is not None and parsed > max_val:
        parsed = max_val
    return parsed


def parse_optional_float(
    value: Any,
    *,
    min_val: float | None = None,
    max_val: float | None = None,
    default: float | None = None,
) -> float | None:
    """Parse optional float with optional clamping."""
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if min_val is not None and parsed < min_val:
        parsed = min_val
    if max_val is not None and parsed > max_val:
        parsed = max_val
    return parsed


def parse_string_list(value: Any) -> list[str]:
    """
    Parse a string list from a Python list, JSON array string, or newline/comma-separated text.
    """
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            loaded = json.loads(text)
            if isinstance(loaded, list):
                return [str(v).strip() for v in loaded if str(v).strip()]
        except json.JSONDecodeError:
            pass
    # Split on newlines first; if single line, also split on commas
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) == 1 and "," in lines[0]:
        return [part.strip() for part in lines[0].split(",") if part.strip()]
    return lines


def parse_json_object(value: Any, field_name: str) -> dict[str, Any] | None:
    """Parse an optional JSON object (from dict or JSON string), raising PageSiftInvalidRequestError."""
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise PageSiftInvalidRequestError(f"Invalid JSON in '{field_name}': {e}") from e
    if not isinstance(parsed, dict):
        raise PageSiftInvalidRequestError(f"Parameter '{field_name}' must be a JSON object.")
    return parsed


def parse_json_list(value: Any, field_name: str) -> list[Any] | None:
    """Parse an optional JSON array (from list or JSON string)."""
    if value is None or value == "":
        return None
    if isinstance(value, list):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise PageSiftInvalidRequestError(f"Invalid JSON in '{field_name}': {e}") from e
    if not isinstance(parsed, list):
        raise PageSiftInvalidRequestError(f"Parameter '{field_name}' must be a JSON array.")
    return parsed


def normalize_context_documents(raw: Any, field_name: str = "documents") -> list[dict[str, Any]] | None:
    """
    Parse and normalize inline Context documents for /v2/context/{ingest,search,pack,action}.

    Accepts:
    - A list of ContextDocumentInput dicts (`{url, markdown, ...}`)
    - A single PageSift Document dict (`{markdown, metadata: {url, title, ...}}`)
    - A crawl/batch output dict (`{pages: [...]}`)
    - A JSON string encoding any of the above.
    """
    if raw is None or raw == "":
        return None

    parsed = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise PageSiftInvalidRequestError(f"Invalid JSON in '{field_name}': {e}") from e

    items: list[Any]
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        if isinstance(parsed.get("pages"), list):
            items = parsed["pages"]
        elif isinstance(parsed.get("data"), list):
            items = parsed["data"]
        elif isinstance(parsed.get("data"), dict):
            items = [parsed["data"]]
        else:
            items = [parsed]
    else:
        raise PageSiftInvalidRequestError(
            f"Parameter '{field_name}' must be a JSON array or document object."
        )

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise PageSiftInvalidRequestError(
                f"Entry #{idx} in '{field_name}' must be a JSON object."
            )
        # Already a ContextDocumentInput
        if "url" in item and "markdown" in item:
            normalized.append(item)
            continue
        # Adapt PageSift scrape/parse/crawl Document shape (`{markdown, metadata: {...}}`)
        markdown = item.get("markdown")
        if markdown is None:
            raise PageSiftInvalidRequestError(
                f"Entry #{idx} in '{field_name}' is missing required 'markdown' field."
            )
        meta = item.get("metadata") or {}
        url = (
            item.get("url")
            or meta.get("url")
            or meta.get("sourceURL")
            or f"inline://doc-{idx + 1}"
        )
        doc_entry: dict[str, Any] = {
            "url": str(url),
            "markdown": str(markdown),
        }
        title = item.get("title") or meta.get("title")
        if title:
            doc_entry["title"] = str(title)
        for passthrough in (
            "sourceKind",
            "observedAtMs",
            "validFrom",
            "validUntil",
            "subjectKey",
            "originRoot",
            "originIndependent",
            "statusCode",
            "unreliable",
            "confirmedGone",
        ):
            if passthrough in item and item[passthrough] is not None:
                doc_entry[passthrough] = item[passthrough]
        normalized.append(doc_entry)

    return normalized


def build_query_filter(
    query: str | None,
    max_tokens: int | None = None,
) -> str | dict[str, Any] | None:
    """Construct PageSift `queryFilter` payload from query text and optional token cap."""
    q = (query or "").strip()
    if not q:
        return None
    if max_tokens is not None and max_tokens > 0:
        return {"query": q, "maxTokens": int(max_tokens)}
    return q


def build_chunking_config(
    chunking_type: str | None,
    chunk_size: int | None = None,
) -> dict[str, Any] | None:
    """Construct PageSift `ChunkStrategy` payload with required strategy-specific defaults."""
    ct = (chunking_type or "").strip()
    if not ct or ct == "none":
        return None
    target_size = int(chunk_size) if (chunk_size is not None and chunk_size > 0) else 400
    if ct in ("recursive", "fixed_tokens"):
        return {"type": ct, "size": target_size}
    if ct == "sliding_window":
        return {"type": ct, "window": target_size, "step": max(1, target_size // 2)}
    if ct == "overlapping":
        return {"type": ct, "window": target_size, "overlap": max(1, target_size // 4)}
    # headings, paragraphs, sentences, regex take no required `size` field
    return {"type": ct}


def build_graph_option(
    enable_graph: bool,
    subject_keys: list[str] | None = None,
) -> bool | dict[str, Any] | None:
    """Construct PageSift 1.4+ `graph` option payload."""
    if not enable_graph and not subject_keys:
        return None
    if subject_keys:
        return {"enabled": True, "subjectKeys": subject_keys}
    return True


def collect_warnings(response_or_data: dict[str, Any]) -> list[str]:
    """Collect deduplicated warnings from top-level response, data.warning, and metadata.pagesift.warnings."""
    seen: set[str] = set()
    out: list[str] = []

    def add(item: Any) -> None:
        if isinstance(item, str):
            w = item.strip()
            if w and w not in seen:
                seen.add(w)
                out.append(w)
        elif isinstance(item, list):
            for x in item:
                add(x)

    add(response_or_data.get("warning"))
    add(response_or_data.get("warnings"))

    data = response_or_data.get("data")
    if isinstance(data, dict):
        add(data.get("warning"))
        ps = (data.get("metadata") or {}).get("pagesift")
        if isinstance(ps, dict):
            add(ps.get("warnings"))

    meta = response_or_data.get("metadata")
    if isinstance(meta, dict):
        ps = meta.get("pagesift")
        if isinstance(ps, dict):
            add(ps.get("warnings"))

    for key in ("report", "pack", "outcome"):
        nested = response_or_data.get(key)
        if isinstance(nested, dict):
            add(nested.get("warnings"))
            if isinstance(nested.get("pack"), dict):
                add(nested["pack"].get("warnings"))

    return out


def extract_document_url(doc: dict[str, Any]) -> str:
    """Extract canonical/final URL from a PageSift Document object."""
    meta = doc.get("metadata") or {}
    return str(
        meta.get("url")
        or meta.get("sourceURL")
        or doc.get("url")
        or ""
    )


def format_markdown_with_frontmatter(
    markdown: str,
    metadata: dict[str, Any] | None,
    include_metadata: bool = True,
) -> str:
    """Render clean YAML frontmatter ahead of Markdown content when requested."""
    if not include_metadata or not metadata:
        return markdown

    # Keep frontmatter compact and readable: drop empty values and bulky nested pagesift traces
    clean_meta: dict[str, Any] = {}
    for k, v in metadata.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        if k == "pagesift" and isinstance(v, dict):
            compact_ps = {
                pk: pv
                for pk, pv in v.items()
                if pk in ("engine", "browserEngine", "warnings", "ocr", "contentHash")
                and pv not in (None, "", [], {})
            }
            if compact_ps:
                clean_meta["pagesift"] = compact_ps
            continue
        clean_meta[k] = v

    if not clean_meta:
        return markdown

    front_matter = yaml.safe_dump(
        clean_meta,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return f"---\n{front_matter}\n---\n\n{markdown}"


def format_tool_error(exc: Exception, context_label: str = "operation") -> str:
    """Format any PageSiftError into a clear, actionable message for Dify users and LLMs."""
    if isinstance(exc, PageSiftSSRFError):
        return f"Security Alert (SSRF Blocked): {exc.message}"
    if isinstance(exc, PageSiftAuthError):
        return f"Authentication Error ({exc.code}): {exc.message}"
    if isinstance(exc, PageSiftForbiddenError):
        msg = f"Access Denied ({exc.code}): {exc.message}"
        if isinstance(exc.details, dict) and exc.details.get("needsHuman"):
            msg += " (Target requires interactive human verification / CAPTCHA.)"
        return msg
    if isinstance(exc, PageSiftRateLimitError):
        label = {
            "QUOTA_EXCEEDED": "Daily Page Quota Exceeded",
            "CONCURRENCY_LIMIT_EXCEEDED": "Concurrency Limit Exceeded",
            "RATE_LIMIT_EXCEEDED": "API Key Rate Limit Exceeded",
        }.get(exc.code, "Rate Limit Exceeded")
        msg = f"{label} ({exc.code}): {exc.message}"
        if exc.retry_after is not None:
            msg += f" Please retry after {exc.retry_after:.1f} seconds."
        return msg
    if isinstance(exc, PageSiftTimeoutError):
        return f"Timeout Error ({exc.code}): {exc.message}"
    if isinstance(exc, PageSiftUnsupportedError):
        return f"Unsupported Option ({exc.code}): {exc.message}"
    if isinstance(exc, PageSiftInvalidRequestError):
        return f"Invalid Request ({exc.code}): {exc.message}"
    if isinstance(exc, PageSiftNotFoundError):
        return f"Not Found ({exc.code}): {exc.message}"
    if isinstance(exc, PageSiftDocumentError):
        return f"Document Error ({exc.code}): {exc.message}"
    if isinstance(exc, PageSiftServiceError):
        return f"PageSift Service Error ({exc.code}, HTTP {exc.status_code}): {exc.message}"
    if isinstance(exc, PageSiftError):
        return f"PageSift Error ({exc.code}): {exc.message}"
    return f"Unexpected Error during {context_label}: {exc}"
