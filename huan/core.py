#!/usr/bin/env python3
"""
huan - Web Page to Markdown Converter (换 = "convert" in Chinese)

Converts web pages into Markdown files, preserving the site's
URL path structure as a local folder hierarchy.

Features:
- BFS traversal with URL normalization and deduplication
- Multiple HTTP backends (requests, curl_cffi, DrissionPage, Playwright)
- Better browser compatibility for various websites
- Infinite scroll support for lazy-loaded content
- MathML/MathJax/KaTeX to LaTeX conversion
- Image downloading with local path rewriting
- Incremental mode (skip existing files)
- Proxy support (manual or system environment variables)

Dependencies (required):
    pip install requests beautifulsoup4 html2text

Optional dependencies (for difficult sites):
    pip install curl-cffi      # Better browser compatibility (recommended)
    pip install DrissionPage   # Use system Chrome/Edge browser (no extra downloads)
    pip install playwright && playwright install chromium  # Heavyweight alternative

Usage:
    huan https://geopytool.com
    huan https://geopytool.com -o output_folder
    huan https://geopytool.com -m 50 -d 1.0
    huan https://geopytool.com --prefix /docs
    huan https://geopytool.com --proxy http://127.0.0.1:7890
    huan https://geopytool.com --fetcher curl --proxy http://127.0.0.1:7890
    huan https://geopytool.com --fetcher browser --proxy http://127.0.0.1:7890

Or run as module:
    python -m huan https://geopytool.com
"""

import argparse
import json
import os
import re
import sys
import time
from abc import ABC, abstractmethod
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse, unquote, parse_qs, urlencode

# ── Required imports ──────────────────────────────────────────────────────────

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    from bs4 import BeautifulSoup
    import html2text
except ImportError:
    print("Missing required packages. Install with:")
    print("  pip install requests beautifulsoup4 html2text")
    sys.exit(1)

try:
    import certifi
    _CA_BUNDLE = certifi.where()
except ImportError:
    _CA_BUNDLE = True

# ── Optional imports ──────────────────────────────────────────────────────────

HAS_CURL_CFFI = False
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    pass

HAS_DRISSION = False
try:
    from DrissionPage import ChromiumPage, ChromiumOptions
    HAS_DRISSION = True
except ImportError:
    pass

HAS_PLAYWRIGHT = False
try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    pass

HAS_READABILITY = False
try:
    from readability import Document as ReadabilityDocument
    HAS_READABILITY = True
except ImportError:
    pass

# ── Constants ────────────────────────────────────────────────────────────────

SKIP_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".ico", ".webp", ".avif",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".css", ".js", ".mjs", ".map",
    ".xml", ".json", ".yaml", ".yml", ".toml", ".csv", ".rss", ".atom",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".ogg", ".webm", ".wav",
    ".exe", ".dmg", ".apk", ".deb", ".rpm", ".iso",
})

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Full browser-like headers
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="131", "Google Chrome";v="131", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "DNT": "1",
    "Cache-Control": "max-age=0",
}


# ── Fetcher Abstraction ──────────────────────────────────────────────────────

class BaseFetcher(ABC):
    """Abstract base class for HTTP fetchers."""

    @abstractmethod
    def fetch(self, url: str) -> tuple[str | None, str | None]:
        """
        Fetch a URL and return (html_content, error_message).
        Returns (html, None) on success, (None, error) on failure.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Clean up resources."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Fetcher name for display."""
        pass


class RequestsFetcher(BaseFetcher):
    """Standard requests-based fetcher with enhanced browser headers."""

    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        verify_ssl: bool = True,
        proxy: str | None = None,
        timeout: int = 30,
    ):
        self.timeout = timeout
        self.session = requests.Session()

        # Full browser headers
        headers = {"User-Agent": user_agent}
        headers.update(BROWSER_HEADERS)
        self.session.headers.update(headers)

        # SSL verification
        if verify_ssl:
            self.session.verify = _CA_BUNDLE
        else:
            self.session.verify = False
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Proxy
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

        # Retry strategy
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def fetch(self, url: str) -> tuple[str | None, str | None]:
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            resp.raise_for_status()
        except requests.RequestException as exc:
            return None, str(exc)

        ctype = resp.headers.get("Content-Type", "")
        if "text/html" not in ctype and "application/xhtml" not in ctype:
            return None, "not HTML content"

        # Encoding priority: explicit Content-Type charset > detection > utf-8
        # requests defaults to ISO-8859-1 for text/* when no charset is declared,
        # so only trust resp.encoding when it's explicitly set to something else.
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text, None

    def close(self) -> None:
        self.session.close()

    @property
    def name(self) -> str:
        return "requests"


class CurlCffiFetcher(BaseFetcher):
    """curl_cffi-based fetcher with better browser compatibility."""

    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        verify_ssl: bool = True,
        proxy: str | None = None,
        timeout: int = 30,
    ):
        if not HAS_CURL_CFFI:
            raise ImportError("curl_cffi not installed")

        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.proxy = proxy
        self.session = curl_requests.Session(impersonate="chrome")

        # Full browser headers
        headers = {"User-Agent": user_agent}
        headers.update(BROWSER_HEADERS)
        self.session.headers.update(headers)

    def fetch(self, url: str) -> tuple[str | None, str | None]:
        try:
            resp = self.session.get(
                url,
                timeout=self.timeout,
                allow_redirects=True,
                verify=self.verify_ssl,
                proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None,
            )
            resp.raise_for_status()
        except Exception as exc:
            return None, str(exc)

        ctype = resp.headers.get("Content-Type", "")
        if "text/html" not in ctype and "application/xhtml" not in ctype:
            return None, "not HTML content"

        # curl_cffi uses .text property
        return resp.text, None

    def close(self) -> None:
        self.session.close()

    @property
    def name(self) -> str:
        return "curl_cffi"


class PlaywrightFetcher(BaseFetcher):
    """Playwright-based fetcher with full JavaScript rendering."""

    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        verify_ssl: bool = True,
        proxy: str | None = None,
        timeout: int = 30,
    ):
        if not HAS_PLAYWRIGHT:
            raise ImportError("playwright not installed")

        self.timeout = timeout * 1000  # Playwright uses ms
        self._pw = sync_playwright().start()

        # Browser launch options
        launch_opts: dict = {"headless": True}
        if proxy:
            launch_opts["proxy"] = {"server": proxy}

        self._browser = self._pw.chromium.launch(**launch_opts)

        # Context with custom UA and ignore SSL if needed
        context_opts: dict = {
            "user_agent": user_agent,
            "viewport": {"width": 1920, "height": 1080},
            "ignore_https_errors": not verify_ssl,
        }
        self._context = self._browser.new_context(**context_opts)
        self._page = self._context.new_page()

    def fetch(self, url: str) -> tuple[str | None, str | None]:
        try:
            self._page.goto(url, timeout=self.timeout, wait_until="networkidle")
            # Wait a bit more for any late JS
            self._page.wait_for_timeout(500)
            html = self._page.content()
            return html, None
        except Exception as exc:
            return None, str(exc)

    def close(self) -> None:
        try:
            self._context.close()
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "playwright"


class DrissionPageFetcher(BaseFetcher):
    """DrissionPage-based fetcher using system browser (Chrome/Edge)."""

    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        verify_ssl: bool = True,
        proxy: str | None = None,
        timeout: int = 30,
        scroll_count: int = 5,  # Number of times to scroll for lazy-loaded content
    ):
        if not HAS_DRISSION:
            raise ImportError("DrissionPage not installed")

        self.timeout = timeout
        self.scroll_count = scroll_count

        # Configure browser options
        opts = ChromiumOptions()
        opts.headless()  # Run headless
        opts.set_argument("--disable-gpu")
        opts.set_argument("--no-sandbox")
        opts.set_argument("--disable-dev-shm-usage")

        if user_agent:
            opts.set_argument(f"--user-agent={user_agent}")

        if proxy:
            opts.set_argument(f"--proxy-server={proxy}")

        if not verify_ssl:
            opts.set_argument("--ignore-certificate-errors")

        # Auto-detect system browser (Chrome or Edge)
        opts.auto_port()

        # Try to find browser executable
        browser_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
        for path in browser_paths:
            if os.path.exists(path):
                opts.set_browser_path(path)
                break

        self._page = ChromiumPage(opts)

    def fetch(self, url: str) -> tuple[str | None, str | None]:
        try:
            self._page.get(url, timeout=self.timeout)
            # Wait for page to be ready
            self._page.wait.doc_loaded()

            # Scroll to load lazy-loaded content (for infinite scroll sites)
            # Uses incremental scrolling (viewport-by-viewport) to trigger
            # IntersectionObserver-based lazy loading
            if self.scroll_count > 0:
                scroll_num = 0
                no_change_count = 0
                last_height = self._page.run_js("return document.body.scrollHeight") or 0
                viewport_h = self._page.run_js("return window.innerHeight") or 900
                current_pos = 0

                for _ in range(self.scroll_count):
                    doc_height = self._page.run_js("return document.body.scrollHeight") or 0

                    if current_pos + viewport_h < doc_height:
                        # Still have room: scroll down by one viewport
                        current_pos += int(viewport_h * 0.85)
                        self._page.run_js(f"window.scrollTo(0, {current_pos})")
                        scroll_num += 1
                        time.sleep(0.4)
                    else:
                        # Reached current bottom: jump to absolute end
                        self._page.run_js("window.scrollTo(0, document.body.scrollHeight)")
                        current_pos = doc_height
                        scroll_num += 1
                        time.sleep(1.5)  # Longer wait at bottom for new batch

                        new_height = self._page.run_js("return document.body.scrollHeight") or 0
                        if new_height == last_height:
                            no_change_count += 1
                            if no_change_count >= 5:
                                print(f"  [scroll] Stopped after {scroll_num} scrolls (page fully loaded, height={new_height}px)")
                                break
                            # Extra wait and re-trigger
                            time.sleep(2.0)
                            self._page.run_js("window.scrollTo(0, document.body.scrollHeight)")
                            time.sleep(1.5)
                        else:
                            no_change_count = 0
                        last_height = new_height

                    if scroll_num % 20 == 0:
                        cur_h = self._page.run_js("return document.body.scrollHeight") or 0
                        print(f"  [scroll] {scroll_num} scrolls, pos={current_pos}, page height={cur_h}px")
                else:
                    print(f"  [scroll] Reached max scroll count ({self.scroll_count})")

                # Final: jump to absolute bottom
                self._page.run_js("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.0)

            html = self._page.html
            return html, None
        except Exception as exc:
            return None, str(exc)

    def close(self) -> None:
        try:
            self._page.quit()
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "drission"


def create_fetcher(
    fetcher_type: str,
    user_agent: str = DEFAULT_UA,
    verify_ssl: bool = True,
    proxy: str | None = None,
    timeout: int = 30,
    scroll_count: int = 5,
) -> BaseFetcher:
    """
    Factory function to create a fetcher with graceful fallback.

    fetcher_type: "requests", "curl", "browser", or "drission"
    """
    # browser = DrissionPage (uses system browser, no extra install)
    if fetcher_type == "browser":
        if HAS_DRISSION:
            return DrissionPageFetcher(user_agent, verify_ssl, proxy, timeout, scroll_count)
        else:
            print("[WARN] DrissionPage not installed. Install with: pip install DrissionPage")
            print("       Falling back to playwright...")
            fetcher_type = "playwright"

    if fetcher_type == "drission":
        if HAS_DRISSION:
            return DrissionPageFetcher(user_agent, verify_ssl, proxy, timeout, scroll_count)
        else:
            print("[WARN] DrissionPage not installed. Install with: pip install DrissionPage")
            print("       Falling back to curl_cffi...")
            fetcher_type = "curl"

    if fetcher_type == "playwright":
        if HAS_PLAYWRIGHT:
            return PlaywrightFetcher(user_agent, verify_ssl, proxy, timeout)
        else:
            print("[WARN] playwright not installed. Install with:")
            print("       pip install playwright && playwright install chromium")
            print("       Falling back to curl_cffi...")
            fetcher_type = "curl"

    if fetcher_type == "curl":
        if HAS_CURL_CFFI:
            return CurlCffiFetcher(user_agent, verify_ssl, proxy, timeout)
        else:
            print("[WARN] curl_cffi not installed. Install with: pip install curl-cffi")
            print("       Falling back to requests...")
            fetcher_type = "requests"

    # Default: requests
    return RequestsFetcher(user_agent, verify_ssl, proxy, timeout)


# ── Math Formula Conversion ──────────────────────────────────────────────────

def _mathml_to_latex(element) -> str:
    """Convert a MathML <math> element to LaTeX string."""
    tag = getattr(element, 'name', None)
    if tag is None:
        # NavigableString (text node)
        return element.string.strip() if element.string else ""

    children_latex = [_mathml_to_latex(c) for c in element.children
                      if not (isinstance(c, str) and c.strip() == "")]

    if tag == "math":
        return " ".join(children_latex)
    elif tag == "mrow":
        return " ".join(children_latex)
    elif tag == "mi":
        text = element.get_text(strip=True)
        # Multi-char identifiers get \mathrm{}
        if len(text) > 1 and text.isalpha():
            return rf"\mathrm{{{text}}}"
        return text
    elif tag == "mn":
        return element.get_text(strip=True)
    elif tag == "mo":
        op = element.get_text(strip=True)
        op_map = {
            "\u00d7": r"\times", "\u00b7": r"\cdot", "\u2212": "-",
            "\u2264": r"\leq", "\u2265": r"\geq", "\u2260": r"\neq",
            "\u221e": r"\infty", "\u2211": r"\sum", "\u220f": r"\prod",
            "\u222b": r"\int", "\u2202": r"\partial", "\u2207": r"\nabla",
            "\u00b1": r"\pm", "\u2213": r"\mp", "\u2229": r"\cap",
            "\u222a": r"\cup", "\u2208": r"\in", "\u2209": r"\notin",
            "\u2282": r"\subset", "\u2283": r"\supset", "\u2192": r"\to",
            "\u21d2": r"\Rightarrow", "\u21d4": r"\Leftrightarrow",
            "\u2026": r"\ldots", "\u22ef": r"\cdots",
            "(": "(", ")": ")", "[": "[", "]": "]",
            "{": r"\{", "}": r"\}", "|": "|",
            "+": "+", "-": "-", "=": "=", "<": "<", ">": ">",
            ",": ",", ";": ";", ":": ":", "!": "!",
            "/": "/", "*": r"\ast",
        }
        return op_map.get(op, op)
    elif tag == "msup":
        if len(children_latex) >= 2:
            base, exp = children_latex[0], children_latex[1]
            return f"{{{base}}}^{{{exp}}}"
        return " ".join(children_latex)
    elif tag == "msub":
        if len(children_latex) >= 2:
            base, sub = children_latex[0], children_latex[1]
            return f"{{{base}}}_{{{sub}}}"
        return " ".join(children_latex)
    elif tag == "msubsup":
        if len(children_latex) >= 3:
            base, sub, sup = children_latex[0], children_latex[1], children_latex[2]
            return f"{{{base}}}_{{{sub}}}^{{{sup}}}"
        return " ".join(children_latex)
    elif tag == "mfrac":
        if len(children_latex) >= 2:
            num, den = children_latex[0], children_latex[1]
            return rf"\frac{{{num}}}{{{den}}}"
        return " ".join(children_latex)
    elif tag == "msqrt":
        inner = " ".join(children_latex)
        return rf"\sqrt{{{inner}}}"
    elif tag == "mroot":
        if len(children_latex) >= 2:
            base, idx = children_latex[0], children_latex[1]
            return rf"\sqrt[{idx}]{{{base}}}"
        return " ".join(children_latex)
    elif tag == "mover":
        if len(children_latex) >= 2:
            base, over = children_latex[0], children_latex[1]
            over_map = {"\u0302": "hat", "\u0303": "tilde", "\u0304": "bar",
                        "\u20d7": "vec", "\u02d9": "dot", "\u00af": "bar",
                        "^": "hat", "~": "tilde", "\u2192": "vec"}
            cmd = over_map.get(over, None)
            if cmd:
                return rf"\{cmd}{{{base}}}"
            return rf"\overset{{{over}}}{{{base}}}"
        return " ".join(children_latex)
    elif tag == "munder":
        if len(children_latex) >= 2:
            base, under = children_latex[0], children_latex[1]
            return rf"\underset{{{under}}}{{{base}}}"
        return " ".join(children_latex)
    elif tag == "munderover":
        if len(children_latex) >= 3:
            base, under, over = children_latex[0], children_latex[1], children_latex[2]
            return f"{{{base}}}_{{{under}}}^{{{over}}}"
        return " ".join(children_latex)
    elif tag == "mtext":
        text = element.get_text(strip=True)
        if text:
            return rf"\text{{{text}}}"
        return ""
    elif tag == "mspace":
        return r"\;"
    elif tag == "mtable":
        rows = []
        for tr in element.find_all("mtr", recursive=False):
            cells = []
            for td in tr.find_all("mtd", recursive=False):
                cells.append(_mathml_to_latex(td))
            rows.append(" & ".join(cells))
        return r"\begin{matrix} " + r" \\ ".join(rows) + r" \end{matrix}"
    elif tag in ("mtr", "mtd"):
        return " ".join(children_latex)
    elif tag == "mfenced":
        open_d = element.get("open", "(")
        close_d = element.get("close", ")")
        sep = element.get("separators", ",")
        inner = f" {sep} ".join(children_latex) if children_latex else ""
        return rf"\left{open_d} {inner} \right{close_d}"
    elif tag == "menclose":
        inner = " ".join(children_latex)
        return inner  # Best effort
    elif tag == "mpadded":
        return " ".join(children_latex)
    elif tag == "mstyle":
        return " ".join(children_latex)
    elif tag == "semantics":
        # Try to get annotation with LaTeX first
        ann = element.find("annotation", encoding="TeX")
        if ann and ann.string:
            return ann.string.strip()
        ann = element.find("annotation", encoding="application/x-tex")
        if ann and ann.string:
            return ann.string.strip()
        # Fall back to first child (presentation MathML)
        if children_latex:
            return children_latex[0]
        return ""
    elif tag == "annotation":
        return ""  # Handled by semantics
    elif tag == "annotation-xml":
        return ""
    else:
        # Unknown tag: just join children
        return " ".join(children_latex)


def preprocess_math(soup: BeautifulSoup) -> None:
    """Convert math elements in-place to LaTeX notation before html2text.

    Handles:
    1. MathML <math> tags -> $...$ or $$...$$
    2. <script type="math/tex"> -> $...$
    3. KaTeX data attributes
    4. Equation images with alt text containing math
    """
    from bs4 import NavigableString

    # 1. MathML <math> tags
    for math_tag in soup.find_all("math"):
        display = math_tag.get("display", "")
        # Try alttext first (many renderers include original LaTeX here)
        alttext = math_tag.get("alttext", "").strip()
        if alttext:
            latex = alttext
        else:
            latex = _mathml_to_latex(math_tag)

        if not latex:
            continue

        if display == "block":
            replacement = f"\n\n$${latex}$$\n\n"
        else:
            replacement = f"${latex}$"
        math_tag.replace_with(NavigableString(replacement))

    # 2. <script type="math/tex"> (MathJax v2)
    for script in soup.find_all("script", type=re.compile(r"math/tex")):
        latex = script.string
        if not latex:
            continue
        latex = latex.strip()
        stype = script.get("type", "")
        if "display" in stype or "mode=display" in stype:
            replacement = f"\n\n$${latex}$$\n\n"
        else:
            replacement = f"${latex}$"
        script.replace_with(NavigableString(replacement))

    # 3. KaTeX rendered elements
    for elem in soup.find_all(class_=re.compile(r"katex")):
        # KaTeX stores original in annotation
        ann = elem.find("annotation", encoding="application/x-tex")
        if ann and ann.string:
            latex = ann.string.strip()
            # Check if display mode
            if "katex-display" in (elem.get("class", []) or []):
                elem.replace_with(NavigableString(f"\n\n$${latex}$$\n\n"))
            else:
                elem.replace_with(NavigableString(f"${latex}$"))

    # 4. MathJax v3 elements (mjx-container)
    for elem in soup.find_all("mjx-container"):
        # MathJax v3 often has a <script type="math/tex"> inside or aria-label
        aria = elem.get("aria-label", "").strip()
        if aria:
            display = elem.get("display", "") == "true" or "block" in elem.get("class", [])
            if display:
                elem.replace_with(NavigableString(f"\n\n$${aria}$$\n\n"))
            else:
                elem.replace_with(NavigableString(f"${aria}$"))
            continue
        # Check for inner math tag
        inner_math = elem.find("math")
        if inner_math:
            continue  # Will be handled by rule 1

    # 5. Equation images: skip download, use alt text if it looks like math
    eq_img_pattern = re.compile(r"equation|formula|math|latex|tex", re.I)
    for img in soup.find_all("img"):
        src = img.get("src", "")
        alt = img.get("alt", "").strip()
        title = img.get("title", "").strip()

        # Detect equation images by path pattern or alt text
        is_eq = False
        if eq_img_pattern.search(src):
            is_eq = True
        if alt and any(c in alt for c in ("\\", "^", "_", "{", "}")):
            is_eq = True

        if not is_eq:
            continue

        # Use alt or title as LaTeX source
        latex = alt or title
        if not latex:
            continue

        # Determine if block or inline
        parent = img.parent
        is_block = (parent and parent.name in ("p", "div", "td")
                    and len(parent.get_text(strip=True)) < len(latex) + 5)

        if is_block:
            img.replace_with(NavigableString(f"\n\n$${latex}$$\n\n"))
        else:
            img.replace_with(NavigableString(f"${latex}$"))


# ── Image Downloader ─────────────────────────────────────────────────────────

IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".ico", ".webp", ".avif",
    ".tif", ".tiff",
})


class ImageDownloader:
    """Downloads images referenced in HTML pages and manages local paths."""

    def __init__(
        self,
        output_dir: str,
        page_domain: str,
        verify_ssl: bool = True,
        proxy: str | None = None,
        overwrite: bool = False,
        verbose: bool = False,
    ):
        self.output_dir = output_dir
        self.page_domain = page_domain
        self.overwrite = overwrite
        self.verbose = verbose

        # Session for downloading images (lightweight, binary-capable)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_UA,
            "Accept": "image/*, */*",
        })
        if verify_ssl:
            self.session.verify = _CA_BUNDLE
        else:
            self.session.verify = False
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}

        # Cache: image_url -> local_path (avoid re-downloading in same run)
        self.downloaded: dict[str, str] = {}
        self.download_count = 0
        self.skip_count = 0
        self.error_count = 0

    def extract_image_urls(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        """Extract all image URLs from parsed HTML."""
        urls: set[str] = set()

        # 1. <img> tags: src, data-src, data-lazy-src, data-original
        for img in soup.find_all("img"):
            for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                val = img.get(attr, "")
                if val and not val.startswith("data:"):
                    urls.add(urljoin(page_url, val.strip()))
            # srcset: "url 1x, url 2x" or "url 300w, url 600w"
            srcset = img.get("srcset", "")
            if srcset:
                for entry in self._parse_srcset(srcset, page_url):
                    urls.add(entry)

        # 2. <picture><source srcset>
        for source in soup.find_all("source", srcset=True):
            for entry in self._parse_srcset(source["srcset"], page_url):
                urls.add(entry)

        # 3. Inline style background-image: url(...)
        bg_pattern = re.compile(r"background-image:\s*url\(['\"]?([^'\"()]+)['\"]?\)", re.I)
        for elem in soup.find_all(style=True):
            for match in bg_pattern.findall(elem["style"]):
                if not match.startswith("data:"):
                    urls.add(urljoin(page_url, match.strip()))

        return list(urls)

    @staticmethod
    def _parse_srcset(srcset: str, page_url: str) -> list[str]:
        """Parse srcset attribute, return list of absolute image URLs."""
        results = []
        for part in srcset.split(","):
            part = part.strip()
            if not part:
                continue
            # Format: "url descriptor" or just "url"
            tokens = part.split()
            if tokens:
                url = tokens[0].strip()
                if url and not url.startswith("data:"):
                    results.append(urljoin(page_url, url))
        return results

    def download(self, image_url: str) -> str | None:
        """Download an image and return its local path, or None on failure."""
        # Already downloaded this session
        if image_url in self.downloaded:
            return self.downloaded[image_url]

        local_path = self._url_to_image_path(image_url)

        # Incremental: skip if exists
        if not self.overwrite and os.path.exists(local_path):
            self.downloaded[image_url] = local_path
            self.skip_count += 1
            return local_path

        # Download
        try:
            resp = self.session.get(image_url, timeout=20, stream=True)
            resp.raise_for_status()
        except Exception as exc:
            self.error_count += 1
            if self.verbose:
                print(f"    [img-err] {image_url}: {exc}")
            return None

        # Save
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
        except Exception as exc:
            self.error_count += 1
            if self.verbose:
                print(f"    [img-err] save failed {local_path}: {exc}")
            return None

        self.downloaded[image_url] = local_path
        self.download_count += 1
        if self.verbose:
            print(f"    [img] {image_url} -> {local_path}")
        return local_path

    def _url_to_image_path(self, image_url: str) -> str:
        """Compute local filesystem path for an image URL."""
        p = urlparse(image_url)
        path = unquote(p.path).lstrip("/")

        # Handle query strings: append sanitized hash to filename
        if p.query:
            base, ext = os.path.splitext(path)
            safe_q = re.sub(r'[<>:"/\\|?*&=]', "-", p.query)
            if len(safe_q) > 40:
                safe_q = safe_q[:40]
            path = f"{base}_{safe_q}{ext}"

        # Sanitize path segments
        segments = path.split("/")
        clean = []
        for seg in segments:
            seg = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", seg)
            seg = seg.strip(". ")
            if seg:
                if len(seg) > 200:
                    base, ext = os.path.splitext(seg)
                    seg = base[:200] + ext
                clean.append(seg)

        if not clean:
            clean = ["image"]

        # Same-domain vs external
        is_same_domain = (p.netloc == self.page_domain or p.netloc == "")
        if is_same_domain:
            return os.path.join(self.output_dir, *clean)
        else:
            safe_domain = re.sub(r'[<>:"/\\|?*]', "_", p.netloc)
            return os.path.join(self.output_dir, "_external", safe_domain, *clean)

    @staticmethod
    def compute_relative_path(image_local_path: str, md_filepath: str) -> str:
        """Compute relative path from markdown file to image file."""
        md_dir = os.path.dirname(os.path.abspath(md_filepath))
        img_abs = os.path.abspath(image_local_path)
        rel = os.path.relpath(img_abs, md_dir)
        # Use forward slashes for markdown compatibility
        return rel.replace("\\", "/")

    def close(self) -> None:
        self.session.close()


# ── Utility functions ─────────────────────────────────────────────────────────


def _count_tokens(text: str) -> tuple[int, int]:
    """Return (word_count, estimated_token_count).

    Uses a simple heuristic: split on whitespace for word count,
    then estimate tokens as words * 1.3 (reasonable for mixed-language text).
    """
    words = len(text.split())
    tokens = int(words * 1.3)
    return words, tokens


def _format_front_matter(meta: dict) -> str:
    """Format metadata dict as YAML front matter string."""
    lines = ["---"]
    for key, value in meta.items():
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                # Escape items that contain special YAML chars
                item_str = str(item)
                if any(c in item_str for c in (':', '"', "'", "\n", "#", "[", "]", "{", "}")):
                    item_str = f'"{item_str}"'
                lines.append(f"  - {item_str}")
        elif isinstance(value, int):
            lines.append(f"{key}: {value}")
        elif isinstance(value, str):
            # Quote strings that contain YAML special characters
            if any(c in value for c in (':', '"', "'", "\n", "#", "[", "]", "{", "}")):
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{key}: "{escaped}"')
            else:
                lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


# ── Archiver ─────────────────────────────────────────────────────────────────

class SiteCrawler:
    """BFS website archiver that saves a website as Markdown files."""

    def __init__(
        self,
        start_url: str,
        output_dir: str | None = None,
        delay: float = 0.5,
        max_pages: int | None = None,
        prefix: str | None = None,
        full_content: bool = False,
        verify_ssl: bool = True,
        proxy: str | None = None,
        system_proxy: bool = False,
        fetcher_type: str = "requests",
        scroll_count: int = 5,
        overwrite: bool = False,
        verbose: bool = False,
        download_images: bool = True,
        save_html: bool = False,
        extractor: str = "readability",
        metadata: bool = True,
    ):
        parsed = urlparse(start_url)
        if not parsed.scheme:
            start_url = "https://" + start_url
            parsed = urlparse(start_url)

        self.start_url = start_url
        self.overwrite = overwrite
        self.domain = parsed.netloc
        self.scheme = parsed.scheme
        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
        self.prefix = prefix
        self.full_content = full_content

        # Content extraction mode
        if extractor == "full":
            self.full_content = True
        self.use_readability = (extractor == "readability")
        if self.use_readability and not HAS_READABILITY:
            print("  [WARN] readability-lxml not installed, falling back to heuristic extractor.")
            print("         Install with: pip install readability-lxml")
            self.use_readability = False
        self.extractor_name = "readability" if self.use_readability else ("full" if self.full_content else "heuristic")
        self.metadata = metadata

        if output_dir is None:
            safe_domain = re.sub(r'[<>:"/\\|?*]', "_", self.domain)
            output_dir = safe_domain
        self.output_dir = output_dir

        self.delay = delay
        self.max_pages = max_pages
        self.verbose = verbose
        self.save_html = save_html

        self.visited: set[str] = set()
        self.queue: deque[str] = deque()

        # Resolve proxy
        self.proxy_label = "(none)"
        actual_proxy = proxy
        if proxy:
            self.proxy_label = proxy
        elif system_proxy:
            env_https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy", "")
            env_http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy", "")
            actual_proxy = env_https or env_http or None
            self.proxy_label = actual_proxy if actual_proxy else "(system-proxy requested but no env vars found)"

        # Create fetcher
        self.fetcher = create_fetcher(
            fetcher_type=fetcher_type,
            user_agent=DEFAULT_UA,
            verify_ssl=verify_ssl,
            proxy=actual_proxy,
            timeout=30,
            scroll_count=scroll_count,
        )

        # Image downloader
        self.download_images = download_images
        self.image_downloader: ImageDownloader | None = None
        if download_images:
            self.image_downloader = ImageDownloader(
                output_dir=self.output_dir,
                page_domain=self.domain,
                verify_ssl=verify_ssl,
                proxy=actual_proxy,
                overwrite=overwrite,
                verbose=verbose,
            )

        # Configure html2text converter
        self.h2t = html2text.HTML2Text()
        self.h2t.body_width = 0
        self.h2t.unicode_snob = True
        self.h2t.ignore_links = False
        self.h2t.ignore_images = False
        self.h2t.ignore_tables = False
        self.h2t.protect_links = True
        self.h2t.wrap_links = False
        self.h2t.single_line_break = False

    # ── URL helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _normalize(url: str) -> str:
        """Normalize URL: strip fragment, trailing slash, clean query params."""
        p = urlparse(url)
        path = p.path.rstrip("/") or "/"
        # Always strip fragment (anchors don't create separate pages)
        # Keep query string as-is but remove common noise params
        query = p.query
        if query:
            # Remove tracking/noise params
            params = parse_qs(query, keep_blank_values=True)
            noise_keys = {"utm_source", "utm_medium", "utm_campaign", "utm_content",
                          "utm_term", "ref", "source", "open", "s", "r"}
            cleaned = {k: v for k, v in params.items() if k.lower() not in noise_keys}
            query = urlencode(cleaned, doseq=True) if cleaned else ""
        return urlunparse((p.scheme, p.netloc, path, p.params, query, ""))

    def _is_internal(self, url: str) -> bool:
        p = urlparse(url)
        if p.netloc != self.domain:
            return False
        if self.prefix and not p.path.startswith(self.prefix):
            return False
        return True

    def _should_skip(self, url: str) -> bool:
        path = urlparse(url).path
        ext = os.path.splitext(path)[1].lower()
        if ext in SKIP_EXTENSIONS:
            return True

        # Skip known non-content URL patterns
        skip_path_patterns = [
            "/i/",          # Internal section/comment links
            "/comments",    # Comment sections
            "/subscribe",   # Subscription pages
            "/embed",       # Embedded content
            "/api/",        # API endpoints
            "/action/",     # Action endpoints
            "/account/",    # Account management
            "/publish/",    # Publishing interface
        ]
        path_lower = path.lower()
        for pat in skip_path_patterns:
            if pat in path_lower:
                return True

        return False

    def _is_listing_page(self, url: str) -> bool:
        """Check if URL looks like a listing/index page that should be
        re-fetched for link discovery even in incremental mode."""
        p = urlparse(url)
        path = p.path.rstrip("/") or "/"
        # Start URL is always a listing page
        if self._normalize(url) == self._normalize(self.start_url):
            return True
        # Common listing page patterns
        listing_patterns = [
            "/archive", "/index", "/blog", "/posts", "/articles",
            "/page/", "/category/", "/tag/", "/series/", "/topics/",
        ]
        path_lower = path.lower()
        for pat in listing_patterns:
            if pat in path_lower:
                return True
        # Root page
        if path == "/":
            return True
        return False

    # ── Path mapping ─────────────────────────────────────────────────────

    def _url_to_filepath(self, url: str) -> str:
        p = urlparse(url)
        path = unquote(p.path)

        if not path or path == "/":
            path = "/index"
        elif path.endswith("/"):
            path = path + "index"

        path = path.lstrip("/")

        base, ext = os.path.splitext(path)
        if ext.lower() in {".html", ".htm", ".php", ".asp", ".aspx", ".jsp", ".shtml"}:
            path = base

        if p.query:
            safe_query = re.sub(r'[<>:"/\\|?*]', "_", p.query)
            if len(safe_query) > 80:
                safe_query = safe_query[:80]
            path = f"{path}_{safe_query}"

        segments = path.split("/")
        clean = []
        for seg in segments:
            seg = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", seg)
            seg = seg.strip(". ")
            if seg:
                clean.append(seg)

        if not clean:
            clean = ["index"]

        return os.path.join(self.output_dir, *clean) + ".md"

    # ── Content processing ───────────────────────────────────────────────

    def _extract_links(self, soup: BeautifulSoup, page_url: str) -> set[str]:
        links: set[str] = set()
        skipped_count = 0
        
        # 1. Standard <a href="..."> links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("javascript:", "mailto:", "tel:", "#", "data:")):
                continue
            absolute = urljoin(page_url, href)
            normalized = self._normalize(absolute)
            if not self._is_internal(normalized):
                continue
            if self._should_skip(normalized):
                skipped_count += 1
                if self.verbose:
                    print(f"    [filtered] {normalized}")
                continue
            links.add(normalized)
            if self.verbose:
                print(f"    [link] <a href>: {normalized}")
        
        # 2. data-href attributes (used by some JS frameworks)
        for elem in soup.find_all(attrs={"data-href": True}):
            href = elem["data-href"].strip()
            if href.startswith(("javascript:", "mailto:", "tel:", "#", "data:")):
                continue
            absolute = urljoin(page_url, href)
            normalized = self._normalize(absolute)
            if self._is_internal(normalized) and not self._should_skip(normalized):
                links.add(normalized)
                if self.verbose:
                    print(f"    [link] data-href: {normalized}")
        
        # 3. Extract URLs from JSON-LD structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                self._extract_json_urls(data, page_url, links)
            except Exception:
                pass
        
        # 4. Look for URLs in onclick handlers and data attributes
        url_pattern = re.compile(r'https?://[^\s"\'<>]+')
        for elem in soup.find_all(attrs={"onclick": True}):
            for match in url_pattern.findall(elem["onclick"]):
                normalized = self._normalize(match)
                if self._is_internal(normalized) and not self._should_skip(normalized):
                    links.add(normalized)
                    if self.verbose:
                        print(f"    [link] onclick: {normalized}")
        
        # 5. Look for /p/ pattern URLs in any element's text or attributes (article pattern)
        for elem in soup.find_all(True):
            for attr_val in elem.attrs.values():
                if isinstance(attr_val, str) and '/p/' in attr_val:
                    for match in url_pattern.findall(attr_val):
                        normalized = self._normalize(match)
                        if self._is_internal(normalized) and not self._should_skip(normalized):
                            links.add(normalized)
                            if self.verbose:
                                print(f"    [link] attr /p/: {normalized}")
        
        if skipped_count > 0 and self.verbose:
            print(f"    [filtered] {skipped_count} non-content links excluded (e.g. /i/, /comments, etc.)")
        
        return links
    
    def _extract_json_urls(self, data, page_url: str, links: set[str]) -> None:
        """Recursively extract URLs from JSON-LD data."""
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ("url", "@id", "mainEntityOfPage", "itemListElement"):
                    if isinstance(value, str) and value.startswith("http"):
                        normalized = self._normalize(value)
                        if self._is_internal(normalized) and not self._should_skip(normalized):
                            links.add(normalized)
                            if self.verbose:
                                print(f"    [link] JSON-LD {key}: {normalized}")
                self._extract_json_urls(value, page_url, links)
        elif isinstance(data, list):
            for item in data:
                self._extract_json_urls(item, page_url, links)

    def _html_to_markdown(self, html: str, url: str, md_filepath: str = "") -> str:
        # Parse HTML for metadata extraction (before any modification)
        full_soup = BeautifulSoup(html, "html.parser")

        # Extract metadata from the original unmodified HTML
        meta = self._extract_metadata(full_soup, url) if self.metadata else {}

        # ── Content extraction strategy ──────────────────────────────────
        if self.use_readability:
            try:
                doc = ReadabilityDocument(html)
                readable_html = doc.summary()
                readable_title = doc.short_title()
                content_soup = BeautifulSoup(readable_html, "html.parser")
            except Exception:
                # Fallback to heuristic on readability failure
                content_soup = BeautifulSoup(html, "html.parser")
                readable_title = None
                self._strip_boilerplate(content_soup)
                content_soup = self._heuristic_extract(content_soup)
        elif self.full_content:
            content_soup = BeautifulSoup(html, "html.parser")
            readable_title = None
        else:
            content_soup = BeautifulSoup(html, "html.parser")
            readable_title = None
            self._strip_boilerplate(content_soup)
            content_soup = self._heuristic_extract(content_soup)

        # ── Preprocessing on content soup ────────────────────────────────
        # Math formulas (needs <script type="math/tex"> and <math> tags)
        preprocess_math(content_soup)

        # Download images (need full soup for extraction)
        url_mapping: dict[str, str] = {}
        if self.download_images and self.image_downloader and md_filepath:
            image_urls = self.image_downloader.extract_image_urls(content_soup, url)
            for img_url in image_urls:
                local_path = self.image_downloader.download(img_url)
                if local_path:
                    rel_path = self.image_downloader.compute_relative_path(local_path, md_filepath)
                    url_mapping[img_url] = rel_path

        # Preprocess tables for better markdown output
        self._preprocess_tables(content_soup)

        # Preserve code block language hints
        self._preprocess_code_blocks(content_soup)

        # Strip remaining script/style/noscript
        for tag in content_soup.find_all(["script", "style", "noscript"]):
            tag.decompose()

        # ── Title extraction ─────────────────────────────────────────────
        title = ""
        if readable_title:
            title = readable_title
        else:
            title_tag = full_soup.find("title")
            if title_tag:
                title = title_tag.get_text(strip=True)

        # ── Convert to markdown ──────────────────────────────────────────
        md_body = self.h2t.handle(str(content_soup)).strip()

        # Clean up markdown: remove redundant angle brackets in links
        md_body = re.sub(r'\]\(<([^>]+)>\)', r'](\1)', md_body)

        # Replace code language markers with proper fenced code block syntax
        # Marker format: ```\n__CODELANG_python__\n  ->  ```python\n
        md_body = re.sub(r'```\n__CODELANG_(\w+)__\n', r'```\1\n', md_body)

        # Rewrite image URLs in markdown to local relative paths
        if url_mapping:
            for original_url, rel_path in url_mapping.items():
                md_body = md_body.replace(original_url, rel_path)
                decoded = unquote(original_url)
                if decoded != original_url:
                    md_body = md_body.replace(decoded, rel_path)

        # ── Token / word counting ────────────────────────────────────────
        word_count, token_estimate = _count_tokens(md_body)

        # ── Assemble output ──────────────────────────────────────────────
        parts = []

        if self.metadata:
            if not meta.get("title") and title:
                meta["title"] = title
            meta["url"] = url
            meta["word_count"] = word_count
            meta["estimated_tokens"] = token_estimate
            parts.append(_format_front_matter(meta))

        # Only add explicit H1 title if the body doesn't already start with one
        # (readability-extracted content often includes the title as H1)
        body_has_title = md_body.lstrip().startswith("# ")
        if title and not body_has_title:
            parts.append(f"# {title}")
        parts.append(f"> Source: <{url}>")
        parts.append("")
        parts.append(md_body)

        return "\n\n".join(parts) + "\n", word_count, token_estimate

    # ── Content extraction helpers ────────────────────────────────────

    @staticmethod
    def _strip_boilerplate(soup: BeautifulSoup) -> None:
        """Remove script/style/noscript tags from soup in place."""
        for tag in soup.find_all(["script", "style", "noscript"]):
            tag.decompose()

    @staticmethod
    def _heuristic_extract(soup: BeautifulSoup):
        """Extract main content using heuristic tag detection. Returns content root element."""
        for selector in [
            soup.find("article"),
            soup.find("main"),
            soup.find("div", {"role": "main"}),
            soup.find("div", id=re.compile(r"content|main|article", re.I)),
            soup.find("div", class_=re.compile(r"content|main|article|post-body", re.I)),
        ]:
            if selector:
                return selector
        return soup

    # ── Metadata extraction ───────────────────────────────────────────

    @staticmethod
    def _extract_metadata(soup: BeautifulSoup, url: str) -> dict:
        """Extract comprehensive metadata from HTML page."""
        meta = {}

        # Helper to get meta tag content
        def get_meta(attrs: dict) -> str | None:
            tag = soup.find("meta", attrs=attrs)
            if tag:
                return tag.get("content", "").strip() or None
            return None

        # ── Title: og > twitter > <title> ────────────────────────────
        meta["title"] = (
            get_meta({"property": "og:title"})
            or get_meta({"name": "twitter:title"})
        )
        if not meta["title"]:
            title_tag = soup.find("title")
            if title_tag:
                meta["title"] = title_tag.get_text(strip=True) or None

        # ── Description ──────────────────────────────────────────────
        meta["description"] = (
            get_meta({"property": "og:description"})
            or get_meta({"name": "twitter:description"})
            or get_meta({"name": "description"})
        )

        # ── Author ───────────────────────────────────────────────────
        meta["author"] = (
            get_meta({"name": "author"})
            or get_meta({"property": "article:author"})
        )

        # ── Dates ────────────────────────────────────────────────────
        meta["published"] = (
            get_meta({"property": "article:published_time"})
            or get_meta({"name": "date"})
            or get_meta({"name": "publish_date"})
        )
        if not meta["published"]:
            time_tag = soup.find("time", attrs={"datetime": True})
            if time_tag:
                meta["published"] = time_tag["datetime"]

        meta["modified"] = (
            get_meta({"property": "article:modified_time"})
            or get_meta({"name": "last-modified"})
        )

        # ── Canonical URL ────────────────────────────────────────────
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            meta["canonical_url"] = canonical["href"]

        # ── Language ─────────────────────────────────────────────────
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            meta["language"] = html_tag["lang"]

        # ── Keywords ─────────────────────────────────────────────────
        kw_content = get_meta({"name": "keywords"})
        if kw_content:
            keywords = [k.strip() for k in kw_content.split(",") if k.strip()]
            if keywords:
                meta["keywords"] = keywords

        # ── Open Graph extras ────────────────────────────────────────
        site_name = get_meta({"property": "og:site_name"})
        if site_name:
            meta["site_name"] = site_name

        og_image = get_meta({"property": "og:image"})
        if og_image:
            meta["image"] = og_image

        og_type = get_meta({"property": "og:type"})
        if og_type:
            meta["type"] = og_type

        # ── Schema.org JSON-LD (highest priority, overrides above) ───
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                ld = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            items = ld if isinstance(ld, list) else [ld]
            for item in items:
                if not isinstance(item, dict):
                    continue
                schema_type = item.get("@type", "")
                if schema_type in ("Article", "BlogPosting", "NewsArticle",
                                   "TechArticle", "WebPage", "ScholarlyArticle"):
                    if item.get("headline"):
                        meta["title"] = item["headline"]
                    if item.get("description"):
                        meta["description"] = item["description"]
                    if item.get("datePublished"):
                        meta["published"] = item["datePublished"]
                    if item.get("dateModified"):
                        meta["modified"] = item["dateModified"]
                    # Author can be string, dict, or list
                    author = item.get("author")
                    if isinstance(author, str):
                        meta["author"] = author
                    elif isinstance(author, dict):
                        meta["author"] = author.get("name", meta.get("author"))
                    elif isinstance(author, list) and author:
                        names = []
                        for a in author:
                            if isinstance(a, str):
                                names.append(a)
                            elif isinstance(a, dict) and a.get("name"):
                                names.append(a["name"])
                        if names:
                            meta["author"] = ", ".join(names)
                    if item.get("@type"):
                        meta["schema_type"] = item["@type"]
                    break  # Use first matching schema

        # Remove None values
        return {k: v for k, v in meta.items() if v is not None}

    # ── Table preprocessing ───────────────────────────────────────────

    @staticmethod
    def _preprocess_tables(soup: BeautifulSoup) -> None:
        """Pre-process tables for better markdown conversion."""
        for table in soup.find_all("table"):
            # Flatten nested tables: extract inner table content into parent cell
            for nested in table.find_all("table"):
                nested.replace_with(BeautifulSoup(nested.get_text(" ", strip=True), "html.parser"))

            # Expand colspan: duplicate cell content across spanned columns
            for cell in table.find_all(["td", "th"]):
                colspan = int(cell.get("colspan", 1))
                if colspan > 1:
                    del cell["colspan"]
                    for _ in range(colspan - 1):
                        new_cell = soup.new_tag(cell.name)
                        new_cell.string = ""
                        cell.insert_after(new_cell)

            # Expand rowspan: mark cells for later rows
            for cell in table.find_all(["td", "th"]):
                rowspan = int(cell.get("rowspan", 1))
                if rowspan > 1:
                    del cell["rowspan"]
                    # Find cell index in its row
                    row = cell.parent
                    if row is None:
                        continue
                    cells = row.find_all(["td", "th"])
                    try:
                        idx = cells.index(cell)
                    except ValueError:
                        continue
                    # Insert empty cells in subsequent rows
                    sibling = row.find_next_sibling("tr")
                    for _ in range(rowspan - 1):
                        if sibling is None:
                            break
                        sib_cells = sibling.find_all(["td", "th"])
                        new_cell = soup.new_tag(cell.name)
                        new_cell.string = ""
                        if idx < len(sib_cells):
                            sib_cells[idx].insert_before(new_cell)
                        else:
                            sibling.append(new_cell)
                        sibling = sibling.find_next_sibling("tr")

    # ── Code block preprocessing ──────────────────────────────────────

    @staticmethod
    def _preprocess_code_blocks(soup: BeautifulSoup) -> None:
        """Preserve language hints from code blocks for proper markdown fences.

        Injects a unique marker as the first text inside <code> so that after
        html2text conversion we can replace bare ``` fences with ```lang fences.
        """
        for pre in soup.find_all("pre"):
            code = pre.find("code")
            if not code:
                continue
            # Extract language from class attribute
            classes = code.get("class", [])
            lang = ""
            for cls in classes:
                if cls.startswith("language-"):
                    lang = cls[9:]
                    break
                elif cls.startswith("lang-"):
                    lang = cls[5:]
                    break
                elif cls.startswith("hljs") and cls != "hljs":
                    lang = cls.replace("hljs-", "").replace("hljs", "").strip()
                    if not lang:
                        continue
                    break
            if not lang:
                known_langs = {
                    "python", "javascript", "typescript", "java", "c", "cpp", "csharp",
                    "go", "rust", "ruby", "php", "swift", "kotlin", "scala", "html",
                    "css", "sql", "bash", "shell", "json", "xml", "yaml", "toml",
                    "markdown", "r", "matlab", "perl", "lua", "haskell", "elixir",
                }
                for cls in classes:
                    if cls.lower() in known_langs:
                        lang = cls.lower()
                        break
            if lang:
                # Insert marker as first text node; post-processing will move it
                # to the ``` fence line
                marker = f"__CODELANG_{lang}__\n"
                if code.string:
                    code.string = marker + code.string
                else:
                    code.insert(0, marker)

    # ── I/O ──────────────────────────────────────────────────────────────

    @staticmethod
    def _save(filepath: str, content: str) -> None:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    def _fetch(self, url: str) -> str | None:
        html, error = self.fetcher.fetch(url)
        if error:
            print(f"  [ERROR] {error}")
            return None
        return html

    # ── Main loop ────────────────────────────────────────────────────────

    def crawl(self) -> None:
        start = self._normalize(self.start_url)
        self.queue.append(start)
        self.visited.add(start)

        saved = 0
        skipped = 0
        already_exists = 0
        total_words = 0
        total_tokens = 0

        print(f"Domain      : {self.domain}")
        print(f"Start URL   : {start}")
        print(f"Output dir  : {os.path.abspath(self.output_dir)}")
        print(f"Fetcher     : {self.fetcher.name}")
        print(f"Extractor   : {self.extractor_name}")
        print(f"Metadata    : {'on (YAML front matter)' if self.metadata else 'off'}")
        print(f"Proxy       : {self.proxy_label}")
        print(f"Delay       : {self.delay}s")
        print(f"Max pages   : {self.max_pages or 'all (no limit)'}")
        print(f"Path prefix : {self.prefix or '(none)'}")
        print(f"Resume mode : {'off (overwrite)' if self.overwrite else 'on (skip existing)'}")
        print(f"Images      : {'download' if self.download_images else 'skip (URLs only)'}")
        print(f"Save HTML   : {'on' if self.save_html else 'off'}")
        print(f"Verbose     : {'on' if self.verbose else 'off'}")
        print("=" * 64)

        try:
            while self.queue:
                if self.max_pages and saved >= self.max_pages:
                    print(f"\nReached page limit ({self.max_pages}).")
                    break

                url = self.queue.popleft()
                fpath = self._url_to_filepath(url)

                # Check if file already exists (incremental mode)
                if not self.overwrite and os.path.exists(fpath):
                    # Listing/archive pages: always re-fetch for link discovery
                    if self._is_listing_page(url):
                        print(f"\n[re-scan] {url}")
                        print(f"  -> listing page: re-fetching for link discovery")
                        html = self._fetch(url)
                        if html:
                            html_size = len(html)
                            if self.verbose:
                                print(f"  [verbose] Fetched {html_size} bytes of HTML")
                            soup = BeautifulSoup(html, "html.parser")
                            new_links = self._extract_links(soup, url)
                            enqueued = 0
                            for link in new_links:
                                if link not in self.visited:
                                    self.visited.add(link)
                                    self.queue.append(link)
                                    enqueued += 1
                                    if self.verbose:
                                        print(f"    [+queue] {link}")
                            print(f"  -> found {len(new_links)} links, +{enqueued} new queued")
                            if len(new_links) == 0:
                                print(f"  -> WARNING: 0 links found ({html_size} bytes HTML).")
                                a_tags = soup.find_all("a", href=True)
                                print(f"     Raw <a> tags in HTML: {len(a_tags)}")
                                if html_size < 2000 or len(a_tags) == 0:
                                    print(f"     The page may require JavaScript rendering.")
                                    print(f"     Try: --fetcher curl  or  --fetcher browser")
                            print(f"     Queue size: {len(self.queue)}, Total visited: {len(self.visited)}")
                            # Update the markdown file with fresh content
                            md, wc, tc = self._html_to_markdown(html, url, fpath)
                            total_words += wc
                            total_tokens += tc
                            self._save(fpath, md)
                            if self.save_html:
                                html_path = os.path.splitext(fpath)[0] + ".html"
                                self._save(html_path, html)
                            print(f"  -> updated: {fpath}")
                        already_exists += 1
                        if self.delay > 0:
                            time.sleep(self.delay)
                        continue

                    already_exists += 1
                    print(f"\n[skip] {url}")
                    print(f"  -> already exists: {fpath}")

                    # Still need to extract links from existing file to continue traversal
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            existing_content = f.read()
                        # Extract URLs from markdown links [text](url)
                        md_links = re.findall(r'\]\(<([^>]+)>\)', existing_content)
                        # Also extract bare URLs in markdown  [text](url) without angle brackets
                        md_links += re.findall(r'\]\(([^)<>\s]+)\)', existing_content)
                        extracted_count = 0
                        for href in md_links:
                            if href.startswith(("http://", "https://")):
                                normalized = self._normalize(href)
                                if self._is_internal(normalized) and normalized not in self.visited:
                                    self.visited.add(normalized)
                                    self.queue.append(normalized)
                                    extracted_count += 1
                                    if self.verbose:
                                        print(f"    [+queue from md] {normalized}")
                        if extracted_count > 0:
                            print(f"  -> extracted {extracted_count} new links from existing markdown")
                    except Exception:
                        pass  # Ignore errors reading existing file
                    continue

                print(f"\n[{saved + 1}] {url}")

                html = self._fetch(url)
                if html is None:
                    skipped += 1
                    print("  -> skipped (not HTML or fetch error)")
                    continue
                
                html_size = len(html)
                if self.verbose:
                    print(f"  [verbose] Fetched {html_size} bytes of HTML")

                soup = BeautifulSoup(html, "html.parser")
                if self.verbose:
                    print(f"  [verbose] Extracting links from page...")
                new_links = self._extract_links(soup, url)
                enqueued = 0
                already_seen = 0
                for link in new_links:
                    if link not in self.visited:
                        self.visited.add(link)
                        self.queue.append(link)
                        enqueued += 1
                        if self.verbose:
                            print(f"    [+queue] {link}")
                    else:
                        already_seen += 1

                if saved == 0 and enqueued == 0 and len(new_links) == 0:
                    a_tags = soup.find_all("a", href=True)
                    print(f"  -> WARNING: 0 links found ({html_size} bytes HTML, {len(a_tags)} raw <a> tags).")
                    if html_size < 2000 or len(a_tags) == 0:
                        print(f"     The page may require JavaScript rendering.")
                        print(f"     Try: --fetcher curl  or  --fetcher browser")

                md, wc, tc = self._html_to_markdown(html, url, fpath)
                total_words += wc
                total_tokens += tc
                self._save(fpath, md)
                saved += 1

                # Optionally save raw HTML alongside markdown
                if self.save_html:
                    html_path = os.path.splitext(fpath)[0] + ".html"
                    self._save(html_path, html)
                    if self.verbose:
                        print(f"  [html] {html_path}")

                print(f"  -> {fpath}")
                print(f"     Found {len(new_links)} links, +{enqueued} new queued, {already_seen} already seen")
                print(f"     Queue size: {len(self.queue)}, Total visited: {len(self.visited)}")

                if self.delay > 0:
                    time.sleep(self.delay)
        finally:
            self.fetcher.close()
            if self.image_downloader:
                self.image_downloader.close()

        print("\n" + "=" * 64)
        print(f"Done. Saved {saved} new pages, skipped {skipped} errors, {already_exists} already existed.")
        if self.image_downloader:
            dl = self.image_downloader
            print(f"Images: {dl.download_count} downloaded, {dl.skip_count} already existed, {dl.error_count} errors.")
        if total_words > 0:
            print(f"Total: {total_words:,} words, ~{total_tokens:,} estimated tokens")
        print(f"Output: {os.path.abspath(self.output_dir)}")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    from huan import __version__

    ap = argparse.ArgumentParser(
        prog="huan",
        description="Convert web pages to Markdown files, preserving the "
                    "site's directory structure.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Convert entire site (default - no limit)
  huan https://geopytool.com

  # Limit to first 100 pages
  huan https://geopytool.com -m 100

  # With proxy and curl backend
  huan https://geopytool.com --fetcher curl --proxy http://127.0.0.1:7890

  # With system browser (Chrome/Edge) for JS-heavy sites
  huan https://geopytool.com --fetcher browser --proxy http://127.0.0.1:7890

  # For newsletter sites - use /archive to get all articles (infinite scroll)
  huan https://geopytool.com/archive --fetcher browser --scroll 30 --proxy http://127.0.0.1:7890

Tips:
  - For newsletter sites: start with /archive URL to find all articles
  - Use --scroll 30 or higher for sites with many lazy-loaded articles
""",
    )
    ap.add_argument("url", help="Starting URL to archive")
    ap.add_argument(
        "-o", "--output",
        help="Output directory (default: domain name)",
    )
    ap.add_argument(
        "-d", "--delay",
        type=float, default=0.5,
        help="Seconds between requests (default: 0.5)",
    )
    ap.add_argument(
        "-m", "--max-pages",
        type=int, default=None,
        help="Limit number of pages to save (default: no limit, archive entire site)",
    )
    ap.add_argument(
        "--prefix",
        default=None,
        help="Only archive URLs whose path starts with this prefix (e.g. /docs)",
    )
    ap.add_argument(
        "--full",
        action="store_true",
        help="Save full page content (alias for --extractor full, kept for backward compatibility)",
    )
    ap.add_argument(
        "--extractor",
        choices=["readability", "heuristic", "full"],
        default="readability",
        help="Content extraction strategy: readability (default, best quality, requires readability-lxml), "
             "heuristic (tag-based fallback), full (entire page)",
    )
    ap.add_argument(
        "--no-metadata",
        action="store_true",
        help="Disable YAML front matter metadata extraction (enabled by default)",
    )
    ap.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Disable SSL certificate verification",
    )
    ap.add_argument(
        "--proxy",
        default=None,
        help="HTTP/HTTPS proxy URL (e.g. http://127.0.0.1:7890)",
    )
    ap.add_argument(
        "--system-proxy",
        action="store_true",
        help="Use system proxy from HTTP_PROXY / HTTPS_PROXY environment variables",
    )
    ap.add_argument(
        "--fetcher",
        choices=["requests", "curl", "browser", "playwright"],
        default="requests",
        help="Fetcher backend: requests (default), curl (better compatibility), browser (system Chrome/Edge via DrissionPage), playwright (requires playwright install chromium)",
    )
    ap.add_argument(
        "--scroll",
        type=int,
        default=20,
        help="Number of times to scroll page for lazy-loaded content (default: 20, use 0 to disable, only works with --fetcher browser)",
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files (default: skip existing for incremental archiving)",
    )
    ap.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose mode: show all discovered links during archiving (useful for debugging)",
    )
    ap.add_argument(
        "--no-download-images",
        action="store_true",
        help="Disable downloading images (by default images are downloaded and saved locally with relative paths in markdown)",
    )
    ap.add_argument(
        "--save-html",
        action="store_true",
        help="Also save the original HTML file alongside each markdown file",
    )
    ap.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    args = ap.parse_args()

    # --full is an alias for --extractor full
    extractor = args.extractor
    if args.full:
        extractor = "full"

    url = args.url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    archiver = SiteCrawler(
        start_url=url,
        output_dir=args.output,
        delay=args.delay,
        max_pages=args.max_pages,
        prefix=args.prefix,
        full_content=args.full,
        verify_ssl=not args.no_verify_ssl,
        proxy=args.proxy,
        system_proxy=args.system_proxy,
        fetcher_type=args.fetcher,
        scroll_count=args.scroll,
        overwrite=args.overwrite,
        verbose=args.verbose,
        download_images=not args.no_download_images,
        save_html=args.save_html,
        extractor=extractor,
        metadata=not args.no_metadata,
    )
    archiver.crawl()


if __name__ == "__main__":
    main()
