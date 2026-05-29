"""
webapp.py —【第二阶段】第二大脑「网页版」聊天界面

最低门槛体验：不用先配飞书应用，在 Mac mini 上跑起来后，用浏览器就能和你的第二大脑对话。
同一局域网内（手机/平板）也能访问。

运行：
  pip3 install -r second_brain/requirements.txt
  set -a; source second_brain/.env; set +a      # 至少需要 DeepSeek Key
  python3 second_brain/webapp.py
然后浏览器打开终端里提示的地址（默认 http://本机IP:7860）。
"""

import gradio as gr
from brain import Brain

brain = Brain()


def chat(message, history):
    return brain.answer(message)


def main():
    gr.ChatInterface(
        fn=chat,
        title="🧠 我的第二大脑",
        description="基于你的每日科技早报知识库 + 长期记忆 + DeepSeek-V4-Pro。问它任何关于你看过的 AI/计算机/数学前沿的问题。",
        examples=[
            "最近有什么关于扩散模型的论文？",
            "用通俗的话讲讲我看过的强化学习相关内容",
            "我最近关注的方向能怎么用到毕业设计？",
        ],
        theme="soft",
    ).launch(server_name="0.0.0.0", server_port=7860, show_api=False)


if __name__ == "__main__":
    main()
