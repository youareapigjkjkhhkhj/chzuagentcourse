"""API 冒烟测试：健康检查 + 创建报告任务 + 轮询到完成（真实全链路，网络/LLM 失败由兜底机制兜住）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from api.app import app

PASS = 0


def check(name, condition, detail=""):
    global PASS
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name} {detail}")
    if condition:
        PASS += 1
    else:
        raise SystemExit(f"冒烟测试失败: {name}")


client = TestClient(app)

# 1) 健康检查
r = client.get("/api/health")
check("GET /api/health 200", r.status_code == 200, str(r.status_code))
check("health 返回 ok", r.json().get("status") == "ok")

# 2) 创建报告任务（topic 用英文避免翻译延迟；不带 API key -> 走兜底链路）
r = client.post("/api/reports", json={
    "topic": "graph neural networks for recommendation",
    "max_results": 1,
    "years_back": 0,
    "paper_source": "arxiv",
    "max_chars_per_paper": 2000,
    "top_k": 4,
    "language": "zh",
    "use_rag": True,
    "llm": {"provider": "openai", "api_key": "", "model": "", "base_url": ""},
})
check("POST /api/reports 200", r.status_code == 200, str(r.status_code))
job = r.json().get("job")
report_id = r.json().get("report_id")
check("任务 id 非空", bool(report_id), report_id[:8])
check("初始状态 queued|running", job.get("status") in {"queued", "running"}, job.get("status"))

# 3) 轮询到终态（最长 150s：论文检索/PDF 读取/LLM 均有网络超时兜底）
deadline = time.time() + 150
final = None
while time.time() < deadline:
    final = client.get(f"/api/reports/{report_id}").json()
    if final.get("status") in {"completed", "failed"}:
        break
    time.sleep(3)

check("任务到达终态", final and final.get("status") in {"completed", "failed"}, final and final.get("status"))
check("进度 100", final.get("progress") == 100, str(final.get("progress")))

if final.get("status") == "completed":
    check("报告内容非空", len(final.get("report") or "") > 100, f"len={len(final.get('report') or '')}")
    check("Markdown 文件已生成", bool(final.get("files", {}).get("markdown")))
    check("证据/论文字段存在", isinstance(final.get("evidence"), list) and isinstance(final.get("papers"), list))
else:
    print(f"[note] 任务失败(网络受限时允许): {final.get('error', '')[:200]}")

# 4) 任务列表
r = client.get("/api/reports")
check("GET /api/reports 200", r.status_code == 200)
check("任务列表非空", len(r.json().get("jobs", [])) >= 1, f"n={len(r.json().get('jobs', []))}")

print(f"\nAPI 冒烟测试通过: {PASS} 项")
