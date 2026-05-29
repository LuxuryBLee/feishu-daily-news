"""
sources.py — 数据源抓取层

经过 2026-05 实测后的可靠策略：
  • arXiv「RSS 通道」(rss.arxiv.org) 是主力：最新鲜、不被限流。
    —— 旧的 export.arxiv.org/api 接口对云服务器 IP 会返回 “Rate exceeded”（且是 HTTP 200 带错误正文，
        极易被误判为“无数据”），故弃用，改走 RSS。
  • Semantic Scholar 作为补充：需 API Key（环境变量 S2_API_KEY），并遵守「全局 1 次/秒」限速。
    —— SS 对“最近几天”的论文有收录延迟，不适合当唯一来源，故只做补充与拓展。
  • Hacker News：计算机/系统社区热门。
  • Nature / phys.org 等 RSS：自然科学。
  • Papers With Code 已于 2025 年关停（实测 302），移除。

所有抓取函数都「只返回能拿到的，拿不到就返回空列表」，绝不抛异常拖垮主流程。
"""

import os
import re
import time
import html
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

import requests

# ── Semantic Scholar Key + 全局限速（1 次/秒，跨所有端点累计）──────────
SS_API_KEY = (os.environ.get("S2_API_KEY")
              or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
              or "").strip()
_ss_lock = threading.Lock()
_ss_last = [0.0]
SS_MIN_INTERVAL = 1.2  # 秒，留出安全余量


def _ss_throttle():
    with _ss_lock:
        wait = SS_MIN_INTERVAL - (time.time() - _ss_last[0])
        if wait > 0:
            time.sleep(wait)
        _ss_last[0] = time.time()


_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def http_get(url, headers=None, params=None, timeout=25, retries=3):
    """带重试的 GET。能识别 arXiv 的 “Rate exceeded” 软错误（HTTP 200 但正文是限流提示）。"""
    h = {"User-Agent": _DEFAULT_UA}
    if headers:
        h.update(headers)
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=h, params=params, timeout=timeout)
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"  ⏳ 429 限速，等待 {wait}s 重试…")
                time.sleep(wait)
                continue
            # arXiv 软限流：状态 200 但正文极短且含 “Rate exceeded”
            body_head = resp.text[:200] if resp.content else ""
            if "Rate exceeded" in body_head and len(resp.content) < 500:
                wait = 4 * (attempt + 1)
                print(f"  ⏳ arXiv 软限流，等待 {wait}s 重试…")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ⚠️ 请求失败 [{url[:60]}]: {e}")
                return None
            time.sleep(2 * (attempt + 1))
    return None


# ── 通用：解析 RSS/Atom（优先 feedparser，缺失时用 stdlib 兜底）────────
def parse_feed(content):
    """返回 list[{title, link, summary, published}]。

    GitHub Actions 上有 feedparser；本地/极端环境缺失时自动降级为 stdlib ElementTree，
    这本身也是一层稳定性保障。
    """
    # 优先 feedparser
    try:
        import feedparser
        feed = feedparser.parse(content)
        out = []
        for e in feed.entries:
            out.append({
                "title": (e.get("title") or "").strip(),
                "link": e.get("link") or "",
                "summary": (e.get("summary") or e.get("description") or ""),
                "published": e.get("published") or e.get("updated") or "",
            })
        if out:
            return out
    except Exception:
        pass
    # 兜底：stdlib 解析 RSS 2.0 / Atom
    try:
        if isinstance(content, str):
            content = content.encode("utf-8")
        root = ET.fromstring(content)
        out = []
        for item in root.findall(".//item"):  # RSS 2.0
            out.append({
                "title": _text(item, "title"),
                "link": _text(item, "link"),
                "summary": _text(item, "description"),
                "published": _text(item, "pubDate"),
            })
        if not out:
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in root.findall(".//a:entry", ns):  # Atom
                link_el = entry.find("a:link", ns)
                out.append({
                    "title": _text(entry, "a:title", ns),
                    "link": (link_el.get("href") if link_el is not None else ""),
                    "summary": _text(entry, "a:summary", ns),
                    "published": _text(entry, "a:published", ns) or _text(entry, "a:updated", ns),
                })
        return out
    except Exception as e:
        print(f"  ⚠️ feed 解析失败：{e}")
        return []


def _text(el, tag, ns=None):
    node = el.find(tag, ns) if ns else el.find(tag)
    return (node.text or "").strip() if node is not None and node.text else ""


def clean_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# ── 主力：arXiv RSS ────────────────────────────────────────────────────
def fetch_arxiv_rss(categories, limit=120):
    """从 rss.arxiv.org 拉取最新论文（合并多分类一次请求）。

    arXiv RSS 当天发布的条目本身就是最新公告，天然“新鲜”，无需严格日期过滤。
    """
    items = []
    cat_path = "+".join(categories)
    url = f"https://rss.arxiv.org/rss/{cat_path}"
    resp = http_get(url, timeout=30)
    if not resp:
        print(f"  ⚠️ arXiv RSS 无响应（{cat_path[:30]}…）")
        return items
    entries = parse_feed(resp.content)
    for e in entries[:limit]:
        title = clean_html(e["title"])
        link = e["link"]
        raw = e["summary"]
        # 描述形如：'arXiv:2605.xxxx Announce Type: new \nAbstract: <正文>'
        m = re.search(r"Abstract:\s*(.*)", raw, re.S)
        summary = clean_html(m.group(1) if m else raw)[:700]
        # 跳过纯 replace（旧论文更新版），保留 new / cross
        if "Announce Type: replace" in raw:
            continue
        if not title or not link:
            continue
        items.append({"title": title, "link": link, "summary": summary,
                      "source": "arXiv", "published": e.get("published", "")})
    print(f"  arXiv RSS ({cat_path[:24]}…): {len(items)} 条")
    return items


# ── 补充：Semantic Scholar（带 Key + 限速）──────────────────────────────
def fetch_semantic_scholar(query, limit=20, window_days=30):
    """用 API Key 搜索论文，按发表日降序。遵守全局 1 次/秒限速。"""
    items = []
    if not SS_API_KEY:
        # 没配 Key 时匿名池几乎必被 429，直接跳过，避免拖时间
        return items
    _ss_throttle()
    resp = http_get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        headers={"x-api-key": SS_API_KEY},
        params={
            "query": query,
            "fields": "title,abstract,url,publicationDate",
            "limit": limit,
            "sort": "publicationDate:desc",
        },
        timeout=30,
    )
    if not resp:
        return items
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        for p in resp.json().get("data", []):
            title = (p.get("title") or "").strip()
            url = p.get("url") or ""
            abstract = (p.get("abstract") or "")[:700]
            pub = p.get("publicationDate") or ""
            if not title or not url:
                continue
            if pub:
                try:
                    if datetime.fromisoformat(pub).replace(tzinfo=timezone.utc) < cutoff:
                        continue
                except Exception:
                    pass
            items.append({"title": title, "link": url, "summary": abstract,
                          "source": "Semantic Scholar", "published": pub})
    except Exception as e:
        print(f"  ⚠️ Semantic Scholar 解析失败：{e}")
    print(f"  Semantic Scholar [{query[:24]}…]: {len(items)} 条")
    return items


# ── Hacker News ────────────────────────────────────────────────────────
def fetch_hacker_news(window_days=7, scan=30):
    items = []
    r = http_get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=15)
    if not r:
        return items
    try:
        ids = r.json()[:scan]
        cutoff_ts = datetime.now(timezone.utc).timestamp() - window_days * 86400
        for sid in ids:
            sr = http_get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=10, retries=2)
            if not sr:
                continue
            d = sr.json()
            if not d or d.get("type") != "story" or d.get("time", 0) < cutoff_ts:
                continue
            items.append({
                "title": d.get("title", ""),
                "link": d.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                "summary": "Hacker News 社区热门",
                "source": "Hacker News",
                "hn_score": d.get("score", 0),
                "published": "",
            })
    except Exception as e:
        print(f"  ⚠️ HN 失败：{e}")
    print(f"  Hacker News: {len(items)} 条")
    return items


# ── 通用 RSS（自然科学）────────────────────────────────────────────────
def fetch_rss(url, window_days=10, limit=20):
    from email.utils import parsedate_to_datetime
    items = []
    resp = http_get(url, timeout=20)
    if not resp:
        return items
    entries = parse_feed(resp.content)
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    for e in entries[:limit]:
        title = clean_html(e["title"])
        link = e["link"]
        summary = clean_html(e["summary"])[:600]
        pub = e.get("published", "")
        if pub:
            try:
                dt = parsedate_to_datetime(pub)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except Exception:
                pass
        if not title or not link:
            continue
        items.append({"title": title, "link": link, "summary": summary,
                      "source": "RSS", "published": pub})
    print(f"  RSS [{url[:38]}…]: {len(items)} 条")
    return items
