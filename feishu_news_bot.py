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

# 从环境变量读取配置（在 GitHub Actions 中通过 Secrets 注入）
WEBHOOK_URL = os.environ.get(
    "FEISHU_WEBHOOK",
    "https://open.feishu.cn/open-apis/bot/v2/hook/26d07ddf-5139-444e-9ede-0fcc734a904f"
)
client = OpenAI()  # 自动读取 OPENAI_API_KEY 环境变量

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
            "User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)",
            "Accept-Encoding": "gzip, deflate",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        items = []
        for entry in feed.entries[:limit]:
            title = clean_html(entry.get('title', '')).strip()
            link = entry.get('link', '')
            summary = clean_html(entry.get('summary', entry.get('description', '')))[:600]
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
    return unique[:4]

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

从上述新闻中挑选 **1-2条最有价值的** 进行详细解读，每条按以下结构输出：

📌 **[新闻标题](链接)**

💡 **核心解读**
（2-3句话说明核心内容和重要性，语言简洁有力）

🧠 **知识补充**
（通俗解释其中的专业概念，用类比或例子帮助理解，100字以内）

如有其他新闻，最后用"**其他动态：**"一行带过（一句话一条）。

**注意：语言活泼，排版整洁，绝对不捏造事实，只基于提供的摘要进行合理解读。**"""
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "你是一个专业的科技前沿解读助手。"},
                {"role": "user", "content": prompt}
            ],
            max_tokens=900
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI解析失败 ({category}): {e}")
        return "\n".join(f"📌 **[{item['title']}]({item['link']})**\n" for item in news_list[:2])

def build_and_send():
    today_str = datetime.now().strftime("%Y年%m月%d日")
    weekday_map = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_map[datetime.now().weekday()]

    main_content = ""
    for category, sources in RSS_SOURCES.items():
        print(f"📡 抓取 {category}...")
        news_list = fetch_category_news(category, sources)
        print(f"  获取到 {len(news_list)} 条，正在AI解读...")
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
                    "content": "**Timmy，早上好！** ☀️\n\n今日为你精选 **AI、计算机、数学、科研** 领域最新动态，配有深度解读与知识补充，助你跟上时代前沿！\n\n---"
                },
                {"tag": "markdown", "content": main_content},
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": "✨ 由 GitHub Actions + Manus AI 自动抓取 arXiv · Nature · MIT News · Hacker News | 每日 07:00 准时推送"}]
                }
            ]
        }
    }

    resp = requests.post(WEBHOOK_URL, json=card, timeout=15)
    resp.raise_for_status()
    result = resp.json()
    if result.get("StatusCode") == 0 or result.get("code") == 0:
        print("✅ 飞书消息发送成功！")
    else:
        print(f"⚠️ 飞书返回: {result}")

if __name__ == "__main__":
    build_and_send()
