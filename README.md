# 🌅 飞书科技前沿早报机器人 + 🧠 第二大脑

每天早上 **07:00（北京时间）** 自动推送 AI、计算机、数学、自然科学领域的最新动态到飞书，
配有 DeepSeek-V4-Pro 的深度解读与知识补充；并把内容沉淀为可检索、可问答、不断成长的**个人知识库（第二大脑）**。

## ✨ 升级亮点（2026-05）

- **🔧 修复“板块空白”**：arXiv 改走未被限流的 RSS 通道当主力；Semantic Scholar 用 API Key + 全局限速；移除已关停的 Papers With Code。
- **🎨 排版升级**：飞书卡片 2.0，分版块、AI 解读折叠收纳、跳转链接。
- **🧠 知识库地基**：语义去重（不再重复推送）+ 历史档案（Markdown，可搜索）+ RAG 历史衔接。
- **🛡️ 更稳定**：单源失败不影响整体、板块兜底防空白、异常/失败发告警卡片、解析双保险。
- **🗣️ 更生动**：重写解读提示词，多用类比，“一句话看懂 + 核心贡献 + 知识补充 + 与你的关联”。

## 🏗️ 架构

```
① GitHub Actions（每天自动，免费）          ② Mac mini（常驻，可选 = 第二阶段）
   每日早报机器人                              第二大脑问答服务
   • 抓取 → 语义去重 → DeepSeek 解读 → 卡片       • 同步 GitHub 知识库档案
   • 写入 knowledge_base/（档案 + 向量索引）──▶   • RAG 检索 + 记忆层（越聊越懂你）
   • （可选）同步到飞书多维表格                    • 飞书长连接：在飞书里 @它问答
```

## 数据来源

- **arXiv RSS**（主力）：cs.AI/LG/CL/CV/NE、math.OC/NA/ST/CO/PR… 等
- **Semantic Scholar**（需 Key）：论文检索补充
- **Hacker News**：计算机/系统社区热门
- **Nature / phys.org RSS**：自然科学

## 📁 项目结构

```
feishu_news_bot.py     早报主程序（抓取/去重/解读/发送/存档）
sources.py             数据源抓取（arXiv RSS / Semantic Scholar / HN / RSS）
feishu_card.py         飞书卡片 2.0 排版
knowledge_base.py      知识库引擎（语义去重 / 档案 / RAG）
feishu_sync.py         第二阶段：同步到飞书多维表格（可选）
knowledge_base/        自动维护的知识库（档案 + 索引）
second_brain/          第二阶段：Mac mini 第二大脑问答服务
docs/FEISHU_SETUP.md   飞书接入保姆级教程
```

## 🚀 部署（第一阶段，必做）

在仓库 **Settings → Secrets and variables → Actions** 配置：

| Secret | 说明 | 必需 |
|---|---|---|
| `OPENAI_API_KEY` | DeepSeek API 密钥 | ✅ |
| `FEISHU_WEBHOOK` | 飞书自定义机器人 Webhook | ✅ |
| `S2_API_KEY` | Semantic Scholar API Key（**强烈建议**，修复板块空白）| 建议 |

配好后即每日自动运行；也可在 **Actions** 页手动 **Run workflow** 立即测试。

本地调试（不发送，只生成卡片到 `dry_run_card.json`）：
```bash
pip install -r requirements.txt
DRY_RUN=1 S2_API_KEY=你的key python feishu_news_bot.py
```

## 🧠 第二阶段（可选：飞书深度接入 + 第二大脑问答）

见 [`docs/FEISHU_SETUP.md`](docs/FEISHU_SETUP.md) 与 [`second_brain/README.md`](second_brain/README.md)。
