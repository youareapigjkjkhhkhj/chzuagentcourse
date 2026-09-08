"""
LangChain 1.0 - Checkpointing (检查点持久化)
=========================================

本模块重点讲解：
1. SqliteSaver - SQLite 持久化（LangGraph 提供）
2. 与 InMemorySaver 的区别
3. 跨进程、跨重启的对话持久化
4. 实际应用场景


1. invoke 前：LangGraph 自动调用 checkpointer.get(thread_id="user_123")      
    - 查询数据库，读取该 thread_id 的历史消息
    - 如果是第一次，返回空列表
  2. invoke 中：Agent 处理时会看到完整历史(默认确实会全部读取，)
  state = {
      "messages": [历史消息1, 历史消息2, 新消息]  # 自动合并
  }
  3. invoke 后：LangGraph 自动调用 checkpointer.put(thread_id, state)
    - 将新的完整状态写入数据库
    - 数据库存储：(thread_id, timestamp, messages)
"""

import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here_replace_this":
    raise ValueError("请先设置 GROQ_API_KEY")

model = init_chat_model("groq:llama-3.3-70b-versatile", api_key=GROQ_API_KEY)

@tool
def get_order_status(order_id: str) -> str:
    """查询订单状态"""
    orders = {
        "12345": "已发货，预计明天送达",
        "67890": "配送中，今天下午送达"
    }
    return orders.get(order_id, "订单不存在")


# ============================================================================
# 示例 1：InMemorySaver 的限制（对比）
# ============================================================================
def example_1_inmemory_limitation():
    """
    示例1：InMemorySaver 的限制

    问题：
    - 程序重启后丢失
    - 无法跨进程共享
    - 不适合生产环境
    """
    print("\n" + "="*70)
    print("示例 1：InMemorySaver 的限制")
    print("="*70)

    from langgraph.checkpoint.memory import InMemorySaver

    agent = create_agent(
        model=model,
        tools=[],
        checkpointer=InMemorySaver()
    )

    config = {"configurable": {"thread_id": "user_123"}}

    print("\n第一轮对话：")
    agent.invoke(
        {"messages": [{"role": "user", "content": "我叫张三"}]},
        config=config
    )
    print("用户: 我叫张三")

    print("\n第二轮对话（同一进程内）：")
    response = agent.invoke(
        {"messages": [{"role": "user", "content": "我叫什么？"}]},
        config=config
    )
    print(f"Agent: {response['messages'][-1].content}")

    print("\n限制：")
    print("  ❌ 程序重启后，对话历史丢失")
    print("  ❌ 无法在不同进程间共享")
    print("  ❌ 不适合生产环境")
    print("\n解决方案：使用 SqliteSaver 持久化到数据库")


# ============================================================================
# 示例 2：使用 SqliteSaver 持久化
# ============================================================================
def example_2_sqlite_saver():
    """
    示例2：使用 SqliteSaver 实现持久化

    关键：
    1. SqliteSaver.from_conn_string("sqlite:///path/to/db.sqlite")
    2. 对话持久化到 SQLite 文件
    3. 程序重启后仍可恢复
    """
    print("\n" + "="*70)
    print("示例 2：SqliteSaver - 持久化到 SQLite")
    print("="*70)

    # 创建持久化的 checkpointer（使用 with 语句）
    db_path = "checkpoints.sqlite"  # 相对路径

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        agent = create_agent(
            model=model,
            tools=[],
            checkpointer=checkpointer  # 使用 SQLite 持久化
        )

        config = {"configurable": {"thread_id": "persistent_session"}}

        print("\n第一轮对话：")
        print("用户: 我叫李四")
        agent.invoke(
            {"messages": [{"role": "user", "content": "我叫李四"}]},
            config=config
        )

        print("\n第二轮对话：")
        print("用户: 我叫什么？")
        response = agent.invoke(
            {"messages": [{"role": "user", "content": "我叫什么？"}]},
            config=config
        )
        print(f"Agent: {response['messages'][-1].content}")

        print(f"\n关键点：")
        print(f"  ✅ 对话保存到文件：{db_path}")
        print("  ✅ 程序重启后仍可恢复")
        print("  ✅ 可以跨进程访问")
        print("  ✅ 适合生产环境")


# ============================================================================
# 示例 3：验证跨进程持久化
# ============================================================================
def example_3_verify_persistence():
    """
    示例3：验证持久化效果

    模拟程序重启后，从数据库恢复对话
    """
    print("\n" + "="*70)
    print("示例 3：验证持久化（模拟重启后恢复）")
    print("="*70)

    db_path = "checkpoints.sqlite"

    # 模拟"重新启动"：创建新的 agent 和 checkpointer
    print("\n[模拟程序重启...]")

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        agent = create_agent(
            model=model,
            tools=[],
            checkpointer=checkpointer
        )

        # 使用相同的 thread_id
        config = {"configurable": {"thread_id": "persistent_session"}}

        print("\n第三轮对话（新进程，但 thread_id 相同）：")
        print("用户: 我之前说我叫什么？")
        response = agent.invoke(
            {"messages": [{"role": "user", "content": "我之前说我叫什么？"}]},
            config=config
        )
        print(f"Agent: {response['messages'][-1].content}")

        print("\n关键点：")
        print("  - Agent 记得之前的对话（李四）")
        print("  - 即使创建了新的 agent 实例")
        print("  - 因为 SQLite 保存了完整历史")


# ============================================================================
# 示例 4：多用户会话管理
# ============================================================================
def example_4_multi_user_sessions():
    """
    示例4：管理多个用户的持久化会话

    每个用户有独立的 thread_id
    """
    print("\n" + "="*70)
    print("示例 4：多用户会话管理")
    print("="*70)

    db_path = "multi_user.sqlite"

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        agent = create_agent(
            model=model,
            tools=[],
            checkpointer=checkpointer
        )

        # 用户 A
        print("\n[用户 A 的对话]")
        config_a = {"configurable": {"thread_id": "user_alice"}}
        agent.invoke(
            {"messages": [{"role": "user", "content": "我是 Alice，我喜欢编程"}]},
            config_a
        )
        print("Alice: 我是 Alice，我喜欢编程")

        # 用户 B
        print("\n[用户 B 的对话]")
        config_b = {"configurable": {"thread_id": "user_bob"}}
        agent.invoke(
            {"messages": [{"role": "user", "content": "我是 Bob，我喜欢设计"}]},
            config_b
        )
        print("Bob: 我是 Bob，我喜欢设计")

        # 回到用户 A
        print("\n[用户 A 继续对话]")
        response_a = agent.invoke(
            {"messages": [{"role": "user", "content": "我喜欢什么？"}]},
            config_a
        )
        print(f"Alice: 我喜欢什么？")
        print(f"Agent: {response_a['messages'][-1].content}")

        # 回到用户 B
        print("\n[用户 B 继续对话]")
        response_b = agent.invoke(
            {"messages": [{"role": "user", "content": "我喜欢什么？"}]},
            config_b
        )
        print(f"Bob: 我喜欢什么？")
        print(f"Agent: {response_b['messages'][-1].content}")

        print(f"\n关键点：")
        print("  - 不同 thread_id 的会话独立存储")
        print("  - 所有会话持久化在同一数据库")
        print(f"  - 数据库文件：{db_path}")


# ============================================================================
# 示例 5：带工具的持久化 Agent
# ============================================================================
def example_5_tools_with_persistence():
    """
    示例5：工具调用 + 持久化

    Agent 记住工具调用历史
    """
    print("\n" + "="*70)
    print("示例 5：工具调用 + 持久化")
    print("="*70)

    db_path = "tools.sqlite"

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        agent = create_agent(
            model=model,
            tools=[get_order_status],
            checkpointer=checkpointer
        )

        config = {"configurable": {"thread_id": "customer_001"}}

        print("\n第一轮：查询订单")
        print("客户: 查询订单 12345 的状态")
        response1 = agent.invoke(
            {"messages": [{"role": "user", "content": "查询订单 12345 的状态"}]},
            config=config
        )
        print(f"Agent: {response1['messages'][-1].content}")

        print("\n第二轮：询问之前的查询结果")
        print("客户: 我的订单什么时候到？")
        response2 = agent.invoke(
            {"messages": [{"role": "user", "content": "我的订单什么时候到？"}]},
            config=config
        )
        print(f"Agent: {response2['messages'][-1].content}")

        print("\n关键点：")
        print("  - Agent 记住了订单 12345 的查询结果")
        print("  - 工具调用历史也被持久化")
        print("  - 无需重复调用工具")


# ============================================================================
# 示例 6：实际应用 - 客服系统
# ============================================================================
def example_6_customer_service():
    """
    示例6：实际应用 - 持久化客服系统

    场景：客户可能分多次咨询，需要记住历史
    """
    print("\n" + "="*70)
    print("示例 6：实际应用 - 持久化客服系统")
    print("="*70)

    db_path = "customer_service.sqlite"

    with SqliteSaver.from_conn_string(db_path) as checkpointer:
        agent = create_agent(
            model=model,
            tools=[get_order_status],
            system_prompt="""你是客服助手。
特点：
- 记住客户之前的咨询
- 友好、耐心
- 使用工具查询订单""",
            checkpointer=checkpointer
        )

        customer_id = "customer_zhang"
        config = {"configurable": {"thread_id": customer_id}}

        print("\n第一次咨询（今天上午）：")
        conversations_morning = [
            "你好，我想查询订单",
            "订单号是 12345"
        ]

        for msg in conversations_morning:
            print(f"\n客户: {msg}")
            response = agent.invoke(
                {"messages": [{"role": "user", "content": msg}]},
                config=config
            )
            print(f"客服: {response['messages'][-1].content}")

        print("\n" + "-"*70)
        print("[几个小时后...]")
        print("-"*70)

        print("\n第二次咨询（今天下午）：")
        print("\n客户: 我的订单到哪了？")
        response = agent.invoke(
            {"messages": [{"role": "user", "content": "我的订单到哪了？"}]},
            config=config
        )
        print(f"客服: {response['messages'][-1].content}")

        print("\n关键点：")
        print("  - 客户无需重复订单号")
        print("  - 系统记住了上午的咨询")
        print("  - 即使客服系统重启也不影响")
        print("  - 生产级应用的标准做法")


# ============================================================================
# 示例 7：SqliteSaver 参数说明
# ============================================================================
def example_7_sqlite_parameters():
    """
    示例7：SqliteSaver 参数和最佳实践
    """
    print("\n" + "="*70)
    print("示例 7：SqliteSaver 参数详解")
    print("="*70)

    print("""
SqliteSaver 创建方式：

1. from_conn_string + with 语句（推荐）
   with SqliteSaver.from_conn_string("checkpoints.sqlite") as checkpointer:
       agent = create_agent(model=model, checkpointer=checkpointer)
       agent.invoke(...)

   - 自动管理连接和资源
   - 支持相对路径和绝对路径
   - 最简单安全的方式
   - 确保正确释放数据库连接
   - 注意：直接传文件路径，不要加 sqlite:/// 前缀

2. 使用 sqlite3.connect（高级）
   import sqlite3
   conn = sqlite3.connect("checkpoints.sqlite")
   checkpointer = SqliteSaver(conn)

   - 需要手动管理连接
   - 适合需要自定义连接参数的场景

数据库文件路径：
- 相对路径：checkpoints.sqlite（当前目录）
- 绝对路径：C:/Users/xxx/data/checkpoints.sqlite（Windows）
- 内存数据库：:memory:（测试用，程序退出即丢失）

最佳实践：
✅ 始终使用 with 语句管理 SqliteSaver
✅ 直接传文件路径，不要加 sqlite:/// 前缀
✅ 生产环境：使用绝对路径
✅ 开发测试：使用相对路径
✅ 单元测试：使用 :memory:
✅ 定期备份数据库文件
    """)


# ============================================================================
# 主程序
# ============================================================================
def main():
    print("\n" + "="*70)
    print(" LangChain 1.0 - Checkpointing (持久化)")
    print("="*70)

    try:
        example_1_inmemory_limitation()
        input("\n按 Enter 继续...")

        example_2_sqlite_saver()
        input("\n按 Enter 继续...")

        example_3_verify_persistence()
        input("\n按 Enter 继续...")

        example_4_multi_user_sessions()
        input("\n按 Enter 继续...")

        example_5_tools_with_persistence()
        input("\n按 Enter 继续...")

        example_6_customer_service()
        input("\n按 Enter 继续...")

        example_7_sqlite_parameters()

        print("\n" + "="*70)
        print(" 完成！")
        print("="*70)
        print("\n核心要点：")
        print("  SqliteSaver.from_conn_string() - 创建持久化 checkpointer")
        print("  sqlite:///path/to/db.sqlite - 数据库路径")
        print("  程序重启、跨进程访问都不影响")
        print("  适合生产环境")
        print("\n下一步：")
        print("  10_middleware_basics - 自定义中间件")

    except KeyboardInterrupt:
        print("\n\n程序中断")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
