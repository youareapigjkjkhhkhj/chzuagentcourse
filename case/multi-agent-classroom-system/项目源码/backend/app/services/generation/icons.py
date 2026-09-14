"""语义图标：给流程图节点配一枚线描小图标（纯 SVG 路径、确定性）。

为什么要有图标：节点只有文字时，整张图就是「一堆长得一样的方框」——同一门
课每一页的配图没有区别。按**节点文字里的关键词**配一枚图标（太阳、叶绿体、
水滴、分子、能量……），图立刻有了「这一格讲的是什么」的视觉锚点。

图标是 SVG 路径，所以前端预览、PPTX、HTML、PDF 四边都画得出来 —— 不像动画
只能活在能跑 CSS 的地方（见 `visual.py` 模块注释里「导出取静态帧」那条）。

图标画在 24×24 的盒子里、线描（stroke 继承自外层 `<g>`），这里只给路径：
颜色跟着节点走（强调节点用强调色）、尺寸跟着格子走，都由 `diagram` 决定。
"""

from __future__ import annotations

__all__ = ["NAMES", "match", "pick", "render"]

#: 24×24 线描图标。子元素**不写** fill/stroke —— 一律继承外层 `<g>` 的，
#: 这样换色只改一个属性，不会出现「半个图标换了色半个没换」。
_ICONS: dict[str, str] = {
    "sun": '<circle cx="12" cy="12" r="4"/>'
           '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
           'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "cell": '<ellipse cx="12" cy="12" rx="9" ry="6"/>'
            '<path d="M7 10c2 1.5 8 1.5 10 0M7 14c2-1.5 8-1.5 10 0"/>',
    "leaf": '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.5 19 2c1 2 2 4.2 2 8'
            '0 5.5-4.8 10-10 10Z"/><path d="M2 21c0-3 1.9-5.4 5.1-6"/>',
    "bolt": '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8Z"/>',
    "molecule": '<circle cx="5" cy="12" r="2.6"/><circle cx="19" cy="12" r="2.6"/>'
                '<circle cx="12" cy="12" r="2.2"/><path d="M7.6 12h2.2M14.2 12h2.2"/>',
    "bubble": '<circle cx="9" cy="13" r="5"/><circle cx="16.5" cy="9" r="3.5"/>',
    "drop": '<path d="M12 2.7 17.7 8.4a8 8 0 1 1-11.3 0Z"/>',
    "sugar": '<path d="M12 2l8 5v10l-8 5-8-5V7Z"/>',
    "sprout": '<path d="M12 22V9"/><path d="M12 9C12 5 9 2 5 2c0 4 3 7 7 7Z"/>'
              '<path d="M12 13c0-4 3-7 7-7 0 4-3 7-7 7Z"/>',
    "cycle": '<path d="M17 2l4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/>'
             '<path d="M7 22l-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
    "flask": '<path d="M9 2h6"/><path d="M10 2v6l-5 9a3 3 0 0 0 3 4h8a3 3 0 0 0 3-4l-5-9V2"/>',
    "gear": '<circle cx="12" cy="12" r="3"/>'
            '<path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1'
            'M4.9 19.1 7 17M17 7l2.1-2.1"/>',
    "chart": '<path d="M3 3v18h18"/><path d="M7 14l3-3 4 4 5-6"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/>'
              '<circle cx="12" cy="12" r="1.4"/>',
    "bulb": '<path d="M9 18h6"/><path d="M10 22h4"/>'
            '<path d="M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0 0 12 2Z"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>'
            '<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/>',
    "cloud": '<path d="M17.5 19a4.5 4.5 0 1 0 0-9h-1.8A7 7 0 1 0 4 14.9"/>',
    "factory": '<path d="M2 20h20"/><path d="M4 20V8l6 4V8l6 4V4h4v16"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>'
             '<ellipse cx="12" cy="12" rx="4" ry="9"/>',
    "coin": '<circle cx="12" cy="12" r="9"/><path d="M12 6v12"/>'
            '<path d="M15 9a3 3 0 0 0-3-2c-1.7 0-3 .9-3 2.2 0 3 6 1.8 6 4.6 0 1.3-1.3 2.2-3 2.2a3 3 0 0 1-3-2"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/>'
             '<path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/>'
             '<circle cx="17" cy="9" r="3"/><path d="M17.5 14c2.8.3 4.5 2.4 4.5 5"/>',
    "chip": '<rect x="6" y="6" width="12" height="12" rx="2"/>'
            '<path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "scale": '<path d="M12 3v18"/><path d="M8 21h8"/><path d="M4 7h16"/>'
             '<path d="M6 7l-3 6a3 3 0 0 0 6 0Z"/><path d="M18 7l-3 6a3 3 0 0 0 6 0Z"/>',
    "heart": '<path d="M12 21s-7-4.6-9.5-9A5.5 5.5 0 0 1 12 6a5.5 5.5 0 0 1 9.5 6'
             'c-2.5 4.4-9.5 9-9.5 9Z"/>',
    "brain": '<path d="M9 3a3 3 0 0 0-3 3 3 3 0 0 0-2 3c0 1 .4 1.9 1 2.5A3.5 3.5 0 0 0 7 18'
             'a3 3 0 0 0 5 1V4a1 1 0 0 0-1-1Z"/>'
             '<path d="M15 3a3 3 0 0 1 3 3 3 3 0 0 1 2 3c0 1-.4 1.9-1 2.5A3.5 3.5 0 0 1 17 18'
             'a3 3 0 0 1-5 1V4a1 1 0 0 1 1-1Z"/>',
    "shield": '<path d="M12 2l8 3v6c0 5-3.5 9.3-8 11-4.5-1.7-8-6-8-11V5Z"/>',
}

#: 关键词 → 图标。匹配用「**最长关键词命中**」打分（见 `match`），所以这里的
#: 顺序只在同分时作 tie-break；把更具体的词写全（「光反应」三字）比靠顺序抢更稳。
#: 词表覆盖常见学科，让非生物主题（地理 / 经济 / 计算 / 法律 / 健康……）也配得到。
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sun", ("太阳", "光反应", "光能", "光照", "light", "sun")),
    ("cell", ("叶绿体", "类囊体", "细胞", "chloroplast", "thylakoid", "cell")),
    ("leaf", ("光合", "叶", "leaf", "photosyn")),
    ("bolt", ("atp", "nadph", "能量", "电", "energy")),
    ("molecule", ("co2", "二氧化碳", "碳", "分子", "carbon", "molecule")),
    ("bubble", ("o2", "氧", "oxygen")),
    ("drop", ("水", "h2o", "滴", "water")),
    ("sugar", ("糖", "葡萄", "淀粉", "sugar", "glucose", "starch")),
    ("sprout", ("植物", "生长", "苗", "plant", "grow")),
    ("cycle", ("循环", "往返", "再生", "cycle", "loop")),
    ("flask", ("实验", "反应", "化学", "试剂", "experiment", "reaction", "chem")),
    ("gear", ("机制", "过程", "mechanism", "process")),
    ("chart", ("数据", "曲线", "统计", "增长", "data", "chart", "graph")),
    ("target", ("目标", "重点", "关键", "goal", "target")),
    ("bulb", ("原理", "想法", "要点", "idea", "principle")),
    ("book", ("概念", "定义", "理论", "concept", "definition", "theory")),
    ("cloud", ("云", "大气", "cloud", "atmosphere")),
    ("factory", ("工业", "生产", "制造", "factory", "production")),
    ("clock", ("时间", "周期", "time", "clock")),
    ("globe", ("世界", "地理", "地球", "全球", "国际", "globe", "earth", "world", "geo")),
    ("coin", ("经济", "货币", "成本", "价格", "金融", "钱", "money", "cost", "price", "econ", "currency")),
    ("users", ("社会", "人群", "用户", "学生", "群体", "人口", "团队", "society", "people", "user", "population", "team")),
    ("chip", ("计算机", "芯片", "算法", "程序", "代码", "计算", "computer", "chip", "cpu", "algorithm", "code", "comput")),
    ("scale", ("法律", "公正", "权衡", "正义", "law", "legal", "justice", "balance")),
    ("heart", ("健康", "心脏", "身体", "医", "health", "heart", "medical")),
    ("brain", ("心理", "思维", "认知", "记忆", "大脑", "brain", "mind", "cognit", "memory")),
    ("shield", ("安全", "防护", "风险", "security", "safe", "shield", "risk")),
)

#: 全部图标名。给生成提示词列清单用（`prompts`），也让调用方能校验显式给的 icon。
NAMES: tuple[str, ...] = tuple(_ICONS)


def match(text: str) -> str | None:
    """节点文字 → 图标名；认不出返回 None（那格就只画文字，不硬配一个错的）。

    打分制：**命中的关键词越长越优先**（「光反应」三字压过「反应」两字），
    同分取词表里靠前的那条。比「按顺序第一个命中」稳 —— 词表增删不用重排顺序。
    """
    low = str(text or "").lower()
    if not low:
        return None
    best_key: str | None = None
    best_score = 0
    for key, keywords in _RULES:
        for keyword in keywords:
            if keyword in low and len(keyword) > best_score:
                best_key, best_score = key, len(keyword)
    return best_key


def pick(explicit: str | None, text: str) -> str | None:
    """定图标：模型显式给的 `icon` 优先（它懂任何学科的语义），认不得或没给
    就退回按文字关键词猜。两条路都认不出返回 None。
    """
    key = str(explicit or "").strip().lower()
    if key in _ICONS:
        return key
    return match(text)


def render(key: str, cx: float, cy: float, size: float, color: str) -> str:
    """把 24×24 的图标放到 (cx, cy)、缩到 size、着 color；认不得的 key 返回空串。"""
    body = _ICONS.get(key)
    if not body or size <= 0:
        return ""
    scale = round(size / 24, 4)
    x = round(cx - size / 2, 1)
    y = round(cy - size / 2, 1)
    return (
        f'<g class="dg-icon" transform="translate({x},{y}) scale({scale})" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</g>'
    )
