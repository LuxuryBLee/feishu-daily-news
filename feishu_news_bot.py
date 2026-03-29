"""
每日科技与科研前沿速递 - 飞书推送机器人
适用于 GitHub Actions 定时触发，完全免费、永久独立运行

数据源策略：
  - arXiv API（5天内）
  - Hacker News API（计算机与系统）
  - IEEE Spectrum / MIT Tech Review（AI与计算机补充）
  - Nature / Science / Phys.org RSS（自然科学板块）

策略：
  - 时间窗口：5天内
  - 每日去重：收集近5天数据后，使用当前日期作为随机种子进行采样，确保每天推送不同内容
  - 纯技术/理论过滤：过滤政治、人文、商业、娱乐等
"""

import os
import re
import time
import random
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import concurrent.futures
from openai import OpenAI

# ── 配置 ──────────────────────────────────────────────────────────────
WEBHOOK_URL = os.environ.get(
    "FEISHU_WEBHOOK",
    "https://open.feishu.cn/open-apis/bot/v2/hook/26d07ddf-5139-444e-9ede-0fcc734a904f"
)

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url="https://ai.qaq.al/v1",
    timeout=90.0
)

TIME_WINDOW_DAYS = 5

# ── 数据源配置 ─────────────────────────────────────────────────────────
ARXIV_CATEGORIES = {
    "🤖 AI与深度学习": ["cs.AI", "cs.LG", "cs.CV", "cs.CL", "cs.NE", "stat.ML"],
    "💻 计算机科学与系统": ["cs.DS", "cs.CR", "cs.PL", "cs.DC", "cs.AR", "cs.SE", "cs.IT"],
    "📐 数学与理论": ["math.NA", "math.OC", "math.ST", "math.CO", "math.PR", "math.NT", "math.AG", "math.AP", "cs.CC"],
}

EXTRA_RSS_SOURCES = {
    "🤖 AI与深度学习": [
        "https://spectrum.ieee.org/feeds/feed.rss",
        "https://www.technologyreview.com/feed/"
    ],
    "💻 计算机科学与系统": [
        "https://dl.acm.org/action/showFeed?ui-place=journal&type=etoc&feed=rss&jc=jacm"
    ],
    "🔬 自然科学": [
        "https://www.nature.com/nature.rss",
        "https://www.science.org/rss/news_current.xml",
        "https://phys.org/rss-feed/",
        "http://export.arxiv.org/rss/quant-ph"
    ]
}

CATEGORY_LIMITS = {
    "🤖 AI与深度学习":     {"min": 3, "max": 5},
    "💻 计算机科学与系统": {"min": 3, "max": 5},
    "📐 数学与理论":        {"min": 3, "max": 5},
    "🔬 自然科学":          {"min": 1, "max": 3},
}

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
    "论文", "算法", "模型", "神经网络", "定理", "证明", "优化",
    "复杂度", "架构", "基准", "训练", "推理", "收敛", "梯度",
    "量子", "密码", "图论", "数论", "概率", "统计",
]

def clean_html(text):
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

# ── 抓取函数 ───────────────────────────────────────────────────────────
def fetch_arxiv_api(categories):
    cat_query = " OR ".join(f"cat:{c}" for c in categories)
    url = (
        f"http://export.arxiv.org/api/query"
        f"?search_query={requests.utils.quote(cat_query)}"
        f"&sortBy=submittedDate&sortOrder=descending"
        f"&max_results=60"
    )
    items = []
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        cutoff = datetime.now(timezone.utc) - timedelta(days=TIME_WINDOW_DAYS)
        for entry in feed.entries:
            title = clean_html(entry.get('title', '')).replace('\n', ' ').strip()
            link = entry.get('link', '')
            summary = clean_html(entry.get('summary', ''))[:600]
            pub = entry.get('published', '')
            try:
                dt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
                if dt < cutoff: continue
            except: pass
            if not title or not is_technical_content(title, summary): continue
            items.append({"title": title, "link": link, "summary": summary, "score": tech_score(title, summary)})
    except Exception as e:
        print(f"  ⚠️ arXiv API 失败: {e}")
    return items

def fetch_rss(url):
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        cutoff = datetime.now(timezone.utc) - timedelta(days=TIME_WINDOW_DAYS)
        for entry in feed.entries[:20]:
            title = clean_html(entry.get('title', '')).strip()
            link = entry.get('link', '')
            summary = clean_html(entry.get('summary', entry.get('description', '')))[:600]
            
            # 时间过滤
            valid_time = False
            for field in ('published', 'updated'):
                raw = entry.get(field, '')
                if raw:
                    try:
                        dt = parsedate_to_datetime(raw)
                        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                        if dt >= cutoff: valid_time = True
                        break
                    except: continue
            if not valid_time: continue
            if not title or not is_technical_content(title, summary): continue
            items.append({"title": title, "link": link, "summary": summary, "score": tech_score(title, summary)})
    except Exception as e:
        print(f"  ⚠️ RSS 失败 [{url}]: {e}")
    return items

def fetch_hacker_news():
    items = []
    try:
        r = requests.get('https://hacker-news.firebaseio.com/v0/topstories.json', timeout=15)
        story_ids = r.json()[:30]
        cutoff = datetime.now(timezone.utc).timestamp() - TIME_WINDOW_DAYS * 86400
        for sid in story_ids:
            sr = requests.get(f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=10).json()
            if not sr or sr.get('type') != 'story' or sr.get('time', 0) < cutoff: continue
            title = sr.get('title', '')
            link = sr.get('url', f"https://news.ycombinator.com/item?id={sid}")
            if not is_technical_content(title): continue
            score = tech_score(title)
            if score > 0: # HN需要包含技术关键词才算
                items.append({"title": title, "link": link, "summary": "Hacker News Top Story", "score": score})
    except Exception as e:
        print(f"  ⚠️ HN 失败: {e}")
    return items

# ── 每日去重采样策略 ───────────────────────────────────────────────────
def sample_daily_news(items, limit):
    if not items: return []
    # 1. 按标题去重
    seen, unique = set(), []
    for it in items:
        k = it['title'][:50].lower()
        if k not in seen:
            seen.add(k)
            unique.append(it)
    
    # 2. 筛选出技术得分最高的 Top N (比如 20条) 作为候选池
    unique.sort(key=lambda x: x['score'], reverse=True)
    pool = unique[:20]
    
    # 3. 使用当前日期作为随机种子，从候选池中随机抽取 limit 条
    # 这样可以保证：
    # a) 每天抽到的都不完全一样
    # b) 抽到的都是近5天内高质量的技术内容
    today_str = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime('%Y%m%d')
    random.seed(today_str)
    
    sample_size = min(limit, len(pool))
    sampled = random.sample(pool, sample_size)
    
    # 恢复按得分排序
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

以下是{category}领域近{TIME_WINDOW_DAYS}天内的最新论文/技术资讯（均为纯技术/理论内容，已过滤政治、商业、人文内容）：

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
            model="gpt-5.4",
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
            max_tokens=2800,
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

    main_content = ""
    total_news = 0

    # 抓取各板块
    for category in CATEGORY_LIMITS.keys():
        limits = CATEGORY_LIMITS[category]
        print(f"\n📡 抓取 {category}（目标 {limits['min']}-{limits['max']} 条）...")
        
        all_items = []
        
        # arXiv
        if category in ARXIV_CATEGORIES:
            all_items.extend(fetch_arxiv_api(ARXIV_CATEGORIES[category]))
            
        # Hacker News (CS专用)
        if category == "💻 计算机科学与系统":
            all_items.extend(fetch_hacker_news())
            
        # RSS Sources
        rss_urls = EXTRA_RSS_SOURCES.get(category, [])
        if rss_urls:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(fetch_rss, url) for url in rss_urls]
                for future in concurrent.futures.as_completed(futures):
                    all_items.extend(future.result())
        
        # 每日随机采样去重
        news_list = sample_daily_news(all_items, limit=limits["max"])
        total_news += len(news_list)
        print(f"  ✅ 最终选中 {len(news_list)} 条用于推送")
        
        ai_content = generate_ai_analysis(news_list, category)
        main_content += f"## {category}\n\n{ai_content}\n\n---\n\n"

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
                        f"均来自 arXiv、Nature、Science、IEEE、Hacker News 等权威来源（近{TIME_WINDOW_DAYS}天内），"
                        f"配有深度解读与知识补充，已过滤政治/商业/人文内容。\n\n---"
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
