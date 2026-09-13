"""分词与倒排索引（F4-4 / P4-C5）。

**不引入向量库**（AGENTS §20 已定）：一门课的材料是几十到几百块，中文分词 +
BM25 足够把命中的段落捞回来，而向量库要多一个模型、多一份显存/内存、多一次
网络或本地推理 —— 换来的召回提升在「用户自己传的讲义」这个场景里并不明显
（材料内术语一致，用户查的往往就是讲义里的原话）。

三件事在这里定下来：

1. **索引里留单字**。「的」「是」这类单字当然没用，但 BM25 的 IDF 本来就会把
   它们压到接近 0；而「熵」「谱」这种单字是真术语，砍掉就再也搜不到了。
   代价是倒排表大一截 —— 这是我们在「召回」与「体积」之间明确选的那一边。
2. **停用词只删「一定没有信息量」的那些**，且可以由用户加：把
   `stopwords.txt` 放进材料根目录即可（一行一个词），`userdict.txt` 同理，
   用来加学科术语（jieba 会把「过拟合」切成「过」「拟合」，加了词典才是一个词）。
3. **`df` 按「一份材料」算，检索时相加**。一份块只属于一份材料，所以跨材料
   检索时「各自的 df 之和」正好等于「合并语料上的 df」—— 不用为了跨材料检索
   重新扫一遍全表（P4-D3 的 200ms 就靠这条）。

自定义词典是**进程级**的（jieba 的实现如此）：加载一次之后不再重载，换词典
要重启进程。这对部署没影响（词典是运维资产，不是用户数据），但不写下来
容易让人以为「改完文件下一次解析就生效」。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from app.common.logging import get_logger
from app.services.materials import policy

logger = get_logger("app.materials.indexer")

#: 关键词的列宽（`chunk_keywords.keyword`）。jieba 切不出这么长的词，
#: 这里只是防止「一整段没有标点的英文」被当成一个词写进库。
KEYWORD_MAX_CHARS = 64

#: 内置停用词。刻意保持小：只收「删掉一定不损失信息」的词 ——
#: 代词、连接词、语气词、最常见的动词与量词。像「问题」「方法」这种
#: 词频高但**有学科含义**的词一律留着（用户查「这个方法的问题在哪」时，
#: 真正能区分块的往往就是它们）。
STOPWORDS: frozenset[str] = frozenset(
    """
    的 了 是 在 和 与 及 或 而 但 也 就 都 很 还 又 再 更 最 太 才 只 把 被 让 给 对 从 到 于 由 向 往 朝 为 以 之
    其 该 这 那 这个 那个 这些 那些 这样 那样 这么 那么 这里 那里 什么 怎么 怎样 为什么 哪 哪些 哪个 谁 多少
    我 你 他 她 它 我们 你们 他们 她们 它们 自己 大家 咱们 本人 对方
    有 没有 无 不 没 未 别 好 可以 可能 应该 需要 必须 能够 会 能 要 想 让 使 得 着 过 起 来 去 上 下 里 外 中
    一个 一些 一种 一样 一直 一般 一定 一起 一次 一下 一点 一切 各种 各个 每 各 些 个 种 次 遍 点 条 只 件 张
    因为 所以 因此 于是 但是 不过 然而 而且 并且 或者 如果 假如 虽然 即使 只要 只有 除了 关于 对于 至于 按照 根据
    时候 现在 已经 曾经 正在 将要 刚才 后来 然后 最后 首先 其次 接着 总之 例如 比如 等 等等 之类 以及 还有 另外
    其实 确实 当然 也许 大概 差不多 基本 主要 非常 十分 特别 比较 相当 更加 尤其 甚至 反正 究竟 到底
    进行 存在 具有 属于 包括 包含 通过 使用 采用 利用 得到 获得 成为 作为 认为 觉得 知道 了解 看到 发现
    这 那 呢 吗 吧 啊 呀 哦 嗯 哈 唉
    the a an and or but if of to in on at by for with from as is are was were be been being this that these those
    it its they them their we our you your he she his her i me my not no do does did done have has had will would
    can could should may might must shall than then there here when where which who whom whose what how why
    """.split()  # noqa: SIM905 - 按语义分行的可读性比列表字面量重要（见上）
)


@dataclass
class IndexResult:
    """一次索引构建的产物。`keywords[i]` 与传入的 `chunks[i]` 一一对应。"""

    doc_count: int
    avg_doc_len: float
    df: dict[str, int]
    keywords: list[list[tuple[str, int]]]

    @property
    def keyword_rows(self) -> int:
        return sum(len(items) for items in self.keywords)


def userdict_path() -> Path:
    """学科词典（可选）：一行一个词，`#` 开头的行忽略。"""
    return policy.materials_root() / "userdict.txt"


def stopwords_path() -> Path:
    """附加停用词（可选）：一行一个词。"""
    return policy.materials_root() / "stopwords.txt"


@lru_cache(maxsize=1)
def _jieba():
    """惰性导入 + 一次性加载自定义词典。

    jieba 首次 `cut` 要建前缀词典（约 1 秒、几十 MB 内存）。放在函数里是为了
    让「不解析材料的进程」完全不付这个成本 —— 绝大多数测试就属于这一类。

    `lru_cache(maxsize=1)` 就是「每进程一次」：键是空的，所以第一次调用的结果
    被一直记着，之后连 `userdict_path()` 都不再看（与「词典是进程级资产」这条
    前提一致）。
    """
    import jieba

    path = userdict_path()
    if path.is_file():
        try:
            jieba.load_userdict(str(path))
        except (OSError, ValueError) as exc:  # 词典格式错不该让整份材料解析失败
            logger.warning("自定义词典加载失败：%s", type(exc).__name__)
    return jieba


def extra_stopwords() -> frozenset[str]:
    """材料根目录里 `stopwords.txt` 的词（没有文件就是空集）。"""
    path = stopwords_path()
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return frozenset()
    return _read_stopwords(str(path), stamp)


@lru_cache(maxsize=8)
def _read_stopwords(path: str, stamp: float) -> frozenset[str]:
    """读一次停用词。

    缓存键里带上 mtime，于是「改完文件下一次解析就生效」—— 与自定义词典
    （那份是进程级的）不同，这份是用户随时能改的。不改文件时一次磁盘都不读。
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:  # pragma: no cover - 文件刚刚被删
        return frozenset()
    return frozenset(
        line.strip().lower()
        for line in lines
        if line.strip() and not line.startswith("#")
    )


def _is_word(token: str) -> bool:
    """只留「字母数字」。标点、空白、符号都在这儿被筛掉。"""
    return bool(token) and token.isalnum()


def tokenize(text: str) -> list[str]:
    """一段文字 → 词序列（保留重复，BM25 的 tf 与文档长度都要它们）。

    过滤顺序：切词 → 去空白 → 转小写 → 去标点 → 去停用词 → 截到列宽。
    """
    jieba = _jieba()
    stopwords = STOPWORDS | extra_stopwords()
    out: list[str] = []
    for raw in jieba.cut(str(text or "")):
        token = str(raw).strip().lower()
        if not _is_word(token) or token in stopwords:
            continue
        out.append(token[:KEYWORD_MAX_CHARS])
    return out


def terms_of(query: str) -> list[str]:
    """查询串 → 去重后的词（保持出现顺序）。

    去重是有意的：中文查询里把一个词写两遍（「检索 检索」）表达的是强调，
    不是「这件事重要两倍」。BM25 的 tf 已经在文档那一侧处理了频率。
    """
    return list(dict.fromkeys(tokenize(query)))


def build(chunks: Sequence) -> IndexResult:
    """给一批块建倒排索引与语料统计，**并把 `tokens` 回填到每个块上**。

    回填是因为文档长度（BM25 的 `dl`）必须与「建索引时数出来的词数」一致：
    让 store 层自己再数一遍，两处迟早会因为过滤规则改动而不一致，而那种不一致
    表现为「排序莫名其妙」，几乎查不出来。
    """
    df: dict[str, int] = {}
    keywords: list[list[tuple[str, int]]] = []
    total = 0
    for chunk in chunks:
        counts = Counter(tokenize(chunk.text))
        chunk.tokens = sum(counts.values())
        total += chunk.tokens
        for word in counts:
            df[word] = df.get(word, 0) + 1
        # 按 tf 降序、词本身升序：同一份材料解析两次得到的行顺序也一样（P4-C5）
        keywords.append(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    doc_count = len(chunks)
    return IndexResult(
        doc_count=doc_count,
        avg_doc_len=(total / doc_count) if doc_count else 0.0,
        df=df,
        keywords=keywords,
    )


def merge_stats(rows: Iterable) -> tuple[int, float, dict[str, int]]:
    """多份 `MaterialStats` → 合并语料上的 (文档数, 平均长度, df)。

    相加就是对的，因为块不跨材料。这条性质值得写下来：它省掉了「跨材料检索时
    重新扫全表算 df」那一步，而那是唯一会让检索从 O(命中) 变成 O(全语料) 的地方。
    """
    doc_count = 0
    total_len = 0.0
    df: dict[str, int] = {}
    for row in rows:
        count = int(row.doc_count or 0)
        doc_count += count
        total_len += float(row.avg_doc_len or 0.0) * count
        for word, value in (row.keyword_df or {}).items():
            try:
                df[str(word)] = df.get(str(word), 0) + int(value)
            except (TypeError, ValueError):  # pragma: no cover - 脏数据不进检索
                continue
    return doc_count, (total_len / doc_count if doc_count else 0.0), df


__all__ = [
    "KEYWORD_MAX_CHARS",
    "STOPWORDS",
    "IndexResult",
    "build",
    "extra_stopwords",
    "merge_stats",
    "stopwords_path",
    "terms_of",
    "tokenize",
    "userdict_path",
]
