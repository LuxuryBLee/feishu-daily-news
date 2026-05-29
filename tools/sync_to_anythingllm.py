"""
sync_to_anythingllm.py — 把 GitHub 知识库档案自动同步进 AnythingLLM 桌面应用

用途：你在 Mac 上装了 AnythingLLM 后，运行本脚本，会把 knowledge_base/archive 里
每天新增的 Markdown 档案上传并嵌入到你指定的 AnythingLLM 工作区（Workspace），
这样你的「第二大脑」就能随每日早报自动长知识。已上传过的文件不会重复上传。

环境变量（在 Mac 上设置）：
  ANYTHINGLLM_URL        AnythingLLM 地址，默认 http://localhost:3001
  ANYTHINGLLM_API_KEY    在 AnythingLLM「设置 → 工具 → Developer API」生成的 Key（必填）
  ANYTHINGLLM_WORKSPACE  目标工作区的 slug（在工作区设置里看，或用 --list 列出）

用法：
  python3 tools/sync_to_anythingllm.py            # 同步新档案
  python3 tools/sync_to_anythingllm.py --list     # 列出你的工作区(slug)
  python3 tools/sync_to_anythingllm.py --all       # 强制重新同步全部档案
"""

import os
import sys
import json
import glob

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE_GLOB = os.path.join(ROOT, "knowledge_base", "archive", "**", "*.md")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".anythingllm_synced.json")

BASE = os.environ.get("ANYTHINGLLM_URL", "http://localhost:3001").rstrip("/")
API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "").strip()
WORKSPACE = os.environ.get("ANYTHINGLLM_WORKSPACE", "").strip()


def _headers():
    return {"Authorization": f"Bearer {API_KEY}"}


def _check_connection():
    r = requests.get(f"{BASE}/api/v1/workspaces", headers=_headers(), timeout=15)
    r.raise_for_status()


def list_workspaces():
    r = requests.get(f"{BASE}/api/v1/workspaces", headers=_headers(), timeout=15)
    r.raise_for_status()
    for w in r.json().get("workspaces", []):
        print(f"  - 名称: {w.get('name')}  |  slug: {w.get('slug')}")


def _load_state():
    if os.path.exists(STATE_FILE):
        try:
            return set(json.load(open(STATE_FILE)))
        except Exception:
            return set()
    return set()


def _save_state(done):
    json.dump(sorted(done), open(STATE_FILE, "w"), ensure_ascii=False, indent=2)


def upload(path):
    with open(path, "rb") as f:
        files = {"file": (os.path.basename(path), f, "text/markdown")}
        data = {"addToWorkspaces": WORKSPACE}
        r = requests.post(f"{BASE}/api/v1/document/upload",
                          headers=_headers(), files=files, data=data, timeout=120)
    r.raise_for_status()
    return r.json()


def _friendly(fn):
    try:
        return fn()
    except requests.exceptions.ConnectionError:
        sys.exit(f"❌ 连不上 AnythingLLM（{BASE}）。请确认：①AnythingLLM 应用已打开；"
                 f"②地址/端口正确（默认 http://localhost:3001）。")
    except requests.exceptions.HTTPError as e:
        sys.exit(f"❌ AnythingLLM 接口返回错误：{e}。请检查 API Key 是否正确。")


def main():
    if "--list" in sys.argv:
        if not API_KEY:
            sys.exit("❌ 请先设置 ANYTHINGLLM_API_KEY")
        _friendly(list_workspaces)
        return

    if not API_KEY or not WORKSPACE:
        sys.exit("❌ 请先设置 ANYTHINGLLM_API_KEY 和 ANYTHINGLLM_WORKSPACE（用 --list 查看 slug）")

    files = sorted(glob.glob(ARCHIVE_GLOB, recursive=True))
    if not files:
        print("ℹ️ 暂无档案可同步（先让早报机器人跑几天）。")
        return

    done = set() if "--all" in sys.argv else _load_state()
    todo = [f for f in files if f not in done]
    if not todo:
        print(f"✅ 已是最新，无新档案需要同步（共 {len(files)} 个）。")
        return

    # 先做一次连通性/鉴权检查，给出友好提示而不是一堆报错
    _friendly(_check_connection)
    print(f"📤 准备同步 {len(todo)} 个新档案到工作区「{WORKSPACE}」…")
    ok = 0
    for f in todo:
        try:
            upload(f)
            done.add(f)
            ok += 1
            print(f"  ✅ {os.path.relpath(f, ROOT)}")
        except Exception as e:
            print(f"  ⚠️ 失败 {os.path.relpath(f, ROOT)}: {e}")
    _save_state(done)
    print(f"🎉 完成：本次成功同步 {ok}/{len(todo)} 个档案。")


if __name__ == "__main__":
    main()
