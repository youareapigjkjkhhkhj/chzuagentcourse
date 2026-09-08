"""
LangChain 1.0 - 自定义工具 (@tool 装饰器)
=========================================

本模块重点讲解：
1. 使用 @tool 装饰器创建工具（LangChain 1.0 推荐方式）
2. 工具的参数和文档字符串（docstring）的重要性
3. 测试工具
"""

import os
import sys

# Windows终端编码支持
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加tools目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tools'))

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool

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
# 示例 1：创建第一个工具
# ============================================================================
def example_1_simple_tool():
    """
    示例1：使用 @tool 装饰器创建工具

    关键：
    1. 使用 @tool 装饰器
    2. 必须有 docstring（文档字符串）
    3. 参数要有类型注解
    """
    print("\n" + "="*70)
    print("示例 1：创建第一个工具")
    print("="*70)

    @tool
    def get_current_time() -> str:
        """获取当前时间"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("\n工具名称:", get_current_time.name)
    print("工具描述:", get_current_time.description)
    print("工具参数:", get_current_time.args)

    # 调用工具
    result = get_current_time.invoke({})
    # 被 @tool 装饰器装饰的函数会被转换为 LangChain 的 Tool
    # 对象，这个对象有 .invoke() 方法。
    print(f"\n调用结果: {result}")

    print("\n💡 关键点：")
    print("  1. @tool 装饰器会自动提取函数名、docstring、参数")
    print("  2. docstring 很重要！AI 用它理解工具的功能")
    print("  3. 类型注解帮助 AI 理解参数类型")


# ============================================================================
# 示例 2：带参数的工具
# ============================================================================
def example_2_tool_with_params():
    """
    示例2：带参数的工具

    重点：参数的文档说明
    """
    print("\n" + "="*70)
    print("示例 2：带参数的工具")
    print("="*70)

    print("\n查看天气工具的信息：")
    print(f"名称: {get_weather.name}")
    print(f"描述: {get_weather.description}")
    print(f"参数: {get_weather.args}")

    # 测试工具
    print("\n测试工具：")
    result1 = get_weather.invoke({"city": "北京"})
    print(f"北京天气: {result1}")

    result2 = get_weather.invoke({"city": "上海"})
    print(f"上海天气: {result2}")

    print("\n💡 docstring 格式：")
    print('''
    @tool
    def my_tool(param1: str) -> str:
        """
        工具的简短描述

        参数:
            param1: 参数说明

        返回:
            返回值说明
        """
    ''')


# ============================================================================
# 示例 3：多参数工具
# ============================================================================
def example_3_multiple_params():
    """
    示例3：多参数工具
    """
    print("\n" + "="*70)
    print("示例 3：多参数工具 - 计算器")
    print("="*70)

    print("\n计算器工具信息：")
    print(f"名称: {calculator.name}")
    print(f"描述: {calculator.description}")

    # 测试不同运算
    print("\n测试计算：")
    tests = [
        {"operation": "add", "a": 10, "b": 5},
        {"operation": "multiply", "a": 7, "b": 8},
        {"operation": "divide", "a": 20, "b": 4}
    ]

    for test in tests:
        result = calculator.invoke(test)
        print(f"  {result}")


# ============================================================================
# 示例 4：可选参数工具
# ============================================================================
def example_4_optional_params():
    """
    示例4：可选参数

    使用 Optional[类型] 和默认值
    """
    print("\n" + "="*70)
    print("示例 4：可选参数 - 搜索工具")
    print("="*70)

    # 使用默认参数
    print("\n使用默认参数（返回3条结果）：")
    result1 = web_search.invoke({"query": "Python"})
    print(result1)

    # 指定参数
    print("\n指定返回2���结果：")
    result2 = web_search.invoke({"query": "LangChain", "num_results": 2})
    print(result2)


# ============================================================================
# 示例 5：工具绑定到模型（预览）
# ============================================================================
def example_5_bind_tools():
    """
    示例5：将工具绑定到模型

    这是让 AI 使用工具的第一步
    """
    print("\n" + "="*70)
    print("示例 5：工具绑定到模型（预览）")
    print("="*70)

    # 绑定工具到模型
    model_with_tools = model.bind_tools([get_weather, calculator])

    print("模型已绑定工具：")
    print("  - get_weather")
    print("  - calculator")

    # 调用模型（模型可以选择使用工具）
    print("\n测试：AI 是否会调用天气工具？")
    response = model_with_tools.invoke("北京今天天气怎么样？")

    # 检查模型是否要求调用工具
    if response.tool_calls:
        print(f"\n✅ AI 决定使用工具！")
        print(f"工具调用: {response.tool_calls}")
    else:
        print(f"\nℹ️ AI 直接回答（未使用工具）")
        print(f"回复: {response.content}")

    print("\n💡 下一步：")
    print("  在 05_simple_agent 中，我们将学习如何让 AI 自动执行工具")


# ============================================================================
# 示例 6：工具的最佳实践
# ============================================================================
def example_6_best_practices():
    """
    示例6：工具开发最佳实践
    """
    print("\n" + "="*70)
    print("示例 6：工具开发最佳实践")
    print("="*70)

    print("\n✅ 好的工具设计：")
    print("""
1. 清晰的 docstring
   @tool
   def search_products(query: str, max_results: int = 10) -> str:
       '''
       在产品数据库中搜索产品

       参数:
           query: 搜索关键词
           max_results: 最大返回数量，默认10

       返回:
           产品列表的JSON字符串
       '''

2. 明确的参数类型
   - 使用类型注解：str, int, float, bool
   - 可选参数用 Optional[类型]

3. 返回字符串
   - 工具应该返回 str（AI 最容易理解）
   - 复杂数据可以返回 JSON 字符串

4. 错误处理
   - 在工具内部捕获异常
   - 返回友好的错误消息

5. 功能单一
   - 一个工具做一件事
   - 不要把多个功能塞进一个工具
    """)


# ============================================================================
# 主程序
# ============================================================================
def main():
    print("\n" + "="*70)
    print(" LangChain 1.0 - 自定义工具")
    print("="*70)

    try:
        example_1_simple_tool()
        input("\n按 Enter 继续...")

        example_2_tool_with_params()
        input("\n按 Enter 继续...")

        example_3_multiple_params()
        input("\n按 Enter 继续...")

        example_4_optional_params()
        input("\n按 Enter 继续...")

        example_5_bind_tools()
        input("\n按 Enter 继续...")

        example_6_best_practices()

        print("\n" + "="*70)
        print(" 完成！")
        print("="*70)
        print("\n核心要点：")
        print("  ✅ 使用 @tool 装饰器创建工具")
        print("  ✅ 必须有清晰的 docstring")
        print("  ✅ 参数要有类型注解")
        print("  ✅ 工具返回字符串")
        print("\n下一步：")
        print("  05_simple_agent - 学习如何让 AI 自动使用工具")

    except KeyboardInterrupt:
        print("\n\n程序中断")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
