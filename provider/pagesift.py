"""PageSift ToolProvider implementation for Dify Plugin Framework."""

from __future__ import annotations

import logging
from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from lib.errors import PageSiftAuthError, PageSiftError
from lib.tool_helpers import build_client_from_credentials

logger = logging.getLogger(__name__)


class PageSiftToolProvider(ToolProvider):
    """Provider for PageSift 1.6.3 high-throughput web, document, and context engine."""

    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """
        Validate configured PageSift server URL, optional API Key, and default timeout.
        Raises ToolProviderCredentialValidationError if unreachable, misconfigured, or unauthorized.
        """
        base_url = credentials.get("base_url") or "http://localhost:3002"
        raw_timeout = credentials.get("default_timeout")
        if raw_timeout not in (None, ""):
            try:
                t = float(raw_timeout)
                if t < 1.0 or t > 300.0:
                    raise ToolProviderCredentialValidationError(
                        "Default timeout must be between 1 and 300 seconds."
                    )
            except ValueError as e:
                raise ToolProviderCredentialValidationError(
                    f"Invalid default_timeout '{raw_timeout}': must be a number between 1 and 300."
                ) from e

        try:
            with build_client_from_credentials(credentials) as client:
                client.validate_connection()
        except PageSiftAuthError as e:
            raise ToolProviderCredentialValidationError(f"Authentication failed: {e}") from e
        except PageSiftError as e:
            raise ToolProviderCredentialValidationError(f"PageSift server check failed: {e}") from e
        except Exception as e:
            raise ToolProviderCredentialValidationError(
                f"Cannot connect to PageSift server at '{base_url}': {e}"
            ) from e
