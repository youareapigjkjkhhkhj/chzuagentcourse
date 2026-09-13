"""课堂运行时（P3）。

一堂课被拆成六个各管一件事的模块，彼此只认下一层的输入：

| 模块 | 管什么 | 不认识什么 |
|------|--------|-----------|
| `timeline` | 课 → 时间线（每页多少毫秒、beat 在哪） | 谁在说话 |
| `state` | 七个状态的转移与会话行上的位置 | 发言、板书 |
| `scheduler` | 唯一一个说话的人（优先级/抢占/TTL） | 数据库、WebSocket |
| `interjection` | 同学什么时候说、说什么（一次 LLM 调用） | 消息怎么发出去 |
| `board` | `boardPlan` → 笔画 | 什么时候画 |
| `recorder` | 一切落库（事件/消息/举手/作答/在线） | 什么时候该落 |

再往上一层的 `runtime` 才认识它们全部，也才认识 WebSocket（P3-3）。
这样分的理由很实际：**这一层能在没有端口的测试里跑完** ——
`FakeClock` 造 TTL 超时、`FakeTransport` 收事件，都不需要真的连一个客户端。
"""

from __future__ import annotations

__all__: list[str] = []
