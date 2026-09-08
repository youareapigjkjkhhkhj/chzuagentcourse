# -*- coding: utf-8 -*-
"""
deck_ai_wardrobe.py —— Kaleido AI 智能衣柜（ai-wardrobe）39 页技术简报 deck 主装配。
生成路线：swiss-lecture-style 独立生成器（scripts 目录）→ SVG → 质量门禁 → PPTX。

用法：
    python deck_ai_wardrobe.py [输出项目目录]
    # 默认输出到 E:/workbuddy-study/study/PPT/projects/ai_wardrobe_v1_20260907
"""
import os
import sys

# 1) 先把 swiss-lecture-style 的生成器目录放进 sys.path
SKILL_SCRIPTS = r"C:\Users\28407\.workbuddy\skills\swiss-lecture-style\scripts"
if SKILL_SCRIPTS not in sys.path:
    sys.path.insert(0, SKILL_SCRIPTS)

# 2) 导入生成器、20 张示意图、四段页数据
from swiss_lecture_gen import write_deck          # noqa: E402
import deck_diagrams as DD                         # noqa: E402
from deck_pages_a import PAGES_A                   # noqa: E402
from deck_pages_b import PAGES_B                   # noqa: E402
from deck_pages_c import PAGES_C                   # noqa: E402
from deck_pages_d import PAGES_D                   # noqa: E402

PAGES = PAGES_A + PAGES_B + PAGES_C + PAGES_D

# 3) diagram 键 = deck_diagrams 中以 dg_ 开头的函数名（与各页 spec["diagram"] 一致）
DIAGRAMS = {n: getattr(DD, n) for n in dir(DD) if n.startswith("dg_")}

DECK = {
    "title": "Kaleido AI 智能衣柜 · 技术架构详解",
    "file": "Kaleido_AI智能衣柜_技术架构详解.pptx",
    "pages": PAGES,
}


if __name__ == "__main__":
    assert len(PAGES) == 39, f"页数异常: {len(PAGES)}"
    missing = [p["diagram"] for p in PAGES if p["type"] == "diagram" and p["diagram"] not in DIAGRAMS]
    assert not missing, f"缺少示意图: {missing}"
    here = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.normpath(os.path.join(here, "..", "projects", "ai_wardrobe_v1_20260907"))
    out_dir = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else default_out
    svg_dir, files = write_deck(DECK, out_dir, diagrams=DIAGRAMS)
    print(f"[{DECK['title']}] {len(files)} 页 SVG -> {svg_dir}")
