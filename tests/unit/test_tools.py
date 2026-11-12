"""Unit tests for Dify tool implementations."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tools.read_url import ReadUrlTool
from tools.crawl import CrawlTool
from tools.parse_document import ParseDocumentTool


def mock_runtime():
    runtime = SimpleNamespace()
    runtime.credentials = {"base_url": "http://127.0.0.1:3002", "api_key": "test_key"}
    return runtime


def test_read_url_missing_param():
    runtime = mock_runtime()
    session = MagicMock()
    tool = ReadUrlTool(runtime=runtime, session=session)
    messages = list(tool._invoke({}))
    assert len(messages) == 1
    assert "Error: 'url' parameter is required" in messages[0].message.text


@patch("lib.client.PageSiftClient.scrape")
def test_read_url_success(mock_scrape):
    mock_scrape.return_value = {
        "success": True,
        "data": {
            "markdown": "## Article Title\n\nArticle body here.",
            "metadata": {"title": "Article Title", "author": "Author Name"}
        }
    }
    runtime = mock_runtime()
    session = MagicMock()
    tool = ReadUrlTool(runtime=runtime, session=session)
    messages = list(tool._invoke({"url": "https://example.com/post"}))
    assert len(messages) == 2
    # Verify markdown message
    assert "## Article Title" in messages[0].message.text
    # Verify frontmatter presence
    assert "title: Article Title" in messages[0].message.text


def test_crawl_missing_param():
    runtime = mock_runtime()
    session = MagicMock()
    tool = CrawlTool(runtime=runtime, session=session)
    messages = list(tool._invoke({}))
    assert len(messages) == 1
    assert "Error: 'url' parameter is required" in messages[0].message.text


def test_parse_document_missing_param():
    runtime = mock_runtime()
    session = MagicMock()
    tool = ParseDocumentTool(runtime=runtime, session=session)
    messages = list(tool._invoke({}))
    assert len(messages) == 1
    assert "Error: A valid Dify 'file' object or 'file_url' must be provided." in messages[0].message.text
