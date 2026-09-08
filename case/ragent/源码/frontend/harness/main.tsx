// 视觉自验脚手架：预置 zustand 状态直接渲染 Agent 页外壳，验完即删
import ReactDOM from "react-dom/client";
import { MemoryRouter } from "react-router-dom";

import { AgentChatInput } from "@/components/agent/AgentChatInput";
import { AgentLayout } from "@/components/agent/AgentLayout";
import { AgentMessageList } from "@/components/agent/AgentMessageList";
import { useAgentChatStore } from "@/stores/agentChatStore";
import { useAuthStore } from "@/stores/authStore";
import type { AgentMessage, AgentRawFrame, AgentSession } from "@/types/agent";
import "@/styles/globals.css";

const params = new URLSearchParams(window.location.search);
const view = params.get("view") ?? "convo";
// role=user 用来验非管理员看到的空态（少一颗「去后台添加」）
const role = params.get("role") ?? "admin";
// expanded 视图把折叠块直接置为展开态
const openAll = view === "expanded";

// 时间摊开覆盖四个分组桶 含同名会话与闲聊短句的真实压力样本
const sessions: AgentSession[] = [
  { id: "s-current", title: "华东区销售数据分析", lastTime: new Date().toISOString(), turns: 2 },
  { id: "s-6", title: "数据安全怎么做的", lastTime: new Date(Date.now() - 12 * 60000).toISOString(), turns: 1 },
  { id: "s-7", title: "数据安全怎么做的", lastTime: new Date(Date.now() - 25 * 60000).toISOString(), turns: 3 },
  { id: "s-2", title: "差旅报销流程咨询", lastTime: new Date(Date.now() - 40 * 60000).toISOString(), turns: 1 },
  { id: "s-8", title: "你好", lastTime: new Date(Date.now() - 3 * 3600e3).toISOString(), turns: 5 },
  { id: "s-3", title: "高优先级工单跟进", lastTime: new Date(Date.now() - 864e5).toISOString(), turns: 4 },
  { id: "s-4", title: "新员工入职材料清单", lastTime: new Date(Date.now() - 5 * 864e5).toISOString(), turns: 1 },
  { id: "s-5", title: "季度 OKR 对齐会纪要", lastTime: new Date(Date.now() - 20 * 864e5).toISOString(), turns: 3 }
];

const at = (m: number) => new Date(Date.now() - m * 60000).toISOString();
const hms = (m: number) => new Date(Date.now() - m * 60000).toTimeString().slice(0, 8);

const answerMarkdown = `根据知识库中的《华东区季度销售报表》，上季度整体情况如下：

| 城市 | 销售额（万元） | 环比 |
| ---- | ---- | ---- |
| 上海 | 1,842 | +12.4% |
| 杭州 | 1,286 | +8.1% |
| 南京 | 967 | -3.2% |

**补货建议：**

1. 上海、杭州保持增长，建议按 \`safety_stock = 日均销量 × 1.5\` 上调安全库存
2. 南京环比下滑，先排查渠道库存积压，再决定是否补货

> 数据口径为含税出货额，明细见报表第 3 节。`;

const answer2 = `公司差旅报销依据《差旅费管理办法（2025 修订版）》执行，北京属于一类城市：

- 住宿上限 **650 元/晚**，需提供增值税专用发票
- 餐补 **150 元/天**，无需发票、按出差天数打包发放
- 市内交通实报实销，打车需附行程单

出差五天预计可报销上限约 **4,000 元**（不含往返大交通）。`;

function buildMessages(): { messages: AgentMessage[]; isStreaming: boolean } {
  if (view === "welcome") {
    return { messages: [], isStreaming: false };
  }

  const turns: AgentMessage[] = [
    {
      id: "u1",
      role: "user",
      content: "分析一下华东区上季度的销售数据，给出下季度的补货建议",
      createdAt: at(9)
    },
    {
      id: "a1",
      role: "assistant",
      content: "",
      status: "done",
      createdAt: at(9),
      elapsedMs: 26300,
      blocks: [
        {
          id: 11,
          kind: "reasoning",
          at: hms(9),
          durationMs: 3400,
          text: "用户需要销售数据分析与补货建议，先检索知识库中的季度报表，再结合环比趋势给出结论。\n需要注意南京的负增长是否与渠道库存有关。",
          open: false
        },
        {
          id: 12,
          kind: "tool",
          at: hms(9),
          durationMs: 1200,
          name: "search_knowledge",
          displayName: "知识库检索",
          status: "done",
          result: JSON.stringify([
            { doc: "华东区季度销售报表.xlsx", score: 0.92, chunk: "上海 1842 万，环比 +12.4%..." },
            { doc: "渠道库存周报.pdf", score: 0.87, chunk: "南京渠道库存周转天数升至 46 天..." },
            { doc: "补货策略 SOP.docx", score: 0.81, chunk: "安全库存 = 日均销量 × 1.5..." }
          ]),
          open: false
        },
        { id: 13, kind: "answer", at: hms(8), durationMs: 21600, text: answerMarkdown }
      ]
    },
    {
      id: "u2",
      role: "user",
      content: "公司差旅报销流程是怎么规定的？出差北京五天大概能报多少",
      createdAt: at(4)
    },
    {
      id: "a2",
      role: "assistant",
      content: "",
      status: "done",
      createdAt: at(4),
      elapsedMs: 9400,
      blocks: [
        {
          id: 21,
          kind: "tool",
          at: hms(4),
          durationMs: 800,
          name: "search_knowledge",
          displayName: "知识库检索",
          status: "done",
          // 门面合成的 markdown 文本：验证折叠摘要压平 不露 --- ### 等记号
          result:
            "根据当前可用信息，差旅报销规定如下：\n\n---\n\n### 一、住宿标准\n\n- 一类城市（北京、上海、深圳）**650 元/晚**\n- 需提供增值税专用发票\n\n### 二、餐补\n\n- 150 元/天，按出差天数打包发放",
          open: false
        },
        { id: 22, kind: "answer", at: hms(3), durationMs: 8100, text: answer2 }
      ]
    }
  ];

  if (view === "failed") {
    turns.push(
      { id: "u3", role: "user", content: "顺便查下明天上海的天气", createdAt: at(1) },
      {
        id: "a3",
        role: "assistant",
        content: "",
        status: "done",
        createdAt: at(1),
        elapsedMs: 16200,
        blocks: [
          {
            id: 31,
            kind: "tool",
            at: hms(1),
            durationMs: 10000,
            name: "weather_query",
            displayName: "天气查询",
            status: "failed",
            result: "Error: MCP 调用超时（10s），weather 服务未响应",
            open: false
          },
          {
            id: 32,
            kind: "hint",
            at: hms(1),
            text: "已达到最大迭代次数，正在生成当前执行结果的总结"
          },
          {
            id: 33,
            kind: "answer",
            at: hms(0),
            text: "天气服务暂时不可用，稍后可以再试。销售与报销两部分结论不受影响。"
          }
        ]
      }
    );
    return { messages: turns, isStreaming: false };
  }

  if (view === "streaming") {
    turns.push(
      { id: "u3", role: "user", content: "帮我看看最近的高优先级工单处理情况", createdAt: at(0) },
      { id: "a3", role: "assistant", content: "", status: "streaming", createdAt: at(0), blocks: [] }
    );
    return { messages: turns, isStreaming: true };
  }

  if (view === "running") {
    turns.push(
      { id: "u3", role: "user", content: "帮我看看最近的高优先级工单处理情况", createdAt: at(0) },
      {
        id: "a3",
        role: "assistant",
        content: "",
        status: "streaming",
        createdAt: at(0),
        blocks: [
          {
            id: 41,
            kind: "reasoning",
            at: hms(0),
            text: "需要调用工单系统接口查询 P0/P1 工单，再按处理时长排序。",
            open: true
          },
          {
            id: 42,
            kind: "tool",
            at: hms(0),
            name: "ticket_query",
            displayName: "工单查询",
            status: "running"
          }
        ]
      }
    );
    return { messages: turns, isStreaming: true };
  }

  return { messages: turns, isStreaming: false };
}

const { messages, isStreaming } = buildMessages();

// 原始帧抽屉预置几条样例帧
const frames: AgentRawFrame[] = [
  { id: 1, ts: hms(1), name: "meta", data: { conversationId: "s-current", taskId: "t-1024" } },
  { id: 2, ts: hms(1), name: "message", data: { type: "think", delta: "先检索知识库…" } },
  {
    id: 3,
    ts: hms(1),
    name: "tool",
    data: { name: "search_knowledge", displayName: "知识库检索", status: "start" }
  },
  {
    id: 4,
    ts: hms(0),
    name: "tool",
    data: { name: "search_knowledge", displayName: "知识库检索", status: "end", ok: true, result: "[…]" }
  },
  { id: 5, ts: hms(0), name: "message", data: { type: "response", delta: "根据知识库…" } }
];

useAuthStore.setState({ user: { userId: "1", username: "admin", role } as never });
useAgentChatStore.setState({
  sessions,
  currentSessionId: "s-current",
  // expanded 视图预置折叠块为展开态
  messages: openAll
    ? messages.map((message) => ({
        ...message,
        blocks: message.blocks?.map((block) => ({ ...block, open: true }))
      }))
    : messages,
  isLoading: false,
  sessionsLoaded: true,
  isStreaming,
  frames
});

function HarnessApp() {
  // 订阅 store 让 toggleBlockOpen 生效 便于截图前点开折叠块
  const liveMessages = useAgentChatStore((state) => state.messages);
  const liveStreaming = useAgentChatStore((state) => state.isStreaming);
  return (
    <MemoryRouter>
      <AgentLayout>
        <AgentMessageList
          messages={liveMessages}
          isLoading={false}
          isStreaming={liveStreaming}
          sessionKey="s-current"
        />
        <AgentChatInput />
      </AgentLayout>
    </MemoryRouter>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<HarnessApp />);
