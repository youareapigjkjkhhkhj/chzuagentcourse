"""
LangChain 1.0 - Simple Agent (使用 create_agent)
=============================================

本模块重点讲解：
1. 使用 create_agent 创建 Agent（LangChain 1.0 统一API）
2. Agent 自动决定何时使用工具
3. Agent 执行循环的工作原理
"""

import os
import sys

# 添加父目录到路径以导入工具
parent_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(parent_dir, '04_custom_tools', 'tools'))

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent  # LangChain 1.0 统一 API

# 导入自定义工具
from weather import get_weather
from calculator import calculator
from web_search import web_search

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here_replace_this":
    raise ValueError("请先设置 GROQ_API_KEY")

model = init_chat_model("groq:llama-3.3-70b-versatile", api_key=GROQ_API_KEY)


# ============================================================================
# 示例 1：创建第一个 Agent
# ============================================================================
def example_1_basic_agent():
    """
    示例1：创建最简单的 Agent

    关键：
    1. 使用 create_agent 函数
    2. 传入 model 和 tools
    3. Agent 会自动决定是否使用工具
    """
    print("\n" + "="*70)
    print("示例 1：创建第一个 Agent")
    print("="*70)

    # 创建 Agent
    agent = create_agent(
        model=model,
        tools=[get_weather]  # 只给一个工具
    )

    print("\nAgent 创建成功！")
    print("配置的工具：get_weather")

    # 测试：需要工具的问题
    print("\n测试1：询问天气（需要工具）")
    response = agent.invoke({
        "messages": [{"role": "user", "content": "北京今天天气怎么样？"}]
    })

    print(f"\nAgent 回复：{response['messages'][-1].content}")

    # 测试：不需要工具的问题
    print("\n测试2：普通问题（不需要工具）")
    response = agent.invoke({
        "messages": [{"role": "user", "content": "你好，介绍一下你自己"}]
    })

    print(f"\nAgent 回复：{response['messages'][-1].content}")

    print("\n关键点：")
    print("  - Agent 自动判断是否需要使用工具")
    print("  - 需要工具时：调用工具 → 获取结果 → 生成回答")
    print("  - 不需要时：直接回答")


# ============================================================================
# 示例 2：多工具 Agent
# ============================================================================
def example_2_multi_tool_agent():
    """
    示例2：配置多个工具的 Agent

    Agent 会根据问题选择合适的工具
    """
    print("\n" + "="*70)
    print("示例 2：多工具 Agent")
    print("="*70)

    # 创建配置多个工具的 Agent
    agent = create_agent(
        model=model,
        tools=[get_weather, calculator, web_search]
    )

    print("\n配置的工具：")
    print("  - get_weather（天气查询）")
    print("  - calculator（计算器）")
    print("  - web_search（网页搜索）")

    # 测试不同类型的问题
    tests = [
        "上海的天气怎么样？",           # 应该用 get_weather
        "15 乘以 23 等于多少？",         # 应该用 calculator
    ]

    for i, question in enumerate(tests, 1):
        print(f"\n{'='*70}")
        print(f"测试 {i}：{question}")
        print(f"{'='*70}")

        response = agent.invoke({
            "messages": [{"role": "user", "content": question}]
        })

        # 显示最终回答
        print(f"\nAgent 回复：{response['messages'][-1].content}")

    print("\n关键点：")
    print("  - Agent 从多个工具中选择最合适的")
    print("  - 基于工具的 docstring 理解工具用途")


# ============================================================================
# 示例 3：带系统提示的 Agent
# ============================================================================
def example_3_agent_with_system_prompt():
    """
    示例3：自定义 Agent 的行为

    使用 system_prompt 参数
    """
    print("\n" + "="*70)
    print("示例 3：自定义 Agent 行为")
    print("="*70)

    # 创建带系统提示的 Agent
    agent = create_agent(
        model=model,
        tools=[get_weather, calculator],
        system_prompt="""你是一个友好的助手。
特点：
- 回答简洁明了
- 使用工具前先说明
- 结果用表格或列表清晰展示"""
    )

    print("\n测试：自定义行为的 Agent")
    response = agent.invoke({
        "messages": [{"role": "user", "content": "北京天气如何？顺便算一下 100 加 50"}]
    })

    print(f"\nAgent 回复：{response['messages'][-1].content}")

    print("\n关键点：")
    print("  - system_prompt 定义 Agent 的行为风格")
    print("  - 可以指定输出格式、语气、工作流程等")


# ============================================================================
# 示例 4：Agent 执行过程详解
""" Agent 执行过程：

完整消息历史：

--- 消息 1 (HumanMessage) ---
内容：25 乘以 8 等于多少？

--- 消息 2 (AIMessage) ---
内容：
工具调用：[{'name': 'calculator', 'args': {'a': 25, 'b': 8, 'operation': 'multiply'}, 'id': '3022d92m1', 'type': 'tool_call'}]

--- 消息 3 (ToolMessage) ---
内容：25.0 multiply 8.0 = 200.0

--- 消息 4 (AIMessage) ---
内容：25 乘以 8 等于 200。
"""
# ============================================================================
def example_4_agent_execution_details():
    """
    示例4：查看 Agent 执行的完整过程

    理解 Agent 如何一步步工作
    """
    print("\n" + "="*70)
    print("示例 4：Agent 执行过程详解")
    print("="*70)

    agent = create_agent(
        model=model,
        tools=[calculator]
    )

    print("\n问题：25 乘以 8 等于多少？")
    print("\nAgent 执行过程：")

    response = agent.invoke({
        "messages": [{"role": "user", "content": "25 乘以 8 等于多少？"}]
    })

    # 显示完整的消息历史
    print("\n完整消息历史：")
    for i, msg in enumerate(response['messages'], 1):
        print(f"\n--- 消息 {i} ({msg.__class__.__name__}) ---")
        if hasattr(msg, 'content'):
            print(f"内容：{msg.content}")
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            print(f"工具调用：{msg.tool_calls}")

    print("\n执行循环：")
    print("""
    1. 用户提问 → HumanMessage
    2. AI 决定调用工具 → AIMessage (包含 tool_calls)
    3. 执行工具 → ToolMessage (包含结果)
    4. AI 基于结果生成答案 → AIMessage (最终回答)
    """)


# ============================================================================
# 示例 5：多轮对话 Agent
# ============================================================================
def example_5_multi_turn_agent():
    """
    示例5：Agent 的多轮对话

    关键：传入历史消息
    """
    print("\n" + "="*70)
    print("示例 5：多轮对话 Agent")
    print("="*70)

    agent = create_agent(
        model=model,
        tools=[calculator]
    )

    # 第一轮
    print("\n用户：10 加 5 等于多少？")
    response1 = agent.invoke({
        "messages": [{"role": "user", "content": "10 加 5 等于多少？"}]
    })
    print(f"Agent：{response1['messages'][-1].content}")

    # 第二轮：继续上一轮的对话
    print("\n用户：再乘以 3 呢？")
    response2 = agent.invoke({
        "messages": response1['messages'] + [
            {"role": "user", "content": "再乘以 3 呢？"}
        ]
    })
    print(f"Agent：{response2['messages'][-1].content}")

    print("\n关键点：")
    print("  - 多轮对话：传入之前的 messages")
    print("  - Agent 能记住上下文")
    print("  - 格式：上一轮的 response['messages'] + 新问题")


# ============================================================================
# 示例 6：Agent 最佳实践
# ============================================================================
def example_6_best_practices():
    """
    示例6：使用 Agent 的最佳实践
    """
    print("\n" + "="*70)
    print("示例 6：Agent 最佳实践")
    print("="*70)

    print("""
最佳实践：

1. 工具选择
   - 只给 Agent 需要的工具（工具太多会混淆）
   - 工具的 docstring 要清晰
   - 每个工具功能单一

2. System Prompt
   - 明确说明 Agent 的角色
   - 定义输出格式
   - 说明何时使用工具

3. 错误处理
   - 工具内部捕获异常
   - 返回友好的错误信息
   - Agent 可以处理工具失败

4. 性能优化
   - 减少不必要的工具调用
   - 缓存常用查询结果
   - 使用流式输出（后续学习）

5. 测试
   - 测试各种问题类型
   - 测试边界情况
   - 验证工具选择是否正确
    """)

    print("\n示例：良好配置的 Agent")

    agent = create_agent(
        model=model,
        tools=[get_weather, calculator],
        system_prompt="""你是一个专业的助手。
工作流程：
1. 仔细理解用户问题
2. 如果需要工具，先说明将要做什么
3. 调用工具获取准确信息
4. 基于结果给出清晰答案

输出要求：
- 简洁明了
- 数据准确
- 格式清晰"""
    )

    print("\n测试：")
    response = agent.invoke({
        "messages": [{"role": "user", "content": "北京天气如何？"}]
    })
    print(f"Agent 回复：{response['messages'][-1].content}")


# ============================================================================
# 主程序
# ============================================================================
def main():
    print("\n" + "="*70)
    print(" LangChain 1.0 - Simple Agent")
    print("="*70)

    try:
        example_1_basic_agent()
        input("\n按 Enter 继续...")

        example_2_multi_tool_agent()
        input("\n按 Enter 继续...")

        example_3_agent_with_system_prompt()
        input("\n按 Enter 继续...")

        example_4_agent_execution_details()
        input("\n按 Enter 继续...")

        example_5_multi_turn_agent()
        input("\n按 Enter 继续...")

        example_6_best_practices()

        print("\n" + "="*70)
        print(" 完成！")
        print("="*70)
        print("\n核心要点：")
        print("  create_agent 创建 Agent")
        print("  Agent 自动判断何时使用工具")
        print("  执行循环：问题 → 工具调用 → 结果 → 回答")
        print("  多轮对话：传入历史 messages")
        print("  system_prompt 定义 Agent 行为")
        print("\n下一步：")
        print("  06_agent_loop - 深入理解 Agent 执行循环")

    except KeyboardInterrupt:
        print("\n\n程序中断")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
