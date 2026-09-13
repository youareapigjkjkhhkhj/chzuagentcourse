"""材料域的四张表 + 两张关联表（P4 §4）。

这个域与另外两个都不一样：生成域写的是**课的形态**，课堂域写的是**一堂课的经过**，
这里写的是**用户带进来的东西** —— 一份讲义、它切出来的块、块上的倒排索引，
以及「课里的哪一页引用了材料里的哪一段」这笔账。

三件事在这里定下来，后面几层都按它们写：

1. **原文件在盘上，库里只记相对路径**（同 P2-C4 的音频）：换机器只要改
   `MATERIAL_DIR` 一个值，不用改库里的任何一行。
2. **分块与倒排索引是派生数据**：`materials` 那一行是事实，`material_chunks` /
   `chunk_keywords` / `material_stats` 都是从原文件算出来的 —— 删得掉，也重建得回来。
   所以解析失败时清掉派生数据、把 `status` 置 `failed` 就行，不用做「半成品修复」。
3. **页面的引用与页面的 DSL 是两份**：DSL 里那份 `sources` 是给模型与前端看的
   （F4-8 的徽标就在那儿），`page_sources` 这张表是给「这条引文对不对」（P4-C2）
   与「删掉这份材料会影响几页」（P4-A13）查的 —— 后两件事都没法靠翻 JSON 干。

两张关联表用**自然主键**（`chunk_keywords` 用 `(chunk_id, keyword)`、`course_sources`
用 `(course_id, material_id)`）：它们没有「自己」这回事，一行就是「这两个东西有关系」，
再发一个 UUID 只会多一列没有查询价值的数字（`settings_kv` 也是这么处理的）。
"""

from __future__ import annotations

from app.common.timeutil import utcnow_iso
from app.extensions import db
from app.models.base import JSONField, PkMixin, TimestampMixin, enum_check

#: 一份材料的一生。`uploading` 与 `parsing` 分开：前者是「字节还在路上」，
#: 后者是「字节齐了，正在拆」。用户在这两段看到的进度文案不一样，
#: 而失败时要知道是「没传完」还是「传上来但拆不开」（P4-B2）。
MATERIAL_STATUSES = ("uploading", "parsing", "ready", "failed")

#: 能吃的四种扩展名 —— 与 F4-1 的清单同源。`.txt` 与 `.md` 走同一条纯文本路。
MATERIAL_EXTS = (".md", ".txt", ".pdf", ".docx", ".pptx")

class Material(PkMixin, TimestampMixin, db.Model):
    """一份上传的材料（原文件的元信息就在这一行）。"""

    __tablename__ = "materials"

    owner_id = db.Column(
        db.String(32), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: 用户看到的名字（原始文件名）。落盘用的是 id，名字只用来显示与搜索。
    name = db.Column(db.String(255), nullable=False)
    ext = db.Column(db.String(16), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    #: 内容的 sha256。同一份文件重复上传要给「已存在」而不是再解析一遍（P4-C4）——
    #: 去重看的是内容而不是文件名：同一个文件改个名还是同一个文件。
    sha256 = db.Column(db.String(64), nullable=False, default="")
    #: 解析出来的规模：页数（纯文本没有页，是 0）、字符数、块数。
    #: `chunk_count` 是**冗余计数**：列表页要显示它，而 chunks 是正文级的大行，
    #: 为了一个数字把它们全读出来不值得。它只在解析完成时写一次。
    pages = db.Column(db.Integer, nullable=False, default=0)
    char_count = db.Column(db.Integer, nullable=False, default=0)
    chunk_count = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(16), nullable=False, default="uploading")
    #: 相对 MATERIAL_DIR 的路径（`{material_id}/原文.pdf`）。不存绝对路径：
    #: 换机器 / 换目录时，库里不该留下上一台机器的目录名。
    file_path = db.Column(db.String(512), nullable=False, default="")
    #: 失败原因（给用户看的那一句话，如「这份 PDF 没有文本层，需要 OCR」）。
    error = db.Column(db.String(512), nullable=False, default="")

    chunks = db.relationship(
        "MaterialChunk",
        back_populates="material",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    stats = db.relationship(
        "MaterialStats",
        back_populates="material",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    __table_args__ = (
        enum_check("status", MATERIAL_STATUSES, "material_status_valid"),
        # 同一份内容对同一个人只留一份（P4-C4）。owner 为空时（账号已注销）
        # SQLite 把 NULL 当互不相同，正好不该拦。
        db.UniqueConstraint("owner_id", "sha256", name="uq_materials_owner_sha"),
        db.Index("ix_materials_owner_created", "owner_id", "created_at"),
    )

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict:
        return {
            "fileId": self.id,
            "name": self.name,
            "ext": self.ext,
            "sizeBytes": self.size_bytes,
            "pages": self.pages,
            "charCount": self.char_count,
            "chunkCount": self.chunk_count,
            "status": self.status,
            "error": self.error,
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<Material {self.id} {self.name} status={self.status}>"


class MaterialChunk(PkMixin, TimestampMixin, db.Model):
    """一个分块（F4-3 的产物，检索与溯源都以它为最小单位）。"""

    __tablename__ = "material_chunks"

    material_id = db.Column(
        db.String(32), db.ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    #: 从 1 开始的块序号。它是「这份材料里的第几块」，与页码无关。
    chunk_no = db.Column(db.Integer, nullable=False)
    #: 来源页码范围（PDF/DOCX/PPTX 有，纯文本没有 → NULL）。溯源徽标写的
    #: 「第 12 页」就是这个数（P4-A6）。
    page_from = db.Column(db.Integer, nullable=True)
    page_to = db.Column(db.Integer, nullable=True)
    #: 章节路径（`第 3 章 > 3.2 检索`）。按标题层级切块时写下来的，
    #: 没有标题结构的材料是空串（不是 NULL：调用方少一次判空）。
    section_path = db.Column(db.String(255), nullable=False, default="")
    text = db.Column(db.Text, nullable=False, default="")
    char_count = db.Column(db.Integer, nullable=False, default=0)
    #: 分词后的词数。BM25 的文档长度就是它（`avg_doc_len` 也是按它算的平均）。
    tokens = db.Column(db.Integer, nullable=False, default=0)

    material = db.relationship("Material", back_populates="chunks")
    keywords = db.relationship(
        "ChunkKeyword",
        back_populates="chunk",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        db.UniqueConstraint("material_id", "chunk_no", name="uq_chunks_material_no"),
        db.CheckConstraint("chunk_no > 0", name="chunk_no_positive"),
    )

    def to_dict(self, *, with_text: bool = True) -> dict:
        data = {
            "chunkId": self.id,
            "fileId": self.material_id,
            "chunkNo": self.chunk_no,
            "pageFrom": self.page_from,
            "pageTo": self.page_to,
            "sectionPath": self.section_path,
            "charCount": self.char_count,
        }
        if with_text:
            data["text"] = self.text
        return data

    def __repr__(self) -> str:
        return f"<Chunk {self.id} material={self.material_id} no={self.chunk_no}>"


class ChunkKeyword(db.Model):
    """倒排索引的一行：某个块里某个词出现了几次（F4-4）。

    主键就是 `(chunk_id, keyword)` —— 一行的事实就是「这两个东西有关系、强度是 tf」。
    `keyword` 上的索引是检索的入口：先把查询词分出来，一次 `IN` 查询捞出所有候选块。
    """

    __tablename__ = "chunk_keywords"

    chunk_id = db.Column(
        db.String(32),
        db.ForeignKey("material_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    keyword = db.Column(db.String(64), primary_key=True)
    #: 词频。BM25 里那一段 `tf * (k1 + 1) / (tf + k1 * (...))` 的 tf。
    tf = db.Column(db.Integer, nullable=False, default=1)

    chunk = db.relationship("MaterialChunk", back_populates="keywords")

    __table_args__ = (
        db.Index("ix_chunk_keywords_keyword", "keyword"),
        db.CheckConstraint("tf > 0", name="chunk_keyword_tf_positive"),
    )

    def __repr__(self) -> str:
        return f"<ChunkKeyword {self.chunk_id}/{self.keyword} tf={self.tf}>"


class MaterialStats(PkMixin, TimestampMixin, db.Model):
    """一份材料的语料统计（BM25 需要，解析完成时算一次，检索时只读）。

    放在这儿而不是每次检索现算：`df` 要对全语料扫一遍，而检索是在
    用户敲下回车那一刻跑的（P4-B5 要 P95 ≤ 200ms）。
    """

    __tablename__ = "material_stats"

    material_id = db.Column(
        db.String(32), db.ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    doc_count = db.Column(db.Integer, nullable=False, default=0)
    avg_doc_len = db.Column(db.Float, nullable=False, default=0.0)
    #: `{词: 出现在多少个块里}`。语料是「这份材料的全部块」，df 也按它算。
    keyword_df_json = db.Column(db.Text)

    keyword_df = JSONField("keyword_df_json")

    material = db.relationship("Material", back_populates="stats")

    __table_args__ = (
        db.UniqueConstraint("material_id", name="uq_material_stats_material"),
    )

    def __repr__(self) -> str:
        return f"<MaterialStats material={self.material_id} docs={self.doc_count}>"


class CourseSource(TimestampMixin, db.Model):
    """课程用了哪几份材料（F4-14 / P4-A13 的「所用材料清单」）。

    自然主键 `(course_id, material_id)`：同一份材料关联同一门课两次没有意义，
    与其加一列 id 再加一条唯一约束，不如让主键直接说这句话。
    """

    __tablename__ = "course_sources"

    course_id = db.Column(
        db.String(32),
        db.ForeignKey("courses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    material_id = db.Column(
        db.String(32),
        db.ForeignKey("materials.id", ondelete="CASCADE"),
        primary_key=True,
    )
    added_at = db.Column(db.String(32), nullable=False, default=utcnow_iso)

    def __repr__(self) -> str:
        return f"<CourseSource course={self.course_id} material={self.material_id}>"


class PageSource(PkMixin, TimestampMixin, db.Model):
    """一页里的哪一条要点引用了材料的哪一段（F4-8 / P4-C2）。

    外键全部 CASCADE：材料被删，引用它的这几行跟着走。`quote` 是材料的原文片段
    （不是模型的转述），所以「这条引文对不对」可以靠子串匹配判定（P4-C2），
    不需要再问一次模型。
    """

    __tablename__ = "page_sources"

    page_id = db.Column(
        db.String(32), db.ForeignKey("course_pages.id", ondelete="CASCADE"), nullable=False
    )
    material_id = db.Column(
        db.String(32), db.ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id = db.Column(
        db.String(32), db.ForeignKey("material_chunks.id", ondelete="CASCADE"), nullable=False
    )
    #: 材料里的第几页（不是课里的第几页）。徽标上那个「第 12 页」就是它。
    page_no = db.Column(db.Integer, nullable=True)
    section_path = db.Column(db.String(255), nullable=False, default="")
    #: 引文原文。校验时拿它与 chunk 的正文做归一化子串匹配（P4-C2）。
    quote = db.Column(db.Text, nullable=False, default="")
    #: 检索时的 BM25 分（用于「引用强弱」的展示与排查，不参与正确性判定）。
    score = db.Column(db.Float, nullable=False, default=0.0)

    __table_args__ = (
        db.Index("ix_page_sources_material", "material_id"),
        db.Index("ix_page_sources_page", "page_id"),
    )

    def to_dict(self) -> dict:
        """给前端徽标读的那一份。

        `materialId` 这个名字与**同一批出处的另外两处**保持一致：
        `citations.verify` 核出来的那份（它在页面的 DSL 里，前端渲染徽标读的就是它）
        与 `skills._summarize_material` 的摘要出处。三处一个形状，前端才只有一个
        「点开抽屉定位原文」的入口。

        （传材料的那些接口用 `fileId` 称呼同一份东西 —— 那是**材料接口**的词汇，
        这里跟的是**出处**的词汇，两边各自自洽，边界写在 P4 文档 §5。）
        """
        return {
            "pageId": self.page_id,
            "materialId": self.material_id,
            "chunkId": self.chunk_id,
            "pageNo": self.page_no,
            "sectionPath": self.section_path,
            "quote": self.quote,
            "score": self.score,
        }

    def __repr__(self) -> str:
        return f"<PageSource page={self.page_id} chunk={self.chunk_id}>"
