"""
Huan - Unified Python API.

Provides ToolResult-based wrappers for programmatic usage
and agent integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolResult:
    """Standardised return type for all Huan API functions."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }


def archive_site(
    url: str,
    *,
    output_dir: str | None = None,
    delay: float = 0.5,
    max_pages: int | None = None,
    prefix: str | None = None,
    extractor: str = "readability",
    fetcher: str = "requests",
    proxy: str | None = None,
    verbose: bool = False,
    overwrite: bool = False,
    download_images: bool = True,
    save_html: bool = False,
    metadata: bool = True,
    scroll_count: int = 20,
    recursive: bool = False,
) -> ToolResult:
    """Archive a website to local Markdown files.

    Parameters
    ----------
    url : str
        Starting URL to archive.
    output_dir : str or None
        Output directory (default: domain name).
    delay : float
        Seconds between requests.
    max_pages : int or None
        Maximum pages to archive (None = no limit).
    prefix : str or None
        Only archive URLs whose path starts with this prefix.
    extractor : str
        Content extraction strategy: readability, heuristic, or full.
    fetcher : str
        Backend: requests, curl, browser, or playwright.
    proxy : str or None
        HTTP/HTTPS proxy URL.
    verbose : bool
        Show all discovered links during archiving.
    overwrite : bool
        Overwrite existing files.
    download_images : bool
        Download and localise images.
    save_html : bool
        Also save original HTML alongside markdown.
    metadata : bool
        Enable YAML front matter metadata.
    scroll_count : int
        Scroll iterations for lazy-loaded content.

    Returns
    -------
    ToolResult
        With data containing crawl statistics.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        from huan import __version__
        from huan.core import SiteCrawler

        archiver = SiteCrawler(
            start_url=url,
            output_dir=output_dir,
            delay=delay,
            max_pages=max_pages,
            prefix=prefix,
            full_content=(extractor == "full"),
            verify_ssl=True,
            proxy=proxy,
            system_proxy=False,
            fetcher_type=fetcher,
            scroll_count=scroll_count,
            overwrite=overwrite,
            verbose=verbose,
            download_images=download_images,
            save_html=save_html,
            extractor=extractor,
            metadata=metadata,
            recursive=recursive,
        )

        archiver.crawl()

        return ToolResult(
            success=True,
            data={
                "pages_saved": archiver.saved_count if hasattr(archiver, "saved_count") else None,
                "output_dir": str(archiver.output_dir) if hasattr(archiver, "output_dir") else output_dir,
            },
            metadata={
                "start_url": url,
                "version": __version__,
            },
        )
    except Exception as e:
        return ToolResult(success=False, error=str(e))


def update_sites(
    sites: list[str] | None = None,
    *,
    config_path: str | None = None,
    proxy: str | None = None,
    min_delay: float = 2.0,
    max_delay: float = 6.0,
) -> ToolResult:
    """Incrementally update one or more configured websites.

    Unlike :func:`archive_site` (which crawls an arbitrary site), this works
    against a *site config* that knows how to enumerate a site's articles and
    where to save them.  Only content not already saved locally is fetched.

    Parameters
    ----------
    sites : list[str] or None
        Site keys to update (None = all configured sites).
    config_path : str or None
        Path to a sites.json config (default: ~/.config/huan/sites.json).
    proxy : str or None
        Override the proxy for this run.
    min_delay, max_delay : float
        Delay range between requests (seconds).

    Returns
    -------
    ToolResult
        data maps each site key to its per-site stats.
    """
    try:
        from huan import __version__
        from huan.sites import load_sites_config, update_sites as _update

        conf = load_sites_config(config_path)
        results = _update(sites, config_path=config_path, proxy=proxy,
                          min_delay=min_delay, max_delay=max_delay)
        return ToolResult(
            success=all("error" not in r for r in results.values()),
            data=results,
            metadata={
                "config": config_path,
                "proxy": proxy if proxy is not None else conf.get("proxy"),
                "version": __version__,
            },
        )
    except Exception as e:  # noqa: BLE001
        return ToolResult(success=False, error=str(e))
