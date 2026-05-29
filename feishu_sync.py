"""
feishu_sync.py —【第二阶段】把每日早报同步进飞书「多维表格(Base)」

作用：让早报内容不仅“发出来”，还“存进飞书”，从而可在飞书里检索、并被飞书「知识问答」
索引，成为第二大脑的素材来源。

⚠️ 完全可选：只有当下面这些环境变量都配置了，本模块才工作；否则自动安静跳过，
不影响第一阶段（早报推送 + GitHub 知识库）。

需要的环境变量（在 GitHub Secrets 配置，详见 docs/FEISHU_SETUP.md）：
  FEISHU_APP_ID            自建应用 App ID
  FEISHU_APP_SECRET        自建应用 App Secret
  FEISHU_BITABLE_APP_TOKEN 多维表格的 app_token（从表格链接中获取）
  FEISHU_BITABLE_TABLE_ID  目标数据表 table_id

多维表格建议字段：标题(文本) / 链接(超链接) / 分类(单选) / 摘要(文本) / 日期(日期)
"""

import os
import time
import requests

BASE = "https://open.feishu.cn/open-apis"


def _config():
    cfg = {
        "app_id": os.environ.get("FEISHU_APP_ID", "").strip(),
        "app_secret": os.environ.get("FEISHU_APP_SECRET", "").strip(),
        "app_token": os.environ.get("FEISHU_BITABLE_APP_TOKEN", "").strip(),
        "table_id": os.environ.get("FEISHU_BITABLE_TABLE_ID", "").strip(),
    }
    return cfg if all(cfg.values()) else None


def _tenant_token(app_id, app_secret):
    resp = requests.post(
        f"{BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败：{data}")
    return data["tenant_access_token"]


def _batch_create(token, app_token, table_id, records):
    url = f"{BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"records": records},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"写入多维表格失败：{data}")
    return len(records)


def sync_to_feishu(date_iso, categories_data):
    """把当天选中的条目写入飞书多维表格。无配置则跳过。"""
    cfg = _config()
    if not cfg:
        print("  ℹ️ 未配置飞书自建应用，跳过多维表格同步（第二阶段未启用）。")
        return

    # 日期字段用毫秒时间戳
    ts = int(time.mktime(time.strptime(date_iso, "%Y-%m-%d"))) * 1000
    records = []
    for name, items in categories_data:
        for it in items:
            records.append({"fields": {
                "标题": it.get("title", ""),
                "链接": {"text": it.get("title", "")[:40] or "链接", "link": it.get("link", "")},
                "分类": name,
                "摘要": (it.get("summary", "") or "")[:900],
                "来源": it.get("source", ""),
                "日期": ts,
            }})
    if not records:
        return

    token = _tenant_token(cfg["app_id"], cfg["app_secret"])
    # 多维表格批量接口单次最多 500 条
    written = 0
    for i in range(0, len(records), 500):
        written += _batch_create(token, cfg["app_token"], cfg["table_id"], records[i:i + 500])
    print(f"  ☁️ 已同步 {written} 条到飞书多维表格。")
