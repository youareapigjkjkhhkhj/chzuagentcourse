"""HTTP 接口层冒烟测试（单进程，Flask 测试客户端）。

验证 Flask 同时托管前端静态页与 /api 路由，以及问答接口连通性。
不重建索引（复用已持久化的 FAISS），仅消耗 1 次 LLM 调用。
"""
import sys
from app import app


def main():
    c = app.test_client()

    r = c.get("/")
    assert r.status_code == 200, f"GET / -> {r.status_code}"
    assert b"<!DOCTYPE html>" in r.data or b"<html" in r.data, "前端首页未返回 HTML"
    print("[GET /] 200 前端首页 OK")

    r = c.get("/api/health")
    print(f"[GET /api/health] {r.status_code} {r.get_json()}")

    r = c.get("/api/notes")
    notes = r.get_json()["notes"]
    print(f"[GET /api/notes] {r.status_code} 笔记数={len(notes)}")
    assert notes, "笔记列表为空"

    r = c.get("/api/index/status")
    st = r.get_json()
    print(f"[GET /api/index/status] {r.status_code} {st}")
    assert st.get("indexed") is True, "索引状态应为已构建"

    r = c.post("/api/qa", json={"question": "本助手基于什么技术栈？"})
    body = r.get_json()
    print(f"[POST /api/qa] {r.status_code} 回答长度={len(body.get('answer',''))} 来源={[s['source'] for s in body.get('sources',[])]}")
    assert r.status_code == 200 and body.get("answer"), "问答失败"

    print("\n[PASS] HTTP 接口层冒烟测试通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
