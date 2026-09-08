# -*- coding: utf-8 -*-
"""deck_pages_c.py —— P23-P29（稳定性专题：限流/熔断/幂等/可靠消息）"""
PAGES_C = [
    # ---------- P23 四道防线 cards+banner ----------
    {"type": "cards", "kicker": "05 · 稳定性", "title": "稳定性四道防线总览",
     "rows": [[
         {"title": "防线① 限流", "body": ["Sentinel 流控（服务级）", "@RateLimit（用户/手机号级）", "规则 Nacos 下发"]},
         {"title": "防线② 熔断降级", "body": ["Sentinel degrade", "慢调用/异常比例", "blockHandler 本地降级"]},
         {"title": "防线③ 幂等 + 锁", "body": ["@DistributedLock ×8", "bizType+bizId 幂等", "账本流水留痕"]},
         {"title": "防线④ 可靠消息", "body": ["MQ 事件解耦", "状态机 + 落库", "XXL-Job 定时重试"]}]],
     "banner": {"headline": "每一道防线都有「注解/配置 + 代码落点」，不是 PPT 口号",
                "body": ["分别见 P24-P29：原理、实现与真实用例，全部可回到源码验证"]}},
    # ---------- P24 限流三算法 diagram ----------
    {"type": "diagram", "diagram": "dg_rlimit", "kicker": "05 · 原理",
     "title": "限流原理：令牌桶 / 漏桶 / 滑动窗口", "bounds": "100 170 1080 500"},
    # ---------- P25 @RateLimit 剖析 diagram ----------
    {"type": "diagram", "diagram": "dg_rlimit_anno", "kicker": "05 · 实现",
     "title": "自研注解 @RateLimit：从注解到 Redis 令牌桶", "bounds": "100 170 1080 500"},
    # ---------- P26 Sentinel diagram ----------
    {"type": "diagram", "diagram": "dg_sentinel", "kicker": "05 · 实现",
     "title": "Sentinel：流控与熔断降级原理 + 项目接线", "bounds": "100 170 1080 500"},
    # ---------- P27 幂等与账本 two ----------
    {"type": "two", "kicker": "05 · 幂等", "title": "账本安全：Coin 的锁 + 幂等设计",
     "left": {"title": "CoinAccount 账本模型", "items": [
         ("账户聚合", "balance + CoinStream 流水列表"),
         ("流水幂等", "每笔流水以 bizType+bizId 唯一"),
         ("实时配置", "金额实时读 admin 字典 COIN_CONFIG"),
         ("入账场景", "注册 INITIAL=100 / 邀请奖励 100")]},
     "right": {"title": "锁如何保护账本", "items": [
         ("并发串行", "@DistributedLock('coin:stream:'+#userId) 共 7 处"),
         ("覆盖动作", "init / reward / 位置 / 穿搭 / 推荐扣费"),
         ("失败语义", "异常回滚且流水不落，金额不丢"),
         ("对账抓手", "每笔流水留痕，可追溯可对账")]}},
    # ---------- P28 可靠消息 two ----------
    {"type": "two", "kicker": "05 · 可靠消息", "title": "消息留痕 + 定时重试：可靠消息两条腿",
     "left": {"title": "kaleido-message：MQ 消息状态机", "items": [
         ("记录维度", "userId / message / topic / state"),
         ("状态机", "CREATE → COMPLETED / FAILED"),
         ("暴露方式", "RPC 写 + HTTP 查询（按用户）"),
         ("诚实标注", "当前无业务方引用 —— 轨道已铺待接线")]},
     "right": {"title": "kaleido-notice：重试闭环（XXL-Job）", "items": [
         ("发送链路", "验证码/通知 → 适配器分发 → 落库"),
         ("失败重试", "NoticeRetryJob 定时捞取重发"),
         ("并行执行", "Dynamic-TP 动态线程池并发"),
         ("诚实标注", "Email/WeChat 适配器为 TODO 占位")]}},
    # ---------- P29 可靠性复盘 diagram ----------
    {"type": "diagram", "diagram": "dg_reliability", "kicker": "05 · 复盘",
     "title": "端到端可靠性复盘：四道防线如何叠加", "bounds": "100 170 1080 500"},
]
