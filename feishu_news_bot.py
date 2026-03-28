"""
每日科技与科研前沿速递 - 飞书推送机器人
适用于 GitHub Actions 定时触发，完全免费、永久独立运行
"""

import os
import re
import requests
import feedparser
from datetime import datetime
import concurrent.futures
from openai import OpenAI

# 从环境变量读取配置
WEBHOOK_URL = os.environ.get(
    "FEISHU_WEBHOOK",
    "https://open.feishu.cn/open-apis/bot/v2/hook/26d07ddf-5139-444e-9ede-0fcc734a904f"
)

# 使用中转站 API，支持 gpt-5.4 等模型
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url="https://ai.qaq.al/v1",
    timeout=60.0
)

RSS_SOURCES = {
    "🤖 AI与计算机": [
        {"url": "http://export.arxiv.org/rss/cs.AI",  "name": "arXiv · AI"},
        {"url": "http://export.arxiv.org/rss/cs.LG",  "name": "arXiv · 机器学习"},
        {"url": "http://export.arxiv.org/rss/cs.CV",  "name": "arXiv · 计算机视觉"},
        {"url": "https://hnrss.org/frontpage",         "name": "Hacker News"},
    ],
    "📐 数学": [
        {"url": "http://export.arxiv.org/rss/math.NA", "name": "arXiv · 数值分析"},
        {"url": "http://export.arxiv.org/rss/math.OC", "name": "arXiv · 优化与控制"},
        {"url": "http://export.arxiv.org/rss/math.ST", "name": "arXiv · 统计理论"},
    ],
    "🔬 科研与科学": [
        {"url": "https://www.nature.com/nature.rss",                "name": "Nature"},
        {"url": "https://news.mit.edu/rss/research",                "name": "MIT News"},
        {"url": "https://www.sciencedaily.com/rss/top/science.xml", "name": "Science Daily"},
        {"url": "https://phys.org/rss-feed/",                       "name": "Phys.org"},
    ]
}

def clean_html(text):
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def fetch_rss_sync(url, limit=3):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Encoding": "gzip, deflate",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        items = []
        for entry in feed.entries[:limit]:
            title = clean_html(entry.get('title', '')).strip()
            link = entry.get('link', '')
            summary = clean_html(entry.get('summary', entry.get('description', '')))[:800]
            if title and len(title) > 5:
                items.append({"title": title, "link": link, "summary": summary})
        return items
    except Exception as e:
        print(f"⚠️ 抓取失败 [{url}]: {e}")
        return []

def fetch_category_news(category, sources):
    all_items = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_rss_sync, src["url"], 2): src for src in sources}
        for future in concurrent.futures.as_completed(futures):
            all_items.extend(future.result())
    seen, unique = set(), []
    for item in all_items:
        key = item["title"][:50]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:3]  # 每个板块取前3条最有价值的新闻

def generate_ai_analysis(news_list, category):
    if not news_list:
        return f"> 今日{category}暂无新消息，明天继续关注！"
    
    news_text = "".join(
        f"[{i+1}] 标题: {item['title']}\n摘要: {item['summary']}\n链接: {item['link']}\n\n"
        for i, item in enumerate(news_list)
    )
    
    prompt = f"""你是一位资深的{category}专家和科普作家，同时也是大学生的学习导师。

以下是今日{category}领域的最新新闻/论文：

{news_text}

请为一位**信息与计算科学专业的大学生**（对AI、深度学习、数学建模感兴趣，预计2027年毕业）撰写一份精彩的早报解读。

**格式要求（严格遵守）：**

请对提供的**每一条**新闻都进行详细解读（最多解读3条），每条按以下结构输出（不要省略任何一条的解读）：

📌 **[{'{新闻标题}'}]({'{链接}'})**

💡 **核心解读**
（2-3句话说明这篇新闻/论文的核心贡献、创新点和重要性，语言专业但易懂）

🧠 **基础知识补充**
（通俗解释其中的1-2个核心专业概念、算法或数学原理，用类比或例子帮助大学生理解，100-150字）

**注意：**
1. 必须使用中文回答。
2. 绝对不捏造事实，只基于提供的摘要进行合理解读。
3. 排版整洁，层级分明，利用 Markdown 加粗关键字。"""

    try:
        print(f"  正在调用 AI 解读 {category} 的 {len(news_list)} 条新闻...")
        response = client.chat.completions.create(
            model="gpt-5.4",
            messages=[
                {"role": "system", "content": "你是一个专业的科技前沿解读助手，擅长将复杂的学术论文和科技新闻转化为大学生易懂的知识。"},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI解析失败 ({category}): {e}")
        # 如果失败，返回带有错误提示的原始链接，而不是悄悄吞掉错误
        fallback = f"⚠️ AI 解读生成失败，以下是原始新闻链接：\n\n"
        fallback += "\n".join(f"📌 **[{item['title']}]({item['link']})**\n> {item['summary'][:100]}...\n" for item in news_list)
        return fallback

def build_and_send():
    today_str = datetime.now().strftime("%Y年%m月%d日")
    weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_map[datetime.now().weekday()]

    main_content = ""
    for category, sources in RSS_SOURCES.items():
        print(f"📡 抓取 {category}...")
        news_list = fetch_category_news(category, sources)
        print(f"  获取到 {len(news_list)} 条去重新闻")
        ai_content = generate_ai_analysis(news_list, category)
        main_content += f"## {category}\n\n{ai_content}\n\n---\n\n"

    card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"🌅 {today_str} {weekday} · 科技前沿早报"},
                "template": "indigo"
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": "**Timmy，早上好！** ☀️\n\n今日为你精选 **AI、计算机、数学、科研** 领域最新动态，配有深度解读与基础知识补充，助你跟上时代前沿！\n\n---"
                },
                {"tag": "markdown", "content": main_content},
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": "✨ 由 GitHub Actions + Manus AI 自动抓取并生成深度解读 | 每日 07:00 准时推送"}]
                }
            ]
        }
    }

    print("🚀 正在发送到飞书...")
    resp = requests.post(WEBHOOK_URL, json=card, timeout=15)
    resp.raise_for_status()
    result = resp.json()
    if result.get("StatusCode") == 0 or result.get("code") == 0:
        print("✅ 飞书消息发送成功！")
    else:
        print(f"⚠️ 飞书返回: {result}")

if __name__ == "__main__":
    build_and_send()
