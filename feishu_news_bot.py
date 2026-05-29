"""
每日科技与科研前沿速递 - 飞书推送机器人（升级版）
适用于 GitHub Actions 定时触发，免费、独立运行。

本次升级要点：
  1. 数据源修复（实测 2026-05）：arXiv 改走未被限流的 RSS 通道当主力；Semantic Scholar 用 API Key
     并全局限速 1 次/秒；移除已关停的 Papers With Code。彻底解决“板块空白”问题。
  2. 知识库（第二大脑地基）：语义去重 + 历史档案(Markdown) + RAG 历史衔接（见 knowledge_base.py）。
  3. 排版升级：飞书卡片 2.0，AI 解读折叠收纳（见 feishu_card.py）。
  4. 更稳定：单源失败不影响整体；板块兜底防空白；异常/失败发告警卡片。
  5. 解读更生动：重写提示词（继续使用 DeepSeek-V4-Pro）。

环境变量：
  FEISHU_WEBHOOK   飞书自定义机器人 Webhook（必填）
  OPENAI_API_KEY   DeepSeek API Key（用于解读）
  S2_API_KEY       Semantic Scholar API Key（强烈建议配置，否则该源会被限流跳过）
  DRY_RUN=1        只生成不发送（本地调试用）
"""

import os
import sys
import json
import traceback
from datetime import datetime, timezone, timedelta

import requests
from openai import OpenAI

import sources
import feishu_card
from knowledge_base import KnowledgeBase

try:
    import feishu_sync  # 第二阶段：写入飞书多维表格（无密钥则自动跳过）
except Exception:
    feishu_sync = None

# ── 配置 ──────────────────────────────────────────────────────────────
WEBHOOK_URL = os.environ.get(
    "FEISHU_WEBHOOK",
    "https://open.feishu.cn/open-apis/bot/v2/hook/26d07ddf-5139-444e-9ede-0fcc734a904f",
)
DRY_RUN = os.environ.get("DRY_RUN") == "1" or "--dry-run" in sys.argv
TIME_WINDOW_DAYS = 7
MODEL = "deepseek-v4-pro"

# 缺 OPENAI_API_KEY 时用占位符，避免构造即崩溃；真正调用失败会自动降级为原始要点。
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY") or "sk-missing",
    base_url="https://api.deepseek.com",
    timeout=120.0,
)

# ── 内容过滤与打分 ─────────────────────────────────────────────────────
BLOCK_KEYWORDS = [
    "election", "president", "congress", "senate", "democrat", "republican",
    "trump", "biden", "ukraine", "russia", "geopolit",
    "政治", "选举", "政府", "议会", "制裁", "外交", "战争", "军事",
    "stock", "ipo", "funding round", "valuation", "acquisition",
    "融资", "上市", "股价", "市值", "收购",
    "celebrity", "movie", "music album", "entertainment", "sports", "fashion",
    "娱乐", "明星", "电影", "体育",
    "lawsuit", "court ruling", "crime", "arrest", "scandal",
    "诉讼", "犯罪", "丑闻",
    # 软性/生活/社会话题（自然科学板块易混入的泛科普）
    "relationship", "dating", "marriage", "single beats", "self-help",
    "lifestyle", "farm-business", "agri-start", "startup idea", "diet tips",
    "恋爱", "婚姻", "单身", "创业点子",
]

# 自然科学板块的“正向相关性”关键词：命中才算合格，过滤掉社会/生活类软文
SCIENCE_KEYWORDS = [
    "quantum", "physics", "chemistry", "chemical", "biology", "biological",
    "molecul", "gene", "genome", "protein", "cell", "neuron", "brain",
    "material", "nano", "astro", "cosmo", "galaxy", "planet", "climate",
    "particle", "atom", "photon", "electron", "catalyst", "enzyme", "dna",
    "superconduct", "crystal", "fusion", "spectro", "evolution", "ecosystem",
    "量子", "物理", "化学", "生物", "分子", "基因", "蛋白", "细胞", "材料",
    "天文", "气候", "粒子", "催化",
]

TECH_KEYWORDS = [
    "algorithm", "model", "neural", "learning", "theorem", "proof", "transformer",
    "optimization", "complexity", "architecture", "benchmark", "dataset",
    "training", "inference", "convergence", "gradient", "diffusion", "quantum",
    "cryptography", "graph", "matrix", "tensor", "probability", "statistics",
    "topology", "computation", "logic", "verification", "reinforcement",
    "embedding", "attention", "generative", "llm", "language model",
    "论文", "算法", "模型", "神经网络", "定理", "证明", "优化", "复杂度",
    "架构", "基准", "训练", "推理", "收敛", "量子", "密码", "图论", "概率",
]


def is_technical(title, summary=""):
    text = (title + " " + summary).lower()
    return not any(kw.lower() in text for kw in BLOCK_KEYWORDS)


def is_science_relevant(item):
    """自然科学板块专用：必须命中科学关键词，过滤社会/生活类软文。"""
    text = (item.get("title", "") + " " + item.get("summary", "")).lower()
    return any(kw.lower() in text for kw in SCIENCE_KEYWORDS)


def tech_score(item):
    text = (item.get("title", "") + " " + item.get("summary", "")).lower()
    score = sum(1 for kw in TECH_KEYWORDS if kw.lower() in text)
    # arXiv 一手论文优先；HN 高热度加成
    if item.get("source") == "arXiv":
        score += 2
    if item.get("hn_score"):
        score += min(item["hn_score"] // 100, 3)
    return score


def prepare(items):
    """过滤非技术内容并打分。"""
    out = []
    for it in items:
        if not it.get("title") or not it.get("link"):
            continue
        if not is_technical(it.get("title", ""), it.get("summary", "")):
            continue
        it["score"] = tech_score(it)
        out.append(it)
    return out


def select(items, limit, kb, category):
    """去重 + 选优 + 兜底（绝不返回空，除非真的一条都没抓到）。"""
    if not items:
        return []
    items = prepare(items)
    if not items:
        return []
    # 语义去重（对比历史与彼此）
    deduped = kb.filter_new(items, category)
    pool = deduped if deduped else items  # 兜底：若全被判重，宁可少量重复也不空版
    pool.sort(key=lambda x: x.get("score", 0), reverse=True)
    return pool[:limit]


# ── AI 解读 ────────────────────────────────────────────────────────────
def generate_ai_analysis(news_list, category, related=None):
    if not news_list:
        return None

    news_text = "".join(
        f"[{i+1}] 标题：{it['title']}\n摘要：{it.get('summary','(无摘要)')}\n链接：{it['link']}\n\n"
        for i, it in enumerate(news_list)
    )

    related_block = ""
    if related:
        rel = "\n".join(f"- {r['title']}（{r['date']}）" for r in related)
        related_block = (
            f"\n【读者近期看过的相关内容】（可在解读中自然衔接，如“这延续了你之前关注的…”）：\n{rel}\n"
        )

    prompt = f"""你是一位风趣又严谨的{category}领域科普导师，读者是一名**信息与计算科学专业的大学生**（热爱 AI、深度学习、数学建模，2027 年毕业）。
{related_block}
以下是{category}近期的最新论文/技术资讯：

{news_text}

请对**每一条**进行解读，严格按以下格式，不得省略任何一条：

---

📌 **[完整标题](链接)**

💡 **一句话看懂**
（用一个生动的比喻或贴近生活的例子，让外行也能秒懂这项工作在做什么）

🔬 **核心贡献**
（2-3 句：创新点是什么、解决了什么真实痛点、为什么算突破）

🧠 **知识补充**
（挑 1-2 个核心专业概念/数学原理，用类比讲透，100-150 字，让大学生“学到东西”）

🎯 **与你的关联**
（一句话：与信息与计算科学/AI/数学建模学习或未来研究的关联与启发）

---

**要求：**
1. 中文为主，英文术语保留原文并**加粗**。
2. 只基于摘要合理推断，不编造数据或结论。
3. 生动、有画面感、有“原来如此”的感觉，但不失专业与准确。
4. 排版整洁，关键术语用 Markdown 加粗。"""

    try:
        print(f"  🤖 AI 解读 {category}（{len(news_list)} 条）…")
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": (
                    "你是专业又生动的技术前沿解读助手，专注 AI、计算机科学、数学领域的论文与技术突破，"
                    "善用类比把复杂概念讲得通俗易懂，只讨论纯技术与理论内容。")},
                {"role": "user", "content": prompt},
            ],
            max_tokens=3200,
            temperature=0.7,
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f"  ❌ AI 解读失败（{category}）：{e}")
        # 降级：直接给原始要点，保证有内容
        return "\n\n".join(
            f"📌 **[{it['title']}]({it['link']})**\n> {it.get('summary','')[:200]}…"
            for it in news_list
        )


# ── 抓取各板块 ─────────────────────────────────────────────────────────
def gather():
    print("\n📡 抓取各板块数据…\n")

    print("🤖 [AI与深度学习]")
    ai = sources.fetch_arxiv_rss(["cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.NE", "stat.ML"])
    ai += sources.fetch_semantic_scholar("large language model deep learning neural network", limit=20)

    print("💻 [计算机科学与系统]")
    cs = sources.fetch_arxiv_rss(["cs.DS", "cs.CR", "cs.PL", "cs.DC", "cs.AR", "cs.SE", "cs.IT", "cs.OS"])
    cs += sources.fetch_hacker_news()
    cs += sources.fetch_semantic_scholar("distributed systems security cryptography compiler", limit=15)

    print("📐 [数学与理论]")
    math_ = sources.fetch_arxiv_rss(["math.OC", "math.NA", "math.ST", "math.CO", "math.PR", "math.NT", "math.AG", "cs.CC"])
    math_ += sources.fetch_semantic_scholar("optimization theorem combinatorics number theory", limit=12)

    print("🔬 [自然科学]")
    sci = []
    for url in ["https://www.nature.com/nature.rss", "https://phys.org/rss-feed/"]:
        sci += sources.fetch_rss(url)
    sci += sources.fetch_semantic_scholar("quantum physics chemistry biology breakthrough", limit=10)
    # 自然科学板块额外过滤：必须与科学主题相关，剔除社会/生活类软文
    before = len(sci)
    sci = [it for it in sci if is_science_relevant(it)]
    if before != len(sci):
        print(f"  🧪 科学相关性过滤：{before} → {len(sci)} 条")

    return {"AI与深度学习": ai, "计算机科学与系统": cs, "数学与理论": math_, "自然科学": sci}


# ── 发送 ───────────────────────────────────────────────────────────────
def send(payload):
    if DRY_RUN:
        with open("dry_run_card.json", "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("🧪 DRY_RUN：卡片已写入 dry_run_card.json，未发送。")
        return True
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get("StatusCode") == 0 or result.get("code") == 0:
            print("✅ 飞书消息发送成功！")
            return True
        print(f"⚠️ 飞书返回异常：{result}")
        return False
    except Exception as e:
        print(f"❌ 发送失败：{e}")
        return False


# ── 主流程 ─────────────────────────────────────────────────────────────
def build_and_send():
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    date_cn = now.strftime("%Y年%m月%d日")
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    date_iso = now.strftime("%Y-%m-%d")

    kb = KnowledgeBase()
    limits = {"AI与深度学习": 5, "计算机科学与系统": 5, "数学与理论": 4, "自然科学": 3}

    raw = gather()
    categories_data, analyses = [], {}
    print("\n🧠 去重选优 + AI 解读…\n")
    for name in ["AI与深度学习", "计算机科学与系统", "数学与理论", "自然科学"]:
        selected = select(raw.get(name, []), limits[name], kb, name)
        print(f"  ✅ {name}：选中 {len(selected)} 条")
        related = kb.related(selected) if selected else []
        analyses[name] = generate_ai_analysis(selected, name, related)
        categories_data.append((name, selected))

    total = sum(len(items) for _, items in categories_data)
    kb_total = kb.stats().get("total_entries", 0)

    # 全空 → 告警
    if total == 0:
        send(feishu_card.build_alert_card(
            "今日早报抓取为空",
            "所有数据源今日均未返回可用内容，请检查 arXiv RSS / Semantic Scholar Key / 网络。"))
        kb.close()
        return

    card = feishu_card.build_card(date_cn, weekday, categories_data, analyses,
                                  total, TIME_WINDOW_DAYS, kb_total)
    ok = send(card)

    # 写入知识库（档案 + 索引）
    try:
        kb.write_markdown_archive(date_cn, weekday, categories_data, analyses)
        for name, items in categories_data:
            kb.add_entries(date_iso, name, items)
        print(f"  📚 知识库累计沉淀 {kb.stats().get('total_entries', 0)} 条")
    except Exception as e:
        print(f"  ⚠️ 写入知识库失败：{e}")

    # 第二阶段：同步到飞书多维表格（无密钥自动跳过）
    if feishu_sync and not DRY_RUN:
        try:
            feishu_sync.sync_to_feishu(date_iso, categories_data)
        except Exception as e:
            print(f"  ℹ️ 飞书同步跳过/失败：{e}")

    kb.close()
    if not ok and not DRY_RUN:
        send(feishu_card.build_alert_card("早报发送失败", "卡片发送返回异常，请检查 Webhook 配置。"))


if __name__ == "__main__":
    try:
        build_and_send()
    except Exception:
        err = traceback.format_exc()
        print(err)
        try:
            send(feishu_card.build_alert_card("早报脚本异常", f"```\n{err[-800:]}\n```"))
        except Exception:
            pass
        sys.exit(1)
