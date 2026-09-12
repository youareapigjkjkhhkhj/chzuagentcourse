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

它不是「更聪明的假模型」：写页的提示词里给的受众、大纲、上一页要点，
这里一概不读 —— 那是在复刻提示词工程，桩只需要产出**结构合格、彼此不同**的内容。
"""

from __future__ import annotations

import json
import re
import zlib
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
    "记住{title}的结论，再看它是怎么来的",
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
    name = str(task.get("task") or "")
    if name == "profile":
        return _profile(_topic_of(messages))
    if name == "outline":
        return _outline(_topic_of(messages), messages)
    if name in {"page", "rewrite"}:
        return _page(task, messages)
    if name == "discussion":
        return _discussion(messages)
    return None


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
        "visual": {
            "type": "diagram",
            "desc": f"一张关于「{title}」的示意图：左边画输入，右边画输出的变化",
        },
    }

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


def _discussion(messages: Sequence[Mapping[str, Any]]) -> dict:
    """章末讨论问题。章节标题就在提示词的【第 N 章】那一行里。"""
    chapter = ""
    for line in _user_text(messages).splitlines():
        if line.startswith("【第 ") and "章】" in line:
            chapter = line.split("章】", 1)[1].strip()
            break
    name = chapter or "这一章"
    return {"questions": [template.format(chapter=name) for template in _QUESTION_BANK]}


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


def _stable_index(text: str, size: int) -> int:
    """把一段文本稳定地映射到 `0..size-1`。

    不用内置 `hash()`：它对 str 每个进程加一次随机盐（PYTHONHASHSEED），
    同一个输入在不同进程里会给出不同的值 —— 桩就不再是确定的了。
    CRC32 没有这个问题，而且够短。
    """
    if size <= 1:
        return 0
    return zlib.crc32(text.encode("utf-8")) % size


__all__ = ["answer"]
