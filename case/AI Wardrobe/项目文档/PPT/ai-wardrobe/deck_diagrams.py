# -*- coding: utf-8 -*-
"""
deck_diagrams.py —— Kaleido(AI 智能衣柜) 39 页 deck 的 20 张自绘示意图函数。
每个函数返回 SVG 图元文本（由 swiss-lecture-style 生成器的 page_diagram 装入
<g id="diagram" data-pptx-bounds="...">）。只允许使用调色板；元素须落在页面
spec 声明的 bounds 之内（本 deck 统一安全区 x 100..1180、y 175..645）。
"""
from swiss_lecture_gen import (
    WHITE, INK, GRAY, RED, CARD, BODY, LITE, LINE,
    _t, _line, _arrow_seg, _rect_dashed, esc, wrap,
)

# ---------- 小原语 ----------
def TL(x, y, s, fs=12, fill=BODY, bold=False):
    return _t(x, y, s, fs=fs, fill=fill, bold=bold, anchor="start")


def TC(x, y, s, fs=12, fill=INK, bold=False):
    return _t(x, y, s, fs=fs, fill=fill, bold=bold, anchor="middle")


def BX(x, y, w, h, fill=CARD, edge=None, accent=False, sw=1.0):
    o = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="{fill}"/>']
    if edge:
        o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="none" stroke="{edge}" stroke-width="{sw}"/>')
    if accent:
        o.append(f'<rect x="{x}" y="{y}" width="{w}" height="5" fill="{RED}"/>')
    return "".join(o)


def _max_units(x, fs):
    """从文本起点 x 到安全区右界 1180 能容纳的折行单位（CJK=1，保守留 4%）"""
    return max(6, int(((1180 - (x + 14)) / fs) * 0.96))


def BUL(x, y, items, fs=12, gap=24, fill=BODY):
    """条目列表：红方块 + 自动折行文本。每个 item 折成多行，行距 gap。"""
    o, cy = [], y
    maxu = _max_units(x, fs)
    for it in items:
        lines = wrap(it, maxu)
        o.append(f'<rect x="{x}" y="{cy-7:.0f}" width="6" height="6" fill="{RED}"/>')
        first = True
        for ln in lines:
            o.append(TL(x + 14, cy, ln, fs=fs, fill=fill))
            cy += gap
        if not lines:
            cy += gap
    return "\n".join(o)


def CHIP(x, y, s, fs=11.5, fill=GRAY):
    """单条注释/小字，超出安全区自动折行（行距 16）。返回 (text, next_y)。"""
    maxu = _max_units(x, fs)
    o, cy = [], y
    for ln in wrap(s, maxu):
        o.append(TL(x, cy, ln, fs=fs, fill=fill))
        cy += 16
    return "\n".join(o)


# ============================================================
# P05 业务模块地图：业务功能 ↔ 服务模块
# ============================================================
def dg_bizmap():
    o = []
    o.append(BX(100, 190, 460, 40, fill=INK))
    o.append(TC(330, 216, "业务功能（App 用户端 / 管理端）", fs=14, fill=WHITE, bold=True))
    o.append(BX(620, 190, 560, 40, fill=INK))
    o.append(TC(900, 216, "微服务落点（kaleido-biz）", fs=14, fill=WHITE, bold=True))
    pairs = [
        ("服装管理 · 衣橱 · 穿搭 · 位置", "kaleido-wardrobe（Clothing/Outfit/Location/Brand 聚合）"),
        ("AI 搭配 · 穿搭建议 · 会话咨询", "kaleido-ai（Agent 装配 + Chat + 向量检索）"),
        ("搭配方案下单 · 记录编排", "kaleido-recommend（记录 + 异步 AI 工作流）"),
        ("金币 · 邀请返利 · 行为扣费", "kaleido-coin（账户账本 + 幂等流水）"),
        ("注册 / 登录 / 验证码", "kaleido-auth（短信码 + Sa-Token 双体系）"),
        ("RBAC · 字典 · AI Agent 管理", "kaleido-admin（权限三级 + Dubbo 转发 ai）"),
        ("标签体系（服装/穿搭/位置）", "kaleido-tag（类型×实体匹配 + 多对多）"),
    ]
    y = 246
    for i, (b, s) in enumerate(pairs):
        o.append(BX(100, y, 460, 44, fill=CARD))
        o.append(TL(116, y + 26, b, fs=12.5, fill=INK, bold=True))
        o.append(BX(620, y, 560, 44, fill=CARD, accent=True))
        o.append(TL(636, y + 26, s, fs=12, fill=BODY))
        o.append(_arrow_seg(560, y + 22, 620, y + 22, color=RED, sw=1.6))
        y += 54
    o.append(TL(100, y + 8, "注：两端同源功能描述对应 README.md:28-41；服务落点对应 kaleido-biz/pom.xml:17-29 模块清单。", fs=11, fill=GRAY))
    return "\n".join(o)


# ============================================================
# P06 系统架构分层图
# ============================================================
def dg_arch():
    o = []
    o.append(BX(100, 180, 1080, 30, fill=INK))
    o.append(TC(640, 200, "接入层：kaleido-admin-frontend（Vue3 · Element Plus · Vite6）＋ kaleido-interview/fronted（SSE 演示端）", fs=12.5, fill=WHITE, bold=True))
    o.append(BX(100, 214, 1080, 30, fill=CARD, edge=RED, accent=True))
    o.append(TC(640, 234, "API 网关 kaleido-gateway :9010 ｜ Spring Cloud Gateway(WebFlux) + Sa-Token 双端鉴权 ｜ 9 条 lb:// 路由", fs=12, fill=INK, bold=True))
    # 服务层：四类 × chip 网格（只列服务名，端口见 P07/P08）
    o.append(BX(100, 248, 1080, 122, fill=CARD))
    groups = [
        ("认证 / 平台", ["kaleido-auth", "kaleido-admin", "kaleido-notice"]),
        ("衣柜业务", ["kaleido-user", "kaleido-wardrobe", "kaleido-tag", "kaleido-coin", "kaleido-message"]),
        ("AI 智能", ["kaleido-ai", "kaleido-mcp", "kaleido-recommend"]),
        ("对照 / 实验", ["ai-langchain4j", "langchain4j-demo", "kaleido-interview"]),
    ]
    gx = 112
    for gname, apps in groups:
        o.append(BX(gx, 254, 252, 20, fill=INK))
        o.append(TC(gx + 126, 268, gname + f"（{len(apps)}）", fs=10.5, fill=WHITE, bold=True))
        o.append(BX(gx, 278, 252, 86, fill=WHITE, edge=LINE))
        for idx, app in enumerate(apps):
            col, row = idx % 2, idx // 2
            cx = gx + 8 + col * 124
            cy = 286 + row * 21
            o.append(BX(cx, cy, 116, 17, fill=CARD))
            o.append(TC(cx + 58, cy + 12, app, fs=8.5, fill=BODY))
        gx += 266
    # 公共支撑层（两行文字）
    o.append(BX(100, 376, 1080, 54, fill=CARD))
    o.append(TC(640, 396, "公共支撑层 kaleido-common：21 个 starter（Web / 数据 / 分布式协作 / 高可用 / 认证与工具）", fs=12, fill=INK, bold=True))
    o.append(TC(640, 420, "web·aop ｜ ds·cache·file ｜ nacos·rpc·mq·distribute ｜ lock·limiter·sentinel·seata·dynamic-tp·job ｜ sa-token ｜ base·api·doc·sms·monitor", fs=10, fill=BODY))
    # 基础设施
    y = 440
    o.append(BX(100, y, 1080, 96, fill=CARD))
    o.append(TC(640, y + 18, "基础设施", fs=12, fill=INK, bold=True))
    infra_rows = [
        ["MySQL 8.4（ShardingSphere 2 库 4 表）", "MongoDB 7+（AI 会话/记忆）", "Milvus 2.4+（服装向量 1536 维）", "MinIO（图片对象存储）"],
        ["Redis 6+（缓存/锁/限流）+ Caffeine", "RabbitMQ 3.13+（事件总线）", "Nacos 2.3（注册 + 配置）", "XXL-Job 3.3.2（定时重试）"],
    ]
    for r, row in enumerate(infra_rows):
        for c, item in enumerate(row):
            o.append(CHIP(112 + c * 260, y + 38 + r * 22, item, fs=10))
    o.append(TL(100, y + 88, "端口/上下文见 doc/nacos/*-dev.yml；分片与表结构见 doc/sql/kaleido.sql。", fs=10, fill=GRAY))
    return "\n".join(o)


# ============================================================
# P07 服务拓扑与三类通信
# ============================================================
def dg_topology():
    o = []
    o.append(BX(100, 186, 1080, 34, fill=INK))
    o.append(TC(640, 209, "服务拓扑：注册发现（Nacos）× 同步调用（Dubbo）× 异步事件（RabbitMQ）", fs=13.5, fill=WHITE, bold=True))
    # 上：服务三组
    ty = 240
    o.append(BX(100, ty, 340, 120, fill=CARD, accent=True))
    o.append(TC(270, ty + 22, "平台与入口服务", fs=13, fill=INK, bold=True))
    o.append(BUL(118, ty + 40, ["gateway 9010（WebFlux 网关）", "auth 9011（短信码登录）", "admin 9013（RBAC 管理端）", "notice 9014（通知/重试）"], fs=11.5, gap=21))
    o.append(BX(460, ty, 340, 120, fill=CARD, accent=True))
    o.append(TC(630, ty + 22, "衣柜业务服务", fs=13, fill=INK, bold=True))
    o.append(BUL(478, ty + 40, ["user 9012 · wardrobe 9017", "tag 9019 · coin 9018", "message 9030（消息留痕）"], fs=11.5, gap=22))
    o.append(BX(820, ty, 360, 120, fill=CARD, accent=True))
    o.append(TC(1000, ty + 22, "AI 服务", fs=13, fill=INK, bold=True))
    o.append(BUL(838, ty + 40, ["ai 9020（Spring AI 装配/RAG）", "recommend 9029（推荐编排）", "mcp 9021（MCP Server）"], fs=11.5, gap=22))
    # 中：两个枢纽
    hy = 388
    o.append(BX(100, hy, 520, 92, fill=WHITE, edge=INK, sw=1.4))
    o.append(TC(360, hy + 24, "Nacos 2.3 —— 注册 + 配置中心", fs=13.5, fill=INK, bold=True))
    o.append(CHIP(120, hy + 48, "namespace：kaleido（主配置/发现）· dubbo（RPC 分组）", fs=11.5))
    o.append(CHIP(120, hy + 70, "服务心跳注册 · 配置动态下发（${NACOS_HOST} 注入）", fs=11.5))
    o.append(BX(660, hy, 520, 92, fill=WHITE, edge=INK, sw=1.4))
    o.append(TC(920, hy + 24, "RabbitMQ —— 4 条事件 topic", fs=13.5, fill=INK, bold=True))
    o.append(CHIP(680, hy + 48, "auth-change · user-registered", fs=11.5))
    o.append(CHIP(680, hy + 70, "outfit-recommend-completed · clothing-event", fs=11.5))
    for x0 in (180, 500, 850):
        o.append(_line(x0, hy, x0, hy - 40, color=GRAY, sw=1, dash="4 3"))
    # 下：存储带
    dy = 512
    o.append(BX(100, dy, 1080, 44, fill=CARD))
    o.append(TC(640, dy + 27, "数据与中间件：MySQL（分片 2 库 4 表）｜ MongoDB（会话）｜ Milvus（向量）｜ Redis（缓存/锁/限流）｜ MinIO（图片）", fs=12.5, fill=INK, bold=True))
    o.append(BX(100, dy + 56, 1080, 34, fill=WHITE, edge=LINE))
    o.append(TC(640, dy + 77, "通信规则：服务间同步 = Dubbo RPC（30+ 注解，registry=nacos group=dubbo）｜ 跨服务解耦 = RabbitMQ 事件 ｜ 无 OpenFeign / HTTP 直连（全仓未见）", fs=12, fill=BODY))
    return "\n".join(o)


# ============================================================
# P10 端到端旅程：一次 AI 推荐穿搭
# ============================================================
def dg_journey():
    o = []
    steps = [
        ("① 用户请求", "POST /recommend\n携带穿搭提示词", "Sentinel 流控\n@SentinelResource"),
        ("② 校验+扣费", "recommend 调 coin：\n余额校验 + 扣费", "分布式锁\nbizId 幂等"),
        ("③ 调起 AI", "Dubbo→ai\nexecuteOutfitRecommendWorkflow", "工作流 code\nOUTFIT_RECOMMEND"),
        ("④ AI 生成", "向量检索 + LLM\n返回搭配 JSON", "Milvus topK\nBGE-M3 向量"),
        ("⑤ 完成回执", "MQ\noutfit-recommend-completed", "可靠消息\n状态机"),
        ("⑥ 落穿搭", "recommend→wardrobe\n创建 Outfit", "RPC + 领域\n聚合封装"),
        ("⑦ 终态", "记录 COMPLETED\n可查询", "异步闭环\n失败可重试"),
    ]
    w, h, gap = 130, 118, 18
    x0 = 100
    # 上半 4 步
    for i in range(4):
        x = x0 + i * (w + gap)
        o.append(BX(x, 240, w, h, fill=CARD, edge=LINE, accent=(i == 0)))
        ls = steps[i][1].split("\n")
        o.append(TC(x + w / 2, 266, steps[i][0], fs=13, fill=INK, bold=True))
        o.append(TL(x + 8, 294, ls[0], fs=11.5, fill=BODY))
        o.append(TL(x + 8, 312, ls[1], fs=11.5, fill=BODY))
        o.append(BX(x + 6, 324, w - 12, 28, fill=WHITE, edge=LINE))
        o.append(TL(x + 12, 343, steps[i][2], fs=10.5, fill=GRAY))
        if i < 3:
            o.append(_arrow_seg(x + w, 300, x + w + gap, 300, color=INK))
    # 拐弯箭头 + 下半 3 步（自右向左）
    o.append(_arrow_seg(x0 + 3 * (w + gap) + w, 300, x0 + 4 * (w + gap) + 20, 300, color=INK))
    for i in range(3):
        j = 6 - i
        x = x0 + (j) * (w + gap) - 0  # 第5-7 步占右三格，从右向左
    # 简化：下半右→左 3 盒，y=380
    for k, idx in enumerate([6, 5, 4]):
        x = x0 + k * (w + gap)
        st = steps[idx]
        o.append(BX(x, 380, w, h, fill=CARD, edge=LINE, accent=(idx == 6)))
        o.append(TC(x + w / 2, 406, st[0], fs=13, fill=INK, bold=True))
        ls = st[1].split("\n")
        o.append(TL(x + 8, 434, ls[0], fs=11.5, fill=BODY))
        o.append(TL(x + 8, 452, ls[1], fs=11.5, fill=BODY))
        o.append(BX(x + 6, 464, w - 12, 28, fill=WHITE, edge=LINE))
        o.append(TL(x + 12, 483, st[2], fs=10.5, fill=GRAY))
        if k < 2:
            o.append(_arrow_seg(x + w, 440, x + w + gap, 440, color=INK))
    o.append(TL(100, 540, "泳道事实：RecommendCommandService.java:77-113（校验→RPC→落记录→扣费）；OutfitRecommendCompletedEventListener.java:53（MQ 回执→Dubbo 建穿搭→终态）。", fs=11, fill=GRAY))
    return "\n".join(o)


# ============================================================
# P15 Nacos：注册 + 配置中心
# ============================================================
def dg_nacos():
    o = []
    o.append(BX(430, 230, 420, 150, fill=WHITE, edge=INK, sw=1.6))
    o.append(TC(640, 260, "Nacos Server 2.3", fs=17, fill=INK, bold=True))
    o.append(CHIP(452, 292, "服务注册表（实例列表）", fs=12))
    o.append(CHIP(452, 314, "配置存储（kaleido/dubbo namespace）", fs=12))
    o.append(CHIP(452, 336, "配置变更推送 · 心跳健康检查", fs=12))
    # 左侧服务
    o.append(BX(100, 240, 230, 90, fill=CARD, accent=True))
    o.append(TC(215, 268, "Provider 服务", fs=14, fill=INK, bold=True))
    o.append(CHIP(116, 294, "启动时注册实例", fs=11.5))
    o.append(CHIP(116, 316, "暴露 Dubbo/HTTP 元数据", fs=11.5))
    # 右侧
    o.append(BX(950, 240, 230, 90, fill=CARD, accent=True))
    o.append(TC(1065, 268, "Consumer 服务", fs=14, fill=INK, bold=True))
    o.append(CHIP(966, 294, "订阅服务列表", fs=11.5))
    o.append(CHIP(966, 316, "配置热更新", fs=11.5))
    o.append(_arrow_seg(330, 285, 430, 275, color=RED, sw=1.8))
    o.append(_arrow_seg(850, 275, 950, 285, color=RED, sw=1.8))
    o.append(_line(330, 305, 430, 295, color=GRAY, sw=1, dash="4 3"))
    o.append(_line(850, 295, 950, 305, color=GRAY, sw=1, dash="4 3"))
    o.append(TC(215, 352, "register", fs=10.5, fill=GRAY))
    o.append(TC(1065, 352, "subscribe/config", fs=10.5, fill=GRAY))
    o.append(BUL(100, 430, [
        "接入：bootstrap.yml 以 classpath:nacos.yml 引入（server-addr=${NACOS_HOST}:${NACOS_PORT}、双 namespace）——kaleido-nacos/src/main/resources/nacos.yml:4-13",
        "配置：每服务 xxx-dev.yml 独立 dataId（doc/nacos/）；网关 9 条路由、Sentinel 规则 JSON 均经 Nacos 下发",
        "RPC 分组：Dubbo 独立 namespace=dubbo、group=dubbo —— doc/nacos/kaleido-rpc.yml:16-22",
    ], fs=12, gap=30))
    return "\n".join(o)


# ============================================================
# P16 网关与鉴权
# ============================================================
def dg_gateway():
    o = []
    o.append(BX(100, 200, 240, 130, fill=CARD, accent=True))
    o.append(TC(220, 228, "客户端请求", fs=14, fill=INK, bold=True))
    o.append(CHIP(116, 254, "管理端 token:", fs=11.5))
    o.append(CHIP(116, 274, "kaleido-admin-token", fs=11.5))
    o.append(CHIP(116, 296, "用户端 token:", fs=11.5))
    o.append(CHIP(116, 316, "kaleido-user-token", fs=11.5))
    o.append(BX(360, 200, 240, 130, fill=INK))
    o.append(TC(480, 228, "SaReactorFilter", fs=14, fill=WHITE, bold=True))
    o.append(CHIP(378, 254, "addInclude('/**')", fs=11.5, fill=LITE))
    o.append(CHIP(378, 276, "放行 /kaleido-admin/public/**", fs=11.5, fill=LITE))
    o.append(CHIP(378, 298, "setAuth → 策略工厂", fs=11.5, fill=LITE))
    o.append(BX(620, 200, 280, 130, fill=CARD, accent=True))
    o.append(TC(760, 228, "DynamicStrategyFactory", fs=14, fill=INK, bold=True))
    o.append(CHIP(636, 254, "AntPathMatcher 按序匹配", fs=11.5))
    o.append(CHIP(636, 276, "路径→策略 Caffeine 缓存", fs=11.5))
    o.append(CHIP(636, 298, "default: PUBLIC（放行）", fs=11.5))
    o.append(BX(920, 200, 260, 130, fill=WHITE, edge=INK, sw=1.4))
    o.append(TC(1050, 228, "策略实现", fs=14, fill=INK, bold=True))
    o.append(BUL(938, 248, ["PublicPath：放行", "UserPath：checkLogin +", "用户状态 ACTIVE/FROZEN", "AdminPath：checkLogin"], fs=11, gap=19))
    for a, b in [(340, 360), (600, 620)]:
        o.append(_arrow_seg(a + 0, 265, b + 0, 265, color=RED, sw=1.8))
    o.append(_arrow_seg(900, 265, 920, 265, color=RED, sw=1.8))
    o.append(BX(100, 360, 1080, 150, fill=CARD))
    o.append(TC(640, 386, "网关路由（doc/nacos/kaleido-gateway-dev.yml:20-71）—— 9 条 lb:// 路由", fs=13.5, fill=INK, bold=True))
    routes = ["kaleido-auth-server", "kaleido-user", "kaleido-notice", "kaleido-admin", "kaleido-wardrobe",
              "kaleido-tag", "kaleido-coin", "kaleido-recommend", "kaleido-ai"]
    for i, r in enumerate(routes):
        col = i % 5
        row = i // 5
        x = 120 + col * 200
        o.append(BX(x, 406, 190, 30, fill=WHITE, edge=LINE))
        o.append(TC(x + 95, 426, r, fs=11.5, fill=BODY))
        if row == 1:
            o.append(CHIP(120, 452, "AI/interview/demo 不在网关路由表（独立上下文访问）", fs=10.5))
            break
    o.append(BUL(100, 490, [
        "校验实现：UserPathStrategy.checkAuth = checkLogin + checkPermissionOr(ACTIVE, FROZEN)（user/.../UserPathStrategy.java:25-32）；AdminPathStrategy = checkLogin（:24-29）",
        "跨域：globalcors allowedOrigins/Methods/Headers='*'（kaleido-gateway-dev.yml:10-17）",
    ], fs=11.5, gap=24))
    return "\n".join(o)


# ============================================================
# P17 Dubbo RPC
# ============================================================
def dg_dubbo():
    o = []
    o.append(BX(100, 210, 300, 150, fill=CARD, accent=True))
    o.append(TC(250, 238, "Consumer（业务服务）", fs=14, fill=INK, bold=True))
    o.append(CHIP(120, 268, "@DubboReference", fs=12))
    o.append(CHIP(120, 290, "(version=1.0.0)", fs=11.5, fill=GRAY))
    o.append(CHIP(120, 312, "调 kaleido-api 契约接口", fs=11.5))
    o.append(BX(490, 210, 300, 150, fill=WHITE, edge=INK, sw=1.6))
    o.append(TC(640, 240, "Nacos Registry", fs=16, fill=INK, bold=True))
    o.append(CHIP(512, 272, "namespace=dubbo · group=dubbo", fs=11.5))
    o.append(CHIP(512, 294, "服务发现/路由", fs=11.5))
    o.append(CHIP(512, 316, "provider.filter=dubboExceptionFilter", fs=11.5))
    o.append(BX(880, 210, 300, 150, fill=CARD, accent=True))
    o.append(TC(1030, 238, "Provider（服务实现）", fs=14, fill=INK, bold=True))
    o.append(CHIP(900, 268, "@DubboService", fs=12))
    o.append(CHIP(900, 290, "30+ 处（接口/实现注解）", fs=11.5, fill=GRAY))
    o.append(CHIP(900, 312, "如 RpcUserServiceImpl / RpcClothingServiceImpl", fs=10.5))
    o.append(_arrow_seg(400, 285, 490, 285, color=RED, sw=1.8))
    o.append(_arrow_seg(790, 285, 880, 285, color=RED, sw=1.8))
    o.append(_line(400, 320, 640, 350, color=GRAY, sw=1, dash="4 3"))
    o.append(_line(880, 320, 640, 350, color=GRAY, sw=1, dash="4 3"))
    o.append(BX(100, 400, 1080, 44, fill=INK))
    o.append(TC(640, 427, "契约优先：kaleido-api 契约库（128 个接口/DTO）独立于实现 —— 服务间只依赖契约，不依赖实现类", fs=13.5, fill=WHITE, bold=True))
    o.append(BUL(100, 470, [
        "接口示例：IRpcNoticeService（@DubboService，api/notice/IRpcNoticeService.java:23）；实现示例：RpcUserServiceImpl.java:30、RpcCoinServiceImpl.java:28、RpcNoticeServiceImpl.java:35",
        "异常契约：DubboExceptionFilter（provider，order=-10000）把服务端异常转统一 Result，避免跨服务序列化失败 —— rpc/filter/DubboExceptionFilter.java:22-24",
        "配置：超时默认 20s（RpcConstants.java:24）；qos 端口 22230 起（nacos yml）",
    ], fs=12, gap=28))
    return "\n".join(o)


# ============================================================
# P18 RabbitMQ 事件总线
# ============================================================
def dg_mq():
    o = []
    o.append(BX(100, 196, 1080, 36, fill=INK))
    o.append(TC(640, 219, "事件信封与发送抽象（kaleido-mq）", fs=13.5, fill=WHITE, bold=True))
    o.append(CHIP(116, 252, "EventPublisher.publish(topic, event)：rabbitTemplate.convertAndSend —— 默认交换机、routingKey=topic（EventPublisher.java:25）", fs=11.5))
    o.append(CHIP(116, 276, "BaseEvent< T >：topic() 抽象 + EventMessage{id, timestamp, data} 信封（BaseEvent.java:18-32）｜ 业务事件继承它（如 ClothingEvent.java:25-27）", fs=11.5))
    topics = [
        ("auth-change", "kaleido-admin", "AuthChangeCustomer 清角色/权限缓存", "admin/.../listener/AuthChangeCustomer.java:36"),
        ("user-registered", "kaleido-user", "UserRegisteredCoinListener 初始化账户+邀请奖励", "kaleido-coin/.../listener/UserRegisteredCoinListener.java:33"),
        ("clothing-event", "kaleido-wardrobe", "ClothingEventListener 服装向量库增量同步", "kaleido-ai/.../listener/ClothingEventListener.java:34"),
        ("outfit-recommend-completed", "kaleido-ai", "推荐完成回执 → 创建穿搭/终态", "kaleido-recommend/.../OutfitRecommendCompletedEventListener.java:53"),
    ]
    y = 306
    o.append(BX(100, y, 380, 34, fill=CARD, edge=RED, accent=True))
    o.append(TC(290, y + 22, "topic（发布方）", fs=12, fill=INK, bold=True))
    o.append(BX(500, y, 260, 34, fill=CARD, edge=RED, accent=True))
    o.append(TC(630, y + 22, "消费方服务", fs=12, fill=INK, bold=True))
    o.append(BX(780, y, 400, 34, fill=CARD, edge=RED, accent=True))
    o.append(TC(980, y + 22, "业务动作", fs=12, fill=INK, bold=True))
    y += 42
    for t, pub, act, _ in topics:
        o.append(BX(100, y, 380, 40, fill=WHITE, edge=LINE))
        o.append(TC(290, y + 25, t, fs=12.5, fill=RED, bold=True))
        o.append(BX(500, y, 260, 40, fill=WHITE, edge=LINE))
        o.append(TC(630, y + 25, pub, fs=12, fill=BODY))
        o.append(BX(780, y, 400, 40, fill=WHITE, edge=LINE))
        o.append(TL(796, y + 25, act, fs=11.5, fill=BODY))
        o.append(_arrow_seg(480, y + 20, 500, y + 20, color=RED, sw=1.6))
        o.append(_arrow_seg(760, y + 20, 780, y + 20, color=INK, sw=1.4))
        y += 46
    o.append(TL(100, y + 10, "topic→队列名映射在 Nacos：doc/nacos/kaleido-mq.yml:11-15；消息可靠性/重试见稳定性专题 P28。", fs=11, fill=GRAY))
    return "\n".join(o)


# ============================================================
# P19 多级缓存
# ============================================================
def dg_cache():
    o = []
    o.append(BX(100, 200, 240, 44, fill=CARD, accent=True))
    o.append(TC(220, 227, "业务查询", fs=13, fill=INK, bold=True))
    o.append(BX(100, 270, 240, 44, fill=CARD, accent=True))
    o.append(TC(220, 297, "L1 Caffeine 本地缓存", fs=13, fill=INK, bold=True))
    o.append(BX(100, 340, 240, 44, fill=CARD, accent=True))
    o.append(TC(220, 367, "L2 Redis（JetCache）", fs=13, fill=INK, bold=True))
    o.append(BX(100, 410, 240, 44, fill=WHITE, edge=INK, sw=1.4))
    o.append(TC(220, 437, "MySQL / MongoDB", fs=13, fill=INK, bold=True))
    for x1, x2, y1, y2 in [(340, 340, 222, 270), (340, 340, 292, 340), (340, 340, 362, 410)]:
        o.append(_arrow_seg(340, y1, 340, y2, color=INK, sw=1.6))
    o.append(_arrow_seg(340, 432, 340, 410, color=RED, sw=1.6))  # 回源虚线？改实
    o.append(CHIP(356, 225, "未命中下探；回填两级缓存", fs=11, fill=GRAY))
    o.append(CHIP(356, 300, "@Cached 方法缓存开启", fs=11, fill=GRAY))
    o.append(CHIP(356, 372, "Redis database 11（nacos 配置）", fs=11, fill=GRAY))
    # 写链路
    o.append(BX(720, 200, 460, 44, fill=INK))
    o.append(TC(950, 227, "写路径：DB 先写 → 删缓存 → 延迟删除", fs=13, fill=WHITE, bold=True))
    o.append(BX(720, 270, 460, 130, fill=CARD))
    o.append(BUL(740, 296, [
        "DelayDeleteService：默认 2s 后删 JetCache 键（DelayDeleteService.java:29-31），规避" ,
        "写后瞬间读旧值的窗口问题",
        "RedissonService 能力：bucket / queue / map / lock /",
        "semaphore / bloomFilter / setNx 统一封装（RedissonService.java:14）",
    ], fs=11.5, gap=23))
    o.append(BX(720, 416, 460, 44, fill=WHITE, edge=LINE))
    o.append(TL(726, 432, "入口注解：@EnableMethodCache(basePackages='com.xiaoo.kaleido')", fs=10.5, fill=BODY))
    o.append(TL(726, 452, "注册见 RedisAutoConfiguration.java:15-18", fs=10.5, fill=BODY))
    o.append(TL(100, 500, "为什么两级：热点读走 Caffeine（微秒级、进程内），跨进程一致性交给 Redis；JetCache 负责方法级缓存声明与 Redisson 存储。", fs=11.5, fill=GRAY))
    return "\n".join(o)


# ============================================================
# P20 分布式锁
# ============================================================
def dg_lock():
    o = []
    o.append(BX(100, 210, 250, 46, fill=CARD, accent=True))
    o.append(TC(225, 238, "@DistributedLock", fs=13.5, fill=INK, bold=True))
    o.append(CHIP(110, 260, "key(SpEL) · waitTime", fs=10.5, fill=GRAY))
    o.append(CHIP(110, 278, "leaseTime=30 · lockType", fs=10.5, fill=GRAY))
    o.append(_arrow_seg(350, 233, 420, 233, color=RED, sw=1.8))
    o.append(BX(420, 210, 250, 46, fill=CARD, accent=True))
    o.append(TC(545, 238, "DistributedLockAspect", fs=13.5, fill=INK, bold=True))
    o.append(CHIP(430, 260, "@Around 加锁 / finally 解锁", fs=10.5, fill=GRAY))
    o.append(CHIP(430, 278, "键前缀 kaleido:lock:（:55）", fs=10.5, fill=GRAY))
    o.append(_arrow_seg(670, 233, 740, 233, color=RED, sw=1.8))
    o.append(BX(740, 210, 250, 46, fill=CARD, accent=True))
    o.append(TC(865, 238, "DistributedLockService", fs=13.5, fill=INK, bold=True))
    o.append(CHIP(750, 260, "Redisson RLock 家族映射", fs=10.5, fill=GRAY))
    o.append(CHIP(750, 278, "REENTRANT/FAIR/READ/WRITE/MULTI", fs=10.5, fill=GRAY))
    o.append(_arrow_seg(990, 233, 1040, 233, color=RED, sw=1.8))
    o.append(BX(1040, 210, 140, 46, fill=WHITE, edge=INK, sw=1.4))
    o.append(TC(1110, 238, "Redis", fs=13, fill=INK, bold=True))
    # 类型与看门狗
    o.append(BX(100, 330, 1080, 44, fill=INK))
    o.append(TC(640, 357, "锁类型映射（DistributedLockService.java:33-50）：getLock / getFairLock / readWriteLock().read/writeLock｜MULTI 需自行扩展（当前回退 getLock）", fs=12.5, fill=WHITE, bold=True))
    o.append(BUL(100, 402, [
        "实际使用 8 处：kaleido-coin CoinCommandService 7 处（key='coin:stream:'+#userId，覆盖 init/reward/扣费/提现等：35,54,73,92,111,137,164）+ recommend 1 处（'recommend:user:'+#userId：76）",
        "为什么锁+账本配套：CoinStream 流水以 bizType+bizId 幂等唯一，锁保证同用户并发扣费串行化（不超扣/不重复返利）",
        "看门狗续期由 Redisson 提供（默认 leaseTime 30s，临近过期自动续约），避免锁因业务超时提前释放 —— 框架能力，非自研",
    ], fs=12, gap=27))
    return "\n".join(o)


# ============================================================
# P21 数据访问层：MP + ShardingSphere
# ============================================================
def dg_ds():
    o = []
    o.append(BX(100, 205, 300, 130, fill=CARD, accent=True))
    o.append(TC(250, 232, "SQL → ShardingSphere Driver", fs=13.5, fill=INK, bold=True))
    o.append(CHIP(116, 262, "jdbc:shardingsphere:classpath:sharding.yaml", fs=10.5))
    o.append(CHIP(116, 284, "（kaleido-ds.yml:2-4）", fs=10.5))
    o.append(CHIP(116, 306, "分片键：user_id 取模", fs=11.5))
    o.append(_arrow_seg(400, 270, 470, 270, color=RED, sw=1.8))
    o.append(BX(470, 205, 330, 130, fill=CARD, accent=True))
    o.append(TC(635, 232, "CustomShardingAlgorithm", fs=13.5, fill=INK, bold=True))
    o.append(BUL(486, 258, [
        "totalTables = 8（2 库 × 4 表）",
        "库索引 = value % 8 / 4",
        "表后缀 = value % 8 % 4",
        "→ ds_{库}.{表}_{后缀}",
    ], fs=11.5, gap=21))
    o.append(_arrow_seg(800, 270, 870, 270, color=RED, sw=1.8))
    # 2 库 4 表网格
    o.append(BX(870, 205, 310, 130, fill=WHITE, edge=INK, sw=1.4))
    o.append(TC(1025, 230, "ds0 · ds1 × t0..t3", fs=13, fill=INK, bold=True))
    o.append(CHIP(886, 252, "kaleido_0：ds_0.t0..t3", fs=11))
    o.append(CHIP(886, 276, "kaleido_1：ds_1.t0..t3", fs=11))
    o.append(CHIP(886, 300, "双库见 doc/sql/kaleido.sql:2,1213", fs=10.5, fill=GRAY))
    o.append(BUL(100, 380, [
        "MyBatis-Plus 三拦截器：乐观锁（version）＋ 防全表更新 ＋ MySQL 分页（DataSourceAutoConfiguration.java:49-63）",
        "BasePO 审计字段（createTime/updateTime/…）由 MyMetaObjectHandler 自动填充；@MapperScan 扫 *.infrastructure.dao（:32-35）",
        "连接池 Druid 1.2.24；表结构：doc/sql/kaleido.sql 双库共 39 张业务表（含 AI 表 t_ai_agent / t_ai_agent_tool / t_ai_workflow / t_ai_conversation）",
    ], fs=12, gap=26))
    return "\n".join(o)


# ============================================================
# P24 限流三算法
# ============================================================
def dg_rlimit():
    panes = [
        ("令牌桶（本项目 @RateLimit 采用）", [
            "以固定速率向桶内放令牌，容量上限 B",
            "每个请求取 1 枚令牌，无令牌则拒绝/等待",
            "允许突发（桶满时积压令牌）",
            "Redisson RRateLimiter 实现",
        ], "允许短时突发"),
        ("漏桶（Leaky Bucket）", [
            "请求先入桶，以固定速率流出",
            "桶满则新请求被丢弃",
            "输出完全平滑，无突发",
            "适合保护下游恒定速率场景",
        ], "输出绝对平滑"),
        ("滑动窗口（Sentinel 默认计数模型之一）", [
            "把时间窗切成 N 个格子，滚动统计",
            "窗口内计数 ≥ 阈值则限流",
            "比固定窗口更平滑、无边界毛刺",
            "Sentinel 流控按 qps/线程数",
        ], "细粒度统计"),
    ]
    o = []
    o.append(BX(100, 190, 1080, 36, fill=INK))
    o.append(TC(640, 213, "三种限流模型对照（篇幅所限只讲核心差异）", fs=14, fill=WHITE, bold=True))
    x = 100
    for title, items, tag in panes:
        o.append(BX(x, 244, 340, 170, fill=CARD, accent=True))
        o.append(TC(x + 170, 270, title, fs=12.5, fill=INK, bold=True))
        o.append(BUL(x + 16, 292, items, fs=11, gap=20))
        o.append(BX(x, 428, 340, 28, fill=WHITE, edge=LINE))
        o.append(TC(x + 170, 447, tag, fs=11, fill=RED, bold=True))
        x += 370
    o.append(BX(100, 478, 1080, 62, fill=CARD))
    o.append(BUL(118, 500, [
        "本项目双落地：Sentinel 流控规则（集群/服务级，Nacos 下发，见 P26）＋ 自研 @RateLimit（单键精确令牌桶，基于 Redisson，见 P25）。",
        "取舍：Sentinel 负责入口与核心资源的通用限流；@RateLimit 用 SpEL 键做到「每个用户/手机号一个桶」，语义更细。",
    ], fs=12, gap=24))
    o.append(TL(100, 560, "补充概念：Sentinel 还支持并发线程数限流与排队等待模式；熔断/降级同框架实现（P26）。", fs=11, fill=GRAY))
    return "\n".join(o)


# ============================================================
# P25 @RateLimit 自研注解剖析
# ============================================================
def dg_rlimit_anno():
    o = []
    boxes = [
        ("业务方法", "@RateLimit(key='sms:mobile:'+#mobile, limit=1, window=60)", 0),
        ("RateLimitAspect", "@Around 解析 SpEL 键 → 前缀 kaleido:rate:limit:", 1),
        ("RateLimitService", "redisson.getRateLimiter(key) → trySetRate(OVERALL,limit,window)", 2),
        ("Redis 令牌桶", "rateLimiter.tryAcquire() 成功才放行业务", 3),
    ]
    w = 250
    x = 100
    for i, (t, sub, _) in enumerate(boxes):
        o.append(BX(x, 250, w, 92, fill=CARD if i < 3 else WHITE, edge=(None if i < 3 else INK), accent=(i == 0)))
        o.append(TC(x + w / 2, 278, t, fs=13.5, fill=INK, bold=True))
        o.append(TL(x + 12, 300, sub, fs=10, fill=BODY))
        if i < 3:
            o.append(_arrow_seg(x + w, 296, x + w + 30, 296, color=RED, sw=1.8))
        x += w + 30 + 20
    o.append(TL(100, 380, "实现要点：", fs=12.5, fill=INK, bold=True))
    o.append(BUL(100, 404, [
        "RateLimit 注解（limiter/annotation/RateLimit.java:11-35）：key 支持 SpEL、limit 次数、window 秒、message 拒绝提示",
        "切面 @Around(\"@annotation(rateLimit)\")：Redis 键 = kaleido:rate:limit:{SpEL 解析值}（RateLimitAspect.java:43-68）",
        "底层即 Redisson RRateLimiter 令牌桶：RateType.OVERALL（全局速率）+ tryAcquire 非阻塞获取（RateLimitService.java:33-38）",
    ], fs=12, gap=25))
    o.append(BX(100, 500, 1080, 60, fill=INK))
    o.append(TC(640, 524, "两个真实用例", fs=13, fill=WHITE, bold=True))
    o.append(CHIP(140, 548, "短信验证码：limit=1 / 60s（auth/SmsController.java:46）＋ 叠 @SentinelResource + @DistributedLock", fs=11.5, fill=LITE))
    o.append(CHIP(660, 548, "创建推荐：limit=5 / 60s（recommend/RecommendCommandService.java:75）", fs=11.5, fill=LITE))
    return "\n".join(o)


# ============================================================
# P26 Sentinel 流控与熔断降级
# ============================================================
def dg_sentinel():
    o = []
    o.append(BX(100, 190, 520, 150, fill=CARD, accent=True))
    o.append(TC(360, 216, "工作模型：资源 → 规则 → 插槽链", fs=13.5, fill=INK, bold=True))
    o.append(BUL(120, 240, [
        "埋点：@SentinelResource(value, blockHandler, fallback)",
        "规则：流控 flow / 熔断 degrade，经 Nacos",
        "数据源：${app}-sentinel-flow.json / -degrade.json",
        "dashboard：控制台可视化（kaleido-sentinel.yml:4-6）",
    ], fs=11.5, gap=21))
    o.append(BX(640, 190, 540, 150, fill=CARD, accent=True))
    o.append(TC(910, 216, "熔断状态机（限流之外的降级保护）", fs=13.5, fill=INK, bold=True))
    o.append(CHIP(660, 244, "CLOSED →(慢调用/异常比例/异常数超阈值)→ OPEN", fs=11.5))
    o.append(CHIP(660, 268, "OPEN →(熔断窗口结束)→ HALF_OPEN（放少量探测流量）", fs=11.5))
    o.append(CHIP(660, 292, "HALF_OPEN →(探测成功)→ CLOSED ｜ 失败则回到 OPEN", fs=11.5))
    o.append(CHIP(660, 316, "粒度可到：慢调用比例 / 异常比例 / 异常数（degrade 规则类型）", fs=11))
    # 项目接线
    o.append(BX(100, 366, 1080, 36, fill=INK))
    o.append(TC(640, 389, "本项目接入点：3 处 @SentinelResource（均含 blockHandler/fallback 本地降级方法）", fs=13.5, fill=WHITE, bold=True))
    o.append(BX(100, 424, 340, 66, fill=WHITE, edge=LINE))
    o.append(TC(270, 446, "auth / SmsController", fs=12, fill=INK, bold=True))
    o.append(CHIP(116, 470, "sendSmsCode（SmsController.java:40-45）", fs=10.5))
    o.append(BX(460, 424, 340, 66, fill=WHITE, edge=LINE))
    o.append(TC(630, 446, "wardrobe / ClothingController", fs=12, fill=INK, bold=True))
    o.append(CHIP(476, 470, "createClothing（ClothingController.java:46-51）", fs=10.5))
    o.append(BX(820, 424, 360, 66, fill=WHITE, edge=LINE))
    o.append(TC(1000, 446, "recommend / RecommendCommandService", fs=12, fill=INK, bold=True))
    o.append(CHIP(836, 470, "createRecommendRecord（:69-74）", fs=10.5))
    o.append(BUL(100, 526, [
        "依赖壳：kaleido-sentinel 引入 spring-cloud-starter-alibaba-sentinel + nacos 数据源（sentinel/pom.xml:22-42）",
        "降级兜底：GlobalExceptionHandler 反射识别 BlockException 统一处理（web/GlobalExceptionHandler.java:79-88）",
    ], fs=11.5, gap=22))
    return "\n".join(o)


# ============================================================
# P29 端到端可靠性复盘
# ============================================================
def dg_reliability():
    stages = [
        ("阶段 1 · 入口", "Sentinel 流控 + @RateLimit", "QPS 超限→本地 blockHandler 降级返回", "auth/wardrobe/recommend 埋点"),
        ("阶段 2 · 扣费", "@DistributedLock + bizId 幂等", "并发扣费串行化；重复流水被幂等拦下", "coin 账本 7 处锁"),
        ("阶段 3 · AI 异步", "MQ 解耦：recommend→ai", "工作流长时执行不阻塞用户请求", "outfit-recommend 工作流"),
        ("阶段 4 · 回执与重试", "消息落库 + 状态机 + XXL-Job", "失败进 FAILED/重试队列，避免消息丢失", "NoticeRetryJob 同款机制"),
    ]
    o = []
    o.append(BX(100, 190, 1080, 36, fill=INK))
    o.append(TC(640, 213, "一次「AI 推荐」全旅程的四道可靠性防线叠加", fs=14, fill=WHITE, bold=True))
    x = 100
    w = 250
    for i, (t, k, note, tag) in enumerate(stages):
        o.append(BX(x, 250, w, 150, fill=CARD, accent=True))
        o.append(TC(x + w / 2, 276, t, fs=13, fill=INK, bold=True))
        o.append(TC(x + w / 2, 302, k, fs=11.5, fill=RED, bold=True))
        o.append(BX(x + 10, 318, w - 20, 68, fill=WHITE, edge=LINE))
        o.append(TL(x + 18, 340, note[:16], fs=10.5, fill=BODY))
        o.append(TL(x + 18, 358, note[16:32], fs=10.5, fill=BODY))
        o.append(TL(x + 18, 376, tag, fs=9.5, fill=GRAY))
        if i < 3:
            o.append(_arrow_seg(x + w, 325, x + w + 20, 325, color=RED, sw=1.8))
        x += w + 20
    o.append(BUL(100, 436, [
        "单点不阻塞：AI 生成耗时（向量检索+LLM）被 MQ 拆到异步侧，用户请求只等「提交成功」",
        "失败可定位：recommend 记录状态机 PROCESSING→COMPLETED/FAILED（RecommendRecordStatusEnum.isFinalStatus:43）；消息侧 message 模块同款留痕",
        "最终一致：扣费成功但生成失败 → 回执 FAILED → 可退费/重试 —— 由幂等流水保证不会双扣",
    ], fs=12, gap=26))
    o.append(BX(100, 550, 1080, 40, fill=CARD))
    o.append(TC(640, 575, "结论：事件驱动 + 状态机 + 幂等 + 重试，把「长任务」做成「可靠异步编排」——这是本仓库最有价值的工程模式", fs=13, fill=INK, bold=True))
    return "\n".join(o)


# ============================================================
# P30 服装域领域模型
# ============================================================
def dg_domain():
    o = []
    o.append(BX(100, 196, 340, 210, fill=CARD, accent=True))
    o.append(TC(270, 222, "ClothingAggregate（聚合根）", fs=13.5, fill=INK, bold=True))
    o.append(BUL(118, 246, [
        "userId/name/typeCode/colorCode/",
        "seasonCode/size/price/description",
        "brandId · currentLocationId",
        "行为：changeLocation / addImages /",
        "setAsPrimaryImage / updateInfo",
    ], fs=11.5, gap=21))
    o.append(BX(120, 372, 300, 34, fill=WHITE, edge=LINE))
    o.append(TL(134, 394, "ClothingImage（1..10 张，isPrimary）", fs=11, fill=BODY))
    o.append(BX(460, 196, 300, 210, fill=CARD, accent=True))
    o.append(TC(610, 222, "OutfitAggregate（穿搭）", fs=13.5, fill=INK, bold=True))
    o.append(BUL(478, 246, [
        "wearCount · lastWornDate",
        "关联服装清单 OutfitClothing",
        "穿搭图片 OutfitImage",
        "行为：recordWear / compose",
        "创建扣金币（Dubbo→coin）",
    ], fs=11.5, gap=21))
    o.append(BX(780, 196, 400, 210, fill=CARD, accent=True))
    o.append(TC(980, 222, "LocationAggregate（存储位置）", fs=13.5, fill=INK, bold=True))
    o.append(BUL(798, 246, [
        "位置创建/挂载/标签关联；服装可换位置",
        "BrandAggregate（品牌）由 admin 侧管理、用户端只读",
    ], fs=12, gap=24))
    o.append(BX(780, 320, 400, 86, fill=WHITE, edge=LINE))
    o.append(TL(798, 348, "领域服务层：ClothingDomainService /", fs=11.5))
    o.append(TL(798, 370, "OutfitDomainService（编排聚合行为）", fs=11.5))
    o.append(BX(100, 440, 1080, 40, fill=INK))
    o.append(TC(640, 465, "分层骨架：trigger(controller/rpc/listener) → application(command/query) → domain(model/service/adapter) → infrastructure(dao/repository)", fs=13, fill=WHITE, bold=True))
    o.append(TL(100, 512, "事实：聚合类路径 domain/clothing|location|outfit/model/aggregate；仓储/DAO 在 infrastructure；跨域事件走 adapter/event → MQ（ClothingEvent）。全模块 114 个 Java 文件。", fs=11.5, fill=GRAY))
    return "\n".join(o)


# ============================================================
# P31 服装图片责任链
# ============================================================
def dg_chain():
    o = []
    handlers = [
        ("ValidationHandler", "校验 path 非空、顺序≥0\nisPrimary 默认 false"),
        ("MetadataExtractionHandler", "MinIO getImageInfo\n读宽高 / 大小 / mime"),
        ("ImageOptimizationHandler", ">1MB 标压缩、非 webp 标转格式\n（当前为模拟估算）"),
    ]
    x = 100
    o.append(BX(100, 196, 1080, 36, fill=INK))
    o.append(TC(640, 219, "统一图片处理链：Clothing / Location / Outfit 三类业务复用（模板方法 + 责任链 + 策略）", fs=13.5, fill=WHITE, bold=True))
    o.append(BX(100, 250, 300, 44, fill=CARD, accent=True))
    o.append(TC(250, 277, "FileService 入口（三业务各自实现）", fs=12, fill=INK, bold=True))
    o.append(_arrow_seg(400, 272, 450, 272, color=RED, sw=1.8))
    o.append(BX(450, 250, 300, 44, fill=CARD, accent=True))
    o.append(TC(600, 277, "UnifiedImageProcessingService（模板方法）", fs=12, fill=INK, bold=True))
    o.append(_arrow_seg(750, 272, 800, 272, color=RED, sw=1.8))
    o.append(BX(800, 250, 300, 44, fill=WHITE, edge=INK, sw=1.4))
    o.append(TC(950, 277, "ImageProcessingChainBuilder.process", fs=12, fill=INK, bold=True))
    x = 100
    for i, (t, note) in enumerate(handlers):
        o.append(BX(x, 330, 340, 120, fill=CARD if i < 2 else WHITE, edge=(None if i < 2 else INK), accent=(i == 0)))
        o.append(TC(x + 170, 356, t, fs=13.5, fill=INK, bold=True))
        for j, ln in enumerate(note.split("\n")):
            o.append(TL(x + 18, 384 + j * 22, ln, fs=11.5, fill=BODY))
        if i < 2:
            o.append(_arrow_seg(x + 340, 390, x + 370, 390, color=RED, sw=1.8))
        x += 370
    o.append(BX(100, 480, 1080, 40, fill=CARD))
    o.append(TC(640, 505, "装配证据：ImageProcessingChainBuilder.java:56-62（add 顺序 + setNext 串链）｜ Context 携带 basic→minio→processed 三段信息 + 错误位", fs=12, fill=BODY))
    o.append(BUL(100, 548, [
        "收尾策略：ImageConversionContext 按 DomainType(CLOTHING/LOCATION/OUTFIT) 选择转换策略，拼装各业务 DTO；mime → ImageTypeEnums 推文件类型",
        "诚实标注：压缩/转格式为模拟（ImageOptimizationHandler.java:58-82，simulateCompression 系数估算）——链路已预留真实执行位，是「待接入」非「已做真压缩」",
    ], fs=11.5, gap=24))
    return "\n".join(o)


# ============================================================
# P32 向量同步：服装 → Milvus
# ============================================================
def dg_vectorsync():
    o = []
    o.append(BX(100, 210, 300, 96, fill=CARD, accent=True))
    o.append(TC(250, 236, "kaleido-wardrobe", fs=14, fill=INK, bold=True))
    o.append(CHIP(116, 262, "服装 CREATE/UPDATE/DELETE", fs=11.5))
    o.append(CHIP(116, 284, "ClothingEventPublisherImpl:99,121", fs=10.5, fill=GRAY))
    o.append(_arrow_seg(400, 258, 460, 258, color=RED, sw=1.8))
    o.append(BX(460, 210, 320, 96, fill=CARD, accent=True))
    o.append(TC(620, 236, "RabbitMQ clothing-event", fs=14, fill=INK, bold=True))
    o.append(CHIP(476, 262, "topic=${topic.clothing-event}", fs=11.5))
    o.append(CHIP(476, 284, "（kaleido-mq.yml:11-15）", fs=10.5, fill=GRAY))
    o.append(_arrow_seg(780, 258, 840, 258, color=RED, sw=1.8))
    o.append(BX(840, 210, 340, 96, fill=CARD, accent=True))
    o.append(TC(1010, 236, "kaleido-ai ClothingEventListener", fs=14, fill=INK, bold=True))
    o.append(CHIP(856, 262, "@RabbitListener（:34）→ VectorService", fs=11.5))
    o.append(CHIP(856, 284, "handleCreate/Update/Delete（:54-63）", fs=10.5, fill=GRAY))
    o.append(_arrow_seg(1010, 306, 1010, 360, color=RED, sw=1.8))
    o.append(BX(840, 360, 340, 96, fill=WHITE, edge=INK, sw=1.4))
    o.append(TC(1010, 386, "Milvus kaleido_collection", fs=14, fill=INK, bold=True))
    o.append(CHIP(856, 412, "vectorStore.add / similaritySearch", fs=11.5))
    o.append(CHIP(856, 434, "dim 1536 · IVF_FLAT · COSINE", fs=10.5, fill=GRAY))
    o.append(BUL(100, 352, [
        "Embedding：BGE-M3（init_env.bat:23 EMBEDDING_MODEL=BAAI/bge-m3；kaleido-ai-dev.yml:23,51）",
        "ClothingDocumentRepositoryImpl.java:32 注入 MilvusVectorStore；检索按 userId / clothingId 过滤（:91,122,152）",
        "动机：服装入库/编辑/删除后向量库自动同步，保证「搭配检索」永远基于最新衣橱 —— 事件驱动 vs 轮询",
    ], fs=12, gap=26))
    return "\n".join(o)


# ============================================================
# P33 Agent 工厂与装配
# ============================================================
def dg_agent():
    o = []
    o.append(BX(100, 196, 260, 96, fill=CARD, accent=True))
    o.append(TC(230, 220, "DB：t_ai_agent / t_ai_agent_tool", fs=12, fill=INK, bold=True))
    o.append(CHIP(114, 246, "code/model_name/temperature/", fs=10.5))
    o.append(CHIP(114, 266, "max_tokens/system_prompt/tools", fs=10.5))
    o.append(_arrow_seg(360, 244, 420, 244, color=RED, sw=1.8))
    o.append(BX(420, 196, 300, 96, fill=CARD, accent=True))
    o.append(TC(570, 220, "AgentFactory 注册中心", fs=13, fill=INK, bold=True))
    o.append(CHIP(436, 246, "Caffeine 缓存 agent→ChatClient", fs=10.5))
    o.append(CHIP(436, 266, "system_default 默认单例（:34,185-195）", fs=10.5))
    o.append(_arrow_seg(720, 244, 780, 244, color=RED, sw=1.8))
    o.append(BX(780, 196, 400, 96, fill=CARD, accent=True))
    o.append(TC(980, 220, "AgentChatClientArmory 组装", fs=13, fill=INK, bold=True))
    o.append(CHIP(796, 246, "createChatClient(agent)（:64-82）", fs=10.5))
    o.append(CHIP(796, 266, "无参时回退 spring.ai 配置 / deepseek-v3", fs=10.5))
    # 三装配行
    o.append(BX(100, 320, 340, 46, fill=CARD))
    o.append(TC(270, 346, "ChatModel：OpenAI 兼容 API", fs=12.5, fill=INK, bold=True))
    o.append(BX(460, 320, 340, 46, fill=CARD))
    o.append(TC(630, 346, "Advisor：记忆 / RAG（按工具自动挂）", fs=12.5, fill=INK, bold=True))
    o.append(BX(820, 320, 360, 46, fill=CARD))
    o.append(TC(1000, 346, "工具：MEMORY · VECTOR_STORE · MCP", fs=12.5, fill=INK, bold=True))
    o.append(BUL(100, 396, [
        "模型来源：base-url=${AI_BASE_URL} api-key=${AI_API_KEY} model=${CHAT_MODEL}（kaleido-ai-dev.yml:16-23）；默认环境指向硅基流动 + deepseek-ai/DeepSeek-V3（init_env.bat:20-22）",
        "MEMORY → MessageChatMemoryAdvisor（maxMessages 默认 200，MemoryConfig.java:20）；MCP → McpSyncClient + SyncMcpToolCallbackProvider（baseUri http://localhost:9021，/sse）",
        "RAG：Agent 含 VECTOR_STORE 工具时 ChatServiceImpl 挂 RAG advisor，filter=userId==当前用户（ChatServiceImpl.java:73-99）——私有衣橱检索隔离",
        "生命周期：admin 启停 Agent → Dubbo → AgentCommandService → agentFactory.register/unregister（AgentCommandService.java:56-58）",
    ], fs=12, gap=24))
    return "\n".join(o)


# ============================================================
# P34 AI 穿搭推荐内容链路
# ============================================================
def dg_aireco():
    o = []
    steps = [
        ("提示词进入", "recommend 存 prompt\nDubbo→ai"),
        ("工作流调度", "OutfitRecommendWorkflowExecutor\ncode=OUTFIT_RECOMMEND"),
        ("向量检索", "Milvus similaritySearch\ntopK=100 · 阈值 0.0"),
        ("LLM 生成", "DeepSeek-V3 按衣橱\n产出搭配方案 JSON"),
        ("事件回执", "发布完成事件\n→ recommend"),
        ("落库穿搭", "创建 Outfit + 回写\nCOMPLETED"),
    ]
    x = 100
    o.append(BX(100, 190, 1080, 34, fill=INK))
    o.append(TC(640, 213, "「智能穿搭推荐」的生成内容链路（P10 旅程的 AI 内部视角）", fs=13.5, fill=WHITE, bold=True))
    for i, (t, sub) in enumerate(steps):
        o.append(BX(x, 250, 160, 92, fill=CARD, edge=LINE, accent=(i in (2, 3))))
        o.append(TC(x + 80, 276, t, fs=12, fill=INK, bold=True))
        o.append(TL(x + 10, 300, sub.split("\n")[0], fs=10.5, fill=BODY))
        o.append(TL(x + 10, 318, sub.split("\n")[1], fs=10.5, fill=BODY))
        if i < 5:
            o.append(_arrow_seg(x + 160, 296, x + 188, 296, color=RED, sw=1.8))
        x += 188
    o.append(BUL(100, 376, [
        "检索限定「我的衣橱」：Milvus 相似度搜索按 userId(+clothingId) 过滤（ClothingDocumentRepositoryImpl.java:66,94,122,152），返回服装文档再交给 LLM 组搭",
        "参数默认：topK=100、similarityThreshold=0.0（VectorStoreConfig.java:20,32）—— 先召回后由模型精筛，而非硬阈值截断",
        "向量数据来自服装文档（名称/类型/颜色/季节等文本段）而非图像向量 —— embedding 模型 BGE-M3 1536 维",
        "编排归属：ai 侧 WorkflowCommandService 管理工作流与执行记录（t_ai_workflow / t_ai_workflow_execution 表）",
    ], fs=12, gap=24))
    o.append(BX(100, 500, 1080, 44, fill=CARD))
    o.append(TC(640, 527, "小结：RAG 是「检索增强生成」在衣橱场景的落地——先按语义找对衣服，再让 LLM 做搭配推理与文案生成", fs=13, fill=INK, bold=True))
    return "\n".join(o)
