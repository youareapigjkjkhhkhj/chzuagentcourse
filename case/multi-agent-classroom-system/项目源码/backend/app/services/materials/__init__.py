"""材料服务层（P4）。

六个模块，按「谁依赖谁」自上而下 —— 与 `services/voice/` 是同一张表、同一种排法：

| 模块 | 管什么 |
|------|--------|
| `policy`    | 门口：总开关、白名单、魔数、落盘位置（P4-F1/C3/G3） |
| `parsers`   | 五种格式 → 同一串「块」（F4-2 / P4-A1） |
| `chunking`  | 块 → 检索与溯源的最小单位（F4-3 / P4-A2） |
| `indexer`   | 分词、停用词、倒排表与语料统计（F4-4 / P4-C5） |
| `search`    | BM25 检索（F4-5 / P4-A3/A4 / P4-D3） |
| `store`     | 编排：上传、解析、读取、删除、与课程的关联（F4-1~F4-6/F4-14） |

依赖是单向的：`store` 认识上面全部，而 `parsers`/`chunking`/`indexer`/`search`
互不相识 —— 它们各自只认「上一步给我的那个数据结构」。这条约束让每一层都能
单独测：分块的质量（P4-A2）不需要一个 PDF，检索的排序（P4-A3）不需要真的解析。

导入顺序无所谓（子模块之间不互相 `from 本包 import`，见 `policy.py` 顶部那句）。
"""

from __future__ import annotations

from app.services.materials import chunking, indexer, parsers, policy, search, store
from app.services.materials.chunking import Chunk, split
from app.services.materials.indexer import build, tokenize
from app.services.materials.parsers import Block, ParsedDoc, ParseError, parse
from app.services.materials.policy import MaterialDisabledError, enabled
from app.services.materials.search import Hit
from app.services.materials.search import search as retrieve
from app.services.materials.store import (
    attach_to_course,
    create_from_upload,
    delete_material,
    detach_from_course,
    detail,
    get_material,
    impact,
    list_chunks,
    list_materials,
    material_ids_of_course,
    parse_material,
    search_materials,
    submit_parse,
)

__all__ = [
    "Block",
    "Chunk",
    "Hit",
    "MaterialDisabledError",
    "ParseError",
    "ParsedDoc",
    "attach_to_course",
    "build",
    "chunking",
    "create_from_upload",
    "delete_material",
    "detach_from_course",
    "detail",
    "enabled",
    "get_material",
    "impact",
    "indexer",
    "list_chunks",
    "list_materials",
    "material_ids_of_course",
    "parse",
    "parse_material",
    "parsers",
    "policy",
    "retrieve",
    "search",
    "search_materials",
    "split",
    "store",
    "submit_parse",
    "tokenize",
]
