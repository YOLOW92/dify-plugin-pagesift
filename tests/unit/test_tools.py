"""Comprehensive unit tests for all 9 PageSift 1.6.3 Dify tools and YAML manifests."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml
from dify_plugin.core.entities.plugin.setup import PluginConfiguration
from dify_plugin.entities.tool import ToolProviderConfiguration
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from lib.errors import PageSiftAuthError, PageSiftUnsupportedError
from lib.tool_helpers import build_chunking_config
from provider.pagesift import PageSiftToolProvider
from tools.batch_scrape import BatchScrapeTool
from tools.context_ingest import ContextIngestTool
from tools.context_pack import ContextPackTool
from tools.crawl import CrawlTool
from tools.map_site import MapSiteTool
from tools.parse_document import ParseDocumentTool
from tools.query_graph import QueryGraphTool
from tools.read_url import ReadUrlTool
from tools.sync_source import SyncSourceTool

ROOT = Path(__file__).resolve().parent.parent.parent


def mock_runtime(extra_creds=None):
    runtime = SimpleNamespace()
    creds = {
        "base_url": "http://127.0.0.1:3002",
        "api_key": "test_key",
        "session_id": "test-session",
        "default_timeout": "30",
    }
    if extra_creds:
        creds.update(extra_creds)
    runtime.credentials = creds
    return runtime


def _var_map(messages):
    out = {}
    for m in messages:
        if getattr(m.type, "value", m.type) == "variable":
            out[m.message.variable_name] = m.message.variable_value
    return out


# ----------------------------------------------------------------------
# Manifest, Provider & YAML Schema Validation
# ----------------------------------------------------------------------


def test_all_dify_manifests_validate_against_sdk():
    manifest_data = yaml.safe_load((ROOT / "manifest.yaml").read_text(encoding="utf-8"))
    manifest = PluginConfiguration(**manifest_data)
    assert manifest.name == "pagesift"
    assert manifest.version == "0.2.0"

    provider_data = yaml.safe_load((ROOT / "provider/pagesift.yaml").read_text(encoding="utf-8"))
    provider = ToolProviderConfiguration(**provider_data)
    tool_names = [t.identity.name for t in provider.tools]
    assert tool_names == [
        "read_url",
        "parse_document",
        "crawl",
        "map_site",
        "batch_scrape",
        "context_pack",
        "context_ingest",
        "sync_source",
        "query_graph",
    ]
    for tool_cfg in provider.tools:
        assert tool_cfg.output_schema is not None
        assert (ROOT / tool_cfg.extra.python.source).exists()


def test_provider_credential_validation_checks_timeout_and_auth():
    provider = PageSiftToolProvider()
    with pytest.raises(ToolProviderCredentialValidationError, match="between 1 and 300"):
        provider._validate_credentials({"base_url": "http://127.0.0.1:3002", "default_timeout": "999"})

    with patch("lib.client.PageSiftClient.validate_connection", side_effect=PageSiftAuthError("bad key")):
        with pytest.raises(ToolProviderCredentialValidationError, match="Authentication failed"):
            provider._validate_credentials({"base_url": "http://127.0.0.1:3002", "api_key": "bad"})


def test_build_chunking_config_matches_pagesift_rust_enum():
    assert build_chunking_config(None) is None
    assert build_chunking_config("none") is None
    assert build_chunking_config("recursive") == {"type": "recursive", "size": 400}
    assert build_chunking_config("recursive", 800) == {"type": "recursive", "size": 800}
    assert build_chunking_config("fixed_tokens", 256) == {"type": "fixed_tokens", "size": 256}
    assert build_chunking_config("sliding_window", 400) == {"type": "sliding_window", "window": 400, "step": 200}
    assert build_chunking_config("overlapping", 400) == {"type": "overlapping", "window": 400, "overlap": 100}
    assert build_chunking_config("headings", 400) == {"type": "headings"}
    assert build_chunking_config("paragraphs") == {"type": "paragraphs"}
    assert build_chunking_config("sentences") == {"type": "sentences"}


# ----------------------------------------------------------------------
# 1. read_url
# ----------------------------------------------------------------------


def test_read_url_missing_param():
    tool = ReadUrlTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(tool._invoke({}))
    assert len(messages) == 1
    assert "Error: 'url' parameter is required" in messages[0].message.text


@patch("lib.client.PageSiftClient.scrape")
def test_read_url_success_with_1_6_3_features(mock_scrape):
    mock_scrape.return_value = {
        "success": True,
        "warning": "decode: windows-1252",
        "data": {
            "markdown": "## Article Title\n\nArticle body here.",
            "metadata": {
                "title": "Article Title",
                "author": "Author Name",
                "url": "https://example.com/post-final",
                "pagesift": {"engine": "http", "warnings": ["decode: windows-1252"]},
            },
            "chunks": [{"text": "Article body here.", "headingPath": ["Article Title"], "start": 0, "end": 18, "tokens": 4}],
            "extract": [{"headline": "Article Title"}],
            "graph": {"node": {"id": "doc-1"}},
        },
    }
    tool = ReadUrlTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(
        tool._invoke(
            {
                "url": "https://example.com/post",
                "query_filter": "article body",
                "query_filter_max_tokens": 800,
                "engine": "http",
                "chunking_type": "recursive",
                "chunk_size": 400,
                "extract_schema": json.dumps({"baseSelector": "article", "fields": []}),
                "enable_graph": True,
                "max_age": 0,
            }
        )
    )
    assert "## Article Title" in messages[0].message.text
    assert "title: Article Title" in messages[0].message.text
    variables = _var_map(messages)
    assert variables["url"] == "https://example.com/post-final"
    assert variables["title"] == "Article Title"
    assert variables["warnings"] == ["decode: windows-1252"]
    assert len(variables["chunks"]) == 1
    assert variables["extract"] == [{"headline": "Article Title"}]
    assert variables["graph"] == {"node": {"id": "doc-1"}}


# ----------------------------------------------------------------------
# 2. parse_document
# ----------------------------------------------------------------------


def test_parse_document_missing_param():
    tool = ParseDocumentTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(tool._invoke({}))
    assert len(messages) == 1
    assert "Error: A valid Dify 'file' object or 'file_url' must be provided." in messages[0].message.text


@patch("lib.client.PageSiftClient.parse_document")
def test_parse_document_passes_pdf_mode_and_mime_type(mock_parse):
    mock_parse.return_value = {
        "success": True,
        "data": {
            "markdown": "# Parsed PDF",
            "pages": [{"pageNumber": 1, "markdown": "# Parsed PDF"}],
            "metadata": {"numPages": 1, "totalPages": 1, "pagesift": {"warnings": ["pdf_repaired"]}},
        },
    }
    file_obj = SimpleNamespace(filename="report.pdf", blob=b"%PDF-1.7 test", mime_type="application/pdf")
    tool = ParseDocumentTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(
        tool._invoke(
            {
                "file": file_obj,
                "enable_ocr": True,
                "max_pages": 10,
                "per_page": True,
                "chunking_type": "headings",
                "enable_graph": True,
            }
        )
    )
    assert messages[0].message.text == "# Parsed PDF"
    variables = _var_map(messages)
    assert variables["filename"] == "report.pdf"
    assert variables["warnings"] == ["pdf_repaired"]
    assert variables["pages"] == [{"pageNumber": 1, "markdown": "# Parsed PDF"}]

    kwargs = mock_parse.call_args.kwargs
    assert kwargs["pdf_mode"] == "ocr"
    assert kwargs["content_type"] == "application/pdf"
    assert kwargs["max_pages"] == 10
    assert kwargs["per_page"] is True
    assert kwargs["chunking"] == {"type": "headings"}
    assert kwargs["graph"] is True


@patch(
    "lib.client.PageSiftClient.parse_document",
    side_effect=PageSiftUnsupportedError("OCR is not enabled on server"),
)
def test_parse_document_surfaces_unsupported_ocr_clearly(_mock_parse):
    file_obj = SimpleNamespace(filename="scan.pdf", blob=b"%PDF-1.7", mime_type="application/pdf")
    tool = ParseDocumentTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(tool._invoke({"file": file_obj, "enable_ocr": True}))
    assert "Unsupported Option (UNSUPPORTED_OPTION)" in messages[0].message.text


# ----------------------------------------------------------------------
# 3. crawl
# ----------------------------------------------------------------------


def test_crawl_missing_param():
    tool = CrawlTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(tool._invoke({}))
    assert len(messages) == 1
    assert "Error: 'url' parameter is required" in messages[0].message.text


@patch("lib.client.PageSiftClient.get_crawl_graph")
@patch("lib.client.PageSiftClient.get_crawl_errors")
@patch("lib.client.PageSiftClient.get_crawl_status")
@patch("lib.client.PageSiftClient.start_crawl")
def test_crawl_extracts_metadata_url_and_graph(mock_start, mock_status, mock_errors, mock_graph):
    mock_start.return_value = "job-123"
    mock_status.return_value = {
        "success": True,
        "status": "completed",
        "data": [
            {
                "markdown": "# Pricing",
                "metadata": {"title": "Pricing Page", "url": "https://example.com/pricing"},
            }
        ],
        "pagesift": {"stopReason": "coverage_reached", "coverage": 0.95, "pages": 1},
    }
    mock_errors.return_value = {"errors": [], "robotsBlocked": []}
    mock_graph.return_value = {
        "success": True,
        "id": "job-123",
        "status": "completed",
        "stats": {"nodes": 1, "citations": 3, "factClusters": 1, "conflicts": 0},
    }

    tool = CrawlTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(
        tool._invoke(
            {
                "url": "https://example.com",
                "query": "pricing",
                "adaptive": True,
                "attachments": True,
                "enable_graph": True,
                "limit": 10,
            }
        )
    )

    text_msgs = [m.message.text for m in messages if getattr(m.type, "value", m.type) == "text"]
    final_summary = text_msgs[-1]
    assert "[Pricing Page](https://example.com/pricing)" in final_summary
    assert "coverage_reached" in final_summary
    assert "DataGraph:" in final_summary

    variables = _var_map(messages)
    assert variables["job_id"] == "job-123"
    assert variables["count"] == 1
    assert variables["graph"]["stats"]["citations"] == 3


# ----------------------------------------------------------------------
# 4. map_site
# ----------------------------------------------------------------------


@patch("lib.client.PageSiftClient.map_site")
def test_map_site_success(mock_map):
    mock_map.return_value = {
        "success": True,
        "links": [
            {"url": "https://example.com/docs", "title": "Docs"},
            {"url": "https://example.com/pricing"},
        ],
        "warnings": [],
    }
    tool = MapSiteTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(tool._invoke({"url": "https://example.com", "search": "docs", "limit": 20}))
    assert "2 URL(s) found" in messages[0].message.text
    assert "[Docs](https://example.com/docs)" in messages[0].message.text
    variables = _var_map(messages)
    assert variables["count"] == 2
    assert variables["urls"] == ["https://example.com/docs", "https://example.com/pricing"]


# ----------------------------------------------------------------------
# 5. batch_scrape
# ----------------------------------------------------------------------


@patch("lib.client.PageSiftClient.get_batch_errors")
@patch("lib.client.PageSiftClient.get_batch_status")
@patch("lib.client.PageSiftClient.start_batch_scrape")
def test_batch_scrape_success(mock_start, mock_status, mock_errors):
    mock_start.return_value = {"success": True, "id": "batch-1", "invalidURLs": []}
    mock_status.return_value = {
        "success": True,
        "status": "completed",
        "data": [
            {"markdown": "Page 1 body", "metadata": {"title": "P1", "url": "https://example.com/1"}},
            {"markdown": "Page 2 body", "metadata": {"title": "P2", "url": "https://example.com/2"}},
        ],
    }
    mock_errors.return_value = {"errors": [], "robotsBlocked": []}

    tool = BatchScrapeTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(
        tool._invoke(
            {
                "urls": "https://example.com/1\nhttps://example.com/2",
                "query_filter": "body",
                "chunking_type": "recursive",
            }
        )
    )
    assert "Batch Scrape Finished (completed): 2/2" in messages[0].message.text
    assert "Page 1 body" in messages[0].message.text
    variables = _var_map(messages)
    assert variables["job_id"] == "batch-1"
    assert variables["count"] == 2


# ----------------------------------------------------------------------
# 6. context_pack (1.6.0–1.6.3)
# ----------------------------------------------------------------------


@patch("lib.client.PageSiftClient.context_pack")
def test_context_pack_stateless_adapts_read_url_document(mock_pack):
    mock_pack.return_value = {
        "success": True,
        "pack": {
            "compiledContext": "### Compiled Evidence\nPrice is $99/mo (unless annual).",
            "provenanceManifest": [{"unitId": "u1", "sourceUrl": "https://example.com/pricing"}],
            "budgetInsufficient": False,
            "warnings": [],
        },
    }
    upstream_doc = json.dumps(
        {
            "markdown": "Price is $99/mo unless billed annually.",
            "metadata": {"url": "https://example.com/pricing", "title": "Pricing"},
        }
    )
    tool = ContextPackTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(
        tool._invoke(
            {
                "mode": "pack",
                "query": "monthly price and exceptions",
                "documents": upstream_doc,
                "budget_tokens": 1024,
                "effective_at": "2026-06-01T00:00:00Z",
            }
        )
    )
    assert "Compiled Evidence" in messages[0].message.text
    sent = mock_pack.call_args.args[0]
    assert sent["documents"][0]["url"] == "https://example.com/pricing"
    assert sent["budgetTokens"] == 1024
    assert sent["effectiveAt"] == "2026-06-01T00:00:00Z"
    assert sent["mustKeepQualifiers"] is True

    variables = _var_map(messages)
    assert variables["budget_insufficient"] is False
    assert len(variables["provenance_manifest"]) == 1


@patch("lib.client.PageSiftClient.context_action")
def test_context_pack_verify_action_defaults_no_network(mock_action):
    mock_action.return_value = {
        "success": True,
        "outcome": {
            "stoppingReason": "sufficient",
            "reusedExistingContext": True,
            "pack": {
                "compiledContext": "Verified across 2 sources.",
                "provenanceManifest": [],
                "budgetInsufficient": False,
            },
        },
    }
    tool = ContextPackTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(
        tool._invoke(
            {
                "mode": "verify",
                "query": "Enterprise SLA",
                "source_ids": "kb-docs,kb-pricing",
                "min_independent_sources": 2,
            }
        )
    )
    sent = mock_action.call_args.args[0]
    assert sent["mode"] == "verify"
    assert sent["sourceIds"] == ["kb-docs", "kb-pricing"]
    assert sent["allowNetworkAcquisition"] is False
    assert sent["minIndependentSources"] == 2

    variables = _var_map(messages)
    assert variables["stopping_reason"] == "sufficient"


# ----------------------------------------------------------------------
# 7. context_ingest (1.6.0–1.6.3)
# ----------------------------------------------------------------------


@patch("lib.client.PageSiftClient.context_ingest")
def test_context_ingest_adapts_crawl_pages_payload(mock_ingest):
    mock_ingest.return_value = {
        "success": True,
        "sourceId": "kb-main",
        "persisted": True,
        "liveUnitCount": 12,
        "delta": {"deltaSeq": 3},
    }
    crawl_output = json.dumps(
        {
            "pages": [
                {"markdown": "# Doc 1", "metadata": {"url": "https://example.com/1", "title": "Doc 1"}}
            ]
        }
    )
    tool = ContextIngestTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(
        tool._invoke({"operation": "ingest", "source_id": "kb-main", "documents": crawl_output})
    )
    assert "Live KnowledgeUnits:** 12" in messages[0].message.text
    sent = mock_ingest.call_args.args[0]
    assert sent["sourceId"] == "kb-main"
    assert sent["documents"][0]["url"] == "https://example.com/1"
    assert _var_map(messages)["live_unit_count"] == 12


@patch("lib.client.PageSiftClient.context_learn_status")
def test_context_ingest_learn_status_readonly(mock_learn):
    mock_learn.return_value = {
        "success": True,
        "learn": {"enabled": True, "frozen": False, "driftGuard": "cusumPageHinkley", "sampleCount": 15},
    }
    tool = ContextIngestTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(tool._invoke({"operation": "learn_status"}))
    assert "Read-Only" in messages[0].message.text
    assert _var_map(messages)["live_unit_count"] == 15


# ----------------------------------------------------------------------
# 8. sync_source (1.5.0–1.6.3 Loop)
# ----------------------------------------------------------------------


@patch("lib.client.PageSiftClient.create_source")
def test_sync_source_create(mock_create):
    mock_create.return_value = {
        "success": True,
        "source": {"id": "docs-src", "name": "Docs", "seeds": ["https://docs.example.com"], "instanceId": "inst-1"},
    }
    tool = SyncSourceTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(
        tool._invoke(
            {
                "action": "create",
                "source_id": "docs-src",
                "name": "Docs",
                "seeds": "https://docs.example.com",
                "max_requests_per_tick": 25,
                "target_items": 50,
            }
        )
    )
    assert "Loop Data Source Saved: `docs-src`" in messages[0].message.text
    sent = mock_create.call_args.args[0]
    assert sent["budget"] == {"maxRequestsPerTick": 25, "targetItems": 50}


@patch("lib.client.PageSiftClient.get_source_state")
def test_sync_source_state_with_as_of(mock_state):
    mock_state.return_value = {
        "success": True,
        "state": {
            "inventory": [{"url": "https://docs.example.com"}],
            "activeClaimCount": 5,
            "unverifiedClaimCount": 1,
            "factClusters": [],
            "factClustersTruncated": False,
            "conflicts": [],
        },
    }
    tool = SyncSourceTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(
        tool._invoke({"action": "state", "source_id": "docs-src", "as_of": "2026-11-20T00:00:00Z"})
    )
    assert "as of `2026-11-20T00:00:00Z`" in messages[0].message.text
    mock_state.assert_called_once_with("docs-src", as_of="2026-11-20T00:00:00Z")


# ----------------------------------------------------------------------
# 9. query_graph (1.4.0–1.6.3 DataGraph)
# ----------------------------------------------------------------------


@patch("lib.client.PageSiftClient.get_graph_claims")
def test_query_graph_claims_with_as_of(mock_claims):
    mock_claims.return_value = {
        "success": True,
        "subject": "sku:PRO-1",
        "total": 1,
        "claims": [{"subjectKey": "sku:PRO-1", "field": "price", "value": "$49", "status": "active"}],
        "truncated": False,
        "historyUnavailable": True,
    }
    tool = QueryGraphTool(runtime=mock_runtime(), session=MagicMock())
    messages = list(
        tool._invoke(
            {
                "query_type": "claims",
                "subject": "sku:PRO-1",
                "as_of": "2026-01-01T00:00:00Z",
            }
        )
    )
    assert "historyUnavailable=true" in messages[0].message.text
    variables = _var_map(messages)
    assert variables["total"] == 1
    assert variables["history_unavailable"] is True
