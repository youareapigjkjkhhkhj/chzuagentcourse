"""
演示：对话历史过长的问题
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


def demo_long_conversation():
    """
    演示：对话历史过长的问题
    """
    print("\n" + "="*70)
    print(" 演示：对话历史过长的性能问题")
    print("="*70)

    db_path = "long_conversation.sqlite"

    with SqliteSaver.from_conn_string(f"sqlite:///{db_path}") as checkpointer:
        agent = create_agent(
            model=model,
            tools=[],
            checkpointer=checkpointer
        )

        config = {"configurable": {"thread_id": "test_user"}}

        # 模拟 50 轮对话
        print("\n[模拟 50 轮对话...]")
        for i in range(1, 51):
            agent.invoke(
                {"messages": [{"role": "user", "content": f"这是第 {i} 条消息"}]},
                config=config
            )
            if i % 10 == 0:
                print(f"  已完成 {i} 轮...")

        print("\n[尝试获取状态，查看加载的消息数量...]")

        # 获取当前状态
        state = checkpointer.get(config)
        if state and state.values:
            messages = state.values.get("messages", [])
            print(f"\n⚠️ 当前加载的消息数量：{len(messages)}")
            print(f"⚠️ 这意味着每次 invoke 都会加载这么多消息！")

            # 计算大致的 Token 数（简化估算）
            total_chars = sum(len(str(msg)) for msg in messages)
            estimated_tokens = total_chars // 4  # 粗略估算
            print(f"⚠️ 估算 Token 数：~{estimated_tokens}")

            print("\n问题：")
            print("  1. 随着对话增长，每次加载的数据越来越多")
            print("  2. 超过模型上下文窗口限制会报错")
            print("  3. 性能下降，响应变慢")
            print("  4. Token 费用增加")

    # 清理
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"\n[已清理测试数据库]")


def show_solutions():
    """
    展示解决方案
    """
    print("\n" + "="*70)
    print(" 解决方案")
    print("="*70)

    print("""
LangChain 提供了多种策略来管理上下文：

1. 消息修剪（Message Trimming）⭐ 推荐
   - 只保留最近 N 条消息
   - 保留系统消息 + 最近对话

2. 消息摘要（Summarization）
   - 定期总结旧消息
   - 用摘要替换历史

3. 滑动窗口（Sliding Window）
   - 固定窗口大小
   - 自动丢弃旧消息

4. Token 限制
   - 根据 Token 数量裁剪
   - 适配不同模型的上下文窗口

这些策略在 phase2_practical/08_context_management 模块中详细讲解！
    """)


if __name__ == "__main__":
    try:
        demo_long_conversation()
        show_solutions()

        print("\n" + "="*70)
        print(" 下一步")
        print("="*70)
        print("\n查看详细解决方案：")
        print("  cd phase2_practical/08_context_management")
        print("  python main.py")

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
