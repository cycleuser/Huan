# huan

A command-line tool that converts web pages to perfect Markdown files. By default, downloads only the provided URL. Use `-r` to transform entire sites.

The name "huan" (换) means "convert" in Chinese.

## Features

- **Single Page or Full Site** - Default: download one page as perfect Markdown. Use `-r` to recursively transform entire sites
- **Perfect Markdown Output** - Clean, well-formatted Markdown with formulas, code blocks, and images
- **Image Downloading** - Downloads all images to `images/` directory with relative path rewriting
- **Math Formula Conversion** - MathML, MathJax, and KaTeX converted to LaTeX notation
- **Readability Extraction** - Uses Mozilla's Readability algorithm for high-quality content extraction (via readability-lxml)
- **Rich Metadata** - Extracts title, author, date, Open Graph, Schema.org etc. as YAML front matter
- **Multiple HTTP Backends** - Choose from requests, curl_cffi, DrissionPage (system browser), or Playwright
- **Infinite Scroll Support** - Automatic scrolling for lazy-loaded content
- **Code Block Language Detection** - Preserves language hints from HTML for proper fenced code blocks
- **Table Preprocessing** - Handles complex tables with colspan/rowspan for cleaner Markdown output
- **Token Estimation** - Reports word count and estimated token count for LLM usage planning
- **Incremental Mode** - Skip existing files for efficient re-runs
- **Proxy Support** - Manual proxy or system environment variables
- **Save Raw HTML** - Optionally save original HTML alongside Markdown

## Installation

Install from PyPI:
```bash
pip install huan
```

To install the latest development version from source:
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
# Convert a single page to Markdown (default behavior)
huan https://geopytool.com/article-123

# Recursively transform entire site
huan https://geopytool.com -r

# Limit recursive transform to first 100 pages
huan https://geopytool.com -r -m 100

# Specify output directory
huan https://geopytool.com/article -o ./my-archive
```

### Content Extraction

```bash
# Default: readability extraction (best quality, requires readability-lxml)
huan https://geopytool.com/article

# Heuristic extraction (tag-based, no extra dependency needed)
huan https://geopytool.com/article --extractor heuristic

# Full page content (no extraction filtering)
huan https://geopytool.com/article --extractor full
```

### Metadata

Each Markdown file includes YAML front matter with extracted metadata:

```yaml
---
title: "Article Title"
author: "Author Name"
published: 2024-01-15
url: "https://geopytool.com/article"
language: en
word_count: 2847
estimated_tokens: 3701
---
```

To disable metadata extraction:
```bash
huan https://geopytool.com/article --no-metadata
```

### With Proxy

```bash
# Manual proxy
huan https://geopytool.com/article --proxy http://127.0.0.1:7890

# System proxy (from HTTP_PROXY/HTTPS_PROXY env vars)
huan https://geopytool.com/article --system-proxy
```

### Different Fetcher Backends

Some sites use JavaScript to render content, which the default `requests` backend cannot handle. If the tool returns 0 links or incomplete content, try switching to a different backend:

```bash
# Default: standard requests (fast, works for static sites)
huan https://geopytool.com/article

# curl_cffi backend (better compatibility with more sites)
huan https://geopytool.com/article --fetcher curl

# System browser (recommended for JS-rendered sites)
huan https://geopytool.com/article --fetcher browser

# Playwright (requires: playwright install chromium)
huan https://geopytool.com/article --fetcher playwright
```

**Tip**: If the default `requests` backend finds 0 links on a page, the tool will print a warning suggesting you try `--fetcher curl` or `--fetcher browser`.

### For Sites with Infinite Scroll

```bash
# Newsletter sites: use /archive endpoint + browser fetcher + recursive
huan https://geopytool.com/archive -r --fetcher browser --scroll 50

# Blog platforms with infinite scroll
huan https://geopytool.com/ -r --fetcher browser --scroll 30
```

### Additional Options

```bash
# Save raw HTML alongside Markdown
huan https://geopytool.com/article --save-html

# Disable image downloading
huan https://geopytool.com/article --no-download-images

# Overwrite existing files (disable incremental mode)
huan https://geopytool.com/article --overwrite

# Only convert pages under /docs (recursive mode)
huan https://geopytool.com -r --prefix /docs

# Verbose output for debugging
huan https://geopytool.com/article -v
```

## Command-Line Options

| Option | Description |
|--------|-------------|
| `url` | Starting URL (required) |
| `-o, --output` | Output directory (default: domain name) |
| `-d, --delay` | Seconds between requests (default: 0.5) |
| `-m, --max-pages` | Limit number of pages (default: no limit) |
| `-r, --recursive` | Recursively transform entire site (default: single page only) |
| `--prefix` | Only convert URLs with this path prefix (recursive mode) |
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

# Single page (default)
converter = SiteCrawler(
    start_url="https://geopytool.com/article-123",
    output_dir="./archive",
    download_images=True,
    extractor="readability",
)
converter.crawl()

# Recursive transform
converter = SiteCrawler(
    start_url="https://geopytool.com",
    output_dir="./archive",
    max_pages=50,
    fetcher_type="browser",
    download_images=True,
    extractor="readability",
    recursive=True,
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

## Screenshots

![Running Screenshot](images/sample.png)

## Agent Integration (OpenAI Function Calling)

Huan exposes an OpenAI-compatible tool for LLM agents:

```python
from huan.tools import TOOLS, dispatch

response = client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    tools=TOOLS,
)

result = dispatch(
    tool_call.function.name,
    tool_call.function.arguments,
)
```

## CLI Help

![CLI Help](images/huan_help.png)

## License

MIT License - see [LICENSE](LICENSE) for details.
