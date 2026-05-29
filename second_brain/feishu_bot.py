"""
feishu_bot.py —【第二阶段】把第二大脑接入飞书（长连接模式）

用飞书官方 SDK `lark-oapi` 的 WebSocket 长连接：你的 Mac mini 在家、没有公网 IP 也能收消息。
你在飞书里给应用发消息 / @它，它就用 brain.py 的知识库 + 记忆 + DeepSeek 回答你。

运行前提（详见 second_brain/README.md 与 docs/FEISHU_SETUP.md）：
  1. 已创建飞书自建应用，拿到 App ID / App Secret；
  2. 开启「机器人」能力，并在「事件订阅」里用「长连接」模式，订阅 im.message.receive_v1；
  3. 申请权限：im:message、im:message:send_as_bot；
  4. 设置环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET / OPENAI_API_KEY（DeepSeek Key）。

启动：python second_brain/feishu_bot.py
"""

import os
import json

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from brain import Brain

APP_ID = os.environ["FEISHU_APP_ID"]
APP_SECRET = os.environ["FEISHU_APP_SECRET"]

brain = Brain()
api = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()


def _extract_text(message):
    """从消息体里取出纯文本（兼容 text / post，并去掉 @机器人 的部分）。"""
    try:
        content = json.loads(message.content)
    except Exception:
        return ""
    if message.message_type == "text":
        return content.get("text", "").replace("@_user_1", "").strip()
    # 富文本 post 简单兜底
    return content.get("text", "").strip()


def on_message(data: P2ImMessageReceiveV1):
    msg = data.event.message
    question = _extract_text(msg)
    if not question:
        return
    print(f"💬 收到：{question}")
    answer = brain.answer(question)

    req = (ReplyMessageRequest.builder()
           .message_id(msg.message_id)
           .request_body(ReplyMessageRequestBody.builder()
                         .content(json.dumps({"text": answer}))
                         .msg_type("text")
                         .build())
           .build())
    resp = api.im.v1.message.reply(req)
    if not resp.success():
        print(f"⚠️ 回复失败：{resp.code} {resp.msg}")


def main():
    handler = (lark.EventDispatcherHandler.builder("", "")
               .register_p2_im_message_receive_v1(on_message)
               .build())
    ws = lark.ws.Client(APP_ID, APP_SECRET, event_handler=handler,
                        log_level=lark.LogLevel.INFO)
    print("🚀 第二大脑已接入飞书（长连接）。去飞书里给应用发消息试试！")
    ws.start()


if __name__ == "__main__":
    main()
