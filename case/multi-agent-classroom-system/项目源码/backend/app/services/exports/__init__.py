"""导出（P5）：课程 DSL / 课堂记录 → 可下载的产物。

四层，各管一段，谁都不越界：

| 模块 | 管什么 | 不认识什么 |
|------|--------|-----------|
| `ir.py`     | 数据形状（Deck / Page / Block）与 DSL→IR | 渲染器、数据库 |
| `pptx.py` / `html.py` / `pdf.py` | IR → 字节 | 数据库、文件系统 |
| `record.py` | 课堂记录 → IR / Markdown | 数据库（读的是 `record.build()` 的返回值） |
| `store.py`  | 字节 → 盘上的文件 | 导出是什么内容 |
| `queue.py`  | 串起来：建行 → 渲染 → 落盘 → 记状态 | 怎么画一页 |

`ir.py` 不碰 DB、渲染器不碰 DB、`record.py` 不查 DB —— 这条线是刻意的：
三个渲染器因此都能在**没有应用上下文**的地方跑（验收脚本、离线批量导出），
而「查库」这件事全部集中在 `queue.py` 一处，也只需要在这一处想清楚
「导出的时候课程被删了怎么办」。

对外只用 `queue`（加上 `store` 的清理函数）；其余模块是它的零件。
"""

from __future__ import annotations

from app.services.exports import queue

__all__ = ["queue"]
