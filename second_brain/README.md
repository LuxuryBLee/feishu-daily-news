# 🧠 第二大脑服务（Mac mini 常驻）

让你能在**飞书里直接和你的知识库对话**，并且**越聊越懂你**。

```
GitHub 每日早报 ──每天产出──▶ knowledge_base/archive（每日档案）
                                      │  git pull 同步到 Mac mini
                                      ▼
你的 Mac mini ──运行──▶ brain.py（RAG 检索 + 记忆层 + DeepSeek-V4-Pro）
                                      │  飞书长连接
                                      ▼
                              你在飞书里 @它 提问 → 它结合你的知识库与记忆回答
```

## 它和「飞书自带知识问答」有什么不同？

| | 飞书自带知识问答 | 这个第二大脑服务 |
|---|---|---|
| 检索你的资料 | ✅ | ✅ |
| **越聊越懂你（长期记忆）** | ❌ 只检索文档，不记对话 | ✅ 每轮对话都进记忆，下次自动召回 |
| 用哪个模型 | 飞书内置 | 你指定 DeepSeek-V4-Pro |
| 花费 | 会员额度 | 仅 DeepSeek API（很便宜） |
| 维护 | 零维护 | 需 Mac mini 常开 |

> 建议：两者可并存。日常轻问答用飞书自带的省事；想要“真正懂你、可定制”的，用这个服务。

## 安装与运行（保姆级）

> 前置：先按 [`docs/FEISHU_SETUP.md`](../docs/FEISHU_SETUP.md) 建好飞书自建应用，拿到 App ID / Secret。

1. **装 Python 依赖**（Mac mini 终端里）：
   ```bash
   cd ~/feishu-daily-news        # 你 clone 仓库的位置
   pip3 install -r second_brain/requirements.txt
   ```
2. **填密钥**：
   ```bash
   cp second_brain/.env.example second_brain/.env
   # 用文本编辑器打开 second_brain/.env，填入 DeepSeek Key 和飞书 App ID/Secret
   ```
3. **先本地测一下大脑**（不接飞书，命令行问答）：
   ```bash
   set -a; source second_brain/.env; set +a
   python3 second_brain/brain.py
   # 出现 "你> " 后随便问，比如：最近有什么关于扩散模型的论文？
   ```
4. **接入飞书**（长连接，无需公网 IP）：
   ```bash
   python3 second_brain/feishu_bot.py
   # 然后在飞书里给你的应用发消息试试
   ```
5. **让它开机自启 / 一直运行**（可选，进阶）：用 macOS 的 `launchd` 或 `tmux`/`pm2` 守护进程。需要时告诉我，我给你写好配置。

## 让知识库保持最新

Mac mini 上定时 `git pull` 即可拉到 GitHub Actions 每天提交的新档案：
```bash
# 例如用 cron 每天 8 点拉取（crontab -e）
0 8 * * * cd ~/feishu-daily-news && git pull --quiet
```
重启 `feishu_bot.py` 后即加载最新档案（后续可做成自动热加载）。

## 记忆存在哪？

`second_brain/memory.sqlite`（在 Mac mini 本地，不上传 GitHub）。这是你和大脑的私人对话记忆。

---

⚠️ 说明：本服务为**第二阶段骨架**，逻辑完整、可独立运行，但因需在你的 Mac mini + 飞书应用环境下才能端到端联调，作者（Claude）无法替你在云端验证飞书长连接部分。首次跑若有报错，把报错发我，我帮你调通。
