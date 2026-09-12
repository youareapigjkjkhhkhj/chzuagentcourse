"""通用基础设施：响应信封、异常、日志、加密、串行化写库。

本模块刻意不在这里 import 子模块 —— 子模块之间存在相互引用
（例如 errors 依赖 response、dbw 依赖 logging），集中 import 会造成循环。
按需 `from app.common.xxx import yyy`。
"""
