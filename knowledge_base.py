"""
knowledge_base.py — 第二大脑的「地基」

职责（全部在 GitHub Actions 的免费环境里完成，无需服务器、无需 API Key）：
  1. 历史档案：把每天推送的内容写成人类可读的 Markdown，存进仓库，方便在 GitHub 里翻阅/搜索。
  2. 语义去重：新抓到的内容若与最近推过的太相似，则跳过，保证“每天都是新东西”。
  3. RAG 检索：解读时找出与今天内容相关的历史条目，喂给 AI，让它能说“这和你之前看过的 XX 有关”。

设计原则——**绝不拖垮早报推送**：
  - 向量能力（fastembed）是“可选增强”。若未安装或下载失败，自动降级为纯 Python 词法相似度。
  - 任何一步出错都只打印警告并返回安全默认值，主流程照常发早报。

存储：
  - knowledge_base/archive/<年>/<年-月-日>.md   ← 人类可读档案
  - knowledge_base/kb.sqlite                    ← 机器索引（标题/链接/分类/向量），供去重与 RAG 使用
"""

import os
import re
import json
import math
import sqlite3
import hashlib
from datetime import datetime, timezone, timedelta

# ── 可选依赖：numpy / fastembed ───────────────────────────────────────
try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:
    _HAS_NUMPY = False

ROOT = os.path.dirname(os.path.abspath(__file__))
KB_DIR = os.path.join(ROOT, "knowledge_base")
ARCHIVE_DIR = os.path.join(KB_DIR, "archive")
DB_PATH = os.path.join(KB_DIR, "kb.sqlite")

# 去重阈值：相似度高于此值视为“重复内容”（语义后端用余弦，词法后端用 Jaccard）
SEMANTIC_DUP_THRESHOLD = 0.86
LEXICAL_DUP_THRESHOLD = 0.72
# 去重时只和最近这些天的历史比较（防止越积越慢，也符合“近期不重复”的直觉）
DEDUP_WINDOW_DAYS = 45


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _entry_id(title: str) -> str:
    return hashlib.sha1(_normalize(title).encode("utf-8")).hexdigest()[:16]


# ── 向量后端（可选）────────────────────────────────────────────────────
class _Embedder:
    """优先用 fastembed（本地、免费、无 Key）；不可用时返回 None，触发词法降级。"""

    def __init__(self):
        self.model = None
        self.ok = False
        if not _HAS_NUMPY:
            print("  ℹ️ 知识库：未检测到 numpy，使用词法相似度（仍可去重/检索，精度略低）")
            return
        try:
            from fastembed import TextEmbedding
            # bge-small-en：~130MB，首次运行自动下载并缓存；论文标题/摘要以英文为主，效果好
            self.model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            self.ok = True
            print("  ✅ 知识库：fastembed 语义向量已就绪")
        except Exception as e:
            print(f"  ℹ️ 知识库：fastembed 不可用（{e}），降级为词法相似度")

    def embed(self, texts):
        """返回 list[np.ndarray]（已归一化），失败返回 None。"""
        if not self.ok:
            return None
        try:
            vecs = list(self.model.embed(list(texts)))
            out = []
            for v in vecs:
                v = np.asarray(v, dtype="float32")
                n = np.linalg.norm(v)
                out.append(v / n if n > 0 else v)
            return out
        except Exception as e:
            print(f"  ⚠️ 知识库：向量计算失败（{e}），本次降级为词法相似度")
            return None


# ── 词法相似度（无依赖兜底）────────────────────────────────────────────
def _tokens(text: str):
    text = _normalize(text)
    # 英文按词，中文按字，统一成 token 集合
    words = re.findall(r"[a-z0-9]+", text)
    cjk = re.findall(r"[一-鿿]", text)
    return set(words) | set(cjk)


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


class KnowledgeBase:
    def __init__(self):
        os.makedirs(KB_DIR, exist_ok=True)
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        self.embedder = _Embedder()
        self._init_db()

    # ── SQLite ──
    def _init_db(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                id        TEXT PRIMARY KEY,
                date      TEXT,
                category  TEXT,
                title     TEXT,
                link      TEXT,
                summary   TEXT,
                score     REAL,
                embedding BLOB
            )
            """
        )
        self.conn.commit()

    def _recent_rows(self, days=DEDUP_WINDOW_DAYS):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        cur = self.conn.execute(
            "SELECT id, date, category, title, link, summary, embedding "
            "FROM entries WHERE date >= ? ORDER BY date DESC",
            (cutoff,),
        )
        return cur.fetchall()

    # ── 去重 ──
    def filter_new(self, items, category=""):
        """从候选 items 中剔除与历史（或彼此）过于相似的，返回保留下来的列表。

        item: {"title","link","summary","score"}
        """
        if not items:
            return []

        recent = self._recent_rows()
        # 预计算历史向量（若有）
        use_vec = self.embedder.ok and _HAS_NUMPY
        hist_vecs = []
        if use_vec:
            for r in recent:
                emb = r[6]
                hist_vecs.append(np.frombuffer(emb, dtype="float32") if emb else None)

        kept, kept_texts, kept_vecs = [], [], []
        # 今天候选的向量（批量算更快）
        cand_vecs = None
        if use_vec:
            cand_vecs = self.embedder.embed([self._text(it) for it in items])
            if cand_vecs is None:
                use_vec = False

        for idx, it in enumerate(items):
            text = self._text(it)
            is_dup = False

            if use_vec:
                v = cand_vecs[idx]
                # 与历史比
                for hv in hist_vecs:
                    if hv is not None and float(np.dot(v, hv)) >= SEMANTIC_DUP_THRESHOLD:
                        is_dup = True
                        break
                # 与今天已保留的比
                if not is_dup:
                    for kv in kept_vecs:
                        if float(np.dot(v, kv)) >= SEMANTIC_DUP_THRESHOLD:
                            is_dup = True
                            break
                if not is_dup:
                    kept_vecs.append(v)
            else:
                for r in recent:
                    if _jaccard(text, f"{r[3]} {r[5]}") >= LEXICAL_DUP_THRESHOLD:
                        is_dup = True
                        break
                if not is_dup:
                    for kt in kept_texts:
                        if _jaccard(text, kt) >= LEXICAL_DUP_THRESHOLD:
                            is_dup = True
                            break
                if not is_dup:
                    kept_texts.append(text)

            if not is_dup:
                kept.append(it)

        removed = len(items) - len(kept)
        if removed:
            print(f"  🔁 去重：剔除 {removed} 条与历史/彼此重复的内容（{category}）")
        return kept

    # ── RAG：找相关历史 ──
    def related(self, items, k=3):
        """为本批 items 找出最相关的历史条目，用于喂给 AI 做“知识衔接”。

        返回 list[{"title","link","date"}]，最多 k 条，去重。
        """
        recent = self._recent_rows(days=365)
        if not recent or not items:
            return []

        scored = {}  # id -> (sim, row)
        use_vec = self.embedder.ok and _HAS_NUMPY
        if use_vec:
            cand_vecs = self.embedder.embed([self._text(it) for it in items])
            if cand_vecs is None:
                use_vec = False

        if use_vec:
            hist = [(r, np.frombuffer(r[6], dtype="float32")) for r in recent if r[6]]
            for cv in cand_vecs:
                for r, hv in hist:
                    sim = float(np.dot(cv, hv))
                    if sim > scored.get(r[0], (0,))[0]:
                        scored[r[0]] = (sim, r)
        else:
            for it in items:
                text = self._text(it)
                for r in recent:
                    sim = _jaccard(text, f"{r[3]} {r[5]}")
                    if sim > scored.get(r[0], (0,))[0]:
                        scored[r[0]] = (sim, r)

        # 过滤掉相似度过低的，按相似度排序取 top-k
        ranked = sorted(scored.values(), key=lambda x: x[0], reverse=True)
        out = []
        seen_titles = {_normalize(self._text(it).split(" ", 1)[0]) for it in items}
        min_sim = 0.55 if use_vec else 0.18
        for sim, r in ranked:
            if sim < min_sim:
                continue
            if _normalize(r[3]) in seen_titles:
                continue
            out.append({"title": r[3], "link": r[4], "date": r[1]})
            if len(out) >= k:
                break
        return out

    # ── 写入档案 + 索引 ──
    def add_entries(self, date_str, category, items):
        """把今天选中的条目写入 SQLite 索引（供以后去重/检索）。"""
        if not items:
            return
        vecs = None
        if self.embedder.ok and _HAS_NUMPY:
            vecs = self.embedder.embed([self._text(it) for it in items])
        for i, it in enumerate(items):
            emb_blob = None
            if vecs is not None:
                emb_blob = vecs[i].astype("float32").tobytes()
            self.conn.execute(
                "INSERT OR REPLACE INTO entries "
                "(id, date, category, title, link, summary, score, embedding) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    _entry_id(it["title"]),
                    date_str,
                    category,
                    it.get("title", ""),
                    it.get("link", ""),
                    (it.get("summary", "") or "")[:1000],
                    float(it.get("score", 0)),
                    emb_blob,
                ),
            )
        self.conn.commit()

    def write_markdown_archive(self, date_cn, weekday, categories_data, analyses):
        """生成当天 Markdown 档案，存进 knowledge_base/archive/<年>/<日期>.md。

        categories_data: list[(category_name, items)]
        analyses:        dict[category_name -> AI 解读文本]
        """
        now = datetime.now(timezone.utc) + timedelta(hours=8)
        year_dir = os.path.join(ARCHIVE_DIR, now.strftime("%Y"))
        os.makedirs(year_dir, exist_ok=True)
        path = os.path.join(year_dir, now.strftime("%Y-%m-%d") + ".md")

        lines = [f"# 🌅 {date_cn} {weekday} · 科技前沿早报存档\n"]
        for category, items in categories_data:
            lines.append(f"\n## {category}\n")
            if not items:
                lines.append("\n_今日无符合条件的新内容。_\n")
                continue
            for it in items:
                lines.append(f"\n### [{it['title']}]({it['link']})\n")
                if it.get("summary"):
                    lines.append(f"\n> {it['summary'][:400]}\n")
            analysis = analyses.get(category)
            if analysis:
                lines.append(f"\n<details><summary>🤖 AI 解读</summary>\n\n{analysis}\n\n</details>\n")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            print(f"  📚 已写入档案：{os.path.relpath(path, ROOT)}")
        except Exception as e:
            print(f"  ⚠️ 写入 Markdown 档案失败：{e}")
        return path

    def stats(self):
        try:
            n = self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            return {"total_entries": n}
        except Exception:
            return {"total_entries": 0}

    @staticmethod
    def _text(it):
        return f"{it.get('title','')} {it.get('summary','')}".strip()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
