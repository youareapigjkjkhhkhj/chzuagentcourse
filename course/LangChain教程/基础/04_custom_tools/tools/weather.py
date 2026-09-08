"""
自定义工具：天气查询
====================

使用 @tool 装饰器创建工具（LangChain 1.0 推荐方式）
"""

from langchain_core.tools import tool


@tool
def get_weather(city: str) -> str:
    """
    获取指定城市的天气信息

    参数:
        city: 城市名称，如"北京"、"上海"

    返回:
        天气信息字符串
    """
    # 模拟天气数据（实际应用中应调用真实API）
    weather_data = {
        "北京": "晴天，温度 15°C，空气质量良好",
        "上海": "多云，温度 18°C，有轻微雾霾",
        "深圳": "阴天，温度 22°C，可能有小雨",
        "成都": "小雨，温度 12°C，湿度较高"
    }

    return weather_data.get(city, f"抱歉，暂时没有{city}的天气数据")


# 测试工具
if __name__ == "__main__":
    print("测试天气工具：")
    print(f"北京天气: {get_weather.invoke({'city': '北京'})}")
    print(f"上海天气: {get_weather.invoke({'city': '上海'})}")
