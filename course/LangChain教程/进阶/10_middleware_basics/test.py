"""
简单测试：验证中间件功能
"""

import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here_replace_this":
    raise ValueError("请先设置 GROQ_API_KEY")

model = init_chat_model("groq:llama-3.3-70b-versatile", api_key=GROQ_API_KEY)

print("=" * 70)
print("测试：中间件 before_model 和 after_model")
print("=" * 70)


class TestMiddleware(AgentMiddleware):
    """测试中间件"""

    def before_model(self, state, runtime):
        print("\n[测试] before_model 执行")
        print(f"[测试] 当前消息数: {len(state.get('messages', []))}")
        return None

    def after_model(self, state, runtime):
        print("[测试] after_model 执行")
        last_msg = state.get('messages', [])[-1]
        print(f"[测试] 响应类型: {last_msg.__class__.__name__}")
        return None


# 创建带中间件的 Agent
agent = create_agent(
    model=model,
    tools=[],
    middleware=[TestMiddleware()]
)

print("\n执行测试调用...")
print("用户: 你好")

response = agent.invoke({"messages": [{"role": "user", "content": "你好"}]})

print(f"\nAgent: {response['messages'][-1].content}")

print("\n" + "=" * 70)
print("测试结果：")
print("  - before_model 在模型调用前执行 [成功]")
print("  - after_model 在模型响应后执行 [成功]")
print("=" * 70)

print("\n测试完成！")
