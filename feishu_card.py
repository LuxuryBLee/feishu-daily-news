"""
feishu_card.py — 飞书卡片 2.0 排版

用 Card JSON 2.0 重做早报样式：
  • 顶部彩色标题栏 + 副标题（日期/数量）
  • 每个板块：醒目小标题 + 要点列表（带跳转链接）
  • AI 深度解读收进「折叠面板」，默认收起，点开才看，保持整洁
  • 底部署名备注
另含 build_alert_card：抓取/推送异常时发的「告警卡片」，让你第一时间知道出问题了。

注：经实测，飞书自定义机器人 Webhook 接受 schema 2.0 卡片；排版能力与 Webhook 无关。
"""

# 飞书单条卡片有总大小限制，单个 markdown 元素内容过长会被截断或拒收，这里做安全上限
MAX_ANALYSIS_CHARS = 4500

CATEGORY_STYLE = {
    "AI与深度学习": {"emoji": "🤖", "color": "blue"},
    "计算机科学与系统": {"emoji": "💻", "color": "wathet"},
    "数学与理论": {"emoji": "📐", "color": "purple"},
    "自然科学": {"emoji": "🔬", "color": "green"},
}


def _truncate(text, limit):
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + "\n\n…（内容较长，已截断）"


def _category_block(name, items, analysis):
    """构建单个板块的卡片元素列表。"""
    style = CATEGORY_STYLE.get(name, {"emoji": "•", "color": "grey"})
    elements = [{
        "tag": "markdown",
        "content": f"**{style['emoji']} {name}**",
        "text_align": "left",
    }]

    if not items:
        elements.append({
            "tag": "markdown",
            "content": "_今日暂无符合条件的新内容（已自动放宽条件仍未命中，明日继续）。_",
        })
        return elements

    # 要点列表：标题（带链接）+ 来源标签
    bullet_lines = []
    for i, it in enumerate(items, 1):
        src = it.get("source", "")
        tag = f"  `{src}`" if src else ""
        bullet_lines.append(f"**{i}.** [{it['title']}]({it['link']}){tag}")
    elements.append({"tag": "markdown", "content": "\n".join(bullet_lines)})

    # AI 解读 → 折叠面板
    if analysis:
        elements.append({
            "tag": "collapsible_panel",
            "expanded": False,
            "header": {
                "title": {"tag": "markdown", "content": "**🔍 展开 AI 深度解读与知识补充**"},
                "background_color": style["color"],
                "vertical_align": "center",
                "icon": {"tag": "standard_icon", "token": "down-bold_outlined",
                          "color": "grey", "size": "16px 16px"},
            },
            "elements": [{"tag": "markdown", "content": _truncate(analysis, MAX_ANALYSIS_CHARS)}],
        })
    return elements


def build_card(date_cn, weekday, categories_data, analyses, total_news,
               window_days, kb_total=0, model_label="DeepSeek-V4-Pro"):
    """构建完整的 Webhook 卡片消息。

    categories_data: list[(name, items)]
    analyses:        dict[name -> 解读文本]
    """
    body_elements = [{
        "tag": "markdown",
        "content": (
            f"**Timmy，早上好！** ☀️\n\n"
            f"今日精选 **{total_news} 条**前沿资讯，覆盖 "
            f"**AI · 计算机 · 数学 · 自然科学** 四大板块"
            f"（近 {window_days} 天，已语义去重）。"
        ),
    }, {"tag": "hr"}]

    for name, items in categories_data:
        body_elements.extend(_category_block(name, items, analyses.get(name)))
        body_elements.append({"tag": "hr"})

    footer = f"✨ GitHub Actions + {model_label} 自动生成 · 每日 07:00 推送"
    if kb_total:
        footer += f" · 知识库已沉淀 {kb_total} 条"
    body_elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": footer}],
    })

    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"🌅 {date_cn} {weekday} · 科技前沿早报"},
                "subtitle": {"tag": "plain_text", "content": f"每日精选 · 共 {total_news} 条"},
                "template": "indigo",
            },
            "body": {"elements": body_elements},
        },
    }


def build_alert_card(title, detail):
    """异常告警卡片——抓取异常/推送失败/数据为空时提醒你。"""
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"⚠️ {title}"},
                "template": "red",
            },
            "body": {"elements": [{"tag": "markdown", "content": detail}]},
        },
    }
