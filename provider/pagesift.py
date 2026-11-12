"""PageSift ToolProvider implementation for Dify Plugin Framework."""

from __future__ import annotations

import logging
from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from lib.client import PageSiftClient
from lib.errors import PageSiftAuthError, PageSiftError

logger = logging.getLogger(__name__)


class PageSiftToolProvider(ToolProvider):
    """Provider for PageSift high-throughput extraction engine."""

    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """
        Validate configured PageSift server URL and optional API Key.
        Raises ToolProviderCredentialValidationError if unreachable or unauthorized.
        """
        base_url = credentials.get("base_url") or "http://localhost:3002"
        api_key = credentials.get("api_key")

        try:
            client = PageSiftClient(base_url=base_url, api_key=api_key)
            client.validate_connection()
        except PageSiftAuthError as e:
            raise ToolProviderCredentialValidationError(f"Invalid API Key: {e}") from e
        except PageSiftError as e:
            raise ToolProviderCredentialValidationError(f"PageSift server check failed: {e}") from e
        except Exception as e:
            raise ToolProviderCredentialValidationError(f"Cannot connect to PageSift server at '{base_url}': {e}") from e
