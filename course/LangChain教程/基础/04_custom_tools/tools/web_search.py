"""
自定义工具：网页搜索（模拟）
============================

演示可选参数的工具
"""

from langchain_core.tools import tool
from typing import Optional


@tool
def web_search(query: str, num_results: Optional[int] = 3) -> str:
    """
    在网上搜索信息（模拟）

    参数:
        query: 搜索关键词
        num_results: 返回结果数量，默认3条

    返回:
        搜索结果字符串
    """
    # 模拟搜索结果
    mock_results = {
        "Python": [
            "Python官方网站 - https://www.python.org",
            "Python教程 - 菜鸟教程",
            "Python最佳实践 - Real Python"
        ],
        "机器学习": [
            "机器学习入门 - Coursera",
            "Scikit-learn文档",
            "机器学习实战 - GitHub"
        ],
        "LangChain": [
            "LangChain官方文档",
            "LangChain GitHub仓库",
            "LangChain教程 - YouTube"
        ]
    }

    # 查找结果
    results = []
    for key in mock_results:
        if key.lower() in query.lower():
            results = mock_results[key][:num_results]
            break

    if not results:
        return f"未找到关于'{query}'的结果"

    # 格式化输出
    output = f"搜索 '{query}' 找到 {len(results)} 条结果：\n"
    for i, result in enumerate(results, 1):
        output += f"{i}. {result}\n"

    return output.strip()


# 测试工具
if __name__ == "__main__":
    print("测试搜索工具：")
    print(web_search.invoke({"query": "Python"}))
    print("\n" + web_search.invoke({"query": "LangChain", "num_results": 2}))
