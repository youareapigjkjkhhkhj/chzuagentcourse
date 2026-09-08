"""
简单测试：验证 Agent 可以正常工作
"""

import os
import sys

# 添加工具目录到路径
parent_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(parent_dir, '04_custom_tools', 'tools'))

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from weather import get_weather
from calculator import calculator

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here_replace_this":
    raise ValueError("请先设置 GROQ_API_KEY")

model = init_chat_model("groq:llama-3.3-70b-versatile", api_key=GROQ_API_KEY)

print("创建 Agent...")
agent = create_agent(
    model=model,
    tools=[get_weather, calculator],
    system_prompt="你是一个helpful assistant。"
)

print("\n测试1：天气查询")
response1 = agent.invoke({
    "messages": [{"role": "user", "content": "北京天气如何？"}]
})
print(f"回答：{response1['messages'][-1].content}\n")

print("测试2：计算")
response2 = agent.invoke({
    "messages": [{"role": "user", "content": "10 加 20 等于多少？"}]
})
print(f"回答：{response2['messages'][-1].content}\n")

print("测试成功！Agent 可以正常调用工具。")
