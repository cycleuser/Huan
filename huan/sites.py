"""
Huan - Incremental site archiving.

Adds a config-driven "site archiver" on top of Huan's page-to-Markdown core:
for sites that expose a list of articles/topics (via JSON API or an index
page), it only downloads what is not already saved locally, converts each
item to Markdown, and rebuilds index files.

All site-specific details (URL, local save path, adapter type and adapter
options) live in a JSON config file, never in this module.  The adapters here
are *generic* and keyed by structural type, not by any particular website.

Example config (sites.json):
    {
      "proxy": "http://127.0.0.1:7897",
      "sites": {
        "forum": {
          "name": "My Forum",
          "url": "https://forum.example.com",
          "save_dir": "/path/to/archive/forum",
          "type": "nodebb"
        },
        "portal": {
          "name": "My Portal",
          "url": "https://news.example.com",
          "save_dir": "/path/to/archive/portal",
          "type": "article-portal",
          "id_pattern": "/(\\\\d+)\\\\.html",
          "url_template": "{base}/data/{id}.html",
          "title_strip": "[_\\\\s]*\\\\|.*$"
        }
      }
    }
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path
from typing import Any

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:136.0) "
    "Gecko/20100101 Firefox/136.0"
)

#: Default site registry.  Intentionally empty: the user supplies real sites
#: through a config file, so no website is hard-coded here.
DEFAULT_SITES: dict[str, dict[str, Any]] = {}

#: Generic defaults for each adapter type.  These are structural, not
#: site-specific, and can be overridden per-site in the config.
ADAPTER_DEFAULTS: dict[str, dict[str, Any]] = {
    # NodeBB-style forum (standard JSON API: /api/categories, /api/category/…)
    "nodebb": {
        "min_delay": 2.0,
        "max_delay": 4.0,
    },
    # Article portal: discover numeric article IDs from an index page, then
    # fetch each article.  The three regex/template fields below are generic
    # defaults; override them in the config for a particular site.
    "article-portal": {
        "id_pattern": r"/(\d+)\.html",
        "url_template": "{base}/data/{id}.html",
        "title_strip": r"[_\s]*\|.*$",
        "cooldown": 600,
        "min_delay": 4.0,
        "max_delay": 8.0,
    },
}


# --------------------------------------------------------------------------
# Config helpers
# --------------------------------------------------------------------------
def default_config_path() -> Path:
    """Return the conventional config location (~/.config/huan/sites.json)."""
    return Path.home() / ".config" / "huan" / "sites.json"


def load_sites_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load a sites config. Returns an empty site map when no file exists."""
    if path is None:
        path = default_config_path()
    path = Path(path)
    if not path.exists():
        return {"proxy": None, "sites": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("proxy", None)
    data.setdefault("sites", {})
    return data


def write_sites_config_template(path: str | Path | None = None,
                                overwrite: bool = False) -> Path:
    """Write a template config file the user can edit (placeholder URLs)."""
    if path is None:
        path = default_config_path()
    path = Path(path)
    if path.exists() and not overwrite:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    template = {
        "proxy": "http://127.0.0.1:7897",
        "sites": {
            "forum": {
                "name": "My Forum",
                "url": "https://forum.example.com",
                "save_dir": str(Path.home() / "archive" / "forum"),
                "type": "nodebb",
            },
            "portal": {
                "name": "My Portal",
                "url": "https://news.example.com",
                "save_dir": str(Path.home() / "archive" / "portal"),
                "type": "article-portal",
                "id_pattern": r"/(\d+)\.html",
                "url_template": "{base}/data/{id}.html",
                "title_strip": r"[_\s]*\|.*$",
            },
        },
    }
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Shared utilities
# --------------------------------------------------------------------------
def _http_get(url: str, params: dict | None = None, proxy: str | None = None,
              timeout: int = 60, retries: int = 8) -> str | None:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", DEFAULT_UA)
            req.add_header("Accept", "application/json, text/html;q=0.9,*/*;q=0.8")
            if proxy:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
                resp = opener.open(req, timeout=timeout)
            else:
                resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.read().decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001
            if attempt < retries - 1:
                wait = min(5 * (attempt + 1), 60)
                print(f"\n  [retry {attempt + 2}] {url[:60]}... {str(exc)[:40]} wait {wait}s",
                      flush=True)
                time.sleep(wait)
            else:
                print(f"\n  [give up] {url[:60]}... {str(exc)[:50]}", flush=True)
                return None
    return None


def _delay(min_d: float, max_d: float) -> None:
    t = random.uniform(min_d, max_d)
    print(f"  [sleep {t:.1f}s]", end="", flush=True)
    time.sleep(t)


def _sanitize(name: str) -> str:
    safe = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", str(name))
    return re.sub(r"_+", "_", safe).strip("_") or "unknown"


def _html_to_md(html: str) -> str:
    try:
        from markdownify import markdownify as md
        return md(html, heading_style="ATX")
    except ImportError:
        text = re.sub(r"<br\s*/?>", "\n", html)
        text = re.sub(r"<p[^>]*>", "\n\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        return unescape(text)


def _opt(cfg: dict[str, Any], type_key: str, key: str, fallback: Any = None) -> Any:
    """Read an option: site config first, then adapter defaults, then fallback."""
    if key in cfg:
        return cfg[key]
    return ADAPTER_DEFAULTS.get(type_key, {}).get(key, fallback)


# --------------------------------------------------------------------------
# Adapter: nodebb — generic NodeBB-style forum (standard JSON API)
# --------------------------------------------------------------------------
def _run_nodebb(cfg: dict[str, Any], proxy: str | None, min_delay: float,
                max_delay: float) -> dict[str, Any]:
    base = cfg["url"].rstrip("/")
    api = base + "/api"
    save_dir = Path(cfg["save_dir"])
    data_dir = save_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    def api_get(path: str, params: dict | None = None) -> dict:
        text = _http_get(api + urllib.parse.quote(path, safe="/-_.~"), params, proxy)
        return json.loads(text) if text else {}

    def existing_tids() -> set[int]:
        out = set()
        for cat_dir in data_dir.iterdir():
            if cat_dir.is_dir():
                for f in cat_dir.glob("*.md"):
                    if f.name != "index.md":
                        try:
                            out.add(int(f.stem))
                        except ValueError:
                            pass
        return out

    def categories() -> list[dict]:
        data = api_get("/categories")
        return [{"cid": c["cid"], "name": c["name"], "slug": c["slug"]}
                for c in data.get("categories", [])]

    def category_topics(slug: str) -> list[dict]:
        out, page = [], 1
        while True:
            data = api_get(f"/category/{slug}", {"lang": "zh-CN", "page": page})
            for t in data.get("topics", []):
                if not t.get("deleted"):
                    out.append({
                        "tid": t["tid"], "slug": t.get("slug", ""),
                        "title": t["title"],
                        "username": (t.get("user") or {}).get("username", ""),
                    })
            if page >= data.get("pagination", {}).get("pageCount", 1):
                break
            page += 1
            _delay(min_delay, max_delay)
        return out

    def topic_posts(tid: int, slug: str) -> tuple[list[dict], dict]:
        posts, meta, page = [], {}, 1
        while True:
            path = f"/topic/{slug}" if slug else f"/topic/{tid}"
            raw = api_get(path)
            for p in raw.get("posts", []):
                if not p.get("deleted"):
                    posts.append({
                        "username": (p.get("user") or {}).get("username", ""),
                        "content": _html_to_md(p.get("content", "")),
                    })
            if page == 1:
                meta = {
                    "title": raw.get("title", ""),
                    "username": (raw.get("user") or {}).get("username", ""),
                    "timestamp": raw.get("timestampISO", ""),
                    "tags": [t.get("value", str(t)) if isinstance(t, dict) else str(t)
                             for t in raw.get("tags", [])],
                    "slug": raw.get("slug", ""),
                }
            if page >= raw.get("pagination", {}).get("pageCount", 1):
                break
            page += 1
            _delay(min_delay, max_delay)
        return posts, meta

    def save_topic(tid: int, meta: dict, posts: list[dict], cat_name: str,
                   cat_dir: Path) -> None:
        url = f"{base}/topic/{tid}/{meta.get('slug', '')}"
        lines = [
            "---",
            f'title: "{meta["title"]}"',
            f'url: "{url}"',
            f'category: "{cat_name}"',
            f'author: "{meta["username"]}"',
            f'timestamp: "{meta["timestamp"]}"',
            f"tags: {json.dumps(meta['tags'], ensure_ascii=False)}",
            "---", "",
            "# " + meta["title"], "",
            f'> 作者: {meta["username"]}  |  时间: {meta["timestamp"]}',
            f"> 来源: <{url}>",
            "> 标签: " + ", ".join(meta["tags"]), "",
        ]
        for i, p in enumerate(posts):
            lines.append(f"## {'楼主' if i == 0 else '回复 #' + str(i)} @{p['username']}")
            lines += ["", unescape(p["content"]), ""]
        (cat_dir / f"{tid}.md").write_text("\n".join(lines), encoding="utf-8")

    def rebuild_cat_index(cat_name: str, cat_slug: str, rows: list[tuple]) -> None:
        cat_dir = data_dir / _sanitize(cat_name)
        cat_dir.mkdir(parents=True, exist_ok=True)
        lines = ["---", f'title: "{cat_name}"', f'url: "{base}/category/{cat_slug}"',
                 f"topic_count: {len(rows)}", "---", "", "# " + cat_name, "",
                 f"> 来源: <{base}/category/{cat_slug}>", f"> 话题数: {len(rows)}", "",
                 "## 话题列表", ""]
        for tid, title, author in rows:
            lines.append(f"- [{title}]({tid}.md) — @{author}")
        (cat_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")

    def index_rows(cat_dir: Path, current: list[dict]) -> list[tuple]:
        rows = []
        for t in current:
            title, author = t["title"], t.get("username", "")
            fpath = cat_dir / f"{t['tid']}.md"
            if fpath.exists():
                for line in fpath.read_text(encoding="utf-8").split("\n"):
                    if line.startswith('title: "'):
                        title = line.split('"')[1]
                    elif line.startswith('author: "'):
                        author = line.split('"')[1]
                        break
            rows.append((t["tid"], title, author))
        rows.sort(key=lambda x: x[0], reverse=True)
        return rows

    existing = existing_tids()
    cats = categories()
    total_new, by_cid = 0, {}
    for cat in cats:
        cat_dir = data_dir / _sanitize(cat["name"])
        cat_dir.mkdir(parents=True, exist_ok=True)
        current = category_topics(cat["slug"])
        new_topics = [t for t in current if t["tid"] not in existing]
        print(f"\n[{cat['name']}] total {len(current)}, new {len(new_topics)}", flush=True)
        for i, topic in enumerate(new_topics):
            print(f"  [{i + 1}/{len(new_topics)}] {topic['tid']}: {topic['title'][:60]}...",
                  end="", flush=True)
            try:
                posts, meta = topic_posts(topic["tid"], topic["slug"])
                save_topic(topic["tid"], meta, posts, cat["name"], cat_dir)
                existing.add(topic["tid"])
                total_new += 1
                print(f" ok ({len(posts)} posts)")
            except Exception as exc:  # noqa: BLE001
                print(f" fail {str(exc)[:50]}")
            _delay(min_delay, max_delay)
        by_cid[cat["cid"]] = index_rows(cat_dir, current)
        rebuild_cat_index(cat["name"], cat["slug"], by_cid[cat["cid"]])

    total = sum(len(v) for v in by_cid.values())
    _rebuild_forum_index(save_dir, base, cats, by_cid, total)
    return {"new": total_new, "total": total}


def _rebuild_forum_index(save_dir: Path, base: str, cats: list[dict],
                         by_cid: dict, total: int) -> None:
    lines = ["---", 'title: "本地存档"', f'url: "{base}"',
             f"total_topics: {total}", "---", "", "# 本地存档", "",
             f"> 来源: <{base}>",
             f'> 最后更新: {time.strftime("%Y-%m-%d %H:%M:%S")}',
             f"> 总话题数: {total}", "", "## 目录", ""]
    for cat in cats:
        d = _sanitize(cat["name"])
        lines.append(f"- [{cat['name']}](data/{d}/index.md) — "
                     f"{len(by_cid.get(cat['cid'], []))} 个话题")
    lines += ["", "---", ""]
    for cat in cats:
        d = _sanitize(cat["name"])
        lines += [f"## [{cat['name']}](data/{d}/index.md)", ""]
        for tid, title, author in by_cid.get(cat["cid"], []):
            lines.append(f"- [{title}](data/{d}/{tid}.md) — @{author}")
        lines.append("")
    (save_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# Adapter: article-portal — generic article list site
# (discover IDs from index page, fetch each; Playwright + 429 cooldown)
# --------------------------------------------------------------------------
def _portal_parse(html: str, url: str, title_strip: str | None) -> tuple[str, str | None, int]:
    tm = re.search(r"<title>([^<]+)</title>", html)
    title = tm.group(1).strip() if tm else ""
    if title_strip:
        title = re.sub(title_strip, "", title).strip()

    bm = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL)
    body = bm.group(1) if bm else ""
    body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.DOTALL)
    body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.DOTALL)
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = re.sub(r"<p[^>]*>", "\n\n", body)
    body = re.sub(r"<[^>]+>", "", body)
    for e, c in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                 ("&gt;", ">"), ("&quot;", '"')]:
        body = body.replace(e, c)
    body = "\n".join(l.strip() for l in body.split("\n") if l.strip())
    wc = len(body)

    # Only reject actual error/placeholder pages: exact short titles, or a
    # placeholder "Article <id>" title, or an empty/too-short body.
    bad_titles = {"提示信息", "404", "页面不存在", "错误"}
    if title.strip() in bad_titles or title.strip().startswith("Article "):
        return title, None, wc
    if wc <= 300 or not title:
        return title, None, wc

    md_text = (f"---\ntitle: {title}\nurl: \"{url}\"\nword_count: {wc}\n"
               f"estimated_tokens: {wc // 2}\n---\n\n# {title}\n\n"
               f"> Source: <{url}>\n\n\n{body}\n")
    return title, md_text, wc


def _run_article_portal(cfg: dict[str, Any], proxy: str | None, min_delay: float,
                        max_delay: float) -> dict[str, Any]:
    base = cfg["url"].rstrip("/")
    save_dir = Path(cfg["save_dir"])
    data_dir = save_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    id_pattern = _opt(cfg, "article-portal", "id_pattern")
    url_template = _opt(cfg, "article-portal", "url_template")
    title_strip = _opt(cfg, "article-portal", "title_strip")
    cooldown = _opt(cfg, "article-portal", "cooldown", 600)

    try:
        from playwright.async_api import async_playwright  # noqa: WPS433
    except ImportError:
        raise RuntimeError(
            "article-portal adapter needs Playwright: pip install playwright && "
            "playwright install chromium")

    existing = {int(f.stem) for f in data_dir.glob("*.md") if f.stem.isdigit()}
    highest = max(existing) if existing else 0

    async def run() -> int:
        saved = 0
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy={"server": proxy} if proxy else None,
                args=["--no-sandbox", "--disable-setuid-sandbox"])
            ctx = await browser.new_context(
                user_agent=DEFAULT_UA, viewport={"width": 1280, "height": 800})
            page = await ctx.new_page()

            await page.goto(base + "/", timeout=30000, wait_until="networkidle")
            await asyncio.sleep(3)
            html = await page.content()
            all_ids = sorted({int(x) for x in re.findall(id_pattern, html)})
            new_ids = [x for x in all_ids if x > highest]
            print(f"index: {len(all_ids)} articles, new {len(new_ids)} "
                  f"{new_ids[:10]}", flush=True)

            for i, aid in enumerate(new_ids):
                url = url_template.format(base=base, id=aid)
                print(f"[{i + 1}/{len(new_ids)}] id={aid}: ", end="", flush=True)
                for attempt in range(4):
                    try:
                        resp = await page.goto(url, timeout=30000,
                                               wait_until="domcontentloaded")
                        if resp.status == 429:
                            wait = cooldown + attempt * 120
                            print(f"429 rate-limited, cooldown {wait}s...", flush=True)
                            await asyncio.sleep(wait)
                            continue
                        await asyncio.sleep(random.uniform(3, 6))
                        if resp.status != 200:
                            print(f"HTTP {resp.status}")
                            break
                        title, md_text, wc = _portal_parse(
                            await page.content(), url, title_strip)
                        if md_text:
                            (data_dir / f"{aid}.md").write_text(md_text, encoding="utf-8")
                            saved += 1
                            print(f"ok {title[:40]} ({wc} chars)")
                        else:
                            print(f"skip invalid (wc={wc})")
                        break
                    except Exception as exc:  # noqa: BLE001
                        if attempt == 3:
                            print(f"fail {str(exc)[:50]}")
                        else:
                            await asyncio.sleep(10)
                await asyncio.sleep(random.uniform(min_delay, max_delay))

            await browser.close()
        return saved

    saved = asyncio.run(run())
    now = {int(f.stem) for f in data_dir.glob("*.md") if f.stem.isdigit()}
    return {"new": saved, "total": len(now),
            "highest_id": max(now) if now else None}


# --------------------------------------------------------------------------
# Public entry points
# --------------------------------------------------------------------------
_ADAPTERS = {
    "nodebb": _run_nodebb,
    "article-portal": _run_article_portal,
}


def known_types() -> list[str]:
    """List the generic adapter types this module can drive."""
    return sorted(_ADAPTERS)


def update_site(key: str, cfg: dict[str, Any], *, proxy: str | None = None,
                min_delay: float | None = None, max_delay: float | None = None,
                verbose: bool = True) -> dict[str, Any]:
    """Run one site's incremental update. Returns a stats dict."""
    site_type = cfg.get("type", "")
    adapter = _ADAPTERS.get(site_type)
    if adapter is None:
        raise ValueError(f"unknown site type: {site_type!r} "
                         f"(known: {', '.join(known_types())})")
    if not cfg.get("save_dir"):
        raise ValueError(f"site {key!r} has no save_dir configured")
    if not cfg.get("url"):
        raise ValueError(f"site {key!r} has no url configured")

    Path(cfg["save_dir"]).mkdir(parents=True, exist_ok=True)
    lo = min_delay if min_delay is not None else _opt(cfg, site_type, "min_delay", 2.0)
    hi = max_delay if max_delay is not None else _opt(cfg, site_type, "max_delay", 6.0)

    if verbose:
        print(f"\n{'#' * 60}\n# {cfg.get('name', key)}  ({cfg['url']})\n"
              f"# save to: {cfg['save_dir']}\n{'#' * 60}", flush=True)
    return adapter(cfg, proxy, lo, hi)


def update_sites(keys: list[str] | None = None, *, config_path: str | None = None,
                 proxy: str | None = None, min_delay: float | None = None,
                 max_delay: float | None = None) -> dict[str, Any]:
    """Update one or more configured sites.

    Returns a dict keyed by site name with per-site stats (or an ``error``).
    """
    conf = load_sites_config(config_path)
    sites = conf.get("sites", {})
    eff_proxy = proxy if proxy is not None else conf.get("proxy")

    selected = keys or list(sites.keys())
    results: dict[str, Any] = {}
    for key in selected:
        if key not in sites:
            results[key] = {"error": f"unknown site {key!r}"}
            continue
        try:
            results[key] = update_site(key, sites[key], proxy=eff_proxy,
                                       min_delay=min_delay, max_delay=max_delay)
        except Exception as exc:  # noqa: BLE001
            results[key] = {"error": str(exc)}
    return results
