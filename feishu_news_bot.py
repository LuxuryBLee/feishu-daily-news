"""
每日科技与科研前沿速递 - 飞书推送机器人
适用于 GitHub Actions 定时触发，完全免费、永久独立运行

数据源策略（全部对 GitHub Actions IP 友好）：
  - Semantic Scholar API（AI/CS/数学论文，无需注册，无IP限制）
  - Papers With Code（AI/ML最新论文）
  - arXiv HTTPS API（带重试和 User-Agent）
  - Hacker News API（计算机与系统）
  - Nature / Science / Phys.org RSS（自然科学板块）

策略：
  - 时间窗口：5天内
  - 每日去重：使用当前日期作为随机种子进行采样，确保每天推送不同内容
  - 纯技术/理论过滤：过滤政治、人文、商业、娱乐等
"""

import os
import re
import time
import random
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from openai import OpenAI

# ── 配置 ──────────────────────────────────────────────────────────────
WEBHOOK_URL = os.environ.get(
    "FEISHU_WEBHOOK",
    "https://open.feishu.cn/open-apis/bot/v2/hook/26d07ddf-5139-444e-9ede-0fcc734a904f"
)

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    timeout=120.0
)

TIME_WINDOW_DAYS = 5

# ── 内容过滤 ───────────────────────────────────────────────────────────
BLOCK_KEYWORDS = [
    "election", "president", "congress", "senate", "democrat", "republican",
    "trump", "biden", "ukraine", "russia", "china policy", "geopolit",
    "政治", "选举", "政府", "议会", "制裁", "外交", "战争", "军事",
    "stock", "ipo", "funding", "valuation", "revenue", "profit", "acquisition",
    "融资", "上市", "股价", "市值", "收购", "营收",
    "celebrity", "movie", "music", "entertainment", "sports", "fashion",
    "娱乐", "明星", "电影", "音乐", "体育",
    "lawsuit", "court", "crime", "arrest", "scandal",
    "诉讼", "犯罪", "丑闻",
]

TECH_KEYWORDS = [
    "algorithm", "model", "neural", "learning", "theorem", "proof",
    "optimization", "complexity", "architecture", "framework", "benchmark",
    "dataset", "training", "inference", "convergence", "gradient",
    "transformer", "diffusion", "quantum", "cryptography", "graph",
    "matrix", "tensor", "probability", "statistics", "topology",
    "network", "computation", "logic", "formal", "verification",
    "论文", "算法", "模型", "神经网络", "定理", "证明", "优化",
    "复杂度", "架构", "基准", "训练", "推理", "收敛", "梯度",
    "量子", "密码", "图论", "数论", "概率", "统计",
]

def clean_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def is_technical_content(title, summary=""):
    text = (title + " " + summary).lower()
    for kw in BLOCK_KEYWORDS:
        if kw.lower() in text:
            return False
    return True

def tech_score(title, summary=""):
    text = (title + " " + summary).lower()
    return sum(1 for kw in TECH_KEYWORDS if kw.lower() in text)

def safe_get(url, headers=None, params=None, timeout=25, retries=3):
    """带重试的 HTTP GET"""
    default_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DailyNewsBot/1.0; +https://github.com/LuxuryBLee/feishu-daily-news)"
    }
    if headers:
        default_headers.update(headers)
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=default_headers, params=params, timeout=timeout)
            if resp.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"  ⏳ 限速，等待 {wait}s 后重试...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ⚠️ 请求失败 [{url[:60]}]: {e}")
                return None
            time.sleep(3)
    return None

# ── 数据源：Semantic Scholar（最稳定，无IP限制）──────────────────────
def fetch_semantic_scholar(query, fields="title,abstract,url,year,publicationDate", limit=20):
    """使用 Semantic Scholar API 搜索论文"""
    items = []
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=TIME_WINDOW_DAYS)
        resp = safe_get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": query,
                "fields": fields,
                "limit": limit,
                "sort": "publicationDate:desc"
            },
            timeout=30
        )
        if not resp:
            return items
        data = resp.json()
        for paper in data.get("data", []):
            title = paper.get("title", "").strip()
            abstract = (paper.get("abstract") or "")[:600]
            url = paper.get("url", "")
            pub_date = paper.get("publicationDate", "")
            
            if not title or not url:
                continue
            
            # 时间过滤
            if pub_date:
                try:
                    dt = datetime.fromisoformat(pub_date).replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except:
                    pass
            
            if not is_technical_content(title, abstract):
                continue
            
            items.append({
                "title": title,
                "link": url,
                "summary": abstract,
                "score": tech_score(title, abstract)
            })
    except Exception as e:
        print(f"  ⚠️ Semantic Scholar 失败: {e}")
    return items

# ── 数据源：Papers With Code（AI/ML专用）────────────────────────────
def fetch_papers_with_code(limit=20):
    """从 Papers With Code 获取最新 AI/ML 论文"""
    items = []
    try:
        resp = safe_get(
            "https://paperswithcode.com/api/v1/papers/",
            params={"ordering": "-published", "items_per_page": limit},
            timeout=25
        )
        if not resp:
            return items
        data = resp.json()
        cutoff = datetime.now(timezone.utc) - timedelta(days=TIME_WINDOW_DAYS)
        for paper in data.get("results", []):
            title = paper.get("title", "").strip()
            abstract = (paper.get("abstract") or "")[:600]
            url = paper.get("url_pdf") or paper.get("url_abs") or ""
            pub_date = paper.get("published", "")
            
            if not title:
                continue
            if pub_date:
                try:
                    dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except:
                    pass
            if not is_technical_content(title, abstract):
                continue
            
            items.append({
                "title": title,
                "link": f"https://paperswithcode.com/paper/{paper.get('id', '')}" if paper.get("id") else url,
                "summary": abstract,
                "score": tech_score(title, abstract)
            })
    except Exception as e:
        print(f"  ⚠️ Papers With Code 失败: {e}")
    return items

# ── 数据源：arXiv API（带重试）──────────────────────────────────────
def fetch_arxiv_api(categories, max_results=50):
    """使用 arXiv API 获取论文，带重试机制"""
    items = []
    cat_query = " OR ".join(f"cat:{c}" for c in categories)
    url = "https://export.arxiv.org/api/query"
    params = {
        "search_query": cat_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results
    }
    try:
        resp = safe_get(url, params=params, timeout=30)
        if not resp:
            return items
        feed = feedparser.parse(resp.text)
        cutoff = datetime.now(timezone.utc) - timedelta(days=TIME_WINDOW_DAYS)
        for entry in feed.entries:
            title = clean_html(entry.get('title', '')).replace('\n', ' ').strip()
            link = entry.get('link', '')
            summary = clean_html(entry.get('summary', ''))[:600]
            pub = entry.get('published', '')
            try:
                dt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
                if dt < cutoff:
                    continue
            except:
                pass
            if not title or not is_technical_content(title, summary):
                continue
            items.append({
                "title": title,
                "link": link,
                "summary": summary,
                "score": tech_score(title, summary)
            })
    except Exception as e:
        print(f"  ⚠️ arXiv API 失败: {e}")
    return items

# ── 数据源：Hacker News（CS/系统）───────────────────────────────────
def fetch_hacker_news():
    items = []
    try:
        r = safe_get('https://hacker-news.firebaseio.com/v0/topstories.json', timeout=15)
        if not r:
            return items
        story_ids = r.json()[:40]
        cutoff_ts = datetime.now(timezone.utc).timestamp() - TIME_WINDOW_DAYS * 86400
        for sid in story_ids[:25]:
            sr = safe_get(f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=10)
            if not sr:
                continue
            data = sr.json()
            if not data or data.get('type') != 'story' or data.get('time', 0) < cutoff_ts:
                continue
            title = data.get('title', '')
            link = data.get('url', f"https://news.ycombinator.com/item?id={sid}")
            if not is_technical_content(title):
                continue
            score = tech_score(title)
            if score > 0:
                items.append({
                    "title": title,
                    "link": link,
                    "summary": "Hacker News Top Story",
                    "score": score + data.get('score', 0) // 100
                })
    except Exception as e:
        print(f"  ⚠️ HN 失败: {e}")
    return items

# ── 数据源：RSS（自然科学板块）──────────────────────────────────────
def fetch_rss(url):
    items = []
    try:
        resp = safe_get(url, timeout=20)
        if not resp:
            return items
        feed = feedparser.parse(resp.text)
        cutoff = datetime.now(timezone.utc) - timedelta(days=TIME_WINDOW_DAYS)
        for entry in feed.entries[:20]:
            title = clean_html(entry.get('title', '')).strip()
            link = entry.get('link', '')
            summary = clean_html(entry.get('summary', entry.get('description', '')))[:600]
            valid_time = False
            for field in ('published', 'updated'):
                raw = entry.get(field, '')
                if raw:
                    try:
                        dt = parsedate_to_datetime(raw)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt >= cutoff:
                            valid_time = True
                        break
                    except:
                        continue
            if not valid_time:
                continue
            if not title or not is_technical_content(title, summary):
                continue
            items.append({
                "title": title,
                "link": link,
                "summary": summary,
                "score": tech_score(title, summary)
            })
    except Exception as e:
        print(f"  ⚠️ RSS 失败 [{url[:50]}]: {e}")
    return items

# ── 每日去重采样策略 ───────────────────────────────────────────────────
def sample_daily_news(items, limit):
    if not items:
        return []
    seen, unique = set(), []
    for it in items:
        k = it['title'][:50].lower()
        if k not in seen:
            seen.add(k)
            unique.append(it)
    unique.sort(key=lambda x: x['score'], reverse=True)
    pool = unique[:30]
    today_str = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y%m%d')
    random.seed(today_str)
    sample_size = min(limit, len(pool))
    sampled = random.sample(pool, sample_size)
    sampled.sort(key=lambda x: x['score'], reverse=True)
    return sampled

# ── AI 解读 ────────────────────────────────────────────────────────────
def generate_ai_analysis(news_list, category):
    if not news_list:
        return (
            f"> ⚠️ 今日{category}暂无符合条件的技术资讯\n"
            f"> （时间窗口：近{TIME_WINDOW_DAYS}天，已过滤非技术内容）\n"
            f"> 明日继续关注！"
        )

    news_text = "".join(
        f"[{i+1}] 标题: {item['title']}\n"
        f"摘要: {item['summary']}\n"
        f"链接: {item['link']}\n\n"
        for i, item in enumerate(news_list)
    )

    prompt = f"""你是一位资深的{category}专家和科普导师，读者是**信息与计算科学专业大学生**（对AI、深度学习、数学建模感兴趣，预计2027年毕业）。

以下是{category}领域近{TIME_WINDOW_DAYS}天内的最新论文/技术资讯（均为纯技术/理论内容）：

{news_text}

请对**每一条**内容进行详细解读，严格按以下格式输出，不得省略任何一条：

---

📌 **[完整标题](链接)**

💡 **核心贡献**
（2-3句话：该论文/技术的核心创新点、解决了什么问题、有何突破性意义）

🧠 **知识补充**
（通俗解释其中1-2个核心专业概念或数学原理，用类比或具体例子帮助大学生理解，100-150字）

📊 **与你的关联**
（一句话：与信息与计算科学/AI/数学建模的关联，或对未来学习/研究的启发）

---

**严格要求：**
1. 全程使用中文，英文术语保留原文并加粗。
2. 只基于提供的摘要进行合理推断，不捏造数据或结论。
3. 重点突出**技术细节**和**数学原理**，不涉及任何政治、商业评论。
4. 排版整洁，Markdown 加粗关键术语。"""

    try:
        print(f"  🤖 AI 解读 {category}（{len(news_list)} 条）...")
        response = client.chat.completions.create(
            model="qwen3-max",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是专业的技术前沿解读助手，专注于AI、计算机科学、数学领域的学术论文和技术突破解读，"
                        "只讨论纯技术和理论内容，不涉及政治、商业、人文话题。"
                    )
                },
                {"role": "user", "content": prompt}
            ],
            max_tokens=3000,
            temperature=0.6
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"  ❌ AI解析失败 ({category}): {e}")
        fallback = f"⚠️ AI 解读生成失败（{e}），原始资讯如下：\n\n"
        fallback += "\n\n".join(
            f"📌 **[{item['title']}]({item['link']})**\n> {item['summary'][:200]}..."
            for item in news_list
        )
        return fallback

# ── 构建并发送飞书消息 ─────────────────────────────────────────────────
def build_and_send():
    now_utc8 = datetime.now(timezone.utc) + timedelta(hours=8)
    today_str = now_utc8.strftime("%Y年%m月%d日")
    weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_map[now_utc8.weekday()]

    # ── 各板块数据抓取策略 ────────────────────────────────────────────
    print("\n📡 开始抓取各板块数据...\n")

    # 板块1：AI与深度学习
    print("🤖 [AI与深度学习] 抓取中...")
    ai_items = []
    # Semantic Scholar（最稳定）
    ai_items.extend(fetch_semantic_scholar(
        "deep learning neural network transformer reinforcement learning large language model",
        limit=25
    ))
    print(f"  Semantic Scholar: {len(ai_items)} 条")
    # Papers With Code
    pwc = fetch_papers_with_code(limit=20)
    ai_items.extend(pwc)
    print(f"  Papers With Code: {len(pwc)} 条")
    # arXiv 备用
    arxiv_ai = fetch_arxiv_api(["cs.AI", "cs.LG", "cs.CV", "cs.CL", "cs.NE", "stat.ML"], max_results=40)
    ai_items.extend(arxiv_ai)
    print(f"  arXiv: {len(arxiv_ai)} 条")
    ai_news = sample_daily_news(ai_items, limit=5)
    print(f"  ✅ 最终选中 {len(ai_news)} 条\n")

    # 板块2：计算机科学与系统
    print("💻 [计算机科学与系统] 抓取中...")
    cs_items = []
    cs_items.extend(fetch_semantic_scholar(
        "computer systems distributed computing security cryptography programming language compiler",
        limit=20
    ))
    print(f"  Semantic Scholar: {len(cs_items)} 条")
    hn = fetch_hacker_news()
    cs_items.extend(hn)
    print(f"  Hacker News: {len(hn)} 条")
    arxiv_cs = fetch_arxiv_api(["cs.DS", "cs.CR", "cs.PL", "cs.DC", "cs.AR", "cs.SE", "cs.IT"], max_results=40)
    cs_items.extend(arxiv_cs)
    print(f"  arXiv: {len(arxiv_cs)} 条")
    cs_news = sample_daily_news(cs_items, limit=5)
    print(f"  ✅ 最终选中 {len(cs_news)} 条\n")

    # 板块3：数学与理论
    print("📐 [数学与理论] 抓取中...")
    math_items = []
    math_items.extend(fetch_semantic_scholar(
        "mathematical theorem proof optimization combinatorics number theory topology algebra analysis",
        limit=20
    ))
    print(f"  Semantic Scholar: {len(math_items)} 条")
    math_items.extend(fetch_semantic_scholar(
        "computational complexity algorithm graph theory probability statistics",
        limit=15
    ))
    arxiv_math = fetch_arxiv_api(
        ["math.NA", "math.OC", "math.ST", "math.CO", "math.PR", "math.NT", "math.AG", "math.AP", "cs.CC"],
        max_results=40
    )
    math_items.extend(arxiv_math)
    print(f"  arXiv: {len(arxiv_math)} 条")
    math_news = sample_daily_news(math_items, limit=5)
    print(f"  ✅ 最终选中 {len(math_news)} 条\n")

    # 板块4：自然科学
    print("🔬 [自然科学] 抓取中...")
    sci_items = []
    sci_rss = [
        "https://www.nature.com/nature.rss",
        "https://phys.org/rss-feed/",
        "https://www.science.org/rss/news_current.xml",
    ]
    for rss_url in sci_rss:
        fetched = fetch_rss(rss_url)
        sci_items.extend(fetched)
        print(f"  RSS [{rss_url[:40]}]: {len(fetched)} 条")
    sci_items.extend(fetch_semantic_scholar(
        "quantum physics chemistry biology breakthrough discovery",
        limit=15
    ))
    sci_news = sample_daily_news(sci_items, limit=3)
    print(f"  ✅ 最终选中 {len(sci_news)} 条\n")

    # ── AI 解读 ───────────────────────────────────────────────────────
    print("🤖 开始 AI 解读...\n")
    categories_data = [
        ("🤖 AI与深度学习", ai_news),
        ("💻 计算机科学与系统", cs_news),
        ("📐 数学与理论", math_news),
        ("🔬 自然科学", sci_news),
    ]

    main_content = ""
    total_news = sum(len(d[1]) for d in categories_data)

    for category, news_list in categories_data:
        ai_content = generate_ai_analysis(news_list, category)
        main_content += f"## {category}\n\n{ai_content}\n\n---\n\n"

    # ── 构建飞书卡片 ──────────────────────────────────────────────────
    card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"🌅 {today_str} {weekday} · 科技前沿早报"
                },
                "template": "indigo"
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"**Timmy，早上好！** ☀️\n\n"
                        f"今日为你精选 **{total_news} 条**纯技术/理论前沿资讯，"
                        f"涵盖 **AI与深度学习、计算机科学、数学与理论、自然科学** 四大板块，"
                        f"来自 Semantic Scholar、Papers With Code、arXiv、Nature、Hacker News 等权威来源"
                        f"（近{TIME_WINDOW_DAYS}天内），配有深度解读与知识补充。\n\n---"
                    )
                },
                {"tag": "markdown", "content": main_content},
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [{
                        "tag": "plain_text",
                        "content": (
                            f"✨ 由 GitHub Actions + GPT-5.4 自动生成 | "
                            f"数据池：近{TIME_WINDOW_DAYS}天 | 每日随机采样防重复 | "
                            f"每日 07:00 准时推送"
                        )
                    }]
                }
            ]
        }
    }

    print("\n🚀 正在发送到飞书...")
    resp = requests.post(WEBHOOK_URL, json=card, timeout=15)
    resp.raise_for_status()
    result = resp.json()
    if result.get("StatusCode") == 0 or result.get("code") == 0:
        print("✅ 飞书消息发送成功！")
    else:
        print(f"⚠️ 飞书返回: {result}")

if __name__ == "__main__":
    build_and_send()
