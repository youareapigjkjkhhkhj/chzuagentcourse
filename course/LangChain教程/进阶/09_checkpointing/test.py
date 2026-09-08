"""
简单测试：验证 SQLite 持久化功能
"""

import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here_replace_this":
    raise ValueError("请先设置 GROQ_API_KEY")

model = init_chat_model("groq:llama-3.3-70b-versatile", api_key=GROQ_API_KEY)

print("=" * 70)
print("测试：SqliteSaver 持久化功能")
print("=" * 70)

# 创建持久化 checkpointer（直接使用文件名，无需 sqlite:/// 前缀）
db_path = "test_checkpoints.sqlite"

# 使用 with 语句正确管理 SqliteSaver
with SqliteSaver.from_conn_string(db_path) as checkpointer:  # 直接传文件名
    # 创建 Agent
    agent = create_agent(
        model=model,
        tools=[],
        checkpointer=checkpointer
    )

    config = {"configurable": {"thread_id": "test_persistence"}}

    print("\n第一轮对话：")
    print("用户: 我叫王五")
    response1 = agent.invoke(
        {"messages": [{"role": "user", "content": "我叫王五"}]},
        config=config
    )
    print(f"Agent: {response1['messages'][-1].content}")

print("\n第二轮对话（模拟重启）：")
print("[创建新的 agent 实例...]")

# 模拟重启：创建新的 checkpointer 和 agent
with SqliteSaver.from_conn_string(db_path) as checkpointer_new:  # 直接传文件名
    agent_new = create_agent(
        model=model,
        tools=[],
        checkpointer=checkpointer_new
    )

    print("用户: 我叫什么？")
    response2 = agent_new.invoke(
        {"messages": [{"role": "user", "content": "我叫什么？"}]},
        config=config
    )
    print(f"Agent: {response2['messages'][-1].content}")

    print("\n" + "=" * 70)
    print("持久化状态：")
    print(f"  数据库文件: {db_path}")
    print(f"  thread_id: {config['configurable']['thread_id']}")
    print(f"  总消息数: {len(response2['messages'])}")
    print("=" * 70)

    if "王五" in response2['messages'][-1].content:
        print("\n[成功] 测试成功！Agent 记住了名字（持久化有效）。")
    else:
        print("\n[警告] Agent 可能没有正确记住")

print("\n测试完成！")
