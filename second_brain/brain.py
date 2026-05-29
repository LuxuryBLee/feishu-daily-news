"""
brain.py —【第二阶段】第二大脑核心（在你的 Mac mini 上常驻运行）

它做三件事，合起来就是“越问越懂你”：
  1. RAG：把 GitHub 仓库里 knowledge_base/archive 的每日档案切块、向量化，回答时检索最相关的片段。
  2. 记忆：把你和它的每轮对话（及其中的关键事实）存进长期记忆，下次自动召回 → 越聊越懂你。
  3. 生成：用 DeepSeek-V4-Pro 基于「检索到的知识 + 召回的记忆 + 你的问题」给出回答。

只依赖：openai（调 DeepSeek）、fastembed（本地免费向量）、numpy。无需任何云服务。
可独立测试：直接 `python brain.py` 进入命令行问答。飞书接入见 feishu_bot.py。
"""

import os
import glob
import sqlite3
import time
from datetime import datetime

import numpy as np
from openai import OpenAI
from fastembed import TextEmbedding

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE_GLOB = os.path.join(ROOT, "knowledge_base", "archive", "**", "*.md")
MEM_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.sqlite")

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "sk-missing",
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    timeout=120.0,
)
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")


def _normit(v):
    v = np.asarray(v, dtype="float32")
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


class Brain:
    def __init__(self):
        print("🧠 启动第二大脑：加载向量模型…")
        self.embed_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        self.chunks = []          # [(text, source)]
        self.chunk_vecs = None    # np.ndarray [N, dim]
        self._load_archive()
        self._init_memory()

    # ── 知识库（RAG）──
    def _embed(self, texts):
        return [_normit(v) for v in self.embed_model.embed(list(texts))]

    def _load_archive(self):
        files = sorted(glob.glob(ARCHIVE_GLOB, recursive=True))
        chunks = []
        for fp in files:
            try:
                text = open(fp, encoding="utf-8").read()
            except Exception:
                continue
            # 按 “### 标题” 切块（每条新闻 + 其解读为一块）
            parts = text.split("\n### ")
            tag = os.path.basename(fp).replace(".md", "")
            for i, p in enumerate(parts):
                p = p.strip()
                if len(p) < 40:
                    continue
                chunks.append((("### " + p) if i else p, tag))
        self.chunks = chunks
        if chunks:
            self.chunk_vecs = np.vstack(self._embed([c[0][:1500] for c in chunks]))
            print(f"🧠 已索引 {len(chunks)} 个知识片段（来自 {len(files)} 天档案）")
        else:
            print("🧠 暂无档案，知识库为空（先让早报机器人跑几天）")

    def retrieve(self, query, k=5):
        if self.chunk_vecs is None or not len(self.chunks):
            return []
        qv = self._embed([query])[0]
        sims = self.chunk_vecs @ qv
        idx = np.argsort(-sims)[:k]
        return [(self.chunks[i][0], self.chunks[i][1], float(sims[i])) for i in idx if sims[i] > 0.3]

    # ── 记忆层（越聊越懂你）──
    def _init_memory(self):
        self.mem = sqlite3.connect(MEM_DB)
        self.mem.execute(
            "CREATE TABLE IF NOT EXISTS memory ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, role TEXT, text TEXT, embedding BLOB)")
        self.mem.commit()

    def remember(self, role, text):
        if not text.strip():
            return
        v = self._embed([text])[0]
        self.mem.execute(
            "INSERT INTO memory (ts, role, text, embedding) VALUES (?,?,?,?)",
            (datetime.now().isoformat(), role, text[:2000], v.astype("float32").tobytes()))
        self.mem.commit()

    def recall(self, query, k=4):
        rows = self.mem.execute("SELECT text, role, embedding FROM memory").fetchall()
        if not rows:
            return []
        qv = self._embed([query])[0]
        scored = []
        for text, role, emb in rows:
            if not emb:
                continue
            sim = float(np.frombuffer(emb, dtype="float32") @ qv)
            scored.append((sim, role, text))
        scored.sort(reverse=True)
        return [(r, t) for s, r, t in scored[:k] if s > 0.4]

    # ── 回答 ──
    def answer(self, question):
        knowledge = self.retrieve(question, k=5)
        memories = self.recall(question, k=4)

        ctx = ""
        if knowledge:
            ctx += "【你知识库里的相关内容】\n" + "\n---\n".join(
                f"(来自 {src}) {txt[:700]}" for txt, src, _ in knowledge) + "\n\n"
        if memories:
            ctx += "【关于你的长期记忆】\n" + "\n".join(
                f"- ({role}) {txt[:200]}" for role, txt in memories) + "\n\n"

        prompt = (
            f"{ctx}【用户的问题】\n{question}\n\n"
            "请基于上面的知识库内容与长期记忆作答。若知识库有相关内容，优先引用并标注来自哪天的档案；"
            "若记忆显示用户的偏好/背景，请据此调整深度与措辞。回答用中文，专业、生动、有条理。")

        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": (
                        "你是用户的私人 AI 第二大脑，熟悉用户长期关注的 AI/计算机/数学前沿，"
                        "善于把检索到的论文知识与用户背景结合，给出贴心而专业的解答。")},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2500,
                temperature=0.6,
            )
            ans = resp.choices[0].message.content
        except Exception as e:
            ans = f"（抱歉，调用模型出错：{e}）"

        # 写入记忆 → 下次更懂你
        self.remember("user", question)
        self.remember("assistant", ans)
        return ans


if __name__ == "__main__":
    b = Brain()
    print("\n💬 第二大脑已就绪，输入问题（Ctrl+C 退出）：")
    while True:
        try:
            q = input("\n你> ").strip()
            if not q:
                continue
            print("\n🧠 " + b.answer(q))
        except (KeyboardInterrupt, EOFError):
            print("\n再见！")
            break
