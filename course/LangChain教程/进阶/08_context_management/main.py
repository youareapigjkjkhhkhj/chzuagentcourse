"""
LangChain 1.0 - Context Management (上下文管理)
==============================================

本模块重点讲解：
1. SummarizationMiddleware - 自动摘要中间件（LangChain 1.0 新增）
2. trim_messages - 消息修剪工具
3. 管理对话长度，避免超 token
4. 中间件的使用
"""

import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents.middleware import SummarizationMiddleware

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here_replace_this":
    raise ValueError("请先设置 GROQ_API_KEY")

model = init_chat_model("groq:llama-3.3-70b-versatile", api_key=GROQ_API_KEY)

@tool
def calculator(operation: str, a: float, b: float) -> str:
    """执行数学计算"""
    ops = {
        "add": lambda x, y: x + y,
        "multiply": lambda x, y: x * y,
    }
    result = ops.get(operation, lambda x, y: 0)(a, b)
    return f"{a} {operation} {b} = {result}"


# ============================================================================
# 示例 1：问题演示 - 对话历史无限增长
# ============================================================================
def example_1_problem_unlimited_growth():
    """
    示例1：问题演示 - 对话历史会无限增长

    问题：
    - 消息越来越多
    - 超过模型 token 限制
    - 成本增加、响应变慢
    """
    print("\n" + "="*70)
    print("示例 1：问题演示 - 对话历史无限增长")
    print("="*70)

    agent = create_agent(
        model=model,
        tools=[],
        checkpointer=InMemorySaver()
    )

    config = {"configurable": {"thread_id": "long_conversation"}}

    # 模拟多轮对话
    print("\n模拟 10 轮对话...")
    for i in range(1, 11):
        agent.invoke(
            {"messages": [{"role": "user", "content": f"这是第 {i} 轮对话"}]},
            config=config
        )

    # 查看消息数量
    response = agent.invoke(
        {"messages": [{"role": "user", "content": "总结一下"}]},
        config=config
    )

    print(f"\n总消息数: {len(response['messages'])}")
    print("(包含用户消息 + AI 回复)")

    print("\n问题：")
    print("  - 消息越来越多，内存占用增加")
    print("  - 超过模型 token 限制会报错")
    print("  - 每次调用都要传输全部历史，成本增加")


# ============================================================================
# 示例 2：解决方案 1 - SummarizationMiddleware（推荐）
# ============================================================================
def example_2_summarization_middleware():
    """
    示例2：使用 SummarizationMiddleware 自动摘要

    关键：LangChain 1.0 新增的中间件
    当消息数超过阈值时，自动摘要旧消息
    """
    print("\n" + "="*70)
    print("示例 2：SummarizationMiddleware - 自动摘要")
    print("="*70)

    # 创建带摘要中间件的 Agent
    agent = create_agent(
        model=model,
        tools=[],
        checkpointer=InMemorySaver(),
        middleware=[
            SummarizationMiddleware(
                model="groq:llama-3.3-70b-versatile",
                max_tokens_before_summary=500  # 超过 500 tokens 就摘要
            )
        ]
    )

    config = {"configurable": {"thread_id": "with_summary"}}

    print("\n进行多轮对话...")
    conversations = [
        "我叫张三，是工程师",
        "我在北京工作",
        "我喜欢编程和阅读",
        "我最近在学习 AI",
        "请总结一下我的信息"
    ]

    for msg in conversations:
        print(f"\n用户: {msg}")
        response = agent.invoke(
            {"messages": [{"role": "user", "content": msg}]},
            config=config
        )
        print(f"Agent: {response['messages'][-1].content[:100]}...")

    print(f"\n消息数: {len(response['messages'])}")
    print("\n关键点：")
    print("  - SummarizationMiddleware 会自动摘要旧消息")
    print("  - 保持对话历史在可控范围内")
    print("  - 重要信息通过摘要保留")


# ============================================================================
# 示例 3：理解 SummarizationMiddleware 参数
# ============================================================================
def example_3_middleware_parameters():
    """
    示例3：SummarizationMiddleware 参数详解
    """
    print("\n" + "="*70)
    print("示例 3：Summarization 参数详解")
    print("="*70)

    print("""
SummarizationMiddleware 参数：

1. model (必需)
   - 用于生成摘要的模型
   - 可以用便宜的模型（如 gpt-3.5）降低成本

2. max_tokens_before_summary
   - 触发摘要的 token 数阈值
   - 默认: 1000
   - 建议：根据模型上下文窗口设置（如 4k 模型设为 3000）

3. summarization_prompt (可选)
   - 自定义摘要提示词
   - 默认：简洁摘要对话历史

示例：
```python
agent = create_agent(
    model=model,
    tools=[],
    middleware=[
        SummarizationMiddleware(
            model="groq:llama-3.3-70b-versatile",  # 摘要模型
            max_tokens_before_summary=500,         # 500 tokens 触发
        )
    ],
    checkpointer=InMemorySaver()
)
```
    """)


# ============================================================================
# 示例 4：手动消息修剪（trim_messages）
# ============================================================================
def example_4_manual_trimming():
    """
    示例4：使用 trim_messages 手动修剪消息

    适用场景：需要精确控制保留的消息数量
    """
    print("\n" + "="*70)
    print("示例 4：手动消息修剪")
    print("="*70)

    from langchain_core.messages import trim_messages

    # 模拟一个长对话历史
    from langchain_core.messages import HumanMessage, AIMessage

    messages = [
        HumanMessage(content="消息 1"),
        AIMessage(content="回复 1"),
        HumanMessage(content="消息 2"),
        AIMessage(content="回复 2"),
        HumanMessage(content="消息 3"),
        AIMessage(content="回复 3"),
        HumanMessage(content="消息 4"),
        AIMessage(content="回复 4"),
    ]

    print(f"\n原始消息数: {len(messages)}")

    # 只保留最近 4 条消息 
    # 按 token 数裁剪（不严格条数）	max_tokens=N + 合理 token_counter
    # 严格保留最后 N 条消息	max_count=N

    trimmed = trim_messages(
        messages,
        max_count=5,  # 严格保留最后 5 条消息
        # max_tokens=100,  # 或使用 token 数限制
        strategy="last",  # 保留最后的消息
        token_counter=len  # 简单计数器（实际应该用 token 计数）这里其实不会被用到，因为 max_count 优先
    )

    print(f"修剪后消息数: {len(trimmed)}")
    print("\n保留的消息：")
    for msg in trimmed:
        print(f"  {msg.__class__.__name__}: {msg.content}")

    print("\n关键点：")
    print("  - trim_messages 手动控制消息数量")
    print("  - 适合需要精确控制的场景")
    print("  - 需要自己管理修剪逻辑")


# ============================================================================
# 示例 5：对比不同策略
# ============================================================================
def example_5_comparison():
    """
    示例5：对比不同的上下文管理策略
    """
    print("\n" + "="*70)
    print("示例 5：策略对比")
    print("="*70)

    print("""
策略对比：

1. 不做处理（默认）
   优点：保留完整历史
   缺点：会超 token、成本高
   适用：短对话

2. SummarizationMiddleware（推荐）
   优点：
   - 自动化，无需手动管理
   - 保留重要信息（通过摘要）
   - 平滑过渡
   缺点：
   - 摘要可能丢失细节
   - 额外的摘要成本
   适用：长对话、需要保留上下文

3. trim_messages（手动修剪）
   优点：
   - 精确控制
   - 简单直接
   - 无额外成本
   缺点：
   - 旧消息完全丢失
   - 可能断开上下文
   适用：只需要最近 N 轮

4. 滑动窗口（自定义）
   优点：
   - 保留系统消息 + 最近消息
   - 可控成本
   缺点：
   - 需要自己实现
   适用：有明确规则的场景

推荐方案：
- 短对话（<10轮）：不处理
- 中长对话：SummarizationMiddleware
- 只要最近几轮：trim_messages
    """)


# ============================================================================
# 示例 6：实际应用 - 客服机器人
# ============================================================================
def example_6_practical_customer_service():
    """
    示例6：实际应用 - 客服机器人

    场景：客服对话可能很长，需要管理上下文
    """
    print("\n" + "="*70)
    print("示例 6：实际应用 - 客服机器人")
    print("="*70)

    # 创建客服 Agent
    agent = create_agent(
        model=model,
        tools=[calculator],
        system_prompt="""你是客服助手。
特点：
- 记住用户问题
- 简洁回答
- 使用工具计算""",
        checkpointer=InMemorySaver(),
        middleware=[
            SummarizationMiddleware(
                model="groq:llama-3.3-70b-versatile",
                max_tokens_before_summary=800  # 适合客服场景
            )
        ]
    )

    config = {"configurable": {"thread_id": "customer_123"}}

    # 模拟客服对话
    conversations = [
        "你好，我想咨询订单",
        "我的订单号是 12345",
        "帮我算一下 100 乘以 2 的优惠价",
        "谢谢"
    ]

    for msg in conversations:
        print(f"\n客户: {msg}")
        response = agent.invoke(
            {"messages": [{"role": "user", "content": msg}]},
            config=config
        )
        print(f"客服: {response['messages'][-1].content}")

    print(f"\n总消息数: {len(response['messages'])}")
    print("\n关键点：")
    print("  - 自动管理对话长度")
    print("  - 重要信息（订单号）通过摘要保留")
    print("  - 适合生产环境")


# ============================================================================
# ��程序
# ============================================================================
def main():
    print("\n" + "="*70)
    print(" LangChain 1.0 - Context Management")
    print("="*70)

    try:
        example_1_problem_unlimited_growth()
        input("\n按 Enter 继续...")

        example_2_summarization_middleware()
        input("\n按 Enter 继续...")

        example_3_middleware_parameters()
        input("\n按 Enter 继续...")

        example_4_manual_trimming()
        input("\n按 Enter 继续...")

        example_5_comparison()
        input("\n按 Enter 继续...")

        example_6_practical_customer_service()

        print("\n" + "="*70)
        print(" 完成！")
        print("="*70)
        print("\n核心要点：")
        print("  SummarizationMiddleware - 自动摘要（推荐）")
        print("  trim_messages - 手动修剪")
        print("  max_tokens_before_summary - 触发阈值")
        print("  middleware 在 create_agent 中配置")
        print("\n下一步：")
        print("  09_checkpointing - 持久化对话状态")

    except KeyboardInterrupt:
        print("\n\n程序中断")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
