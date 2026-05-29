# 🧠 第二大脑（推荐方案）：AnythingLLM + 你的知识库

> 这是经调研后**最推荐**给非技术用户的方案：装一个成熟的 Mac 应用，双击即用，
> 把你的每日早报档案当知识库，用 DeepSeek 问答，并且**越聊越懂你**（内置长期记忆）。
> 全程**不用写一行代码**。

为什么不自研 App？因为把带 AI 依赖的程序打包成 Mac 应用要过苹果「签名+公证」（否则双击打不开），
还要 99 美元/年开发者账号且长期维护——性价比远不如直接用 AnythingLLM 现成的已公证安装包。

---

## 一、安装 AnythingLLM（5 分钟）

1. 打开 <https://anythingllm.com> → 下载 **Mac（Apple Silicon）** 版 `.dmg`。
2. 双击安装、打开。首次启动它会自带本地嵌入模型 + 本地向量库（数据都存在你 Mac 上）。

## 二、把大模型设成 DeepSeek-V4-Pro

进入 **Settings（设置）→ LLM Preference（大模型偏好）**：
- Provider 选 **Generic OpenAI**（通用 OpenAI 兼容）
- **Base URL**：`https://api.deepseek.com/v1`
- **API Key**：你的 DeepSeek Key（和 GitHub 里 `OPENAI_API_KEY` 同一个）
- **Chat Model Name**：`deepseek-v4-pro`  ← 已核实为当前有效模型名
- Token context window 填 `64000`（够用即可）

保存后可在任意对话里测一句，能回中文就说明通了。

## 三、开启「长期记忆」（越聊越懂你）

进入 **Settings → 找到 Memory / Memories（记忆）** 开关并开启。
开启后它会自动记住关于你的重要信息（专业、偏好、关注方向），下次自动调用 → 越聊越懂你。

## 四、新建工作区并喂入你的知识库

1. 左侧 **New Workspace（新建工作区）**，命名如「科技第二大脑」。
2. 把你的每日档案喂进去（二选一）：
   - **手动**：把 `feishu-daily-news/knowledge_base/archive` 里的 `.md` 文件拖进工作区上传框；
   - **自动**（推荐，见第六节）：用同步脚本每天自动喂。

完成后，你就能问它：「最近有哪些关于扩散模型的论文？用通俗的话讲讲」之类。

---

## 五、把知识库下载到 Mac（一次性）

打开「终端」（Terminal），粘贴执行（把路径换成你想放的位置）：
```bash
cd ~
git clone https://github.com/LuxuryBLee/feishu-daily-news.git
cd feishu-daily-news
```
以后 GitHub Actions 每天会把新档案提交上去，你这边 `git pull` 就能拿到最新（第六节自动化）。

## 六、自动同步：让每天的新档案自动进 AnythingLLM

1. **拿 AnythingLLM 的 API Key**：AnythingLLM → **Settings → Tools → Developer API → Generate New API Key**，复制。
2. **查你的工作区 slug**：
   ```bash
   cd ~/feishu-daily-news
   ANYTHINGLLM_API_KEY=你的Key python3 tools/sync_to_anythingllm.py --list
   ```
   记下你工作区的 `slug`（形如 `keji-di-er-da-nao`）。
3. **写一个配置文件** `tools/.anythingllm.env`（不会上传 GitHub）：
   ```bash
   ANYTHINGLLM_URL=http://localhost:3001
   ANYTHINGLLM_API_KEY=你的AnythingLLM_Key
   ANYTHINGLLM_WORKSPACE=你的工作区slug
   ```
4. **手动同步一次试试**：
   ```bash
   cd ~/feishu-daily-news && bash tools/run_anythingllm_sync.sh
   ```
   成功后，去 AnythingLLM 工作区就能看到档案，开始问答。
5. **设成每天自动**（每天早上 8 点拉取+同步，cron）：
   ```bash
   crontab -e
   # 加一行（路径按你的实际位置）：
   0 8 * * * /bin/bash ~/feishu-daily-news/tools/run_anythingllm_sync.sh >> /tmp/anythingllm_sync.log 2>&1
   ```

---

## 数据与隐私

- 你的文档、向量、记忆**都存在你自己的 Mac 上**（本机嵌入 + 本地向量库）。
- 只有「和 DeepSeek 对话」这一步会把问题发给 DeepSeek API——这是你主动选 DeepSeek 的必然，无法纯本地（除非改用本地模型，效果不如 V4-Pro）。

## 备选应用

若以后想要更花哨：**Cherry Studio**（功能最全，记忆需启用 memory MCP）或 **Msty**（精致但记忆弱、闭源）。AnythingLLM 是综合最优起步。

## 遇到问题

把报错截图发我（Claude），我按你的实际情况一步步带你弄通。
> 注：`tools/sync_to_anythingllm.py` 基于 AnythingLLM 官方 Developer API 编写，因需在你装好 App 的环境里才能联调，
> 首次运行若有接口差异（不同版本端口/字段），把报错发我，我立即适配。
