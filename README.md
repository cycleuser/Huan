# huan

A command-line tool that converts web pages to Markdown files, preserving the site's URL structure as a local folder hierarchy.

The name "huan" (换) means "convert" in Chinese.

## Features

- **Web Page Conversion** - Traverses a website and converts every page to clean Markdown
- **Readability Extraction** - Uses Mozilla's Readability algorithm for high-quality content extraction (via readability-lxml)
- **Rich Metadata** - Extracts title, author, date, Open Graph, Schema.org etc. as YAML front matter
- **Multiple HTTP Backends** - Choose from requests, curl_cffi, DrissionPage (system browser), or Playwright
- **Infinite Scroll Support** - Automatic scrolling for lazy-loaded content
- **Math Formula Conversion** - MathML, MathJax, and KaTeX converted to LaTeX notation
- **Image Downloading** - Downloads images locally with relative path rewriting in Markdown
- **Code Block Language Detection** - Preserves language hints from HTML for proper fenced code blocks
- **Table Preprocessing** - Handles complex tables with colspan/rowspan for cleaner Markdown output
- **Token Estimation** - Reports word count and estimated token count for LLM usage planning
- **Incremental Mode** - Skip existing files for efficient re-runs
- **Proxy Support** - Manual proxy or system environment variables
- **Save Raw HTML** - Optionally save original HTML alongside Markdown

## Installation

```bash
git clone https://github.com/cycleuser/Huan.git
cd Huan
pip install -e .
```

### Optional Dependencies

For better content extraction quality (recommended):
```bash
pip install -e ".[readability]"
```

For better browser compatibility:
```bash
pip install -e ".[curl]"
```

For JavaScript-heavy sites:
```bash
pip install -e ".[browser]"   # Uses system Chrome/Edge via DrissionPage
```

Or install all optional dependencies:
```bash
pip install -e ".[all]"
```

## Usage

### Basic Usage

```bash
# Convert an entire site
huan https://example.com

# Limit to first 100 pages
huan https://example.com -m 100

# Specify output directory
huan https://example.com -o ./my-archive
```

### Content Extraction

```bash
# Default: readability extraction (best quality, requires readability-lxml)
huan https://example.com

# Heuristic extraction (tag-based, no extra dependency needed)
huan https://example.com --extractor heuristic

# Full page content (no extraction filtering)
huan https://example.com --extractor full
```

### Metadata

Each Markdown file includes YAML front matter with extracted metadata:

```yaml
---
title: "Article Title"
author: "Author Name"
published: 2024-01-15
url: "https://example.com/article"
language: en
word_count: 2847
estimated_tokens: 3701
---
```

To disable metadata extraction:
```bash
huan https://example.com --no-metadata
```

### With Proxy

```bash
# Manual proxy
huan https://example.com --proxy http://127.0.0.1:7890

# System proxy (from HTTP_PROXY/HTTPS_PROXY env vars)
huan https://example.com --system-proxy
```

### Different Fetcher Backends

Some sites use JavaScript to render content, which the default `requests` backend cannot handle. If the tool returns 0 links or incomplete content, try switching to a different backend:

```bash
# Default: standard requests (fast, works for static sites)
huan https://example.com

# curl_cffi backend (better compatibility with more sites)
huan https://example.com --fetcher curl

# System browser (recommended for JS-rendered sites)
huan https://example.com --fetcher browser

# Playwright (requires: playwright install chromium)
huan https://example.com --fetcher playwright
```

**Tip**: If the default `requests` backend finds 0 links on a page, the tool will print a warning suggesting you try `--fetcher curl` or `--fetcher browser`.

### For Sites with Infinite Scroll

```bash
# Newsletter sites: use /archive endpoint + browser fetcher
huan https://example.com/archive --fetcher browser --scroll 50

# Blog platforms with infinite scroll
huan https://example.com/ --fetcher browser --scroll 30
```

### Additional Options

```bash
# Save raw HTML alongside Markdown
huan https://example.com --save-html

# Disable image downloading
huan https://example.com --no-download-images

# Overwrite existing files (disable incremental mode)
huan https://example.com --overwrite

# Only convert pages under /docs
huan https://example.com --prefix /docs

# Verbose output for debugging
huan https://example.com -v
```

## Command-Line Options

| Option | Description |
|--------|-------------|
| `url` | Starting URL (required) |
| `-o, --output` | Output directory (default: domain name) |
| `-d, --delay` | Seconds between requests (default: 0.5) |
| `-m, --max-pages` | Limit number of pages (default: no limit) |
| `--prefix` | Only convert URLs with this path prefix |
| `--extractor` | Content extraction: readability, heuristic, full |
| `--full` | Alias for `--extractor full` |
| `--no-metadata` | Disable YAML front matter metadata |
| `--no-verify-ssl` | Disable SSL certificate verification |
| `--proxy` | HTTP/HTTPS proxy URL |
| `--system-proxy` | Use system proxy from environment |
| `--fetcher` | Backend: requests, curl, browser, playwright |
| `--scroll` | Scroll count for lazy-loaded content (default: 20) |
| `--overwrite` | Overwrite existing files |
| `-v, --verbose` | Verbose output |
| `--no-download-images` | Skip image downloading |
| `--save-html` | Save raw HTML alongside Markdown |
| `--version` | Show version |

## Output Structure

```
example.com/
├── index.md
├── about.md
├── blog/
│   ├── index.md
│   ├── post-1.md
│   └── post-2.md
├── images/
│   ├── logo.png
│   └── hero.jpg
└── _external/
    └── cdn.example.com/
        └── assets/
            └── image.webp
```

- Markdown files mirror the site's URL structure
- Same-domain images are saved preserving their path
- External CDN images go under `_external/{domain}/`
- All image references in Markdown use relative paths

## Python API

```python
from huan import SiteCrawler

converter = SiteCrawler(
    start_url="https://example.com",
    output_dir="./archive",
    max_pages=50,
    fetcher_type="browser",
    download_images=True,
    extractor="readability",
)
converter.crawl()
```

## Requirements

- Python 3.10+
- requests
- beautifulsoup4
- html2text

Optional:
- readability-lxml (better content extraction)
- curl-cffi (better compatibility)
- DrissionPage (for system browser)
- playwright (for headless Chromium)

## License

MIT License - see [LICENSE](LICENSE) for details.
