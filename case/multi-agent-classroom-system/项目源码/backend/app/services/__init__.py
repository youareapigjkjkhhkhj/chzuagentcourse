"""业务服务层。

放「需要应用上下文（配置 / 数据库 / 当前 app）」的装配与业务逻辑。
纯逻辑（不依赖 Flask）请下沉到 app/providers、app/common，便于单独测试。
"""
