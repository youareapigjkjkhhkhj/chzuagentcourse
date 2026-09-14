"""离线课程桩（P1-G2）：让 MockLLM 在没有网络、没有密钥时产出一门**完整课程**。

`mock.py` 里那份 `_fill`（照着 JSON Schema 填样例值）在 P0 够用 —— 那时只需要
「输出是合法 JSON」。到了 P1 不够了：管线要的是「12 页课，每页 3 条要点、
3 个 beat、测验四个选项」，而 `_fill` 给的是 `示例文本`、`示例文本`、`示例文本`——
结构合法，内容像一句复读，`parse_page` 之后的相似度检查（P1-E5）会直接判它不合格。

所以这里补上另一半：**按提示词里的任务头分派，产出符合 Schema 的课程内容**。

三条纪律：

1. **确定性**。同一个输入永远同一个输出（`MockLLM` 的既有承诺）。
   索引一律用 `_stable_index()` 从文本算，不用 `hash()` —— 后者在 Python 里
   每个进程都加了随机盐，同一个脚本跑两次会得到两门不同的课，
   而「验收脚本这次过了、下次不过」是最贵的一种 bug。
2. **内容跟着主题走**。章节名、页标题、讲稿都从主题与本章标题里长出来，
   不是「示例文本 A/B/C」。桩数据要能被人眼看一眼就说「这是那门课」，
   否则页面上一堆占位文字，验收时根本看不出管线有没有把主题传对。
3. **只认任务头分派**。任务头是提示词里那行机器可读的 `【任务】{…}`
   （见 `prompts.task_header`）—— 它是管线与桩之间唯一的约定。
   **不认识的调用返回 None**，由 `MockLLM` 回落到 `_fill`：P0 的老用例
   （拿一个任意 schema 来要 JSON）照样能过。
   唯一的例外是工作台那一轮（`_plan`）：那句提示词是手写的、没有任务头，
   所以按形状认（`_PLAN_MARK`）。例外只有这一个，而且 `_is_plan` 要求
   两个小标题同时出现 —— 不拿「出现过某个词」当判据。

它不是「更聪明的假模型」：写页的提示词里给的受众、大纲、上一页要点，
这里一概不读 —— 那是在复刻提示词工程，桩只需要产出**结构合格、彼此不同**的内容。
"""

from __future__ import annotations

import json
import re
import zlib
from collections.abc import Callable
from typing import Any, Mapping, Sequence

#: 任务头那一行。字段都在一行里（`task_header` 就是这么拼的），
#: 所以按行取就够了 —— 用 `.*?` 配非贪婪的回车，比解析整个花括号更稳。
_TASK = re.compile(r"【任务】(\{.*?\})\s*$", re.M)

#: 主题（`wrap_user_text(topic, label="TOPIC")` 的围栏）。
_TOPIC = re.compile(r"<<<TOPIC>>>\s*(.*?)\s*<<<END_TOPIC>>>", re.S)

#: 大纲那句「建议 3 章左右，正文合计约 6 页」。
#:
#: 桩**不去重算**页数预算：那是 `prompts.page_budget` 的活，重算一份就是
#: 同一件事的两个真相。这里读的是提示词自己许下的数字，而
#: `tests/unit/test_generation_fixture.py` 钉住了「它一定许得出来」——
#: 哪天那句话改了措辞，测试会当场报，而不是悄悄退化成 3 章 2 页。
_OUTLINE_PLAN = re.compile(r"建议\s*(\d+)\s*章左右，正文合计约\s*(\d+)\s*页")

#: 重写这一页时，提示词里带着这一页现在的样子（JSON）。标题就从那儿取。
_CURRENT_TITLE = re.compile(r'"title"\s*:\s*"([^"]*)"')

#: 提示词里的材料围栏（`prompts.material_block`）。一片一块，块头带 chunkId。
_MATERIAL_BLOCK = re.compile(
    r"<<<MATERIAL chunk:(?P<id>[^>]+)>>>\n(?P<body>.*?)\n<<<END>>>", re.S
)

#: 围栏正文开头那行出处小字（`prompts._material_caption`）。**它不是材料原文**，
#: 引文不能从它里面抄 —— 抄了就去 `page_sources` 里落一段材料上根本没有的话。
_MATERIAL_CAPTION = re.compile(r"^（出处：[^）]*）\s*")

#: 认得出「这一页讲的就是材料里这一段」所需的最短重合字数。
_MATERIAL_KEY_MIN = 2

#: 退到「切片」来找时，一片至少这么长。四字以下的重合（「的核心」）到处都是，
#: 拿它当依据等于随机指一段原文 —— 那比找不到更糟。
_MATERIAL_SLICE_MIN = 4

#: 一个标题最多试多少个切片候选。标题都很短，这只是给「万一很长」兜个底。
_MATERIAL_SLICE_MAX = 40

#: 没读到大纲那句时的兜底：3 章 × 每章 2 页。宁可给一份小的，也不给空的。
_FALLBACK_PLAN = (3, 6)

#: 章标题的样式。索引由章节号决定，所以第 2 章永远是「核心方法」——
#: 同一门课两次生成的章名一致，验收脚本才能照着名字去找那一章。
_CHAPTER_LABELS: tuple[str, ...] = (
    "认识{topic}",
    "{topic}的核心方法",
    "{topic}的常见误区",
    "{topic}的进阶用法",
    "{topic}的综合运用",
    "{topic}的动手实践",
)

#: 章内各页的落点。每章两页，正好取前两个（大纲里页数变了也不会越界）。
_PAGE_LABELS: tuple[str, ...] = (
    "先看整体",
    "一步一步拆开",
    "看一个例子",
    "最容易错的地方",
    "换一个场景",
    "把这一章收个尾",
)

#: 上面两套模板里**不含 `{topic}`** 的那部分（「的核心方法」「先看整体」…）。
#: 页标题是 `章标签：页标签` 拼出来的，判断「材料写没写这一页」时只能看
#: `{topic}` 那一截 —— 模板碎片是本桩自己写上去的，材料里当然也可能有
#: （任何一份讲义都有「核心方法」这个词），拿它当依据等于自己骗自己。
#: 长的排前面：「的核心方法」要先去，否则先去掉「核心方法」会剩下一个孤零零
#: 的「的」。
_BOILERPLATE: tuple[str, ...] = tuple(
    sorted(
        tuple(label.replace("{topic}", "") for label in _CHAPTER_LABELS) + _PAGE_LABELS,
        key=len,
        reverse=True,
    )
)

#: 正文页型循环。**只用 CONTENT_KINDS**：封面、大纲页、测验页、小结、
#: 研讨页由管线按排版规则补齐（`store.allocate_pages`），桩排它们只会重复。
#: 循环而不是随机：同一章里页型自然就错开了，不会连着三页都是概念讲解。
_CONTENT_CYCLE: tuple[str, ...] = ("concept", "example", "figure", "concept")

#: 讲稿句式（初稿）。每句都带本页标题，所以一页页翻过去不是同一句话复读。
_BEATS_DRAFT: tuple[str, ...] = (
    "我们从一个熟悉的场景说起：{title}其实就在身边。",
    "这一页只讲一件事，把{title}说清楚。",
    "先记住结论，再看它是怎么一步步推出来的。",
    "如果这里卡住了，回头看一眼上一页的要点。",
)

#: 讲稿句式（重写）。与初稿**句句不同** —— P1-A7 量的是「重写后讲稿变化率」，
#: 桩要是把原话再吐一遍，这条验收就永远是绿的，等于没测。
#: 三组轮换，选哪组由指令算出来：换个指令就换一种说法，
#: 但同一个指令永远得到同一版（确定性）。
_BEATS_REWRITE: tuple[tuple[str, ...], ...] = (
    (
        "换个说法：{title}可以先当成生活里的一个例子。",
        "别急着记结论，先想想它想解决什么麻烦。",
        "把这一步想成做菜：先备料，再下锅，最后调味。",
        "到这里停一下，用自己的话把刚才那句说一遍。",
    ),
    (
        "我们换个角度再看一遍{title}，这次从结果倒着推。",
        "你会发现中间那一步才是关键，其余都是铺垫。",
        "把这个过程画成三个格子，每个格子只写一句话。",
        "现在合上书，试着把它讲给同桌听。",
    ),
    (
        "把{title}放到一个具体场景里，它立刻就清楚了。",
        "先说结论：它解决的问题比它的做法更重要。",
        "再看做法，无非是把大问题拆成几个小问题。",
        "最后留一个问题给你，我们下一节接着讲。",
    ),
)

_BULLET_BANK: tuple[str, ...] = (
    "先看清{topic}要解决的那个问题",
    "把{title}拆成几步，每一步都有明确的输入与输出",
    # 带一条内联公式：要点里的 `$…$` 与主图共用同一个排版引擎，
    # 这条路离线也得走过一次（见 `_visual_of` 的同一条理由）
    "记住{title}的结论 $y = kx + b$，再看它是怎么来的",
    "留意{title}最容易出错的地方",
    "想想{title}和上一页的关系",
)

_BULLET_BANK_REWRITE: tuple[str, ...] = (
    "{title}：一句话版本，先记住它",
    "它解决的问题，比它的做法更值得记住",
    "拆成三步之后，每一步都能单独验证",
    "这里有个反直觉的地方，正是最容易错的点",
)

_QUESTION_BANK: tuple[str, ...] = (
    "如果把「{chapter}」里的条件换掉一个，结论还成立吗？",
    "请用「{chapter}」里的概念，解释一个你身边的例子。",
    "有人不同意「{chapter}」的做法，你会怎么回应？",
)

#: 课堂桩：三条倾向 → 说话的样子。**与 `seeds/roles.py` 的 `tendency` 对齐**，
#: 也与 `services/classroom/prompts.py` 的 `TENDENCY_LABELS` 说同一件事。
#: 三种说法都是学生口吻、都能过 P3-E4（不出现「作为一个 AI」），
#: 也都带本页标题 —— 一句话提到眼前这一页，人工判「相关性」时才有的可判。
_TENDENCY_STYLES: Mapping[str, Mapping[str, Any]] = {
    "question": {
        "type": "question",
        "bank": (
            "老师，这里为什么要先做「{title}」这一步？跳过它后面还成立吗？",
            "我有个疑问：如果「{title}」里的条件是别的样子，结论会不会反过来？",
            "没跟上「{title}」这一步，能再举个更简单的例子吗？",
        ),
    },
    "supplement": {
        "type": "supplement",
        "bank": (
            "我想到另一个角度：「{title}」也可以看成把大问题先拆小，再逐个验证。",
            "补一句，我觉得「{title}」的关键在中间那一步，两头都是铺垫。",
            "这里我想提个反例：条件稍微变一下，「{title}」就不一定成立了。",
        ),
    },
    "reflect": {
        "type": "reflect",
        "bank": (
            "我复述一下：刚说的是「{title}」，我理解得对吗？那接下来是看例子吗？",
            "用我自己的话说，「{title}」就是先定目标再分步做，是不是这个意思？",
            "所以「{title}」可以理解成一句话：先看清楚要解决什么，对吗？",
        ),
    },
}

#: 课堂桩：老师收尾讨论时用的几句。轮数不同说法不同，免得连着两轮像复读。
_TEACHER_TURNS: tuple[str, ...] = (
    "大家说的都有道理。回到这一章的主线：先把问题定义清楚，再谈做法。",
    "这个讨论先收一收。记住刚才那个分歧，我们后面的例子里还会遇到。",
    "对，这一步值得停一下。把你们说的归纳成一句话，就是先定标准再动手。",
)

#: 课堂桩：板书认得的那几个工具。
_BOARD_TOOLS = ("polyline", "curve", "text", "arrow", "rect", "ellipse")

#: 板书计划里的一笔：`- 第 1 笔：工具「text」，要画的是：…`
_BOARD_PLAN_LINE = re.compile(r"^- 第\s*\d+\s*笔：工具「(?P<tool>[^」]*)」，要画的是：(?P<desc>.*)$", re.M)

#: 人设行：`- 林晓（code: xiaoxiao）「好奇、爱提问」 倾向：提问：…。…`
_PERSONA_LINE = re.compile(r"^-\s*(?P<name>[^（(]+)[（(]code:\s*(?P<code>[^）)]+)[）)](?P<rest>.*)$", re.M)

#: 人设行尾那段「倾向：…」到哪一类。提到哪个词就算哪一类，判不出来按补充。
_TENDENCY_WORDS: tuple[tuple[str, str], ...] = (
    ("复述反问", "reflect"),
    ("提问", "question"),
    ("补充", "supplement"),
)

#: 离线桩的内容不求专业，但求「一看就知道是桩」。这一行写在讲稿里没有意义
#: （学生不该看到），所以放在副标题上：验收时肉眼一眼就能分辨。
_SUBTITLE_KINDS: Mapping[str, str] = {
    "cover": "从入门到会用",
    "outline": "这一门课要讲什么",
    "concept": "先把概念讲清楚",
    "figure": "看图理解",
    "example": "看一个具体的例子",
    "code": "动手写一遍",
    "quiz": "检验一下刚才听懂了没有",
    "summary": "回顾与思考",
    "debate": "两种立场，你站哪边",
}


def answer(messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any] | None) -> dict | None:
    """给这次调用造一份内容。**认不出任务的返回 None**（由调用方回落）。"""
    if schema is None:
        return None
    task = _task_of(messages)
    builder = _BUILDERS.get(str(task.get("task") or ""))
    if builder is None and _is_plan(messages):
        return _plan(messages)  # 工作台那次没有任务头，按形状认（见 `_PLAN_MARK`）
    return builder(task, messages) if builder else None


# --- 四步各自的产物 ---


def _profile(topic: str) -> dict:
    """受众画像。字段与 `schema.AudienceProfile` 对齐。"""
    return {
        "audience": "大学低年级学生",
        "difficulty": "入门",
        "durationMin": 25,
        "chapterCount": _FALLBACK_PLAN[0],
        "style": "口语化、多举例，每页留一个思考点",
        "objectives": [
            f"说清「{topic}」要解决什么问题",
            f"能用自己的话复述「{topic}」的关键步骤",
            f"知道「{topic}」最容易出错的地方",
        ],
    }


def _outline(topic: str, messages: Sequence[Mapping[str, Any]]) -> dict:
    """课程大纲。章数与每章页数照提示词许下的预算来。"""
    chapters_wanted, content_wanted = _plan_of(messages)
    # 正文页均分给各章，除不尽的从第一章起各多一页 —— 各章相加正好是总数，
    # 每章至少 1 页（一章没有正文页，`parse_outline` 会把整章丢掉）
    base, extra = divmod(max(content_wanted, chapters_wanted), chapters_wanted)

    chapters: list[dict] = []
    for no in range(1, chapters_wanted + 1):
        count = max(1, base + (1 if no <= extra else 0))
        label = _chapter_label(topic, no)
        pages = [
            {"title": f"{label}：{_PAGE_LABELS[index % len(_PAGE_LABELS)]}",
             "kind": _CONTENT_CYCLE[index % len(_CONTENT_CYCLE)]}
            for index in range(count)
        ]
        chapters.append(
            {
                "no": no,
                "title": f"第 {no} 章 · {label}",
                "summary": f"这一章解决「{label}」，一共 {len(pages)} 页。",
                "points": [
                    f"「{label}」里哪一步最难理解？",
                    f"如果让你用「{label}」解释一个身边的现象，你会怎么说？",
                ],
                "pages": pages,
            }
        )
    return {
        "title": f"{topic}：一门离线示例课",
        "subtitle": "由离线桩生成，用于在没有模型的机器上跑通全流程",
        "chapters": chapters,
    }


def _visual_of(title: str) -> dict[str, Any]:
    """这一页配的图。三种轮着来。

    **三种都要真出一次**：离线桩也走「spec → SVG」，验收环境没有外网、
    也没有模型，桩要是只会画流程图，曲线与公式这两条路在离线就是没跑过的 ——
    「离线全绿、上线第一页就露馅」。轮换按标题算，所以同一门课每次跑
    拿到的是同一批图（见模块 docstring 第 1 条）。
    """
    desc = f"一张关于「{title}」的示意图"
    kind = _stable_index(title, 3)
    if kind == 0:
        return {
            "type": "diagram",
            "desc": desc + "：左边画输入，右边画输出的变化",
            "spec": {
                "rows": [
                    [{"text": "输入", "shape": "box"}, {"text": title[:8] or "处理", "shape": "box", "accent": True}],
                    [{"text": "判断", "shape": "diamond"}, {"text": "输出", "shape": "box"}],
                ],
                "edges": [
                    {"from": [0, 0], "to": [0, 1]},
                    {"from": [0, 1], "to": [1, 0]},
                    {"from": [1, 0], "to": [1, 1], "label": "通过"},
                ],
            },
        }
    if kind == 1:
        # 带可调参数：滑块这条路只有真跑过一次才知道有没有画出来
        return {
            "type": "plot",
            "desc": desc + f"：{title}随步长变化的两条曲线，可以拖动滑块看参数的影响",
            "spec": {
                "title": title[:16],
                "xlabel": "x",
                "ylabel": "y",
                "xrange": [0, 6.28],
                "params": [{"name": "k", "label": "系数 k", "values": [0.5, 1, 2]}],
                "curves": [
                    {"expr": "sin(k*x)", "label": "sin(kx)"},
                    {"expr": "k*x/6.28", "label": "k·x"},
                ],
            },
        }
    return {
        "type": "formula",
        "desc": desc + "：把这一页的核心关系写成一个式子",
        "spec": {
            "tex": r"\sigma(z) = \frac{1}{1 + e^{-z}}",
            "caption": title[:20],
        },
    }


def _page(task: Mapping[str, Any], messages: Sequence[Mapping[str, Any]]) -> dict:
    """一页内容。页型决定要补哪些字段，通用字段每页都有。"""
    kind = str(task.get("kind") or "concept")
    rewriting = str(task.get("task") or "") == "rewrite"
    title = str(task.get("title") or "").strip() or _current_title(messages)
    topic = _topic_of(messages) or title

    beats = _BEATS_REWRITE[_stable_index(_instruction_of(messages), len(_BEATS_REWRITE))] if rewriting else _BEATS_DRAFT
    bullets = _BULLET_BANK_REWRITE if rewriting else _BULLET_BANK

    page: dict[str, Any] = {
        "title": title,
        "subtitle": _SUBTITLE_KINDS.get(kind, "这一页讲什么"),
        "bullets": [
            {"text": template.format(title=title, topic=topic)} for template in bullets
        ],
        "narration": [
            {"text": template.format(title=title)} for template in beats
        ],
        "visual": _visual_of(title),
    }
    sources, gaps = _citation(kind, title, messages)
    page["sources"] = sources
    page["gaps"] = gaps

    if kind == "cover":
        page["subtitle"] = f"{topic} · {_SUBTITLE_KINDS['cover']}"
        page["meta"] = {
            "lecturer": "沈老师",
            "durationMin": 25,
            "audience": "大学低年级学生",
        }
    elif kind == "outline":
        page["chapters"] = _outline_page_chapters(topic, messages)
    elif kind == "example":
        page["steps"] = [
            f"第一步：把「{title}」的输入写清楚",
            "第二步：按顺序做一遍，每一步都别跳",
            "第三步：回头验证结果对不对",
        ]
    elif kind == "code":
        page["code"] = {
            "lang": "python",
            "content": (
                "# 离线桩给的示例代码，只为让页面结构完整\n"
                f"def demo():\n"
                f'    """{title}"""\n'
                "    return 'ok'\n"
            ),
        }
        page["explanation"] = [
            "第一行只是占位，真正的代码由真实模型写",
            "注意函数名与返回值都写全，前端才画得出来",
        ]
    elif kind == "quiz":
        page["quiz"] = _quiz(title, topic)
    elif kind == "summary":
        page["question"] = f"如果要你用一句话向同学解释「{topic}」，你会怎么说？"
        page["bullets"] = [
            {"text": f"这一门课的线索是「{topic}」"},
            {"text": "每一页的结论都挂在同一个问题上"},
            {"text": "回去把讲稿再读一遍，比记笔记有用"},
        ]
    elif kind == "debate":
        page["topic"] = f"「{title}」该不该成为必修内容？"
        page["sides"] = [
            {
                "stance": "正方：应该先讲清楚它的原理",
                "points": ["原理讲透了，后面的用法自己就能推", "换一个场景也不会失效"],
            },
            {
                "stance": "反方：应该先上手做，再回头补原理",
                "points": ["先做出来才有的可讨论", "兴趣来自做成的那一刻"],
            },
        ]
        page["arbiterSummary"] = "两种立场都有道理，取决于这节课想把学生带到哪里。"
    return page


#: 会「讲知识」的页型。只有这几种才谈得上「依据材料 / 材料没写」——
#: 封面、大纲页、测验题、小结这些要么是结构、要么是题目本身，
#: 它们本来就不该有出处（§5：没有依据的页留空 sources 即可）。
_CITING_KINDS: frozenset[str] = frozenset({"concept", "example", "code", "debate"})


def _material_chunks(messages: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """这次提示词里给了哪几片材料 → `[(chunkId, 正文)]`（顺序就是给的顺序）。"""
    found: list[tuple[str, str]] = []
    for block in _MATERIAL_BLOCK.finditer(_user_text(messages)):
        body = _MATERIAL_CAPTION.sub("", block.group("body")).strip()
        if body:
            found.append((block.group("id").strip(), body))
    return found


def _squeeze(text: str) -> str:
    """只留字，去掉空白与标点。**与 `materials.citations` 同一把尺子**：
    那边核对引文时就是这么比的，这里先按同一把尺子决定「材料里有没有这句话」。"""
    return re.sub(r"[\s\W_]+", "", str(text or ""))


def _quote_at(body: str, at: int, span: int = 60) -> str:
    """从材料原文里切一段连续的引文（`at` 是命中处）。**切出来的一定是原文**，
    不是拼的句子 —— 拼的话它就不是引文，`citations.verify` 会当场判它不通过。"""
    start = max(0, at - 10)
    quote = body[start : start + span].strip()
    if len(_squeeze(quote)) < 20:  # 核对要求 ≥ 20 字，短了就往前多带一点
        quote = body[:span].strip()
    return quote


def _citation(kind: str, title: str, messages: Sequence[Mapping[str, Any]]) -> tuple[list[dict], list[str]]:
    """给这一页配出处（F4-8）或说出缺口（P4-A8）。

    规则一句话：**这一页的标题在材料里出现过就引它，没出现就说材料没写**。

    这条规则比真模型蠢得多，但它是**同一个岔口**的两条路 —— 离线验收要验的
    正是这个岔口分得对不对（A5「要点能在材料里找到依据」与 A8「缺口显式化」），
    而不是桩有多聪明。规则里没有随机：同一份材料、同一页标题，结果永远一样。

    标题先整句找，找不到再退到「：」后面那半句、再退到最长的那个中文词 ——
    页标题常常是「倒排索引：为什么不能逐个扫」这种，整句在材料里未必连在一起。
    """
    if kind not in _CITING_KINDS:
        return [], []
    chunks = _material_chunks(messages)
    if not chunks:
        return [], []  # 这次没给材料：与 P1 一样，不说「材料没写」（本来就没材料）

    for key in _title_keys(title):
        for chunk_id, body in chunks:
            at = body.find(key)
            if at >= 0:
                return [{"chunkId": chunk_id, "quote": _quote_at(body, at)}], []
    # 一片都没命中：**说出来**，而不是让模型（这里是桩）凭常识编一段看不出来的话
    return [], [f"材料未涉及「{title}」，这一页按通用讲解写"]


def _strip_boilerplate(title: str) -> str:
    """去掉标题里**本桩自己拼上去**的那几个模板碎片（`_BOILERPLATE`）。

    拿「的核心方法」当依据，找到的是材料碰巧也有一个叫「核心方法」的小节，
    与这一页讲什么毫无关系：一门「量子计算入门」的课，页面会引到
    「梯度下降的核心方法」上去 —— 章标签是 `{topic}的核心方法`，
    桩没看 `{topic}`，只看中了自己写的那半截。

    去掉之后剩下的就是这一页的**题目本身**（「量子计算入门」），那才是能拿来
    判断「材料写没写」的东西。
    """
    for fragment in _BOILERPLATE:
        title = title.replace(fragment, "，")
    return title.strip("， ") if title.strip("， ") else ""


def _title_keys(title: str) -> list[str]:
    """页标题 → 拿来在材料里找的几个候选词（长的优先，短的兜底）。

    为什么要一路退到**切片**：页标题是管线自己拼的（「认识梯度下降：先看整体」
    这种 —— 章标签加页标签），材料里当然不会有这么一句。可真人不就是这么找的
    吗：整句找不到，就往短了退，退到「梯度下降」为止。不这么做，离线跑出来
    每一页都报「材料没写」，A5/A8 那两条岔路其实只有一条被人走过。

    退的**起点**是去掉模板碎片之后的那截（见 `_strip_boilerplate`）—— 否则
    退到「核心方法」这种自己写的词上，命中与否全是巧合。整句仍然留着：
    它真出现在材料里就是最强的证据，只是机器拼的标题几乎不会。

    退到底线是 `_MATERIAL_SLICE_MIN` 个字：再短下去（「的核心」）会在材料里
    到处命中，那就不是依据，是随机指一段原文。
    """
    text = str(title or "").strip()
    if not text:
        return []
    keys = [text]
    subject = _strip_boilerplate(text)
    for sep in ("：", ":", "——", "·", "，"):
        if sep in subject:
            keys.extend(part.strip() for part in subject.split(sep))
    # 中文连排里最长的一段：标题里的关键词通常就在那里（切片也从它切）
    longest = max(re.findall(r"[一-鿿]+", subject) or [""], key=len)
    keys.append(longest)
    keys.extend(_title_slices(longest))

    seen: list[str] = []
    for key in sorted((k for k in keys if len(k) >= _MATERIAL_KEY_MIN), key=len, reverse=True):
        if key not in seen:
            seen.append(key)
    return seen


def _title_slices(run: str) -> list[str]:
    """一个中文长串的连续切片（长片在前，同长按出现位置）。"""
    found: list[str] = []
    limit = min(len(run), 8)  # 长片已经由整句那几条覆盖了，这里从 8 字往下切
    for size in range(limit, _MATERIAL_SLICE_MIN - 1, -1):
        for start in range(len(run) - size + 1):
            found.append(run[start : start + size])
            if len(found) >= _MATERIAL_SLICE_MAX:
                return found
    return found


def _interjection(task: Mapping[str, Any], messages: Sequence[Mapping[str, Any]]) -> dict:
    """同学插话：**从提示词给的人设里挑一位**，按他的倾向说一句。

    挑谁不随机 —— 由页号决定（`_stable_index`）。验收脚本要能在「第几页该谁说话」
    这件事上得到可复现的结果，否则 P3-A3 的「抽 5 条人工判定」每次抽到的人都不同。
    说话内容里带本页标题，这样两条插话天然不像（P3-E2）。
    """
    people = _personas_of(messages)
    if not people:
        return {"speakerCode": "xiaoxiao", "text": "老师，这里我还是没太跟上。",
                "type": "question", "trigger": "concept_midway"}

    page_no = int(task.get("pageNo") or 0)
    speaker = people[_stable_index(f"page:{page_no}", len(people))]
    style = _TENDENCY_STYLES.get(speaker["tendency"], _TENDENCY_STYLES["supplement"])
    sentences = style["bank"]
    text = sentences[_stable_index(f"page:{page_no}:{speaker['code']}", len(sentences))].format(
        title=_page_title_of(messages)
    )
    return {
        "speakerCode": speaker["code"],
        "text": text,
        "type": style["type"],
        "trigger": f"第 {page_no} 页讲到一半",
    }


def _discussion_turn(task: Mapping[str, Any], messages: Sequence[Mapping[str, Any]]) -> dict:
    """章末讨论的一轮：这轮轮到谁，就按谁的口吻说。"""
    question = _line_of(messages, "【讨论题】") or "这一章讲的内容"
    round_no = int(task.get("round") or 1)
    people = _personas_of(messages)
    speaker = people[0] if people else {"code": "", "tendency": "supplement", "role": "student"}
    is_teacher = str(speaker.get("role") or "") == "teacher"
    index = _stable_index(f"{question}:{speaker['code']}:{round_no}", 3)

    bank: Sequence[str]
    if is_teacher:
        bank = _TEACHER_TURNS
        kind = "comment"
    else:
        style = _TENDENCY_STYLES.get(speaker["tendency"], _TENDENCY_STYLES["supplement"])
        # 讨论这一轮的「话题」就是讨论题本身 —— 三句句式里的 `{title}` 填它，
        # 说出来的就是「刚说的是『为什么先定标准再动手？』，我理解得对吗？」
        bank = [item.format(title=question) for item in style["bank"]]
        kind = style["type"]
    return {"text": bank[index % len(bank)], "type": kind}


def _answer(messages: Sequence[Mapping[str, Any]]) -> dict:
    """教师答疑。回答里要**带上学生问的那件事**，否则人工评分（P3-E3）无从谈起。

    引导的收束那一步（提示词里有 `ORIGINAL` 围栏）要走另一套话术：**先接住
    学生自己想出来的那半截**，再补全 —— 桩也要把这层差别演出来，不然「引导」
    在离线验收里和「直接答疑」长得一模一样。
    """
    lines = _fenced(messages, "QUESTION").splitlines()
    asked = lines[0].strip() if lines else ""
    title = _page_title_of(messages)
    key = _first_point(messages)
    original = _fenced(messages, "ORIGINAL").splitlines()
    if original:
        first = original[0].strip()
        body = (
            f"你说的「{asked[:32]}」——这一步是对的，抓的就是它。"
            f"回到你一开始问的「{first[:28]}」：{key or title}，"
            f"把这一步接上去，整条就通了。"
        )
    elif asked:
        body = (
            f"你问的是「{asked[:40]}」。放到这一页来看，{key or title}——"
            f"所以先按刚才讲的那一步来做，遇到特殊情况我们再单独说。"
        )
    else:
        body = f"这个问题先记着。就「{title}」来说，{key or '先抓住结论再回头看推导'}。"
    return {"text": body, "followUp": f"你可以自己找一个例子，套一下「{title}」试试。"}


def _scaffold(messages: Sequence[Mapping[str, Any]]) -> dict:
    """引导模式下的那句反问。

    **必须是一句真问句**（句尾带问号）：离线验收要能一眼看出「老师没有直接
    给答案」，说成一句陈述句就白测了。
    """
    lines = _fenced(messages, "QUESTION").splitlines()
    asked = lines[0].strip() if lines else ""
    title = _page_title_of(messages)
    if asked:
        text = f"先别急着要结论 —— 你觉得「{asked[:24]}」的关键在哪一步？"
    else:
        text = f"就「{title}」来说，你先说说自己卡在哪一步？"
    return {"text": text}


def _board(messages: Sequence[Mapping[str, Any]]) -> dict:
    """板书画笔：把【板书计划】里每一笔翻译成一条指令，**顺序保持、位置错开**。

    布局按行往下排（`0.18 + 0.16 * i`）：桩不知道画什么好看，
    但它必须保证笔画**不会全叠在同一个点上** —— 叠在一起的板书看着像没画。
    """
    plan = _plan_lines(messages)
    strokes: list[dict] = []
    for index, item in enumerate(plan):
        y = round(min(0.18 + 0.16 * index, 0.86), 4)
        tool = item["tool"] if item["tool"] in _BOARD_TOOLS else "polyline"
        if tool == "text":
            strokes.append(
                {"tool": "text", "points": [[0.12, y]], "text": _label_of(item["desc"]), "durMs": 600}
            )
        elif tool == "arrow":
            strokes.append({"tool": "arrow", "points": [[0.12, y], [0.62, y]], "durMs": 800})
        elif tool == "curve":
            strokes.append(
                {"tool": "curve", "points": [[0.12, y], [0.36, y - 0.06], [0.62, y]], "durMs": 900}
            )
        else:
            strokes.append({"tool": "polyline", "points": [[0.12, y], [0.62, y]], "durMs": 800})
    return {"strokes": strokes}


def _discussion(messages: Sequence[Mapping[str, Any]]) -> dict:
    """章末讨论问题。章节标题就在提示词的【第 N 章】那一行里。"""
    chapter = ""
    for line in _user_text(messages).splitlines():
        if line.startswith("【第 ") and "章】" in line:
            chapter = line.split("章】", 1)[1].strip()
            break
    name = chapter or "这一章"
    return {"questions": [template.format(chapter=name) for template in _QUESTION_BANK]}


# --- 工作台那一次（P4-F4-10） ---


#: 工作台这一次的提示词是**手写**的（`workbench.agent._plan_messages`），
#: 没有 `【任务】{…}` 那一行 —— 桩不能因为它没长成别人的样子就不认它，
#: 否则离线跑工作台时永远只有一句 `reply`、一个技能都不调，
#: `agent.skill` / `agent.skill_done` 这两帧就从来没被人看见过。
#: 所以这里按形状认：两个小标题同时在，才算一张计划。
_PLAN_MARK = "【可用技能】"
_PLAN_TEXT = re.compile(r"^【用户这句话】\n(?P<text>.*?)(?:\n\s*\n|\Z)", re.S | re.M)
_PLAN_PAGE = re.compile(r"^【用户正看着】第\s*(\d+)\s*页", re.M)

#: 老师这句话里的意图 → 一个技能。**长词在前**：先认「加一页」再认「一页」。
#: 这是桩唯一读语义的地方，规则写得直白 —— 认不出就不调技能，
#: 与提示词里叮嘱真模型的那句「能一句话说清的事就不要调技能」是一个口径。
_PLAN_INTENTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("删掉", "删除", "删了", "去掉这一页", "去掉这页"), "remove_page"),
    (("加一页", "插一页", "补一页", "再加一页", "新增一页"), "add_page"),
    (("测验", "出题", "考题", "考一下"), "add_quiz"),
    (("大纲", "章节标题", "章标题"), "revise_outline"),
    (("材料", "出处", "溯源", "原文"), "summarize_material"),
    (("口语", "学术", "通俗", "正式", "语气", "轻松"), "change_tone"),
    (("重写", "改写", "改一下", "改改", "换个说法", "重讲"), "rewrite_page"),
)

#: 技能 → 说给用户听的那句话。`{page}` 是「第 N 页」，`{ask}` 是老师原话的短写。
_PLAN_REPLIES: Mapping[str, str] = {
    "rewrite_page": "好的，我把{page}按「{ask}」重写一遍，讲稿跟着一起改。",
    "add_page": "行，我在{page}后面插一页，讲什么按你说的来。",
    "remove_page": "好，{page}删掉，后面的页号顺延。",
    "add_quiz": "我在这一章末尾加一道随堂测验，考的就是刚才讲的这几点。",
    "revise_outline": "我只改大纲上这一章的写法，页面内容先不动。",
    "change_tone": "我把这几页的语气调一下，内容不变。",
    "summarize_material": "我翻一下关联的材料，把相关的那几段找出来说给你听，带上出处。",
}


def _is_plan(messages: Sequence[Mapping[str, Any]]) -> bool:
    """这是工作台那一次吗（见 `_PLAN_MARK`）。"""
    text = _user_text(messages)
    return _PLAN_MARK in text and _PLAN_TEXT.search(text) is not None


def _plan(messages: Sequence[Mapping[str, Any]]) -> dict:
    """这一轮说什么、要调哪个技能（F4-10）。

    桩只做一件事：**认得出老师这句话想干什么就调对应的技能，认不出就不调**。
    所以离线也能看到完整的链路 —— 操作卡从 `agent.skill` 开始转圈、
    到 `agent.skill_done` 填上结果，而不是永远只有一句回复。
    """
    found = _PLAN_TEXT.search(_user_text(messages))
    text = (found.group("text") if found else "").strip()
    page_no = int(match.group(1)) if (match := _PLAN_PAGE.search(_user_text(messages))) else 0
    name = _plan_skill(text)
    action = _plan_action(name, text, page_no)
    reply = _PLAN_REPLIES.get(name, "这句我先不动课程。{ask}").format(
        page=f"第 {page_no} 页" if page_no else "这一页", ask=_short(text)
    )
    return {"reply": reply, "actions": [action] if action else []}


def _plan_skill(text: str) -> str:
    """老师这句话要对上哪个技能。**认不出返回空串**，由调用方给一句不调技能的回复。"""
    for words, name in _PLAN_INTENTS:
        if any(word in text for word in words):
            return name
    return ""


def _plan_action(name: str, text: str, page_no: int) -> dict | None:
    """技能的参数。页号缺省用「用户正看着」的那一页 —— 提示词就是这么叮嘱的。"""
    if not name:
        return None
    args: dict[str, Any] = {}
    if name == "remove_page":
        args = {"pageNo": page_no} if page_no else {}
    elif name == "add_page":
        args = {"afterPageNo": page_no, "instruction": text} if page_no else {"instruction": text}
    elif name == "add_quiz":
        args = {}
    elif name == "revise_outline":
        args = {"summary": f"按「{_short(text)}」调整后的本章说明。"}
    elif name == "summarize_material":
        args = {"query": text}
    elif name == "change_tone":
        args = {"tone": _tone_of(text)}
        if page_no:
            args["pageNos"] = [page_no]
    elif name == "rewrite_page":
        args = {"pageNo": page_no, "instruction": text} if page_no else {"instruction": text}
    return {"skill": name, "args": args, "why": f"老师说：{_short(text)}"}


def _tone_of(text: str) -> str:
    """「更口语一点」要的是哪种语气。三种之外一律给最常用的那种。"""
    if "学术" in text or "正式" in text:
        return "更学术"
    if "通俗" in text or "轻松" in text:
        return "更通俗"
    return "更口语"


def _short(text: str, limit: int = 24) -> str:
    """一句话的短写：回复里要引用老师原话，但不能把整段话抄进去。"""
    flat = " ".join(str(text or "").split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


# --- 小工具 ---


def _task_of(messages: Sequence[Mapping[str, Any]]) -> dict:
    """取任务头。解析不了就当没带（返回空字典 → 上层回落）。"""
    found = _TASK.search(_user_text(messages))
    if not found:
        return {}
    try:
        parsed = json.loads(found.group(1))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _topic_of(messages: Sequence[Mapping[str, Any]]) -> str:
    """取主题。围栏里可能有多行，取第一行做短名。"""
    found = _TOPIC.search(_user_text(messages))
    text = (found.group(1) if found else "").strip()
    return text.splitlines()[0].strip() if text else ""


def _user_text(messages: Sequence[Mapping[str, Any]]) -> str:
    """最后一条用户消息。提示词的一切（任务头、主题、章节）都在它里面。"""
    for message in reversed(list(messages)):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def _instruction_of(messages: Sequence[Mapping[str, Any]]) -> str:
    """重写指令（`wrap_user_text(instruction, label="改写要求")` 的围栏）。"""
    found = re.search(r"<<<改写要求>>>\s*(.*?)\s*<<<END_改写要求>>>", _user_text(messages), re.S)
    return (found.group(1).strip() if found else "")


def _current_title(messages: Sequence[Mapping[str, Any]]) -> str:
    """重写时，从提示词里那份「这一页现在的样子」中取回标题。

    取不到就等 `_page` 的调用方判失败 —— 返回空标题会让 `parse_page` 报
    「缺少必填字段 title」，那是一个能看懂的错误。
    """
    found = _CURRENT_TITLE.search(_user_text(messages))
    return (found.group(1).strip() if found else "")


def _plan_of(messages: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """提示词许下的「几章、几页正文」。读不到就用兜底值。"""
    found = _OUTLINE_PLAN.search(_user_text(messages))
    if not found:
        return _FALLBACK_PLAN
    return max(1, int(found.group(1))), max(1, int(found.group(2)))


def _outline_page_chapters(topic: str, messages: Sequence[Mapping[str, Any]]) -> list[dict]:
    """大纲页上那份章节目录。页号是示意值 —— 它不参与任何校验。"""
    chapters_wanted, _ = _plan_of(messages)
    return [
        {
            "no": no,
            "title": f"第 {no} 章 · {_chapter_label(topic, no)}",
            "pages": [no * 2, no * 2 + 1],
        }
        for no in range(1, chapters_wanted + 1)
    ]


def _chapter_label(topic: str, no: int) -> str:
    return _CHAPTER_LABELS[(no - 1) % len(_CHAPTER_LABELS)].format(topic=topic)


def _quiz(title: str, topic: str) -> dict:
    """一道四选一。四个选项都在，答案与解析对得上（P1-A6 / P1-E4）。"""
    options = [
        f"它先解决「{title}」想要回答的那个问题",
        "它只在不常见的特殊情况下才成立",
        "它和后一页要讲的结论互相矛盾",
        "它必须依赖额外的工具才能使用",
    ]
    return {
        "stem": f"关于「{title}」，下面哪一种说法是对的？",
        "options": options,
        "answer": options[0],
        "explain": "其余三个选项要么只在特例里成立，要么与前面的结论冲突。",
        "conceptTag": topic or title,
    }


def _personas_of(messages: Sequence[Mapping[str, Any]]) -> list[dict]:
    """提示词里那份人设卡（【可选的人设】下面那几行）。

    返回 `[{code, name, tendency, role}]`。`role` 由倾向推不出来，
    所以讨论轮里用它判断「这轮是不是老师」时只能看这一行里有没有老师特有的说法 ——
    这里用「人设行里带没带『主讲老师』」来认（`seeds/roles.py` 的 systemHint 里有）。
    """
    people: list[dict] = []
    for found in _PERSONA_LINE.finditer(_user_text(messages)):
        rest = found.group("rest")
        tendency = "supplement"
        for word, name in _TENDENCY_WORDS:
            if word in rest:
                tendency = name
                break
        people.append(
            {
                "code": found.group("code").strip(),
                "name": found.group("name").strip(),
                "tendency": tendency,
                "role": "teacher" if "主讲老师" in rest else "student",
            }
        )
    return people


def _page_title_of(messages: Sequence[Mapping[str, Any]]) -> str:
    """【当前页】那一行里的标题。`第 3 页 · concept · 先看整体` → `先看整体`。"""
    line = _line_of(messages, "【当前页】")
    if not line:
        return "这一页"
    parts = [part.strip() for part in line.split("·")]
    return parts[-1] if parts and parts[-1] else "这一页"


def _first_point(messages: Sequence[Mapping[str, Any]]) -> str:
    """【本页要点】里的第一条（分号隔开）。"""
    line = _line_of(messages, "【本页要点】")
    return line.split("；")[0].strip() if line else ""


def _label_of(desc: str, limit: int = 12) -> str:
    """板书上写的那几个字。整句 desc 写上去，白板就成了 PPT。"""
    text = " ".join(str(desc or "").split())
    return text[:limit] if text else "要点"


def _plan_lines(messages: Sequence[Mapping[str, Any]]) -> list[dict]:
    """【板书计划】里的一项一行。"""
    return [
        {"tool": found.group("tool").strip(), "desc": found.group("desc").strip()}
        for found in _BOARD_PLAN_LINE.finditer(_user_text(messages))
    ]


def _fenced(messages: Sequence[Mapping[str, Any]], label: str) -> str:
    """取围栏里的原文（`wrap_user_text(text, label=…)` 拼出来的那块）。"""
    found = re.search(
        rf"<<<{re.escape(label)}>>>\s*(.*?)\s*<<<END_{re.escape(label)}>>>",
        _user_text(messages),
        re.S,
    )
    return found.group(1).strip() if found else ""


def _line_of(messages: Sequence[Mapping[str, Any]], prefix: str) -> str:
    """带前缀那一行的正文：`【讨论题】X` 取 `X`，`【本页要点】X；Y` 取 `X；Y`。"""
    for line in _user_text(messages).splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _stable_index(text: str, size: int) -> int:
    """把一段文本稳定地映射到 `0..size-1`。

    不用内置 `hash()`：它对 str 每个进程加一次随机盐（PYTHONHASHSEED），
    同一个输入在不同进程里会给出不同的值 —— 桩就不再是确定的了。
    CRC32 没有这个问题，而且够短。
    """
    if size <= 1:
        return 0
    return zlib.crc32(text.encode("utf-8")) % size


#: 任务名 → 造内容的函数。做成表而不是一长串 `if`：
#: 「桩认得哪些任务」成了一个能被读、被断言的集合，而不是散在函数体里。
#: 前五个是 P1 生成课用的，后五个是 P3 **讲课当中**用的（它们必须又短又快，
#: 而且不能出现「示例文本」—— 一句话被播出去就是要被人听见的）。
_BUILDERS: dict[
    str, Callable[[Mapping[str, Any], Sequence[Mapping[str, Any]]], dict | None]
] = {
    "profile": lambda task, messages: _profile(_topic_of(messages)),
    "outline": lambda task, messages: _outline(_topic_of(messages), messages),
    "page": _page,
    "rewrite": _page,
    "discussion": lambda task, messages: _discussion(messages),
    "interjection": _interjection,
    "discussion_turn": _discussion_turn,
    "answer": lambda task, messages: _answer(messages),
    "scaffold": lambda task, messages: _scaffold(messages),
    "board": lambda task, messages: _board(messages),
}

__all__ = ["answer"]
