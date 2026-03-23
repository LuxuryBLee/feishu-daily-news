# 🌅 飞书科技前沿早报机器人

每天早上 **07:00（北京时间）** 自动推送 AI、计算机、数学、科研领域最新动态到飞书，配有 GPT 深度解读与知识补充。

## 数据来源

- **arXiv**：CS.AI / CS.LG / CS.CV / math.NA / math.OC / math.ST
- **Hacker News**：科技社区热门
- **Nature**：顶级科学期刊
- **MIT News**：麻省理工最新研究
- **Science Daily / Phys.org**：综合科学资讯

## 技术栈

- Python 3.11 + feedparser + OpenAI GPT-4.1-mini
- GitHub Actions 定时触发（每日 UTC 23:00）
- 飞书自定义机器人 Webhook 推送

## 部署说明

在仓库 Settings → Secrets 中配置：
- `OPENAI_API_KEY`：OpenAI API 密钥
- `FEISHU_WEBHOOK`：飞书机器人 Webhook 地址
