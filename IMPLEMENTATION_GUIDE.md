# 飞书科技前沿早报机器人 - 完整技术实现文档

本文档详细记录了“飞书科技前沿早报机器人”的架构设计、数据源策略、核心实现逻辑以及在开发过程中遇到的各种问题（坑）和最终的解决方案。本文档旨在帮助其他智能体（AI Agent）或开发者快速学习、理解并复现该系统。

---

## 1. 系统架构概览

该项目是一个完全独立、无需常驻服务器、基于云端定时任务触发的自动化资讯推送系统。其核心目标是每天早上准时为用户推送 AI、计算机、数学及自然科学领域的最新前沿纯技术内容，并附带大语言模型（LLM）的深度解读。

### 1.1 核心组件

1. **触发与执行环境**：**GitHub Actions**
   - 负责每天定时（UTC 23:00，即北京时间 07:00）拉起 Ubuntu 虚拟机环境执行 Python 脚本。
   - 优点：完全免费，永久独立运行，无需维护个人服务器。
2. **数据采集模块**：**Python Requests & Feedparser**
   - 负责从多个学术 API 和 RSS 源抓取最新的论文和新闻资讯。
3. **内容过滤与采样模块**：**自定义 Python 逻辑**
   - 负责剔除政治、商业等非技术内容，确保时间窗口在近 5 天内，并利用日期作为随机种子进行去重采样。
4. **AI 解读模块**：**OpenAI 兼容 API (如 Qwen3-Max)**
   - 负责对筛选出的英文/中文摘要进行阅读，提炼核心贡献，并针对大学生群体生成通俗易懂的知识补充。
5. **消息推送模块**：**飞书自定义机器人 Webhook**
   - 负责将生成的 Markdown 内容组装成精美的交互式卡片（Interactive Card），推送到用户的飞书群聊。

---

## 2. 数据源策略与选型

在云端环境（特别是 GitHub Actions 提供的 Azure IP 段）抓取学术数据时，最容易遇到的问题是 **IP 限制（HTTP 429 Too Many Requests）**。因此，数据源的选择和容错机制至关重要。

### 2.1 核心数据源

为了保证稳定性和覆盖面，系统采用了多源互补策略：

| 数据源 | 覆盖领域 | 接入方式 | 优缺点与适用场景 |
| :--- | :--- | :--- | :--- |
| **Semantic Scholar** | AI、计算机、数学、自然科学 | REST API (`/graph/v1/paper/search`) | **优点**：最稳定，对 GitHub Actions IP 友好，无需 API Key。<br>**缺点**：部分论文可能缺失具体发布日期（仅有年份）。 |
| **Papers With Code** | AI 与机器学习 | REST API (`/api/v1/papers/`) | **优点**：专注于最新 AI 论文，包含代码链接。<br>**缺点**：覆盖面仅限于 AI/ML。 |
| **arXiv** | 计算机、数学各细分领域 | 官方 HTTPS API (`export.arxiv.org/api/query`) | **优点**：最权威的预印本源，分类极细。<br>**缺点**：对高频请求极敏感，部分云服务 IP 易被封禁。 |
| **Hacker News** | 计算机系统、极客讨论 | Firebase REST API | **优点**：能抓取到工业界最新的技术讨论。<br>**缺点**：需进行严格的关键词过滤，以剔除创业/融资新闻。 |
| **Nature / Science 等** | 自然科学综合 | RSS Feed (`feedparser` 解析) | **优点**：权威期刊的官方输出。<br>**缺点**：RSS 格式不一，时间字段解析复杂。 |

### 2.2 踩坑记录：arXiv 的限速与周末停更

1. **周末无数据问题**：
   - **坑**：最初尝试使用 arXiv 的 RSS 源，发现周末（Saturday, Sunday）RSS 不更新，导致抓取结果为空。
   - **解决方案**：放弃 RSS，全面改用 arXiv 的 HTTPS API（`export.arxiv.org/api/query`），通过指定 `sortBy=submittedDate` 获取最新提交。
2. **IP 限速（429 错误）**：
   - **坑**：在沙箱环境中频繁请求 arXiv API，迅速触发了 HTTP 429 错误，甚至导致连接超时。
   - **解决方案**：
     - 将多个分类（如 `cs.AI`, `cs.LG`）合并为一次查询（使用 `OR` 逻辑连接 `search_query`）。
     - 增加 `safe_get` 函数，内置指数退避重试机制（Exponential Backoff）。
     - 增加伪装的 `User-Agent`。
     - **最关键的一点**：部署到 GitHub Actions 后，利用其不同的出口 IP 绕过了部分严格的封锁。
3. **日期解析兼容性问题**：
   - **坑**：部分 API 返回的日期格式不固定（如 `Z` 结尾与 `+00:00` 结尾混用），导致日期解析失败，条目被误删。
   - **解决方案**：引入 `parsedate_to_datetime` 并结合 `replace('Z', '+00:00')` 的多重兼容解析方案。
4. **抓取频率控制**：
   - **坑**：并发请求过快会导致 arXiv 即使在 GitHub Actions IP 下也偶尔触发限速。
   - **解决方案**：在请求之间显式增加 `time.sleep(2)`，并引入随机 `User-Agent` 模拟真实浏览器访问。

---

## 3. 内容过滤与时间窗口控制

系统需要确保推送的内容是“最新的”且是“纯技术/理论的”。

### 3.1 严格的时间过滤

- **设定**：时间窗口为近 5 天（`TIME_WINDOW_DAYS = 5`）。
- **坑**：Semantic Scholar 返回的部分论文只有 `year: 2025`，没有 `publicationDate`，导致旧论文被当作新论文抓取。
- **解决方案**：在代码中实现**严格过滤**。如果条目没有明确的发布日期（精确到日），直接丢弃。对于有日期的条目，将其转换为 UTC 时间的 `datetime` 对象，与 `cutoff`（当前时间减 5 天）进行严格比对。

### 3.2 关键词过滤与打分机制

- **黑名单（Block Keywords）**：包含 `election`, `trump`, `stock`, `ipo`, `融资`, `政治` 等词汇。命中任何一个即丢弃该条目。
- **白名单（Tech Keywords）**：包含 `algorithm`, `theorem`, `optimization`, `transformer`, `量子`, `证明` 等词汇。用于计算该条目的“技术浓度得分（Tech Score）”。
- **去重与采样**：
  - 将所有合格条目按 `Tech Score` 降序排列。
  - 截取前 30 条作为候选池。
  - 使用当前日期字符串（如 `20260402`）作为 `random.seed`，从候选池中随机采样指定数量（如 5 条）。这保证了每天推送的内容不重复，且质量最高。

---

## 4. AI 解读模块（Prompt Engineering）

该模块是提升早报价值的核心。单纯推送链接毫无意义，必须由 LLM 进行消化和降维解释。

### 4.1 模型选择与配置

- **模型**：最初使用 GPT-5.4，后切换为阿里云的 **Qwen3-Max**（`dashscope.aliyuncs.com`）。
- **坑**：在切换模型时，由于 `base_url` 未及时从国际版（`dashscope-intl`）改为国内版，导致 API 鉴权失败（HTTP 401 Invalid API Key）。
- **解决方案**：明确区分国内版与国际版的 API Endpoint，并通过 GitHub Secrets 安全注入。

### 4.2 Prompt 设计要点

为了让信息与计算科学专业的大学生能够快速吸收，Prompt 必须具有强烈的结构性和针对性：

1. **角色设定**：资深专家和科普导师。
2. **受众设定**：信息与计算科学专业大学生（对AI、数学建模感兴趣）。
3. **输出结构强制要求**：
   - 💡 **核心贡献**：2-3句话总结创新点。
   - 🧠 **知识补充**：通俗解释 1-2 个数学/算法概念（100-150字）。
   - 📊 **与你的关联**：一句话点明对该专业学生的启发。
4. **约束条件**：全程中文、英文术语保留并加粗、绝不捏造数据、不涉及政治商业。

---

## 5. 飞书消息组装与推送

### 5.1 飞书卡片格式（Interactive Card）

飞书不支持原生的长篇 Markdown 直接发送，必须使用其特定的卡片 JSON 结构。

- **Header**：设置 `template: "indigo"` 使标题栏呈现美观的蓝色，标题包含当天的日期和星期。
- **Elements**：
  - 第一部分：使用 `markdown` 标签输出问候语和摘要。
  - 第二部分：使用 `markdown` 标签输出 AI 生成的各板块详细解读。
  - 第三部分：使用 `hr` 分割线。
  - 第四部分：使用 `note` 标签输出灰色的系统免责声明和状态信息。

### 5.2 踩坑记录：GitHub Actions 环境变量注入

- **坑**：在本地测试时，脚本通过 `os.environ.get("OPENAI_API_KEY")` 读取环境变量一切正常。但部署到 GitHub Actions 后，如果不显式传递，Python 脚本无法读取到 Secrets。
- **解决方案**：在 `.github/workflows/daily_news.yml` 的 `run` 步骤中，必须显式声明 `env`：
  ```yaml
  - name: 运行推送脚本
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      FEISHU_WEBHOOK: ${{ secrets.FEISHU_WEBHOOK }}
    run: python feishu_news_bot.py
  ```

---

## 6. 总结与智能体学习要点

对于任何试图复现或修改此项目的智能体，请牢记以下几点原则：

1. **网络环境差异**：本地沙箱的网络环境与 GitHub Actions 服务器（Azure）截然不同。在沙箱中被 429 限速的 API，在线上往往能正常工作。测试时应以 Actions 的线上运行结果为准。
2. **时间处理的鲁棒性**：学术 API 和 RSS 返回的时间格式千奇百怪（ISO 8601, RFC 822 等），必须使用 `try-except` 块妥善处理日期解析，避免因一条数据的日期格式错误导致整个脚本崩溃。
3. **Secrets 管理**：绝对不要在代码中硬编码任何 API Key 或 Webhook URL，必须通过环境变量读取，并指导用户在 GitHub Settings 中配置。
4. **依赖管理**：在修改脚本引入新库（如 `beautifulsoup4`, `lxml`, `pyyaml`）时，务必同步更新 GitHub Actions workflow 文件中的 `pip install` 命令，否则线上运行必然报 `ModuleNotFoundError`。

（文档完）
