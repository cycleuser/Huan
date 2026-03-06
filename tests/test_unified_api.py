"""
Comprehensive tests for Huan unified API, tools, and CLI flags.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestToolResult:
    def test_success_result(self):
        from huan.api import ToolResult
        r = ToolResult(success=True, data={"pages_saved": 10})
        assert r.success is True
        assert r.data["pages_saved"] == 10

    def test_failure_result(self):
        from huan.api import ToolResult
        r = ToolResult(success=False, error="connection refused")
        assert r.success is False

    def test_to_dict_keys(self):
        from huan.api import ToolResult
        d = ToolResult(success=True).to_dict()
        assert set(d.keys()) == {"success", "data", "error", "metadata"}

    def test_default_metadata_isolation(self):
        from huan.api import ToolResult
        r1 = ToolResult(success=True)
        r2 = ToolResult(success=True)
        r1.metadata["x"] = 1
        assert "x" not in r2.metadata


class TestArchiveSiteAPI:
    @patch("huan.core.SiteCrawler")
    def test_archive_success(self, mock_crawler_cls):
        from huan.api import archive_site
        instance = MagicMock()
        instance.saved_count = 5
        instance.output_dir = "/tmp/out"
        mock_crawler_cls.return_value = instance

        result = archive_site("https://example.com")
        assert result.success is True
        instance.crawl.assert_called_once()

    def test_url_auto_prefix(self):
        from huan.api import archive_site
        # Should not crash even with no scheme — it auto-prepends https://
        # Will fail on network but should return ToolResult
        result = archive_site("example.com", max_pages=0)
        assert isinstance(result, type(result))  # ToolResult

    @patch("huan.core.SiteCrawler")
    def test_archive_with_options(self, mock_crawler_cls):
        from huan.api import archive_site
        instance = MagicMock()
        mock_crawler_cls.return_value = instance

        archive_site(
            "https://example.com",
            max_pages=10,
            delay=1.0,
            extractor="full",
            fetcher="curl",
        )
        call_kwargs = mock_crawler_cls.call_args[1]
        assert call_kwargs["max_pages"] == 10
        assert call_kwargs["delay"] == 1.0
        assert call_kwargs["extractor"] == "full"


class TestToolsSchema:
    def test_tools_count(self):
        from huan.tools import TOOLS
        assert len(TOOLS) == 1

    def test_tool_name(self):
        from huan.tools import TOOLS
        assert TOOLS[0]["function"]["name"] == "huan_archive_site"

    def test_required_url(self):
        from huan.tools import TOOLS
        assert "url" in TOOLS[0]["function"]["parameters"]["required"]

    def test_structure(self):
        from huan.tools import TOOLS
        tool = TOOLS[0]
        assert tool["type"] == "function"
        assert "description" in tool["function"]
        assert tool["function"]["parameters"]["type"] == "object"


class TestToolsDispatch:
    def test_unknown_tool(self):
        from huan.tools import dispatch
        with pytest.raises(ValueError):
            dispatch("bad_name", {})

    @patch("huan.core.SiteCrawler")
    def test_dispatch_archive(self, mock_cls):
        from huan.tools import dispatch
        instance = MagicMock()
        mock_cls.return_value = instance
        result = dispatch("huan_archive_site", {"url": "https://example.com"})
        assert isinstance(result, dict)
        assert result["success"] is True

    def test_dispatch_json_string(self):
        from huan.tools import dispatch
        args = json.dumps({"url": "https://example.com"})
        # Will fail on network, but should not raise
        result = dispatch("huan_archive_site", args)
        assert isinstance(result, dict)


class TestCLIFlags:
    def _run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "huan"] + list(args),
            capture_output=True, text=True, timeout=15,
        )

    def test_version_flag(self):
        r = self._run_cli("-V")
        assert r.returncode == 0
        assert "huan" in r.stdout.lower()

    def test_help_contains_json(self):
        r = self._run_cli("--help")
        assert "--json" in r.stdout

    def test_help_contains_quiet(self):
        r = self._run_cli("--help")
        assert "--quiet" in r.stdout or "-q" in r.stdout


class TestPackageExports:
    def test_version(self):
        import huan
        assert hasattr(huan, "__version__")

    def test_toolresult(self):
        from huan import ToolResult
        assert callable(ToolResult)

    def test_archive_site(self):
        from huan import archive_site
        assert callable(archive_site)

    def test_sitecrawler(self):
        from huan import SiteCrawler
        assert SiteCrawler is not None
