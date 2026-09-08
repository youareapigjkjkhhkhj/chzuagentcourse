"""
自定义工具：计算器
==================

演示带多个参数的工具
"""

from langchain_core.tools import tool


@tool
def calculator(operation: str, a: float, b: float) -> str:
    """
    执行基本的数学计算

    参数:
        operation: 运算类型，支持 "add"(加), "subtract"(减), "multiply"(乘), "divide"(除)
        a: 第一个数字
        b: 第二个数字

    返回:
        计算结果字符串
    """
    operations = {
        "add": lambda x, y: x + y,
        "subtract": lambda x, y: x - y,
        "multiply": lambda x, y: x * y,
        "divide": lambda x, y: x / y if y != 0 else "错误：除数不能为零"
    }

    if operation not in operations:
        return f"不支持的运算类型：{operation}。支持的类型：add, subtract, multiply, divide"

    try:
        result = operations[operation](a, b)
        return f"{a} {operation} {b} = {result}"
    except Exception as e:
        return f"计算错误：{e}"


# 测试工具
if __name__ == "__main__":
    print("测试计算器工具：")
    print(calculator.invoke({"operation": "add", "a": 10, "b": 5}))
    print(calculator.invoke({"operation": "multiply", "a": 7, "b": 8}))
    print(calculator.invoke({"operation": "divide", "a": 20, "b": 4}))
